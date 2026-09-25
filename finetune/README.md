# Manual GPU training on the HP Nano

This is the procedure tested on the team's GB10 Nano on 2026-09-25. Start with the **two-step smoke test**, which checks training, evaluation, LoRA merging and saving. It does not establish model quality or prove that a full run cannot OOM.

## What was measured

| Test | Train batch | Eval batch | Gradient accumulation | Peak PyTorch allocated | Peak PyTorch reserved |
|---|---:|---:|---:|---:|---:|
| Conservative diagnostic | 1 | 1 | 1 | 15.61 GiB | 16.36 GiB |
| Current defaults | 4 | 8 | 4 | 17.97 GiB | 20.48 GiB |

Both completed without OOM. Sampled **whole-system** memory usage peaked at 45.07 GiB during the current-default test; this includes CPU buffers, the OS and other processes. It is different from GPU allocator usage. The inference server was stopped during both tests and restored afterward.

The model was Qwen2.5-7B-Instruct, using BF16 LoRA rank 16, gradient checkpointing and PyTorch 2.11.0+cu130. Actual training examples were 408–1,233 tokens long, below the configured 3,072-token cap. Full-length inputs, full-epoch training and concurrent serving/training remain untested. See the [measurements and limits](../reports/training-oom-probe/summary.md).

## 1. Open the Nano terminal

Use the VS Code terminal in your SSH-connected Nano window. Commands below run **on the Nano**, not your Mac. If connecting from a Mac terminal, use your assigned Tailscale IP:

```bash
ssh hp13@YOUR_NANO_TAILSCALE_IP
```

Use the separate merged checkout so the old `~/edgehack` folder's uncommitted files are preserved:

```bash
cd ~/edgehack-integrated-20260924
git status --short --branch
```

The prepared checkout tracks `main`. If it is clean, update with `git pull --ff-only`. On another machine, use a new clone and `bash scripts/setup.sh` first; the cached model and CUDA-runtime paths below are specific to this Nano.

## 2. Check the prepared training environment

```bash
export EDGE_TRAIN_PY="$HOME/edgehack-training-smoke-venv/bin/python"
"$EDGE_TRAIN_PY" -c 'import torch; print(torch.__version__); print("CUDA:", torch.cuda.is_available())'
"$EDGE_TRAIN_PY" -m pip check
zrt status
free -h
```

Expect `CUDA: True` and `No broken requirements found`. The separate training environment is already installed on the team's Nano. It reads the existing CUDA runtime and keeps its training packages separate from the serving environment. Do not install these packages into `/opt/hp/zrt/venv`.

<details>
<summary>Only if the separate training environment is missing</summary>

The tested native route avoids Docker because this Nano user cannot access its Docker daemon without elevated privileges. It requires the existing ZRT CUDA Python runtime at `/opt/hp/zrt/venv/bin/python`.

```bash
/opt/hp/zrt/venv/bin/python -m venv "$HOME/edgehack-training-smoke-venv"
export EDGE_TRAIN_PY="$HOME/edgehack-training-smoke-venv/bin/python"
"$EDGE_TRAIN_PY" - <<'PY'
import subprocess, sysconfig
from pathlib import Path
source = subprocess.check_output([
    '/opt/hp/zrt/venv/bin/python', '-c',
    'import sysconfig; print(sysconfig.get_path("purelib"))'
], text=True).strip()
(Path(sysconfig.get_path('purelib')) / 'zrt_readonly_runtime.pth').write_text(source + '\n')
PY
"$EDGE_TRAIN_PY" -m pip install \
  'accelerate==1.15.0' 'datasets==5.0.1' 'huggingface_hub==1.33.0' \
  'peft==0.21.0' 'transformers==5.17.0' 'trl==1.13.0' \
  'setuptools>=77.0.3,<81'
"$EDGE_TRAIN_PY" -m pip check
```

This reuses this Nano's installed CUDA-compatible PyTorch instead of downloading another build. If the ZRT runtime is changed later, recheck compatibility; this is not an independent, portable environment lock.

</details>

## 3. Build the training examples

Keep the intended prompt settings in `.env` before building data. On the prepared checkout these include strict schema, compact prompt, BM25 retrieval and `keep_network` local redaction.

```bash
.venv/bin/python finetune/build_sft.py
```

Expected output: `387 examples`, written to `finetune/data/sft.jsonl`, plus `sft_meta.json` recording the prompt settings. This uses team-written synthetic **training** data and template targets. It does not invoke a teacher model unless `--teacher` is explicitly supplied. Do not pass test, hard-test or calibration files as training input.

## 4. Run a bounded GPU training test

The following block reproduces the **current-default** test: train batch 4, evaluation batch 8, accumulation 4, two optimizer steps. Evaluation batch 8 is currently inherited from the training library; `--batch` changes training batch only. The conservative diagnostic above used an instrumentation override for evaluation batch 1.

Coordinate the brief inference downtime with teammates. Paste the entire block into the same Nano terminal:

