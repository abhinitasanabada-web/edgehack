"""Seeded synthetic incident generator with a template-disjoint held-out split.

Every category has separate TRAIN and TEST phrasings, log lines and out-of-scope requests,
so test tickets never reuse a sentence the fine-tuned model saw. The knowledge corpus is
not generated from these templates. Output:
  data/eval/train.jsonl  - fine-tuning source (never used for scoring)
  data/eval/test.jsonl   - benchmark set
Rows use the integrated format (incident.description is mapped to complaint by eval/evaluate.py;
telemetry carries network.dns_ok and processes) and include expected_action for fine-tuning.
This is still synthetic data written by the team; report it as such.
"""
import argparse
import json
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import ROOT

FIELD = {"cpu_saturation": "cpu_percent", "memory_pressure": "memory_percent", "disk_pressure": "disk_percent",
         "thermal_throttling": "temperature_c", "battery_degradation": "battery_health_percent",
         "wifi_connectivity": "wifi_signal_percent"}
BAD = {"cpu_percent": (92, 100), "memory_percent": (92, 99), "disk_percent": (93, 99.5),
       "temperature_c": (88, 99), "battery_health_percent": (38, 66), "wifi_signal_percent": (8, 30)}
NORMAL = {"cpu_percent": (8, 60), "memory_percent": (30, 75), "disk_percent": (20, 80),
          "temperature_c": (40, 72), "battery_health_percent": (80, 98), "wifi_signal_percent": (55, 95)}
PROCS = ["chrome", "Teams", "zoom", "OUTLOOK", "MsMpEng", "node", "python", "SearchIndexer"]
DEMO_APPS = ["notepad", "mspaint", "calculatorapp"]  # the only apps the Windows collector may close

