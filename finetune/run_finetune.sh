#!/usr/bin/env bash
# On-device LoRA distillation for the edge-fast model. Run ON THE NANO from the repo root.
#   STAGE=data     build finetune/data/sft.jsonl (TEACHER=large to distil from the served second-tier model)
#   STAGE=train    LoRA train + merge inside the NGC PyTorch container (GPU)
#   STAGE=all      both
# Library versions below were smoke-tested with a tiny local model (CPU); GPU runs on the Nano are unverified.
# Free GPU memory first: stop or shrink other zrt/vLLM servers (see README "Memory budget").
set -euo pipefail
cd "$(dirname "$0")/.."
STAGE=${STAGE:-all}
IMAGE=${NGC_IMAGE:-nvcr.io/nvidia/pytorch:25.12-py3}
BASE_MODEL=${BASE_MODEL:-Qwen/Qwen2.5-7B-Instruct}
EPOCHS=${EPOCHS:-2}

if [[ $STAGE == data || $STAGE == all ]]; then
  [[ -f data/eval/train.jsonl ]] || .venv/bin/python scripts/make_dataset.py
  .venv/bin/python finetune/build_sft.py ${TEACHER:+--teacher "$TEACHER"}
fi

if [[ $STAGE == train || $STAGE == all ]]; then
  PUSH=""; [[ -n ${HF_REPO_ID:-} ]] && PUSH="--push"
  docker run --rm --gpus all --ipc=host --ulimit memlock=-1 --ulimit stack=67108864 \
    -e HF_TOKEN -e HF_REPO_ID -e BASE_MODEL="$BASE_MODEL" \
    -v "$PWD":/workspace/edgehack -v "${HF_HOME:-$HOME/.cache/huggingface}":/root/.cache/huggingface \
    -w /workspace/edgehack "$IMAGE" bash -lc "
      pip install -q 'accelerate==1.15.0' 'datasets==5.0.1' 'huggingface_hub==1.33.0' 'peft==0.21.0' 'transformers==5.17.0' 'trl==1.13.0' &&
      { pip uninstall -y -q torchao || true; } &&
      python finetune/train_lora.py --epochs $EPOCHS $PUSH"
  echo "Merged model: finetune/outputs/merged"
  echo "Serve it:  zrt serve ${HF_REPO_ID:-$PWD/finetune/outputs/merged} --host 127.0.0.1 --port 8000"
  echo "Then set LOCAL_LLM_MODEL in .env to the id from: curl -s 127.0.0.1:8000/v1/models"
fi
