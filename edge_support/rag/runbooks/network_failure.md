# Network failure

## Symptoms
The endpoint cannot reach expected network services.

## Evidence to collect
Adapter state, gateway reachability, DNS status, and a sanitized error summary.

## Likely causes
Adapter outage, DHCP issue, DNS failure, VPN policy, or upstream outage.

## Approved fixes
Diagnose first; use DNS actions only when DNS evidence supports them.

## Verification steps
Repeat the same connectivity checks after an action.

## When to escalate
Escalate for policy, hardware, authentication, or persistent upstream failures.

