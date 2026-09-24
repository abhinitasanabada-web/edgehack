"""Compare evaluation reports side by side (A/B switches, sample counts, base vs fine-tuned).

  python scripts/compare_runs.py reports/                       # every report in the folder
  python scripts/compare_runs.py reports/base-*.json reports/finetuned-*.json --out reports/summary.md

Writes a Markdown table (stdout, and --out) plus a JSON summary next to it (--out with .json) that the
README updater and the presentation builder read. Only numbers present in the reports are shown.
"""
import argparse
import json
import sys
from pathlib import Path

SWITCHES = ("strict_schema", "compact_prompt", "gate_mode", "lenient_parse", "retrieval", "local_redaction")


def load(paths):
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.json")) if p.is_dir() else [p]
    reports = []
    for f in files:
        try:
            r = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(r, dict) and "category_accuracy" in r and "sweep" in r and r.get("label", "").split("-")[-1] != "latency":
            reports.append((f, r))
    return reports


def at_threshold(r):
    curve = (r.get("sweep_by_mode") or {}).get(r.get("gate_mode"), r.get("sweep") or [])
    return next((p for p in curve if abs(p["threshold"] - r["threshold"]) < 1e-9), None)


def row(f, r):
    p = at_threshold(r) or {}
    sw = r.get("switches") or {}
    changed = [k for k in SWITCHES if sw.get(k) not in (None, False, "any", "legacy", "full")]
    cost = r.get("cost_estimate") or {}
    return {
        "run": r.get("label") or f.stem, "file": f.name, "dataset": r.get("dataset"), "mode": r.get("mode"),
        "model": r.get("model"), "samples": r.get("sample_count"), "gate": r.get("gate_mode"), "threshold": r.get("threshold"),
        "switches_on": ",".join(f"{k}={sw[k]}" if not isinstance(sw[k], bool) else k for k in changed) or "baseline",
        "cases": r.get("cases"), "category_accuracy": r.get("category_accuracy"), "category_ci": r.get("category_accuracy_ci"),
        "rules_baseline": (r.get("rules_baseline") or {}).get("category_accuracy"), "route_accuracy": r.get("route_accuracy"),
        "action_accuracy": r.get("action_accuracy"), "local_rate": r.get("local_rate"),
        "selective_error": p.get("selective_error"), "unsafe_accepts": p.get("unsafe_accepts"),
        "p50_ms": r.get("p50_ms"), "p95_ms": r.get("p95_ms"), "workers": r.get("workers", 1),
        "prompt_tokens": (r.get("tokens") or {}).get("prompt_mean"),
        "pii_leaked": (r.get("privacy") or {}).get("pii_leaked"), "pii_planted": (r.get("privacy") or {}).get("pii_planted"),
        "egress_hybrid_b": (r.get("egress") or {}).get("hybrid_bytes_per_ticket"),
        "egress_cloud_only_b": (r.get("egress") or {}).get("cloud_only_bytes_per_ticket"),
        "cost_hybrid_1k": (r.get("hybrid_cloud") or {}).get("cost_per_1k") or cost.get("hybrid_cost_per_1k"),
        "cost_cloud_only_1k": (r.get("cloud_baseline") or {}).get("cost_per_1k") or cost.get("cloud_only_cost_per_1k"),
        "cost_measured": bool((r.get("hybrid_cloud") or {}).get("measured") or (r.get("cloud_baseline") or {}).get("measured")),
        "joules": (r.get("energy") or {}).get("joules_per_incident"),
        "sweep": r.get("sweep_by_mode") or {r.get("gate_mode"): r.get("sweep")},
        "by_kind": r.get("by_kind"), "timestamp": r.get("timestamp_utc"),
    }


def pct(x):
    return "—" if x is None else f"{100 * x:.1f}%"


def num(x, d=0):
    return "—" if x is None else f"{x:,.{d}f}"


def markdown(rows):
    head = ("| Run | Dataset | Samples | Gate / τ | Switches | Category acc. | Rules only | Local | Error when local | "
            "Unsafe | p50 (workers) | PII leaked | Egress B (hybrid / cloud-only) |")
    out = [head, "|" + "|".join(["---"] * (head.count("|") - 1)) + "|"]
    for r in rows:
        ci = f" ({pct(r['category_ci'][0])}–{pct(r['category_ci'][1])})" if r.get("category_ci") else ""
        out.append(f"| {r['run']} | {r['dataset']} | {r['samples']} | {r['gate']} / {r['threshold']} | {r['switches_on']} | "
                   f"{pct(r['category_accuracy'])}{ci} | {pct(r['rules_baseline'])} | {pct(r['local_rate'])} | "
                   f"{pct(r['selective_error'])} | {r['unsafe_accepts'] if r['unsafe_accepts'] is not None else '—'} | "
                   f"{num(r['p50_ms'] / 1000 if r['p50_ms'] is not None else None, 1)} s ({r['workers']}) | "
                   f"{r['pii_leaked'] if r['pii_leaked'] is not None else '—'}/{r['pii_planted'] or 0} | "
                   f"{num(r['egress_hybrid_b'])} / {num(r['egress_cloud_only_b'])} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", help="write Markdown here and a .json summary beside it")
    a = ap.parse_args()
    reports = load(a.paths)
    if not reports:
        sys.exit("no evaluation reports found")
    rows = sorted((row(f, r) for f, r in reports), key=lambda x: (x["dataset"] or "", x["run"]))
    md = markdown(rows)
    print(md)
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# EdgeSupport evaluation summary\n\nGenerated by scripts/compare_runs.py from reports/. "
                       "Synthetic team-written data; error bars are 95% Wilson intervals.\n\n" + md + "\n")
        out.with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str))


if __name__ == "__main__":
    main()
