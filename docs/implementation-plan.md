# Nexus Cloud Implementation Plan

## Goal
Build Nexus Cloud as a thin orchestration layer that keeps product apps portable, federated, and self-hostable.

## Phase 1: Core control plane
Own the smallest useful core first:

1. Identity and trust
2. Node registration
3. Scheduling
4. Policy and quota checks
5. Placement decisions

### Exit criteria
- A node can register and be stored in state
- A workload can be accepted, validated, and planned
- The control plane code is split into real modules instead of living in the HTTP handler

## Phase 2: API extraction
Make the HTTP entrypoint thin:

- `src/server.ts` only starts the server
- `src/api/router.ts` owns request routing
- business logic lives in control-plane and federation modules
- route metadata stays in `src/api/index.ts`

### Exit criteria
- `src/server.ts` is mostly wiring
- endpoint behavior is unchanged after the refactor
- API and domain logic are independently testable

## Phase 3: Federation trust
Add first-class peer trust handling:

- peer records
- signed request metadata
- trust renewal and expiry
- future routing hooks

## Phase 4: Observability and state
Expand the operator surface:

- health checks
- audit events
- placement visibility
- workload and peer snapshots

## Phase 5: Storage and runtime expansion
Add the rest of the substrate:

- storage classes and attachments
- runtime adapters
- policy enforcement
- richer scheduling inputs
