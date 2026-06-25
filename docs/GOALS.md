# Nexus AI Goals Bootstrap

Purpose: provide guaranteed startup inputs for autonomous orchestration.

## Mission

Build Nexus AI into a sovereign, self-hosted AI platform with strong safety, reliability, and developer productivity.

## Current Goal

Reach beta reliability and platform hardening with stable autonomous execution loops, strong governance, and production-safe defaults.

## Success Criteria

- Core API contracts remain green in tests.
- Safety and HITL flows are persistent and auditable.
- Planner -> executor -> verifier loop can complete tasks with minimal supervision.
- Critical docs stay aligned with runtime behavior.
- Beta-priority gaps from the roadmap are tracked in the autonomy ledger and sequenced for execution.

## Constraints

- Privacy-first and self-hosted-first by default.
- No secrets committed to repository.
- Prefer additive, low-risk, test-backed changes.

## Priority Backlog

1. HITL approval frontend workflow.
2. Durable job queue for background workflows.
3. Per-user rate limits and quota controls.
4. Production document understanding path.

## Escalation Policy

Escalate to human supervisor when:

- A blocker repeats for 3 iterations.
- Safety/compliance checks conflict with delivery objective.
- Required context is missing or ambiguous.
