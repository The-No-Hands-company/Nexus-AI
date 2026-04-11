# Nexus Cloud: Public Address Issuance Flow

This document describes how Nexus Cloud mints public addresses (websites/domains/emails/custom addresses) and how the other tools consume them. The core idea:

1. A tool registers with the Systems API and asks for a website address via `/api/v1/addresses` or `/api/v1/public-url`.
2. Nexus Cloud issues a canonical address record, creates an exposure record, and stores the history.
3. Other tools such as Hosting, AI, Computer, Vault, and Deploy read these records from `/api/v1/addresses`, `/api/v1/exposures`, `/api/v1/domains`, and optionally verify them via `/api/v1/domains/:domain/verify`.

## Sample issuance request

```bash
CLOUD="https://nexus.cloud"
TOKEN="Bearer ${NEXUS_CLOUD_TOKEN}"

curl -s -X POST "${CLOUD}/api/v1/public-url" \
  -H "Authorization: ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"toolId":"nexus-hosting","desiredHost":"node123.nexus.local"}'
```

Successful response:

```json
{
  "publicUrl": {
    "toolId": "nexus-hosting",
    "url": "https://node123.nexus.local",
    "status": "active",
    "issuedAt": "2026-05-01T12:00:00Z",
    "expiresAt": "..."
  },
  "tool": { ... }
}
```

## Consuming the issuance data

- **Hosting** uses `/api/v1/addresses` + exposures to know which hostnames are live for each site. After Deploy publishes, Hosting calls `/api/v1/domains` with `toolId` to bind custom domains, then polls `/api/v1/domains/:domain` to verify.
- **AI** can fetch `/api/v1/addresses` for tool discovery, enabling it to link public addresses back to the tool that owns them (for cross-tool composition).
- **Computer** fetches `/api/v1/public-url` to display edge-running endpoints for users and ensure local servers are reachable.
- **Vault** stores token metadata and uses `/api/v1/addresses` to map generated secrets to public hostnames before sharing them with tooling.
- **Deploy** registers every managed deployment via `/api/v1/deployments`, then continues to consume `/api/v1/addresses` when generating preview URLs.

## Verifying the contract

Every consuming tool should:

1. Read the address/exposure record via `/api/v1/addresses` or `/api/v1/exposures`.
2. Confirm `status === "active"` before surfacing the URL.
3. Call `/api/v1/domains/:domain` (if binding a custom domain) and check `target.status` changes from `pending` → `verified`.
4. Emit logs tracing `exposure.target.publicUrl`, `domain.publicUrl`, and `registry.domainCount`.

Use `bin/verify-address-contract.sh` (coming) to validate your tool against the Harness once published.