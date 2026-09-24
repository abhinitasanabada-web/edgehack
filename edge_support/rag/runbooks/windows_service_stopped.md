# Windows service stopped

## Symptoms
A required background service is not running.

## Evidence to collect
Service name, startup mode, recent service errors, and dependency state.

## Likely causes
Failed update, dependency failure, policy, or resource pressure.

## Approved fixes
Only the explicitly approved DNS Client restart is available in this prototype.

## Verification steps
Confirm service state and repeat the original operation.

## When to escalate
Escalate for protected services, dependencies, or repeated failure.

