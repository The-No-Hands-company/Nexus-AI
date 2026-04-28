# Nexus AI Architect Bootstrap

Purpose: define high-level execution architecture for autonomous startup.

## System Shape

- Interface Layer: FastAPI routes and web UI.
- Orchestration Layer: planning, decomposition, scheduling, and state governance.
- Execution Layer: specialist skills that implement and validate tasks.
- Enforcement Layer: safety, privacy, compliance, and approval gates.
- Persistence Layer: SQLite-backed operational state and audit logs.

## Runtime Loop

Supervisor -> Orchestrator -> Autonomizers -> Enforcers -> Orchestrator -> Supervisor

## Role Contract

- Orchestrator plans and delegates; it does not directly perform broad implementation work.
- Autonomizers execute in plan -> code -> test -> fix cycles.
- Enforcers can block unsafe transitions.
- State synchronizer records task and contract changes in shared state.
- Supervisor reporter translates execution into concise status updates.

## Startup Inputs

- Mission source: GOALS.md
- Architecture source: docs/ARCHITECTURE.md and this file
- Execution state: .nexus/state.json
- Validation source: tests/test_v1_contracts.py

## Guardrails

- Keep public API contracts stable unless explicitly versioned.
- Require test evidence for task completion.
- Never bypass safety and approval policies for speed.
- Prefer reversible, incremental changes.
