# Nexus-AI Strategy and Guardrails

This document captures execution rules and strategic constraints that should not clutter the main roadmap.

## Product Principle

Nexus-AI should remain zero-friction by default:

- User picks persona/mode and prompts.
- Runtime handles provider/model/routing complexity automatically.
- `PROVIDER=auto` remains the default-first path.

## Execution Guardrails

- Build in dependency order, not feature order.
- Any item that depends on missing contracts is blocked.
- A feature is only marked shipped if concrete code paths exist.
- Prefer provider-agnostic contracts over provider-specific behavior.
- Do not expose provider complexity in the default user flow.

## Delivery Order Rules

1. Foundation contracts first

- Request/response schemas
- Typed error mappings
- Capability metadata
- Tool interfaces

1. Runtime second

- Routing
- Safety middleware
- Orchestration reliability
- Context management

1. UX third

- Dashboards and advanced views only after contracts/runtime stabilize

## Compatibility Rule

Borrow patterns and interfaces from external projects, but avoid lock-in and avoid any UX regressions to the default flow.

## Validation Rule for Checkmarks

Before changing `[ ]` to `[x]`, confirm:

- Endpoint exists and is callable.
- Response shape matches documented contract.
- Error path is typed and deterministic.
- At least one regression/contract test exists.
