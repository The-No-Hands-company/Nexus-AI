# Nexus AI Go SDK

Official Go client for the Nexus AI API.

## Module path

```go
import "github.com/the-no-hands-company/nexus-ai/sdk/go/nexusai"
```

## Example

```go
client := nexusai.NewClient("http://localhost:8000", "")
models, err := client.AutonomyPlan("harden a release", 6)
_ = models
_ = err
```

## Release tag

Go SDK releases are published from tags in the form `sdk/go/vX.Y.Z`.