# Nano runbook — test everything in one session

Run on the ZGX Nano (VS Code ZTK terminal or SSH), from the repo root. Commands are in order, top to bottom.
Nothing here reboots the Nano, but a reboot can drop Tailscale, so keep someone near the lab keyboard.

## 0. Get the code and check the model (10 min)

```bash
git pull                                    # or clone the branch your team merged
bash scripts/setup.sh                       # venv, deps, knowledge index, all dataset splits
zrt status && curl -s 127.0.0.1:8000/v1/models   # the served model id -> LOCAL_LLM_MODEL in .env
nano .env                                   # set LOCAL_LLM_MODEL; leave every v2 switch blank for now
.venv/bin/python -m pytest -q               # expect everything to pass here, including the API tests
```

**Serving tips** (only if you restart the model; don't start a second copy while a teammate is using it):
- `zrt serve <model> --host 127.0.0.1 --port 8000 --max-model-len 8192 --gpu-memory-utilization 0.5`.
  Prompts are about 2k tokens, so 8k context is plenty, and a lower memory share leaves room to fine-tune later.
- vLLM's prefix caching is on by default in current versions, so the fixed system prompt is reused across tickets.
  Pass `--enable-prefix-caching` if your ZRT's vLLM is older.
- Decode speed on GB10 is limited by memory bandwidth. An NVFP4 build of the same model (the brief's fast path)
  should be markedly faster per ticket than BF16. If one is available for your model, benchmark it with the
  same matrix.

## 1. Smoke test (5 min)

```bash
.venv/bin/python eval/evaluate.py --dataset data/eval/test.jsonl --limit 5 --samples 3 --output reports/smoke.json
```

Check `success_rate` is 1.0 and note `p50_ms`. Budget per full matrix: about 1,450 tickets × p50 ÷ `WORKERS`.

## 2. Quick matrix (~30 tickets per file, all configs)

```bash
MODE=quick WORKERS=4 bash scripts/run_matrix.sh quick
cat reports/quick/summary.md
```

Each configuration calibrates its threshold and gate mode on `calib.jsonl`, locks them, then scores `test.jsonl`
and the stress set `test_hard.jsonl`:

| Config | Switches |
|---|---|
| `baseline` | the original behaviour |
| `schema` | `STRICT_SCHEMA` + `COMPACT_PROMPT` + `LENIENT_PARSE` |
| `full` | the above + `RETRIEVAL=bm25` + `LOCAL_REDACTION=keep_network` + `MAX_OUTPUT_TOKENS=450`, then also 1 and 5 samples |

Gate mode (`any` vs `majority`) is chosen automatically during calibration, from one model run.

## 3. Full matrix (as time allows)

```bash
WORKERS=6 bash scripts/run_matrix.sh base                    # everything
ONLY="baseline full" SAMPLE_SWEEP=0 bash scripts/run_matrix.sh base   # if short on time
```

Raise `WORKERS` while p95 latency stays acceptable: vLLM batches concurrent tickets. Stop other GPU work first.

## 4. Pick the demo configuration

Open `reports/base/summary.md`. Pick the row with the highest **Local** (share answered on site) that still has
**Unsafe = 0** and a low **Error when local**, usually `full-n3`. Copy its switches into `.env`, plus the locked
values from `reports/base/threshold-<config>-n<samples>.json`:

```dotenv
STRICT_SCHEMA=true
COMPACT_PROMPT=true
LENIENT_PARSE=true
RETRIEVAL=bm25
LOCAL_REDACTION=keep_network
MAX_OUTPUT_TOKENS=450
GATE_MODE=<gate_mode from the threshold file>
AGREEMENT_THRESHOLD=<threshold from the threshold file>
LOCAL_SAMPLE_COUNT=3
```

## 5. Optional: fine-tune, then the same matrix (1–2 h)

Only once steps 1–4 are saved. Build the training data *after* step 4, because the switches change the prompt.

```bash
STAGE=data bash finetune/run_finetune.sh           # uses the .env switches; writes finetune/data/sft_meta.json
# stop the zrt server (training needs the memory), then:
# Optional upload: omit this line to keep training outputs local.
export PUSH_TO_HF=true HF_TOKEN=... HF_REPO_ID="YOUR_HF_USER/edgesupport-qwen7b-lora"
STAGE=train bash finetune/run_finetune.sh          # preflight checks, LoRA, merge, push
zrt pull $HF_REPO_ID && zrt serve $HF_REPO_ID --host 127.0.0.1 --port 8000   # set LOCAL_LLM_MODEL to the new id
ONLY="full" SAMPLE_SWEEP=0 bash scripts/run_matrix.sh finetuned
.venv/bin/python scripts/compare_runs.py reports/base/full-n3-test.json reports/finetuned/full-n3-test.json
```

Keep whichever model wins. If fine-tuning doesn't beat the switches alone, say so. That's a finding too.

## 6. Publish the evidence (10 min)

```bash
.venv/bin/python scripts/update_readme_results.py reports/base/summary.json   # (+ reports/finetuned/summary.json)
.venv/bin/python scripts/build_deck.py reports/base/summary.json              # embeds results into the deck
git add README.md docs/presentation/index.html reports/*/summary.* reports/*/threshold-*.json
git commit -m "Nano results" && git push
```

`.gitignore` lets through only the summaries and locked thresholds. The large per-ticket reports stay local.
The Nano is wiped after the event, so push before you leave.

## Optional measured cloud comparison (costs money)

With `ENABLE_CLOUD=true`, a cloud endpoint, and `CLOUD_PRICE_IN_PER_MTOK`/`CLOUD_PRICE_OUT_PER_MTOK` set to your
provider's list prices:

```bash
.venv/bin/python eval/evaluate.py --dataset data/eval/test.jsonl --threshold-file reports/base/threshold-full-n3.json \
  --cloud-baseline --cloud-escalations --workers 2 --output reports/base/cloud-test.json
```

This measures cloud-only accuracy and cost, and the hybrid result where only cloud-bound escalations are sent.
Without it, reports show token-based **estimates**, clearly labelled.
