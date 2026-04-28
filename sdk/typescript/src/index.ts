/**
 * @nexus-ai/sdk — Official TypeScript SDK for the Nexus AI API
 *
 * @example
 * ```typescript
 * import { NexusAIClient, NexusOperator } from "@nexus-ai/sdk";
 *
 * // Simple client
 * const client = new NexusAIClient("http://localhost:8000", "sk-...");
 * const response = await client.chatCompletions("gpt-4o", [{ role: "user", content: "Hello!" }]);
 *
 * // Production operator (retry, env-var config, health check)
 * const op = NexusOperator.default();
 * const result = await op.benchmarkDataset({ dataset: "gsm8k", maxSamples: 10 });
 * ```
 */

export {
  // Client types
  NexusAIClient,
  NexusAIError,
  type ChatMessage,
  type StreamChunk,
  type AgentTrace,
  type AgentListing,
  type BenchmarkHistoryParams,
} from "./client.js";

export {
  NexusOperator,
  type OperatorConfig,
  type RetryConfig,
} from "./operator.js";

export const SDK_VERSION = "0.2.0";
export const API_VERSION = "v1";
