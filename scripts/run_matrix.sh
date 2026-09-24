#!/usr/bin/env bash
# One Nano session, every comparison. Run ON THE NANO from the repo root with the model already served.
#
#   bash scripts/run_matrix.sh                 # tag "base"  (stock model)
#   bash scripts/run_matrix.sh finetuned       # same grid after serving the fine-tuned model
#   MODE=quick bash scripts/run_matrix.sh      # 30 tickets per file, for a first smoke pass
#   SIMULATE=1 bash scripts/run_matrix.sh      # plumbing check without a model
#   ONLY="baseline full" SAMPLE_SWEEP=0 ...     # fewer configs / skip the 1- and 5-sample runs (saves time)
#   LATENCY_PROBE=0 ...                         # skip the one-ticket-at-a-time latency measurement
#
# For each configuration: calibrate the threshold + gate mode on calib.jsonl, lock it, then score
# test.jsonl and test_hard.jsonl with it. Then a 1/3/5-sample sweep for the full configuration.
# Every switch is set explicitly here, so results do not depend on what .env contains.
set -euo pipefail
cd "$(dirname "$0")/.."
TAG=${1:-base}
PY=${EDGE_SUPPORT_PYTHON:-.venv/bin/python}
WORKERS=${WORKERS:-4}
OUT=reports/$TAG
mkdir -p "$OUT"
LIMIT=(); [[ ${MODE:-full} == quick ]] && LIMIT=(--limit 30)
SIM=(); [[ ${SIMULATE:-0} == 1 ]] && SIM=(--simulate)
[[ -f data/eval/calib.jsonl && -f data/eval/test_hard.jsonl ]] || "$PY" scripts/make_dataset.py
"$PY" scripts/build_index.py >/dev/null

# name|switches. Empty values mean "original default" and stop .env from filling them in (dotenv never overrides).
PIN="GATE_MODE= KB_TOP_K= BATCH_SAMPLES= FORCE_OFFLINE="
CONFIGS=(
  "baseline|$PIN STRICT_SCHEMA=false COMPACT_PROMPT=false LENIENT_PARSE=false RETRIEVAL=legacy LOCAL_REDACTION=full MAX_OUTPUT_TOKENS="
  "schema|$PIN STRICT_SCHEMA=true COMPACT_PROMPT=true LENIENT_PARSE=true RETRIEVAL=legacy LOCAL_REDACTION=full MAX_OUTPUT_TOKENS="
  "full|$PIN STRICT_SCHEMA=true COMPACT_PROMPT=true LENIENT_PARSE=true RETRIEVAL=bm25 LOCAL_REDACTION=keep_network MAX_OUTPUT_TOKENS=450"
)
run() {  # name switches samples
  local name=$1 switches=$2 n=$3
  echo "=== $TAG / $name / samples=$n"
  # calibration sweeps BOTH gate modes from one model run and locks the best (gate, threshold)
  env $switches "$PY" eval/evaluate.py ${SIM[@]+"${SIM[@]}"} ${LIMIT[@]+"${LIMIT[@]}"} --workers "$WORKERS" --samples "$n" --label "$TAG-$name-n$n-calib" \
      --dataset data/eval/calib.jsonl --calibrate --threshold-out "$OUT/threshold-$name-n$n.json" \
      --output "$OUT/$name-n$n-calib.json" >/dev/null
  for split in test test_hard; do
    env $switches "$PY" eval/evaluate.py ${SIM[@]+"${SIM[@]}"} ${LIMIT[@]+"${LIMIT[@]}"} --workers "$WORKERS" --samples "$n" --label "$TAG-$name-n$n" \
        --dataset "data/eval/$split.jsonl" --threshold-file "$OUT/threshold-$name-n$n.json" \
        --output "$OUT/$name-n$n-$split.json" >/dev/null
  done
}
start=$(date +%s)
ONLY=${ONLY:-baseline schema full}
for cfg in "${CONFIGS[@]}"; do
  if [[ " $ONLY " == *" ${cfg%%|*} "* ]]; then run "${cfg%%|*}" "${cfg#*|}" 3; fi
done
full=$(printf '%s\n' "${CONFIGS[@]}" | grep '^full|'); full=${full#*|}
if [[ ${SAMPLE_SWEEP:-1} == 1 && " $ONLY " == *" full "* ]]; then
  run full "$full" 5
  # One sample can never keep a ticket local (INSUFFICIENT_SAMPLES), so no calibration: it is the
  # single-answer accuracy/latency reference, scored on the test split only.
  echo "=== $TAG / full / samples=1 (reference)"
  env $full "$PY" eval/evaluate.py ${SIM[@]+"${SIM[@]}"} ${LIMIT[@]+"${LIMIT[@]}"} --workers "$WORKERS" --samples 1 --threshold 1.01 \
      --label "$TAG-full-n1" --dataset data/eval/test.jsonl --output "$OUT/full-n1-test.json" >/dev/null
fi
"$PY" scripts/compare_runs.py "$OUT"/*-test.json "$OUT"/*-test_hard.json --out "$OUT/summary.md"
if [[ ${LATENCY_PROBE:-1} == 1 && " $ONLY " == *" full "* && -f "$OUT/threshold-full-n3.json" ]]; then
  # Headline latency: one ticket at a time (the matrix runs WORKERS tickets concurrently, which adds queueing).
  echo "=== $TAG / latency probe (workers=1, 20 tickets)"
  env $full "$PY" eval/evaluate.py ${SIM[@]+"${SIM[@]}"} --workers 1 --limit 20 --samples 3 --label "$TAG-latency" \
      --dataset data/eval/test.jsonl --threshold-file "$OUT/threshold-full-n3.json" --output "$OUT/latency-full-n3.json" >/dev/null
  "$PY" - "$OUT" "$WORKERS" <<'PY'
import json,sys,pathlib
out=pathlib.Path(sys.argv[1]); r=json.loads((out/'latency-full-n3.json').read_text())
line=f"\nSingle-ticket latency (full config, 3 samples, one ticket at a time, n={r['cases']}): p50 {r['p50_ms']/1000:.2f} s, p95 {r['p95_ms']/1000:.2f} s. The matrix rows above ran {sys.argv[2]} tickets concurrently, so their p50 includes queueing.\n"
(out/'summary.md').write_text((out/'summary.md').read_text()+line)
s=json.loads((out/'summary.json').read_text()); s.append({'run':r['label'],'dataset':'latency_probe','mode':r['mode'],'p50_ms':r['p50_ms'],'p95_ms':r['p95_ms'],'workers':1,'cases':r['cases']})
(out/'summary.json').write_text(json.dumps(s,indent=1))
print(line.strip())
PY
fi
echo
echo "Done in $(( ($(date +%s) - start) / 60 )) min. Summary: $OUT/summary.md  (reports: $OUT/)"
echo "Next: .venv/bin/python scripts/update_readme_results.py $OUT/summary.json && .venv/bin/python scripts/build_deck.py $OUT/summary.json"
