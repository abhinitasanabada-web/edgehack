from __future__ import annotations

import glob
import os
import platform
import re
import socket
import subprocess
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


def _clamp(value, low, high):
    return None if value is None else round(max(low, min(high, value)), 1)


def _temperature_c():
    """Hottest CPU-ish sensor (Linux psutil); None where the OS does not expose sensors (macOS, most Windows)."""
    try:
        temps = psutil.sensors_temperatures() or {}
    except (AttributeError, OSError):
        return None
    values = [t.current for name, entries in temps.items() for t in entries
              if t.current and (name in {"coretemp", "k10temp", "cpu_thermal", "acpitz"} or "cpu" in name.lower())]
    return _clamp(max(values), -30, 150) if values else None


def _battery_health_percent():
    """Full-charge vs design capacity. Linux sysfs, macOS ioreg; None elsewhere or on desktops."""
    for bat in glob.glob("/sys/class/power_supply/BAT*"):
        for full, design in (("energy_full", "energy_full_design"), ("charge_full", "charge_full_design")):
            try:
                f = float(open(os.path.join(bat, full)).read()); d = float(open(os.path.join(bat, design)).read())
                if d > 0:
                    return _clamp(100 * f / d, 0, 100)
            except (OSError, ValueError):
                continue
    if platform.system() == "Darwin":
        try:
            out = subprocess.run(["ioreg", "-rn", "AppleSmartBattery"], capture_output=True, text=True, timeout=5).stdout
            full = re.search(r'"(?:AppleRawMaxCapacity|NominalChargeCapacity)"\s*=\s*(\d+)', out)
            design = re.search(r'"DesignCapacity"\s*=\s*(\d+)', out)
            if full and design and int(design.group(1)) > 0:
                return _clamp(100 * int(full.group(1)) / int(design.group(1)), 0, 100)
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def _wifi_signal_percent():
    """Linux /proc/net/wireless link quality (of 70); None elsewhere (the Windows collector reads netsh)."""
    try:
        for line in open("/proc/net/wireless").read().splitlines()[2:]:
            parts = line.split()
            if len(parts) > 2:
                return _clamp(100 * float(parts[2].rstrip(".")) / 70, 0, 100)
    except (OSError, ValueError):
        pass
    return None


def collect_snapshot(complaint: str = "") -> dict:
    if psutil is None:
        return {"complaint": complaint, "collected_at": time.time(), "network": {"dns_ok": _dns_ok()}}
    procs = list(psutil.process_iter(["name", "memory_percent"]))
    for proc in procs:                      # cpu_percent needs a baseline sample; the first call always returns 0
        try:
            proc.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    cpu_total = psutil.cpu_percent(interval=0.5)
    cores = psutil.cpu_count() or 1
    processes = []
    for proc in procs:
        try:
            processes.append({"name": proc.info.get("name") or "", "cpu_percent": round(proc.cpu_percent(None) / cores, 1),
                              "memory_percent": round(proc.info.get("memory_percent") or 0.0, 1)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda item: (item["memory_percent"], item["cpu_percent"]), reverse=True)
    snapshot = {"complaint": complaint, "collected_at": time.time(), "cpu_percent": cpu_total,
                "memory_percent": psutil.virtual_memory().percent, "disk_percent": psutil.disk_usage("/").percent,
                "processes": processes[:20], "network": {"dns_ok": _dns_ok()}}
    for key, value in (("temperature_c", _temperature_c()), ("battery_health_percent", _battery_health_percent()),
                       ("wifi_signal_percent", _wifi_signal_percent())):
        if value is not None:
            snapshot[key] = value
    return snapshot
