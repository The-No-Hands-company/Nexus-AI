# Nexus AI TypeScript SDK

Official TypeScript and JavaScript client for the Nexus AI API.

## Install

```bash
npm install @nexus-ai/sdk
```

## Example

```ts
import { NexusAIClient, NexusOperator } from "@nexus-ai/sdk";

const client = new NexusAIClient("http://localhost:8000", process.env.NEXUS_API_KEY);
console.log(await client.listModels());

const operator = NexusOperator.default();
console.log(await operator.health());
```

## Release tag

TypeScript SDK releases are published from tags in the form `sdk/typescript/vX.Y.Z`.