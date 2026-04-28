# Nexus AI SDKs

This directory contains thin first-party SDK clients for rapid adoption:

- `sdk/python/nexus_ai_sdk` : Python client
- `sdk/typescript` : TypeScript client
- `sdk/go` : Go client

All SDKs target the OpenAI-compatible and agent/autonomy parity routes:

- `POST /v1/chat/completions`
- `POST /v1/agent`
- `POST /v1/autonomy/plan`
- `GET /v1/models`

## Release process

SDK publication is release-tag driven and validated before publish:

- Python: tag `sdk/python/vX.Y.Z`
- TypeScript: tag `sdk/typescript/vX.Y.Z`
- Go: tag `sdk/go/vX.Y.Z`

The release workflow verifies that the tag version matches package metadata, runs package-specific validation, builds publishable artifacts, and only then publishes or announces the release target.

Operator runbook: `docs/production-readiness/sdk_release_process.md`

## Quick usage

Python:

```python
from nexus_ai_sdk import NexusAIClient

client = NexusAIClient(base_url="http://localhost:8000", api_key="")
print(client.list_models())
```

TypeScript:

```ts
import { NexusAIClient } from "./src/client";

const client = new NexusAIClient("http://localhost:8000");
const out = await client.listModels();
console.log(out);
```

Go:

```go
client := nexusai.NewClient("http://localhost:8000", "")
resp, err := client.AutonomyPlan("Plan a release", 6)
```
