# Nexus Cloud

Self-hosted, federated cloud infrastructure for The No Hands Company.

## Purpose

This repository is the starting point for building a cloud layer that can be run by individuals or communities without relying on hyperscalers.

## Architecture scaffold

- `src/architecture.ts` defines the project shape
- `src/control-plane/` holds identity, scheduling, quota, and policy boundaries
- `src/data-plane/` holds runtime and workload boundaries
- `src/federation/` holds trust and peer routing boundaries
- `src/storage/` holds storage classes and volume models
- `src/observability/` holds metrics, logs, traces, and audit boundaries
- `src/api/` defines the initial API surface
- `src/systems-api/` defines the shared platform contract for tools and services
- `docs/architecture.md` describes the first implementation cut
- `docs/implementation-plan.md` is the living roadmap for current and future work

## Deploy integration

- Set `NEXUS_DEPLOY_URL` and `NEXUS_DEPLOY_TOKEN` in your environment to let Nexus Cloud call Nexus Deploy as a service-to-service client.
- The formal contract is documented in `docs/systems-api-spec.md`.
- A small deploy trigger page is available at `public/deploy.html` for quick operator use.

## Testing

- Run the suite with `bun test src`
- Keep shared test helpers in `src/test/`
- Prefer `*.test.ts` next to the module for DTO and unit coverage
- Use `src/test/` for shared harnesses and cross-module route/service behavior
- Keep the route manifest, router handlers, DTOs, and service behavior covered together when changing the Systems API

## Next steps

- Implement node registration and trust
- Add a scheduler stub
- Define workload and deployment models
- Add a runnable API server skeleton
- Expand the Systems API into tool discovery, status, auth, and exposure contracts
