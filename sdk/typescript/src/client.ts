// ── Types ─────────────────────────────────────────────────────────────────────

export type ChatMessage = { role: string; content: string };

export interface StreamChunk {
  delta: string;
  finishReason?: string;
  raw: Record<string, unknown>;
}

export interface AgentTrace {
  traceId: string;
  steps: Record<string, unknown>[];
  status: string;
  raw: Record<string, unknown>;
}

export interface AgentListing {
  agentId: string;
  name: string;
  description: string;
  capabilities: string[];
  raw: Record<string, unknown>;
}

export interface BenchmarkHistoryParams {
  provider?: string;
  model?: string;
  taskType?: string;
  limit?: number;
}

// ── Error ─────────────────────────────────────────────────────────────────────

export class NexusAIError extends Error {
  status: number;

  constructor(message: string, status = 500) {
    super(message);
    this.name = "NexusAIError";
    this.status = status;
  }
}

// ── Client ────────────────────────────────────────────────────────────────────

export class NexusAIClient {
  private readonly baseUrl: string;
  private readonly apiKey?: string;

  constructor(baseUrl: string, apiKey?: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.apiKey = apiKey;
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.apiKey) h.Authorization = `Bearer ${this.apiKey}`;
    return h;
  }

  private async request<T>(method: string, path: string, payload?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: this.headers(),
      body: payload !== undefined ? JSON.stringify(payload) : undefined,
    });
    if (!response.ok) {
      throw new NexusAIError(`${method} ${path} failed: ${response.status}`, response.status);
    }
    if (response.status === 204) return {} as T;
    return (await response.json()) as T;
  }

  private async *streamLines(response: Response): AsyncGenerator<StreamChunk> {
    if (!response.body) return;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const dataStr = line.slice(6).trim();
        if (dataStr === "[DONE]") return;
        try {
          const obj = JSON.parse(dataStr) as Record<string, unknown>;
          const choices = (obj.choices as Record<string, unknown>[] | undefined) ?? [];
          const choice = choices[0] ?? {};
          const delta = ((choice.delta as Record<string, unknown> | undefined)?.content as string | undefined) ?? "";
          yield { delta, finishReason: choice.finish_reason as string | undefined, raw: obj };
        } catch {
          // skip malformed SSE lines
        }
      }
    }
  }

  // ── Chat ───────────────────────────────────────────────────────────────────

  chatCompletions(model: string, messages: ChatMessage[], stream = false): Promise<Record<string, unknown>> {
    return this.request("POST", "/v1/chat/completions", { model, messages, stream });
  }

  async *chatStream(model: string, messages: ChatMessage[]): AsyncGenerator<StreamChunk> {
    const response = await fetch(`${this.baseUrl}/v1/chat/completions`, {
      method: "POST", headers: this.headers(),
      body: JSON.stringify({ model, messages, stream: true }),
    });
    if (!response.ok) throw new NexusAIError(`POST /v1/chat/completions failed: ${response.status}`, response.status);
    yield* this.streamLines(response);
  }

  // ── Agent ──────────────────────────────────────────────────────────────────

  runAgent(task: string, sessionId = "", history: unknown[] = []): Promise<Record<string, unknown>> {
    return this.request("POST", "/v1/agent", { task, session_id: sessionId, history });
  }

  async *streamAgent(task: string, sessionId = "", history: unknown[] = []): AsyncGenerator<StreamChunk> {
    const response = await fetch(`${this.baseUrl}/agent/stream`, {
      method: "POST", headers: this.headers(),
      body: JSON.stringify({ task, session_id: sessionId, history }),
    });
    if (!response.ok) throw new NexusAIError(`POST /agent/stream failed: ${response.status}`, response.status);
    yield* this.streamLines(response);
  }

  async getAgentTrace(traceId: string): Promise<AgentTrace> {
    const data = await this.request<Record<string, unknown>>("GET", `/agent/trace/${traceId}`);
    return {
      traceId,
      steps: (data.steps as Record<string, unknown>[]) ?? [],
      status: (data.status as string) ?? "unknown",
      raw: data,
    };
  }

  stopAgent(streamId: string): Promise<Record<string, unknown>> {
    return this.request("POST", `/agent/stop/${streamId}`);
  }

  // ── Agent marketplace ──────────────────────────────────────────────────────

  async listAgents(): Promise<AgentListing[]> {
    const data = await this.request<Record<string, unknown>>("GET", "/agents");
    const agents = ((data.agents ?? data.data) as Record<string, unknown>[]) ?? [];
    return agents.map((a) => ({
      agentId: String(a.id ?? a.agent_id ?? ""),
      name: String(a.name ?? ""),
      description: String(a.description ?? ""),
      capabilities: (a.capabilities as string[]) ?? [],
      raw: a,
    }));
  }

  getAgent(agentId: string): Promise<Record<string, unknown>> {
    return this.request("GET", `/agents/${agentId}`);
  }

  runNamedAgent(agentId: string, task: string, extra?: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("POST", `/agents/${agentId}/run`, { task, ...extra });
  }

  // ── Autonomy ───────────────────────────────────────────────────────────────

  autonomyPlan(goal: string, maxSubtasks = 6): Promise<Record<string, unknown>> {
    return this.request("POST", "/v1/autonomy/plan", { goal, max_subtasks: maxSubtasks });
  }

  autonomyExecute(plan: Record<string, unknown>, stream = false): Promise<Record<string, unknown>> {
    return this.request("POST", "/autonomy/execute", { ...plan, stream });
  }

  async getAutonomyTrace(traceId: string): Promise<AgentTrace> {
    const data = await this.request<Record<string, unknown>>("GET", `/autonomy/trace/${traceId}`);
    return {
      traceId,
      steps: (data.steps as Record<string, unknown>[]) ?? [],
      status: (data.status as string) ?? "unknown",
      raw: data,
    };
  }

  // ── Models ─────────────────────────────────────────────────────────────────

  listModels(): Promise<Record<string, unknown>> {
    return this.request("GET", "/v1/models");
  }

  // ── Benchmarks ─────────────────────────────────────────────────────────────

  benchmarkRun(providers: string[] = []): Promise<Record<string, unknown>> {
    return this.request("POST", "/benchmark/run", { providers });
  }

  benchmarkRegression(): Promise<Record<string, unknown>> {
    return this.request("GET", "/benchmark/regression");
  }

  benchmarkSetBaseline(baseline: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("POST", "/benchmark/regression/baseline", baseline);
  }

  benchmarkHistory({ provider = "", model = "", taskType = "", limit = 500 }: BenchmarkHistoryParams = {}): Promise<Record<string, unknown>> {
    const qs = new URLSearchParams({ provider, model, task_type: taskType, limit: String(limit) });
    return this.request("GET", `/benchmark/history?${qs}`);
  }

  benchmarkSafety(testCases: Record<string, unknown>[] = []): Promise<Record<string, unknown>> {
    return this.request("POST", "/benchmark/safety", { test_cases: testCases });
  }

  benchmarkDataset(params: {
    dataset: string;
    provider?: string;
    model?: string;
    maxSamples?: number;
  }): Promise<Record<string, unknown>> {
    return this.request("POST", "/benchmark/dataset/run", {
      dataset: params.dataset,
      provider: params.provider ?? "",
      model: params.model ?? "",
      max_samples: params.maxSamples ?? 10,
    });
  }

  benchmarkDatasetSuite(params: {
    datasets?: string[];
    provider?: string;
    model?: string;
    maxSamplesPerDataset?: number;
  } = {}): Promise<Record<string, unknown>> {
    return this.request("POST", "/benchmark/dataset/suite", {
      datasets: params.datasets ?? null,
      provider: params.provider ?? "",
      model: params.model ?? "",
      max_samples_per_dataset: params.maxSamplesPerDataset ?? 10,
    });
  }

  benchmarkDatasetHistory(dataset = "", limit = 50): Promise<Record<string, unknown>> {
    const qs = new URLSearchParams({ dataset, limit: String(limit) });
    return this.request("GET", `/benchmark/dataset/history?${qs}`);
  }

  benchmarkExport(runId: string, formats?: string[]): Promise<Record<string, unknown>> {
    const qs = formats ? `?formats=${formats.join(",")}` : "";
    return this.request("GET", `/benchmark/export/${runId}${qs}`);
  }

  // ── Compliance ─────────────────────────────────────────────────────────────

  getComplianceConfig(): Promise<Record<string, unknown>> {
    return this.request("GET", "/admin/compliance");
  }

  updateComplianceConfig(config: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.request("PUT", "/admin/compliance", config);
  }
}