```bash
(
set -euo pipefail
EDGE_TRAIN_PY="$HOME/edgehack-training-smoke-venv/bin/python"
EDGE_RUN_DIR="finetune/outputs/manual-smoke-$(date +%Y%m%d-%H%M%S)"
EDGE_BASE_MODEL="/opt/hp/zrt/models/hf/Qwen/Qwen2.5-7B-Instruct/main"
mkdir -p "$EDGE_RUN_DIR"
test -r "$EDGE_BASE_MODEL/config.json"
"$EDGE_TRAIN_PY" -c 'import torch; assert torch.cuda.is_available(), "CUDA unavailable; refusing CPU fallback"'

zrt stop hf:Qwen/Qwen2.5-7B-Instruct
trap 'zrt serve hf:Qwen/Qwen2.5-7B-Instruct --gpu-memory-fraction 0.31' EXIT

.venv/bin/python -c \
'import psutil; assert psutil.virtual_memory().available >= 48*2**30, "Less than 48 GiB available; training stopped"'

export HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

timeout 20m "$EDGE_TRAIN_PY" -u finetune/train_lora.py \
  --base "$EDGE_BASE_MODEL" \
  --batch 4 \
  --grad-accum 4 \
  --max-length 3072 \
  --max-steps 2 \
  --out "$EDGE_RUN_DIR" \
  2>&1 | tee "$EDGE_RUN_DIR/run.log"

cat "$EDGE_RUN_DIR/train_metrics.json"
)
```

The memory check is a conservative starting guard, not a guarantee. This block uses cached model weights, makes no Hugging Face upload, and writes to a new directory each time. The EXIT trap attempts to restart the original base model after success, an ordinary error, or a timeout; verify restoration in step 6. Keep the SSH session open. No trap can recover automatically from a machine shutdown or an uncatchable kill.

Allow roughly 5–10 minutes, including model loading, weight saving and server restart. A progress bar may pause while tensors are copied or model shards are saved; the tested current-default run took about five minutes before restarting inference.

## 5. Monitor memory and inspect outputs

In another Nano terminal:

```bash
watch -n 2 free -h
```

Use `nvidia-smi` for process/GPU status. GB10 may show aggregate GPU memory as `Not Supported`; that is not an OOM. Inspect `free -h` as well because CPU and GPU share memory.

Your new `finetune/outputs/manual-smoke-.../` folder contains:

| File/folder | Purpose |
|---|---|
| `run.log` | Training, evaluation, merge/save progress and error tracebacks |
| `train_metrics.json` | Training loss, evaluation loss, duration and peak allocated GPU memory |
| `lora/` | LoRA adapter weights |
| `merged/` | Merged model and tokenizer; not automatically deployed |

The script's `peak_gpu_memory_gb` field uses decimal GB and is recorded before merge/save. The diagnostic report linked above additionally measured allocator reservation and the full merge/save phase, in GiB. These are different measurements.

## 6. Verify inference came back

```bash
zrt status
curl -fsS http://127.0.0.1:8000/v1/models
```

Wait for `Ready` and the model ID `hf:Qwen/Qwen2.5-7B-Instruct`. If restart failed, run:

```bash
zrt serve hf:Qwen/Qwen2.5-7B-Instruct --gpu-memory-fraction 0.31
```

This restores the original base model. Two-step smoke-test weights are not a validated replacement for it.

## 7. Full training later

After a successful smoke test, repeat step 4 with a new output directory, replace `--max-steps 2` with `--epochs 2`, and choose a longer timeout appropriate to the session. Keep inference stopped and monitor memory. Full-epoch memory behavior and model-quality improvement have not been established by these short tests.

Before claiming improvement, serve a separately validated fine-tuned model, recalibrate on `calib.jsonl`, and score the unchanged test/hard-test splits using the same prompt switches and sampling settings. The manual procedure above does not validate ZRT serving from a local merged folder or publish weights. The Docker workflow in `run_finetune.sh` is a separate path and has not been GPU-tested in this environment.

## Common issues and small fixes

| Symptom | What to do |
|---|---|
| `CUDA out of memory` | Let the process exit and inspect `run.log`. Stop competing inference first; retry with `--batch 1`. To lower evaluation memory too, set `per_device_eval_batch_size=1` in the `options` passed to `SFTConfig` in `train_lora.py`; there is currently no `--eval-batch` flag. Reducing `--max-length` may help but can truncate training targets. |
| OOM appears only during evaluation | Training batch and evaluation batch are separate. The current evaluation default is 8; explicitly reduce it as above. |
| Docker `permission denied` / `sudo` needs a password | Use the tested native environment above, or ask the Nano administrator for Docker access. Do not alter the Docker socket permissions. |
| `CUDA: False` or `No module named torch/trl/peft` | Use `~/edgehack-training-smoke-venv/bin/python`, not the app's `.venv/bin/python`, for training. Check step 2. |
| `setuptools` conflicts with inherited vLLM | In the separate training environment, install `'setuptools>=77.0.3,<81'`, then run `pip check`. Do not modify ZRT's environment. |
| Missing cached model / offline-loading error | Check that `config.json`, tokenizer files and all weight shards exist under the local model path. Fix that path or use the team's approved model-download procedure before retrying. |
| `sft.jsonl` missing or prompt settings changed | Repeat step 3 after setting the intended `.env` switches. Never substitute test/calibration data. |
| Old checkout reports untracked files would be overwritten | Preserve those files and use `~/edgehack-integrated-20260924`; do not reset or clean the old checkout. |
| Exit code 124 | The 20-minute limit expired; inspect the log for the last completed phase before deciding whether a longer limit is appropriate. Verify inference restarted. |
| App cannot reach port 8000 after the test | Check `zrt status`; wait for startup or use the recovery command in step 6. Inspect `zrt logs --help` for server logs. |
