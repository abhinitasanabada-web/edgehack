# DNS failure

## Symptoms
Wi-Fi is connected but hostnames do not resolve.

## Evidence to collect
DNS lookup result, gateway reachability, adapter state, and recent network errors.

## Likely causes
Stale resolver cache, unavailable DNS server, VPN policy, or captive portal.

## Safe diagnostic commands
`Resolve-DnsName example.com`, `ipconfig /all`, and a gateway ping.

## Approved fixes
`flush_dns` or `restart_dns_client` after confirmation.

## Verification steps
Resolve the same hostname again and compare before/after.

## When to escalate
Escalate when DNS still fails after the approved fix or policy/VPN evidence is present.

