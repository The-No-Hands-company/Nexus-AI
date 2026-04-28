/**
 * NexusOperator — Production operator wrapper with retry, defaults, and health check.
 *
 * Wraps NexusAIClient and adds:
 * - Exponential backoff retry on transient errors (5xx, 429, network failures)
 * - Environment-variable configuration (NEXUS_BASE_URL, NEXUS_API_KEY, etc.)
 * - Optional health verification at construction time
 * - Singleton default instance
 * - Dataset benchmark helpers wired to the new /benchmark/dataset endpoints
 */

import { NexusAIClient, NexusAIError } from "./client.js";

export interface RetryConfig {
  maxAttempts: number;
  baseDelayMs: number;
  maxDelayMs: number;
  jitter: number;
  retryableStatus: Set<number>;
}

const DEFAULT_RETRY: RetryConfig = {
  maxAttempts: 3,
  baseDelayMs: 500,
  maxDelayMs: 30_000,
  jitter: 0.1,
  retryableStatus: new Set([429, 500, 502, 503, 504]),
};

export interface OperatorConfig {
  baseUrl?: string;
  apiKey?: string;
  timeoutMs?: number;
  verifyHealth?: boolean;
  healthTimeoutMs?: number;
  retry?: Partial<RetryConfig>;
  defaultModel?: string;
  defaultProvider?: string;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function backoffDelay(attempt: number, cfg: RetryConfig): number {
  const raw = cfg.baseDelayMs * Math.pow(2, attempt);
  const capped = Math.min(raw, cfg.maxDelayMs);
  const jitterAmt = capped * cfg.jitter * (2 * Math.random() - 1);
  return Math.max(0, capped + jitterAmt);
}

export class NexusOperator {
  private static _default: NexusOperator | null = null;

  readonly config: Required<OperatorConfig> & { retry: RetryConfig };
  readonly client: NexusAIClient;

  constructor(config: OperatorConfig = {}) {
    const baseUrl =
      config.baseUrl ??
      (typeof process !== "undefined" ? process.env["NEXUS_BASE_URL"] ?? "http://localhost:8000" : "http://localhost:8000");
    const apiKey =
      config.apiKey ??
      (typeof process !== "undefined" ? process.env["NEXUS_API_KEY"] ?? "" : "");

    this.config = {
      baseUrl,
      apiKey,
      timeoutMs: config.timeoutMs ?? 60_000,
      verifyHealth: config.verifyHealth ?? false,
      healthTimeoutMs: config.healthTimeoutMs ?? 10_000,
      retry: { ...DEFAULT_RETRY, ...(config.retry ?? {}) },
      defaultModel:
        config.defaultModel ??
        (typeof process !== "undefined" ? process.env["NEXUS_DEFAULT_MODEL"] ?? "" : ""),
      defaultProvider:
        config.defaultProvider ??
        (typeof process !== "undefined" ? process.env["NEXUS_DEFAULT_PROVIDER"] ?? "" : ""),
    };

    this.client = new NexusAIClient(baseUrl, apiKey);
  }

  static default(config?: OperatorConfig): NexusOperator {
    if (!NexusOperator._default) {
      NexusOperator._default = new NexusOperator(config);
    }
    return NexusOperator._default;
  }

  static resetDefault(): void {
    NexusOperator._default = null;
  }

  private async withRetry<T>(fn: () => Promise<T>): Promise<T> {
    const { retry } = this.config;
    let lastError: unknown;
    for (let attempt = 0; attempt < retry.maxAttempts; attempt++) {
      try {
        return await fn();
      } catch (err) {
        lastError = err;
        const shouldRetry =
          err instanceof NexusAIError
            ? retry.retryableStatus.has(err.status)
            : true;
        if (!shouldRetry || attempt === retry.maxAttempts - 1) break;
        await sleep(backoffDelay(attempt, retry));
      }
    }
    throw lastError;
  }

  // ── Health ──────────────────────────────────────────────────────────────────

  async health(): Promise<Record<string, unknown>> {
    return this.withRetry(() => this.client["request"]("GET", "/health", undefined));
  }

  async isHealthy(): Promise<boolean> {
    try {
      const h = await this.health();
      const status = String(h["status"] ?? "").toLowerCase();
      return ["ok", "healthy", "ready"].includes(status);
    } catch {
      return false;
    }
  }

  // ── Chat ────────────────────────────────────────────────────────────────────

  chat(
    messages: { role: string; content: string }[],
    model?: string,
    stream = false,
  ): Promise<Record<string, unknown>> {
    const m = model ?? this.config.defaultModel;
    return this.withRetry(() => this.client.chatCompletions(m, messages, stream));
  }

  // ── Agent ───────────────────────────────────────────────────────────────────

  runAgent(
    task: string,
    sessionId = "",
    history: unknown[] = [],
  ): Promise<Record<string, unknown>> {
    return this.withRetry(() => this.client.runAgent(task, sessionId, history));
  }

  // ── Dataset benchmarks ──────────────────────────────────────────────────────

  benchmarkDataset(params: {
    dataset: string;
    provider?: string;
    model?: string;
    maxSamples?: number;
  }): Promise<Record<string, unknown>> {
    return this.withRetry(() =>
      this.client["request"]("POST", "/benchmark/dataset/run", {
        dataset: params.dataset,
        provider: params.provider ?? this.config.defaultProvider,
        model: params.model ?? this.config.defaultModel,
        max_samples: params.maxSamples ?? 10,
      }),
    );
  }

  benchmarkDatasetSuite(params: {
    datasets?: string[];
    provider?: string;
    model?: string;
    maxSamplesPerDataset?: number;
  } = {}): Promise<Record<string, unknown>> {
    return this.withRetry(() =>
      this.client["request"]("POST", "/benchmark/dataset/suite", {
        datasets: params.datasets ?? null,
        provider: params.provider ?? this.config.defaultProvider,
        model: params.model ?? this.config.defaultModel,
        max_samples_per_dataset: params.maxSamplesPerDataset ?? 10,
      }),
    );
  }

  benchmarkExport(runId: string, formats?: string[]): Promise<Record<string, unknown>> {
    const qs = formats ? `?formats=${formats.join(",")}` : "";
    return this.withRetry(() =>
      this.client["request"]("GET", `/benchmark/export/${runId}${qs}`, undefined),
    );
  }

  // ── Compatibility check ─────────────────────────────────────────────────────

  async checkCompatibility(): Promise<{
    sdkVersion: string;
    nodeVersion: string;
    serverReachable: boolean;
    serverVersion: string;
    apiVersion: string;
  }> {
    const nodeVersion =
      typeof process !== "undefined" ? process.version : "unknown";
    let serverReachable = false;
    let serverVersion = "";
    let apiVersion = "";

    try {
      const h = await this.health();
      serverReachable = true;
      serverVersion = String(h["version"] ?? "");
      apiVersion = String(h["api_version"] ?? "v1");
    } catch {
      serverReachable = false;
    }

    return {
      sdkVersion: "0.2.0",
      nodeVersion,
      serverReachable,
      serverVersion,
      apiVersion,
    };
  }
}
