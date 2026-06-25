# Nexus AI Python SDK

Official Python client for the Nexus AI API, providing both synchronous and asynchronous interfaces to interact with the Nexus AI platform.

## Features

- **Full API Coverage**: Access to all Nexus AI endpoints including chat, agents, memory, audio, vision, and more
- **Sync & Async Support**: Both synchronous and asynchronous clients for flexible usage
- **Automatic Retries**: Built-in retry mechanism with exponential backoff
- **Type Hints**: Full type hinting support for IDE autocompletion and static analysis
- **Error Handling**: Comprehensive error handling with specific exception types
- **Compatibility Checking**: Built-in version compatibility validation
- **Operator Pattern**: High-level operator interface for common AI operations

## Installation

### Basic Installation

```bash
pip install nexus-ai-sdk
```

### Async Support

For asynchronous client support:

```bash
pip install nexus-ai-sdk[async]
```

Or install both sync and async:

```bash
pip install nexus-ai-sdk[async]
```

### Development Installation

```bash
pip install -e .
```

## Quick Start

### Synchronous Client

```python
from nexus_ai_sdk import NexusAIClient

# Initialize client
client = NexusAIClient(
    base_url="http://localhost:8000",  # Default: http://localhost:8000
    api_key="your-api-key-here",       # Optional: leave empty for no auth
    timeout=30.0                       # Request timeout in seconds
)

# List available models
models = client.list_models()
print(f"Available models: {len(models)}")

# Chat completion
response = client.chat(
    messages=[{"role": "user", "content": "Hello, how are you?"}],
    model="nexus-ai/auto"
)
print(response.choices[0].message.content)

# Generate image
image_result = client.generate_image(
    prompt="A beautiful sunset over mountains",
    width=512,
    height=512
)
print(f"Image generated: {image_result}")
```

### Asynchronous Client

```python
import asyncio
from nexus_ai_sdk import AsyncNexusAIClient

async def main():
    # Initialize async client
    async with AsyncNexusAIClient(
        base_url="http://localhost:8000",
        api_key="your-api-key-here"
    ) as client:
        
        # Chat completion
        response = await client.chat(
            messages=[{"role": "user", "content": "Hello, how are you?"}],
            model="nexus-ai/auto"
        )
        print(response.choices[0].message.content)

# Run async function
asyncio.run(main())
```

### Using the Operator (High-level Interface)

```python
from nexus_ai_sdk import NexusOperator

# Create operator with default configuration
operator = NexusOperator.default()

# Health check
health = operator.health()
print(f"System healthy: {health.status}")

# Run an agent task
result = operator.run_agent_task(
    task="Summarize the key points of machine learning",
    session_id="my-session-123"
)
print(f"Agent result: {result}")

# Stream agent responses
for chunk in operator.stream_agent_task(
    task="Write a story about a robot learning to paint",
    session_id="my-session-456"
):
    print(chunk.content, end="", flush=True)
```

## API Reference

### NexusAIClient

Main synchronous client for interacting with Nexus AI API.

#### Constructor Parameters

- `base_url` (str): Nexus AI API base URL (default: "http://localhost:8000")
- `api_key` (str): API key for authentication (optional)
- `timeout` (float): Request timeout in seconds (default: 30.0)
- `max_retries` (int): Maximum number of retry attempts (default: 3)
- `backoff_factor` (float): Backoff factor for retry delays (default: 0.3)

#### Key Methods

- `chat(messages, model=None, **kwargs)`: Send chat completion request
- `generate_image(prompt, width=512, height=512, backend="auto")`: Generate image
- `list_models()`: Get list of available models
- `run_agent_task(task, session_id=None, **kwargs)`: Execute agent task
- `stream_agent_task(task, session_id=None, **kwargs)`: Stream agent task responses
- `health()`: Check system health status
- And many more methods covering all Nexus AI API endpoints

### AsyncNexusAIClient

Asynchronous version of NexusAIClient with identical interface but async/await support.

### NexusOperator

High-level interface that simplifies common AI operations with automatic session management, retries, and error handling.

#### Key Methods

- `default()`: Create operator with default configuration
- `health()`: Get system health status
- `run_agent_task(task, **kwargs)`: Execute agent task
- `stream_agent_task(task, **kwargs)`: Stream agent task responses
- `chat(messages, **kwargs)`: Send chat message
- `generate_image(prompt, **kwargs)`: Generate image
- And other convenient methods for common operations

## Error Handling

The SDK provides specific exception types for different error scenarios:

```python
from nexus_ai_sdk import NexusAIError, NexusAIValidationError

try:
    result = client.chat(messages=[{"role": "user", "content": "Hello"}])
except NexusAIValidationError as e:
    print(f"Validation error: {e}")
except NexusAIError as e:
    print(f"API error: {e.status_code} - {e.message}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Configuration

The SDK can be configured via environment variables:

- `NEXUS_AI_BASE_URL`: Override default base URL
- `NEXUS_AI_API_KEY`: Set default API key
- `NEXUS_AI_TIMEOUT`: Set default timeout (seconds)
- `NEXUS_AI_MAX_RETRIES`: Set default max retries

## Development

### Running Tests

```bash
# Install test dependencies
pip install -e .[test]

# Run tests
pytest
```

### Building Distribution

```bash
pip install build
python -m build
```

## Compatibility

The SDK includes automatic version compatibility checking to ensure it works with compatible versions of the Nexus AI backend. Use `assert_compatible()` to manually verify compatibility.

## License

MIT

## Release Tags

Python SDK releases are published from tags in the form `sdk/python/vX.Y.Z`.