TEXT = {
 "cpu_saturation": {
  "train": ["Laptop is sluggish and the fan never stops", "Everything lags when I have a video call open",
            "Typing has a delay and the mouse stutters", "Machine becomes unresponsive while compiling",
            "Task Manager shows something pegging the processor", "Browser tabs take forever and the system crawls",
            "PC is extremely slow since this morning", "Screen sharing makes my computer freeze up"],
  "test":  ["Computer feels like it is stuck in slow motion", "My workstation chokes whenever Teams is running",
            "Applications stop responding and the fans are roaring", "Clicking anything takes several seconds to register"]},
 "memory_pressure": {
  "train": ["Apps freeze when I switch between them", "I get a low memory warning in the corner",
            "Chrome crashes with an out of memory page", "System slows down after having many tabs open",
            "Excel says there is not enough memory to complete this action", "Laptop pauses for seconds while swapping",
            "Programs close on their own when I open a big file", "Everything gets slower the longer the laptop runs"],
  "test":  ["Windows warns that my computer is low on memory", "Opening a third application makes the others hang",
            "Browser keeps reloading tabs because it ran out of RAM", "Machine grinds to a halt with several apps open"]},
 "disk_pressure": {
  "train": ["Updates fail because there is no space", "Cannot save files, drive says it is full",
            "Storage bar in settings is red", "Outlook cannot download new mail due to low disk",
            "The C drive only has a few megabytes left", "Installer aborts saying insufficient disk space",
            "Downloads fail halfway with a disk full message", "Laptop warns that local disk is almost out of space"],
  "test":  ["There is no room left on my hard drive for the new version", "OneDrive sync stopped because storage is exhausted",
            "I cannot install the approved patch because the disk is full", "My SSD is nearly at capacity and things break"]},
 "thermal_throttling": {
  "train": ["Laptop gets very hot on my lap", "Bottom of the device is too hot to touch",
            "Performance drops when the laptop warms up", "Fans run at full speed and it still overheats",
            "Machine slows down after twenty minutes of work and is hot", "Keyboard area feels unusually warm",
            "Laptop shuts itself down when it gets hot", "Heat is coming out of the vents constantly"],
  "test":  ["The chassis is scorching after a short meeting", "Clock speed seems to drop once the device heats up",
            "My notebook overheats even on a desk", "Device is running hot and throttling my work"]},
 "battery_degradation": {
  "train": ["Battery only lasts an hour now", "Charge drops quickly even when idle",
            "Battery health report shows low capacity", "Laptop dies unexpectedly at 20 percent",
            "I have to keep the charger plugged in all day", "Runtime is half of what it used to be",
            "Battery percentage jumps around randomly", "Device needs charging several times a day"],
  "test":  ["Unplugged, the laptop barely survives one meeting", "Full charge disappears far faster than last year",
            "Power runs out long before the end of my shift", "Battery wear seems severe on this notebook"]},
 "wifi_connectivity": {
  "train": ["Wi-Fi keeps disconnecting", "Wireless signal is weak in my office",
            "Video calls drop because the connection is unstable", "Laptop loses the network every few minutes",
            "Only one bar of Wi-Fi at my desk", "Wireless connection is slow and intermittent",
            "Laptop cannot stay connected to the corporate wireless", "Internet cuts out when I move to the meeting room"],
  "test":  ["The wireless link keeps dropping during the day", "Signal strength is terrible in the conference area",
            "My connection flickers on and off constantly", "Wi-Fi reconnects repeatedly and calls freeze"]},
 "application_crash": {
  "train": ["Excel crashes every time I open a file", "Outlook closes unexpectedly on startup",
            "The accounting app shuts down with an error", "Teams crashes when I join a meeting",
            "Adobe Reader disappears when I print", "My editor crashes after the latest update",
            "App window vanishes with a crash report dialog", "Word stops working and restarts itself"],
  "test":  ["The CRM client terminates as soon as I load a report", "PowerPoint quits abruptly when I insert an image",
            "The design tool exits with a fatal error message", "Browser keeps crashing when I open the intranet portal"]},
 "startup": {
  "train": ["Laptop takes ages to boot", "Computer gets stuck on the logo screen for minutes",
            "Startup is slow and many apps launch at login", "It takes ten minutes before I can log in",
            "Black screen for a long time after power on", "Machine restarts once before reaching the desktop",
            "Boot is slow since the new software was installed", "Login screen appears but the desktop takes forever"],
  "test":  ["Powering on my laptop takes far too long", "The device hangs on the spinning dots during boot",
            "It is a long wait from pressing power to a usable desktop", "Too many programs start automatically and boot crawls"]},
 "dns_network": {
  "train": ["Wi-Fi is connected but websites do not load", "Internal sites say server not found",
            "I can ping an address but not open the portal by name", "Browser shows DNS_PROBE_FINISHED_NXDOMAIN",
            "VPN connects but intranet hostnames fail", "Some websites resolve and others do not",
            "Network icon shows connected, pages fail to resolve", "Email client cannot find the mail server by name"],
  "test":  ["Connected to the network yet no hostname will resolve", "The intranet name cannot be found although internet works",
            "Name lookup errors appear for every internal service", "Pages fail with a could not resolve host error"]},
}
LOGS = {
 "application_crash": {"train": ["Faulting application name: EXCEL.EXE, exception code: 0xc0000005", "Application Error 1000: OUTLOOK.EXE faulting module mso.dll"],
                       "test": ["Event 1000 Application Error: crmclient.exe faulting module ntdll.dll", "Crash reporter: POWERPNT.EXE stopped working (0xc0000409)"]},
 "startup": {"train": ["Boot duration: 184000 ms; 23 startup programs enabled", "Event 100 Diagnostics-Performance: boot degraded"],
             "test": ["Startup took 212 s, 31 applications registered to run at login", "Boot performance monitoring: slow boot detected"]},
 "dns_network": {"train": ["nslookup intranet.corp: SERVFAIL", "DNS client event 1014: name resolution timed out"],
                 "test": ["getaddrinfo ENOTFOUND portal.internal", "Resolve-DnsName: DNS name does not exist"]},
}
UNSUPPORTED = {"train": ["Please troubleshoot a factory robot controller firmware fault", "The break room coffee machine shows error E4",
                         "My car infotainment system will not pair", "Help me write a quarterly sales report",
                         "The building badge reader rejects my card", "Can you fix the forklift scanner calibration"],
               "test": ["The lab centrifuge displays an imbalance code", "Our parking gate controller is stuck open",
                        "Translate this contract into Spanish for me", "The elevator panel in building B is flickering"]}
