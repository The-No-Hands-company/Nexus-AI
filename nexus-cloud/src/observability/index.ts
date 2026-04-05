export type SignalKind = "metrics" | "logs" | "traces" | "audit";

export type ObservabilityEvent = {
  kind: SignalKind;
  subjectId: string;
  message: string;
  timestamp: string;
};

export const observability = {
  signals: ["metrics", "logs", "traces", "audit"] as SignalKind[],
};
