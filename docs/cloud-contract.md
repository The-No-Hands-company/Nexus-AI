# Nexus Cloud Public Access Contract

## Purpose

This document defines the sovereign public access flow for Nexus tools. It is the canonical contract for issuing public URLs, binding domains, and coordinating public exposure across the Nexus ecosystem.

## Core principles

- Public access must be issued through Nexus Cloud first.
- Nexus Tunnel is the sovereign transport path for public exposure.
- Cloudflare, ngrok, Tailscale, and similar third-party tunnel systems are not part of the contract.
- Every public tool must advertise its discoverability and client contract explicitly.
- Domain and public URL issuance must be deterministic, auditable, and revocable.

## Contract endpoints

### Discovery

- `GET /api/v1/topology`
- `GET /api/v1/apps`
- `GET /api/v1/connections`
- `GET /api/v1/status`
- `GET /api/v1/summary`

### Public access issuance

- `POST /api/v1/public-url`
- `POST /api/v1/addresses`
- `POST /api/v1/exposures`
- `POST /api/v1/domains`
- `POST /api/v1/domains/:domain/verify`
- `DELETE /api/v1/domains/:domain`
- `POST /api/v1/exposures/:toolId/revoke`
- `POST /api/v1/addresses/:toolId/revoke`

### Deployment bridge

- `POST /api/v1/deployments`
- `GET /api/v1/deployments/integration`

## Public URL flow

1. A tool registers with Nexus Cloud.
2. Nexus Cloud issues or refreshes a public URL.
3. Nexus Cloud creates an exposure record.
4. A domain may be bound to the exposure.
5. Nexus Cloud can revoke the exposure, address, or domain binding.

## Client contract

All tools should expose a client contract that includes:
- base URL
- auth scheme
- discovery endpoint
- registration endpoint
- runtime/client endpoints

## Tool categories

- `platform`
- `application`
- `service`
- `edge`
- `trust`
- `network`

## Notes

This document is the shared reference for any public access or domain feature work across the Nexus stack.
