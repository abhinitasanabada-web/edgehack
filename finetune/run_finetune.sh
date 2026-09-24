#!/usr/bin/env bash
# On-device LoRA distillation for the edge-fast model. Run ON THE NANO from the repo root.
#   STAGE=data     build finetune/data/sft.jsonl (TEACHER=large to distil from the served second-tier model)
#   STAGE=train    LoRA train + merge inside the NGC PyTorch container (GPU)
#   STAGE=all      both
# Build data AFTER setting the final .env switches: the prompt they produce is baked into training.
# Library versions below were smoke-tested with a tiny local model (CPU); GPU runs on the Nano are unverified.
set -euo pipefail
cd "$(dirname "$0")/.."
STAGE=${STAGE:-all}
IMAGE=${NGC_IMAGE:-nvcr.io/nvidia/pytorch:25.12-py3}
BASE_MODEL=${BASE_MODEL:-Qwen/Qwen2.5-7B-Instruct}
EPOCHS=${EPOCHS:-2}
DOCKER=${DOCKER:-docker}

if [[ $STAGE == data || $STAGE == all ]]; then
  [[ -f data/eval/train.jsonl ]] || .venv/bin/python scripts/make_dataset.py
  .venv/bin/python finetune/build_sft.py ${TEACHER:+--teacher "$TEACHER"}
fi

if [[ $STAGE == train || $STAGE == all ]]; then
  # Preflight: fail fast instead of an hour in.
  if ! $DOCKER info >/dev/null 2>&1; then
    echo "Cannot reach Docker as $(whoami). Ask the admin to add you to the docker group, or run with DOCKER='sudo docker'."
    echo "(Do not reboot the Nano and walk away: a reboot can drop Tailscale.)"; exit 1
  fi
  if pgrep -f "vllm|zrt serve" >/dev/null 2>&1 && [[ ${ALLOW_SERVING:-0} != 1 ]]; then
    echo "A zrt/vLLM server is still running and holds unified memory. Stop it first (or ALLOW_SERVING=1 to try anyway)."; exit 1
  fi
  avail_gb=$(awk '/MemAvailable/ {printf "%d", $2/1048576}' /proc/meminfo 2>/dev/null || echo 0)
  if (( avail_gb > 0 && avail_gb < 48 )); then echo "Only ${avail_gb} GB available; a 7B BF16 LoRA run wants ~48 GB+. Free memory first."; exit 1; fi
  [[ -f finetune/data/sft.jsonl ]] || { echo "Run STAGE=data first."; exit 1; }
  PUSH=""; [[ -n ${HF_REPO_ID:-} ]] && PUSH="--push"
  # Pass HF credentials through a private env file: `sudo docker` resets the environment, and -e VALUE on the
  # command line would expose the token in the process list.
  ENVF=$(mktemp); chmod 600 "$ENVF"; trap 'rm -f "$ENVF"' EXIT
  printf 'HF_TOKEN=%s\nHF_REPO_ID=%s\nBASE_MODEL=%s\nHOST_UID=%s\nHOST_GID=%s\n' \
    "${HF_TOKEN:-}" "${HF_REPO_ID:-}" "$BASE_MODEL" "$(id -u)" "$(id -g)" > "$ENVF"
  $DOCKER run --rm --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 --env-file "$ENVF" \
    -v "$PWD":/workspace/edgehack -v "${HF_HOME:-$HOME/.cache/huggingface}":/root/.cache/huggingface \
    -w /workspace/edgehack "$IMAGE" bash -lc "
      pip install -q 'accelerate==1.15.0' 'datasets==5.0.1' 'huggingface_hub==1.33.0' 'peft==0.21.0' 'transformers==5.17.0' 'trl==1.13.0' &&
      { pip uninstall -y -q torchao || true; } &&
      python finetune/train_lora.py --epochs $EPOCHS $PUSH;
      status=\$?; chown -R \$HOST_UID:\$HOST_GID finetune/outputs 2>/dev/null || true; exit \$status"
  echo "Merged model: finetune/outputs/merged   (training metrics: finetune/outputs/train_metrics.json)"
  if [[ -n ${HF_REPO_ID:-} ]]; then
    echo "Serve it (documented ZRT path):  zrt pull $HF_REPO_ID && zrt serve $HF_REPO_ID --host 127.0.0.1 --port 8000"
  else
    echo "No HF_REPO_ID set. Serving a local folder with zrt is unverified; set HF_REPO_ID and re-run with --push, or try:"
    echo "  zrt serve $PWD/finetune/outputs/merged --host 127.0.0.1 --port 8000"
  fi
  echo "Then set LOCAL_LLM_MODEL in .env to the id from: curl -s 127.0.0.1:8000/v1/models"
  echo "Keep the same .env switches as in finetune/data/sft_meta.json, re-calibrate, then compare:"
  echo "  bash scripts/run_matrix.sh finetuned   &&   .venv/bin/python scripts/compare_runs.py reports/"
fi
