from __future__ import annotations

import re
from pathlib import Path


RUNBOOK_DIR = Path(__file__).with_name("runbooks")


def _tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9_]+", text.lower()) if len(x) > 2}


def retrieve(query: str, limit: int = 3) -> list[dict]:
    query_tokens = _tokens(query)
    results: list[dict] = []
    for path in sorted(RUNBOOK_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        score = len(query_tokens & _tokens(content))
        if score:
            results.append({"source": path.name, "score": score, "content": content[:5000]})
    return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]

