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

export type SystemsApiToolHistoryAction =
  | "registered"
  | "updated"
  | "enabled"
  | "disabled"
  | "public-url-issued"
  | "public-url-revoked"
  | "address-issued"
  | "address-revoked"
  | "exposure-requested"
  | "exposure-activated"
  | "exposure-revoked"
  | "domain-bound"
  | "domain-verified"
  | "domain-revoked";

export type SystemsApiToolHistoryEntry = {
  toolId: string;
  action: SystemsApiToolHistoryAction;
  summary: string;
  at: string;
};

export type SystemsApiExposureStatus = "requested" | "active" | "suspended" | "revoked";

export type SystemsApiExposureRecord = {
  id: string;
  toolId: string;
  canonicalUrl: string;
  publicUrl: string;
  desiredHost?: string;
  status: SystemsApiExposureStatus;
  requestedAt: string;
  activatedAt?: string;
  revokedAt?: string;
  updatedAt: string;
};

export type SystemsApiPublicUrlStatus = "active" | "pending" | "revoked";

export type SystemsApiPublicUrl = {
  toolId: string;
  url: string;
  status: SystemsApiPublicUrlStatus;
  issuedAt: string;
  expiresAt: string;
};

export type SystemsApiAddressKind = "website" | "email" | "server" | "custom";

export type SystemsApiAddressStatus = "requested" | "active" | "revoked";

export type SystemsApiAddress = {
  id: string;
  toolId: string;
  kind: SystemsApiAddressKind;
  subject: string;
  canonicalTarget: string;
  publicAddress: string;
  desiredHost?: string;
  status: SystemsApiAddressStatus;
  requestedAt: string;
  activatedAt?: string;
  revokedAt?: string;
  updatedAt: string;
};

export type SystemsApiAddressRevokeRequest = {
  toolId: string;
  kind?: SystemsApiAddressKind;
};

export type SystemsApiDomainBindingStatus = "pending" | "verified" | "revoked" | "expired";

export type SystemsApiDomainBinding = {
  domain: string;
  toolId: string;
  canonicalUrl: string;
  publicUrl: string;
  verificationToken: string;
  verificationIssuedAt: string;
  verificationExpiresAt: string;
  status: SystemsApiDomainBindingStatus;
  requestedAt: string;
  verifiedAt?: string;
  revokedAt?: string;
  updatedAt: string;
};

export type SystemsApiDomainVerificationChallenge = {
  domain: string;
  token: string;
  issuedAt: string;
  expiresAt: string;
  status: "pending" | "verified" | "expired" | "revoked";
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
  addressCount: number;
  addressKinds: readonly SystemsApiAddressKind[];
  activeExposureCount: number;
  domainCount: number;
  verifiedDomainCount: number;
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
  addressKinds: readonly SystemsApiAddressKind[];
  deploy?: {
    endpoint: string;
    auth: "bearer";
    purpose: string;
  };
};

export type SystemsApiAppKind = "platform" | "application" | "service" | "edge" | "trust" | "network";

export type SystemsApiAppIntegrationMode = "embedded" | "hybrid" | "referenced" | "standalone";

export type SystemsApiApp = {
  id: string;
  name: string;
  description: string;
  kind: SystemsApiAppKind;
  integrationMode: SystemsApiAppIntegrationMode;
  embeddedIn: string | null;
  exposes: readonly string[];
  consumes: readonly string[];
  requiredApis: readonly string[];
  standalone: boolean;
  cloudConnected: boolean;
  registeredAt: string;
  updatedAt: string;
};

export type SystemsApiConnectionKind = "depends-on" | "references" | "routes-through" | "exposes" | "embedded-in";

export type SystemsApiConnection = {
  id: string;
  sourceAppId: string;
  targetAppId: string;
  kind: SystemsApiConnectionKind;
  description: string;
  embedded: boolean;
  createdAt: string;
  updatedAt: string;
};

export type SystemsApiTopologySummary = {
  appCount: number;
  connectionCount: number;
  embeddedAppCount: number;
  referencedAppCount: number;
  hybridAppCount: number;
};

export type SystemsApiTopology = {
  apps: readonly SystemsApiApp[];
  connections: readonly SystemsApiConnection[];
  summary: SystemsApiTopologySummary;
  updatedAt: string;
};

export type SystemsApiExposureKind = SystemsApiAddressKind;

export type SystemsApiDeployRequest = {
  toolId: string;
  name?: string;
  repo: string;
  branch?: string;
  buildCommand?: string;
  startCommand?: string;
  volumePath?: string;
  port?: number;
  env?: Record<string, string>;
  customDomain?: string;
  autoDeployEnabled?: boolean;
  notifyUrl?: string;
  deployNow?: boolean;
  commitSha?: string;
};

export type SystemsApiDeployResponse = {
  created: boolean;
  project: {
    id: string;
    name: string;
    repo: string;
    branch: string;
    buildCommand: string;
    startCommand: string;
    volumePath: string;
    port: number;
    env: Record<string, string>;
    status: string;
    domain?: string;
    customDomain?: string;
    containerId?: string;
    imageTag?: string;
    webhookSecret?: string;
    memoryLimit?: string;
    cpus?: string;
    notifyUrl?: string;
    autoDeployEnabled: boolean;
    sourceToolId?: string;
    createdAt: number;
    updatedAt: number;
  };
  deployment: {
    id: string;
    projectId: string;
    commitSha: string;
    triggeredBy: "manual" | "webhook" | "rollback";
    status: "queued" | "building" | "live" | "failed" | "cancelled";
    imageTag: string;
    logs: string[];
    createdAt: number;
    finishedAt?: number;
  } | null;
};
