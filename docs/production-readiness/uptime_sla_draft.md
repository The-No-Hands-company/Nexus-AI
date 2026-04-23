# Uptime SLA Draft (Starter)

## Gate Progress

- Current gate: `G3` (External engagement started)
- Evidence timestamp: `2026-04-23`
- Engagement record:
	- Legal/finance review packet moved to active external engagement queue.
	- Draft SLA language and credit policy prepared for counterpart review kickoff.
	- Publication pathway dependencies shared with external process owners.

## Service Commitment (Draft)

- Monthly uptime target: 99.9%
- Measurement scope: production API request success and availability window
- Exclusions: scheduled maintenance, force majeure, upstream provider outages beyond contractual control

## User-Facing Communication Baseline

- Status page must expose current operational state with clear labels: Operational, Degraded, Major Outage.
- Incident communication should include impact scope, start time, mitigation status, and next update ETA.
- Publish uptime target text consistently in user-facing surfaces so expectations match actual SLA draft.
- Do not claim finalized SLA terms publicly until legal and finance approvals are complete.

## Measurement Inputs

1. `/health` and deep-health probes
2. Request success/error metrics from observability pipeline
3. Incident timeline records from alerting and on-call logs

## Customer Credit Framework (Draft)

- <99.9% and >=99.0%: 10% service credit
- <99.0% and >=95.0%: 25% service credit
- <95.0%: 50% service credit

## Exit Criteria to Promote From Partial

- Legal review complete
- Finance approval of credit policy
- Public publication endpoint/page approved
