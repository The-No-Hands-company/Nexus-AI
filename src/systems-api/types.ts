export type SystemsApiVersion = "v1";

export type SystemsApiMode = "standalone" | "orchestrated";

export type SystemsApiEndpoint = {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  description: string;
};

export type SystemsApiCapability = {
  id: string;
  description: string;
};

export type SystemsApiToolHealth = "healthy" | "degraded" | "offline";

export type SystemsApiToolExposure = "private" | "public" | "pending";

export type SystemsApiTool = {
  id: string;
  name: string;
  description: string;
  mode: SystemsApiMode;
  exposed: boolean;
  exposure: SystemsApiToolExposure;
  health: SystemsApiToolHealth;
  capabilities: readonly string[];
  publicUrl?: string;
  registeredAt: string;
  updatedAt: string;
};

export type SystemsApiToolHistoryAction = "registered" | "updated" | "enabled" | "disabled" | "public-url-issued";

export type SystemsApiToolHistoryEntry = {
  toolId: string;
  action: SystemsApiToolHistoryAction;
  summary: string;
  at: string;
};

export type SystemsApiPublicUrlStatus = "active" | "pending" | "revoked";

export type SystemsApiPublicUrl = {
  toolId: string;
  url: string;
  status: SystemsApiPublicUrlStatus;
  issuedAt: string;
  expiresAt: string;
};

export type SystemsApiRegistryMetadata = {
  path: string;
  exists: boolean;
  sizeBytes: number;
  lastWriteAt: string | null;
  ageSeconds: number | null;
};

export type SystemsApiStatus = {
  version: SystemsApiVersion;
  mode: SystemsApiMode;
  toolCount: number;
  exposedToolCount: number;
  healthyToolCount: number;
  publicUrlCount: number;
  registry: SystemsApiRegistryMetadata;
  updatedAt: string;
};

export type SystemsApiSummary = {
  version: SystemsApiVersion;
  scope: string;
  endpoints: readonly SystemsApiEndpoint[];
  capabilities: readonly SystemsApiCapability[];
  toolCount: number;
  status: SystemsApiStatus;
};
