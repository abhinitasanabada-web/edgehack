# 5-minute demo run sheet

Driven from a laptop over the private tunnel to the Nano (dashboard on Nano port 8501). Rehearse twice. Record a
backup video of the full run the evening before, in case the pitch room isn't on the SJSU network.

## Before you walk in (T-30 min)

- ZRT is serving the model. `.env` has the demo configuration from `docs/NANO_RUNBOOK.md` step 4.
- `bash run_demo.sh`, forward port 8501, and open the dashboard. Check that no SIMULATION banner is showing.
- Warm the model up with one throwaway ticket.
- Open the deck (`docs/presentation/index.html`, with results embedded) in a second tab.

Paste each ticket into **What is happening?** and **Telemetry JSON**:

| # | Complaint | Telemetry JSON | Logs |
|---|---|---|---|
| 1 | `Apps freeze whenever I switch between them` | `{"memory_percent":94,"network":{"dns_ok":true},"processes":[{"name":"notepad","cpu_percent":3,"memory_percent":61}]}` | |
| 2 | `Wi-Fi is connected but no website opens by name` | `{"network":{"dns_ok":false}}` | `Resolve-DnsName: DNS name does not exist` |
| 3 | `There is a burning smell from the vents and it is very hot` | `{"temperature_c":93}` | |
| 4 | `Something is wrong with my computer, it is acting weird` | `{}` | |
| 5 | `Everything is slow today` | `{"memory_percent":88}` | |

## The run

| Time | Beat | What you do | What you say |
|---|---|---|---|
| 0:00 | **The user** | Dashboard | "A Tier-1 help-desk tech supports hundreds of laptops. The telemetry they need has e-mails, user paths and IPs that shouldn't leave the building, and the #1 ticket, 'websites won't load', is exactly when a cloud assistant can't be reached." |
| 0:30 | **Routine, answered on site** | Ticket 1 | Point at the decision panel: evidence checked ✅, "3 of 3 agree" ✅, safety gates ✅, *Kept on site*. "The model was asked three times in one request. It cited the memory signal and the runbook. Nothing left the Nano." |
| 1:20 | **Self-heal (if a Windows laptop is ready)** | Ticket 2 via `windows_collector.ps1 -AutoApply` | The endpoint prompts for `APPLY`, flushes DNS, and verification shows `dns_ok` false → true. "The fix runs only on the endpoint, only from an allowlist, only after a person types APPLY, and only for a LOCAL route." Without Windows, run ticket 2 in the dashboard and show `flush_dns` as the allowed action. |
| 2:10 | **Risk goes to a person** | Ticket 3 | "Burning smell trips a hard gate. It goes to a person, and no model confidence can override that." |
| 2:40 | **Doesn't guess** | Tickets 4 and 5 | Ticket 4: vague, no evidence → *Needs a second opinion*. Ticket 5: memory 88% is under the threshold, so the telemetry doesn't back the complaint → defers. Open **What would leave the building**: redaction markers and the byte count. |
| 3:30 | **Uplink cut** | Restart with `FORCE_OFFLINE=true bash run_demo.sh`, rerun ticket 1 | Banner: *Uplink DOWN*. The answer still arrives on site. The cloud button refuses: "nothing was sent". |
| 4:00 | **Evidence** | Deck → routing slide | Toggle *any* / *majority* and drag τ. "On held-out tickets we answer X% on site with Y% error and zero unsafe accepts. The threshold was locked on a separate calibration split." Then the A/B chart: "strict schema + BM25 moved on-site answers from A% to B% without training." |
| 4:40 | **Close** | Impact slide | "One Nano per site: most tickets answered in seconds, the telemetry stays home, and every escalation comes with a reason code." |

## If something breaks

| Symptom | Live fix |
|---|---|
| Dashboard says API unavailable | `bash run_demo.sh` again (it checks the port). |
| Model errors (502) | ZRT stopped: `zrt status`. Meanwhile, run `SIMULATION_MODE=true bash run_demo.sh` and say so out loud. |
| Slow answers | Lower `LOCAL_SAMPLE_COUNT` to 3 and `MAX_OUTPUT_TOKENS` to 450, and restart. |
| The Nano rebooted | Someone at the lab runs `sudo tailscale up`. Play the backup video. |
