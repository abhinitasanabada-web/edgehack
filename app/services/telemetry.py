CATEGORIES = {
    "cpu_percent": "cpu_saturation", "memory_percent": "memory_pressure",
    "disk_percent": "disk_pressure", "temperature_c": "thermal_throttling",
    "battery_health_percent": "battery_degradation", "wifi_signal_percent": "wifi_connectivity",
}

def analyze(telemetry, thresholds):
    signals = []
    for field, category in CATEGORIES.items():
        value, limit = getattr(telemetry, field), getattr(thresholds, field)
        low = field in {"battery_health_percent", "wifi_signal_percent"}
        if value is not None and (value < limit if low else value > limit):
            signals.append({"category": category, "field": field, "value": value,
                            "threshold": limit, "operator": "<" if low else ">"})
    return signals