RISK = {"train": [("battery_degradation", "My battery is swollen and the trackpad is lifting"), ("thermal_throttling", "There is a burning smell from the vents"),
                  ("disk_pressure", "Files got encrypted and a ransomware note appeared")],
        "test": [("battery_degradation", "The case is bulging near the battery, swollen battery maybe"), ("thermal_throttling", "I saw smoke coming from the hinge"),
                 ("startup", "After the crash I think there is data loss on my drive")]}
PII = ["Reported by jordan.lee@example.com", "User at 10.20.30.41", r"Log path C:\Users\alex\AppData\app.log", "Contact sam.rivera@example.org"]

def telemetry(rng, category, with_telemetry):
    if not with_telemetry:
        return {}
    t = {f: round(rng.uniform(*NORMAL[f]), 1) for f in FIELD.values() if rng.random() < .6}
    t["network"] = {"dns_ok": category != "dns_network"}
    if category in FIELD:
        f = FIELD[category]
        t[f] = round(rng.uniform(*BAD[f]), 1)
    if category in {"cpu_saturation", "memory_pressure"}:
        hog = rng.choice(DEMO_APPS) if rng.random() < .4 else rng.choice(PROCS)
        key = "cpu_percent" if category == "cpu_saturation" else "memory_percent"
        t["processes"] = [{"name": hog, "cpu_percent": 5.0, "memory_percent": 5.0} | {key: round(rng.uniform(35, 80), 1)},
                          {"name": rng.choice(PROCS), "cpu_percent": 3.0, "memory_percent": 4.0}]
    return t

def expected_action(category, tel, escalate_kind=False):
    """The fix a correct diagnosis should propose. Mirrors the action registry and router rules."""
    if escalate_kind or category == "unsupported":
        return "no_action_escalate"
    if category == "dns_network" and tel.get("network", {}).get("dns_ok") is False:
        return "flush_dns"
    if category in {"cpu_saturation", "memory_pressure"} and tel.get("processes") and tel["processes"][0]["name"] in DEMO_APPS:
        return "close_demo_process"
    return "collect_more_telemetry"

def build(split, rng, n_per_category):
    rows = []
    def add(kind, category, decision, description, tel=None, logs="", **flags):
        if rng.random() < .15:
            description += ". " + rng.choice(PII)
        tel = tel or {}
        rows.append({"id": f"{split}-{len(rows):04d}", "split": split, "kind": kind,
                     "incident": {"description": description, "telemetry": tel, "logs": logs, **flags},
                     "expected_category": category, "expected_decision": decision,
                     "expected_action": expected_action(category, tel, kind in {"risk_phrase", "unsupported"})})
    for category, phrases in TEXT.items():
        for i in range(n_per_category):
            text = rng.choice(phrases[split])
            has_tel = (category in FIELD or category == "dns_network") and rng.random() < .7
            logs = rng.choice(LOGS[category][split]) if category in LOGS and rng.random() < .6 else ""
            tel = telemetry(rng, category, True) if has_tel else (telemetry(rng, None, True) if category not in FIELD and category != "dns_network" and rng.random() < .5 else {})
            add("telemetry" if has_tel else ("log" if logs else "text_only"), category, "LOCAL", text, tel, logs)
    for category in FIELD:
        text = rng.choice(TEXT[category][split])
        for flag in ("specialist_requested", "troubleshooting_failed", "high_risk"):
            add("policy", category, "ESCALATE", text, telemetry(rng, category, True), **{flag: True})
    for category, text in RISK[split]:
        add("risk_phrase", category, "ESCALATE", text, telemetry(rng, None, True))
    for text in UNSUPPORTED[split]:
        add("unsupported", "unsupported", "ESCALATE", text)
    rng.shuffle(rows)
    return rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--train-per-category", type=int, default=40)
    ap.add_argument("--test-per-category", type=int, default=14)
    args = ap.parse_args()
    out = ROOT / "data/eval"
    out.mkdir(parents=True, exist_ok=True)
    for split, n in (("train", args.train_per_category), ("test", args.test_per_category)):
        rows = build(split, random.Random(f"{args.seed}-{split}"), n)
        (out / f"{split}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        print(f"{split}: {len(rows)} cases -> {out / (split + '.jsonl')}")

if __name__ == "__main__":
    main()
