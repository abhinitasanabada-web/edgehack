from __future__ import annotations

import socket
import time

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


def _dns_ok(host: str = "example.com") -> bool:
    try:
        socket.gethostbyname(host)
        return True
    except OSError:
        return False


def collect_snapshot(complaint: str = "") -> dict:
    if psutil is None:
        return {"complaint": complaint, "collected_at": time.time(), "network": {"dns_ok": _dns_ok()}}
    processes = []
    for proc in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
            processes.append({"name": info.get("name") or "", "cpu_percent": info.get("cpu_percent") or 0.0, "memory_percent": info.get("memory_percent") or 0.0})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda item: item["memory_percent"], reverse=True)
    return {"complaint": complaint, "collected_at": time.time(), "cpu_percent": psutil.cpu_percent(interval=0.25), "memory_percent": psutil.virtual_memory().percent, "disk_percent": psutil.disk_usage("/").percent, "processes": processes[:20], "network": {"dns_ok": _dns_ok()}}

