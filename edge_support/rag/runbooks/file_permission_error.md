# File permission error

## Symptoms
An application cannot read or write a file.

## Evidence to collect
Sanitized path category, user role, ACL summary, and application identity.

## Likely causes
ACL change, protected location, lock, or policy restriction.

## Approved fixes
No automatic ACL changes or ownership changes.

## Verification steps
Test access after a reviewed policy change.

## When to escalate
Escalate before changing permissions or handling sensitive files.

