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
