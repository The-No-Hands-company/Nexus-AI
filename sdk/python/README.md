# Nexus AI Python SDK

Official Python client for the Nexus AI API.

## Install

```bash
pip install nexus-ai-sdk
```

Async support:

```bash
pip install nexus-ai-sdk[async]
```

## Example

```python
from nexus_ai_sdk import NexusAIClient, NexusOperator

client = NexusAIClient(base_url="http://localhost:8000", api_key="")
print(client.list_models())

operator = NexusOperator.default()
print(operator.health())
```

## Release tag

Python SDK releases are published from tags in the form `sdk/python/vX.Y.Z`.