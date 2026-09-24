from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path


RUNBOOK_DIR = Path(__file__).with_name("runbooks")
KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge"


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


# --- RETRIEVAL=bm25 -----------------------------------------------------------------------------
# One ranked index over both corpora. Sources are namespaced ("runbooks/x.md", "knowledge/x.md") so the
# two files that share a name are distinct kb: evidence IDs, and scores are on one scale.

STOP = set("""the and for with that this from are was were has have had not but you your our its can will
into when what which then than them they their there here also just very really been being does did""".split())


def _terms(text: str) -> list[str]:
    out = []
    for t in re.findall(r"[a-z0-9]+", text.lower().replace("_", " ")):
        if len(t) < 3 or t in STOP:
            continue
        for suffix in ("ing", "ies", "es", "ed", "s"):
            if len(t) > len(suffix) + 3 and t.endswith(suffix):
                t = t[: -len(suffix)] + ("y" if suffix == "ies" else "")
                break
        out.append(t)
    return out


@lru_cache(maxsize=1)
def _index():
    docs = []
    for namespace, directory in (("runbooks", RUNBOOK_DIR), ("knowledge", KNOWLEDGE_DIR)):
        for path in sorted(directory.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = path.stem.replace("_", " ")
            tf = Counter(_terms((title + " ") * 3 + text))       # filename/title weighted like a heading
            docs.append({"source": f"{namespace}/{path.name}", "content": text[:1200], "tf": tf, "len": sum(tf.values())})
    df = Counter(t for d in docs for t in d["tf"])
    n = len(docs)
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    avg = sum(d["len"] for d in docs) / max(1, n)
    return docs, idf, avg


def retrieve_bm25(query: str, limit: int = 4, k1: float = 1.2, b: float = 0.75) -> list[dict]:
    docs, idf, avg = _index()
    q = Counter(_terms(query))
    hits = []
    for d in docs:
        score = 0.0
        for t, qf in q.items():
            f = d["tf"].get(t)
            if f:
                score += idf[t] * f * (k1 + 1) / (f + k1 * (1 - b + b * d["len"] / avg)) * min(qf, 2)
        if score > 0:
            hits.append({"source": d["source"], "score": round(score, 3), "content": d["content"], "retrieval": "bm25"})
    return sorted(hits, key=lambda h: -h["score"])[:limit]
