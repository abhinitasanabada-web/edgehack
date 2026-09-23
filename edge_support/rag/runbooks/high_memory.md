# High memory

## Symptoms
Applications become slow, especially during video calls.

## Evidence to collect
Memory percentage and top processes by memory usage.

## Likely causes
Runaway application, too many browser tabs, or insufficient available memory.

## Safe diagnostic commands
Collect process names and memory counters without changing the endpoint.

## Approved fixes
Close only an explicitly allowlisted demo process after confirmation.

## Verification steps
Collect memory telemetry again and confirm the selected process is gone.

## When to escalate
Escalate if the process is protected, unknown, or memory pressure persists.

