"""Synthetic incident evaluation. Default runs the REAL local model; --simulate is explicit."""
import argparse
import json
import math
import platform
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT, Settings
from app.models import Incident
from app.services.pipeline import run
from app.services.provider import ProviderError

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--output", default="reports/benchmark.json")
    args = parser.parse_args()
    settings = Settings.from_env().model_copy(update={"simulation": args.simulate, "enable_cloud": False})
    cases = json.loads((ROOT / "data/evaluation.json").read_text())
    rows = []
    for case in cases:
        try:
            r = run(Incident.model_validate(case["incident"]), settings)
            rows.append({"id": case["id"], "ok": True, "latency_ms": r["latency_ms"], "inference_ms": r["inference_ms"],
                         "category_correct": r["diagnosis"]["issue_category"] == case["expected_category"],
                         "routing_correct": r["decision"]["decision"] == case["expected_decision"],
                         "decision": r["decision"]["decision"], "reason_codes": r["decision"]["reason_codes"]})
        except (ProviderError, ValueError, OSError):
            rows.append({"id": case["id"], "ok": False, "error": "Local inference or index failure"})
    good = [r for r in rows if r["ok"]]
    latencies = sorted(r["latency_ms"] for r in good)
    report = {"mode": "SIMULATION_NOT_MODEL_BENCHMARK" if args.simulate else "LOCAL_LLM",
              "timestamp_utc": datetime.now(timezone.utc).isoformat(), "host_architecture": platform.machine(),
              "model": "synthetic fixture" if args.simulate else settings.local_model,
              "dataset": "Synthetic demo cases; not representative or clinically calibrated",
              "cases": len(rows), "success_rate": len(good)/len(rows),
              "category_accuracy_all_cases": sum(r.get("category_correct", False) for r in rows)/len(rows),
              "routing_accuracy_all_cases": sum(r.get("routing_correct", False) for r in rows)/len(rows),
              "local_resolution_rate_all_cases": sum(r.get("decision") == "LOCAL" for r in rows)/len(rows),
              "p50_ms": statistics.median(latencies) if latencies else None,
              "p95_ms": latencies[math.ceil(.95*len(latencies))-1] if latencies else None,
              "cloud_requests": 0, "rows": rows}
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != "rows"}, indent=2))
    if not good:
        sys.exit(1)
if __name__ == "__main__":
    main()
