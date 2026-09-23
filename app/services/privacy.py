"""Best-effort pattern redaction, not a complete DLP system."""
import re

PATTERNS = [
    ("PRIVATE_KEY", r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----"),
    ("EMAIL", r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    ("IPV4", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ("USER_PATH", r"(?:[A-Z]:\\Users\\|/Users/|/home/)[^/\\\s\"']+"),
    ("SECRET", r"\b(?:api[_-]?key|access[_-]?token|token|password|secret)\b[\"']?\s*[:=]\s*[\"']?[^\s,;\"'}]+"),
    ("BEARER", r"\bBearer\s+[^\s\"']+"),
    ("TOKEN", r"\b(?:sk-|hf_|ghp_)[A-Za-z0-9_-]{8,}\b"),
]

def redact(text):
    counts = {}
    for label, pattern in PATTERNS:
        text, count = re.subn(pattern, f"[REDACTED_{label}]", text, flags=re.I)
        if count:
            counts[label] = count
    return text, counts

def sanitize(value):
    counts = {}
    def visit(item):
        if isinstance(item, str):
            clean, found = redact(item)
            for key, n in found.items():
                counts[key] = counts.get(key, 0) + n
            return clean
        if isinstance(item, dict):
            return {key: visit(val) for key, val in item.items()}
        if isinstance(item, list):
            return [visit(val) for val in item]
        return item
    return visit(value), counts
