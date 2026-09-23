from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8502")
    parser.add_argument("--output", default="eval/results.json")
    args = parser.parse_args()
    cases = [json.loads(line) for line in Path("eval/incidents.jsonl").read_text().splitlines() if line.strip()]
    rows = []
    with httpx.Client(timeout=120, trust_env=False) as client:
        for case in cases:
            start = time.perf_counter()
            response = client.post(f"{args.base_url}/diagnose", json={"complaint": case["input"], "telemetry": case["telemetry"]})
            elapsed = (time.perf_counter() - start) * 1000
            response.raise_for_status()
            rows.append({"input": case["input"], "latency_ms": round(elapsed, 2), "diagnosis": response.json()["diagnosis"], "expected": case})
    rows.sort(key=lambda row: row["latency_ms"])
    result = {"count": len(rows), "p50_latency_ms": rows[len(rows) // 2]["latency_ms"], "cases": rows}
    Path(args.output).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

