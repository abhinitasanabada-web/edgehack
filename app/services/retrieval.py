"""Dependency-free, local hashed bag-of-words embeddings with cosine retrieval.
Lexical baseline, not pretrained semantic embeddings. Replace embed() for upgrades.
"""
import hashlib
import json
import math
import re
from app.config import ROOT

DIMENSIONS = 2048
INDEX = ROOT / "data/index.json"

def embed(text):
    vector = {}
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        bucket = str(int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % DIMENSIONS)
        vector[bucket] = vector.get(bucket, 0) + 1
    norm = math.sqrt(sum(v*v for v in vector.values())) or 1
    return {k: v/norm for k,v in vector.items()}

def build_index(directory=ROOT / "data/knowledge", destination=INDEX):
    records = []
    for path in sorted(directory.glob("*.md")):
        text = path.read_text()
        for i, offset in enumerate(range(0, len(text), 1200)):
            chunk = text[offset:offset+1400]
            records.append({"source": path.name, "chunk": i, "text": chunk, "vector": embed(chunk)})
    destination.write_text(json.dumps({"embedding": "sha256-bow-v1", "dimensions": DIMENSIONS, "records": records}))
    return len(records)

def retrieve(query, k=3):
    if not INDEX.exists():
        raise ValueError("Local index missing. Run python scripts/build_index.py.")
    index = json.loads(INDEX.read_text())
    if index.get("embedding") != "sha256-bow-v1":
        raise ValueError("Index version mismatch. Rebuild the local index.")
    vector = embed(query)
    hits = []
    for row in index["records"]:
        score = sum(v * row["vector"].get(t, 0) for t,v in vector.items())
        if score > 0:
            hits.append({k:v for k,v in row.items() if k != "vector"} | {"score": round(score, 4)})
    return sorted(hits, key=lambda h: h["score"], reverse=True)[:k]
