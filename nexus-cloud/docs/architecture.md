# Nexus Cloud Architecture Scaffold

## Project goal

Nexus Cloud is a self-hosted, federated cloud platform for The No Hands Company.

## Core layers

### Control plane

Owns identity, registration, scheduling, policy, quota, and placement.

### Data plane

Runs workloads with clear runtime boundaries and pluggable execution targets.

### Federation layer

Handles trust, discovery, signed routing, and cross-cluster communication.

### Storage layer

Provides object, block, and snapshot storage with replication and retention policies.

### Observability

Tracks metrics, logs, traces, and audit trails for operators.

## Initial API surface

- `GET /health`
- `GET /v1/architecture`
- `POST /v1/nodes/register`
- `POST /v1/workloads/plan`
- `GET /v1/federation/peers`
- `POST /v1/federation/peers/:domain/trust`
