import type { ArchitectureLayer } from "../architecture";
import type { FederationTrust } from "../architecture";
import type { NodeCapacity, NodeRegistrationRequest, NodeSpec, PlacementPlan, WorkloadSpec } from "../control-plane";
import type { PolicyDecision } from "../control-plane/policy";
import type { QuotaDecision } from "../control-plane/quota";
import type { FederationPeer, FederationSignedRequest } from "../federation";
import type { FederationSummary } from "../federation/service";
import type { ObservabilityEvent } from "../observability";
import type { ObservabilitySummary } from "../observability/service";
import type { StorageVolume } from "../storage";
import type { SystemsApiCapability, SystemsApiDeployRequest, SystemsApiDeployResponse, SystemsApiDomainBinding, SystemsApiDomainVerificationChallenge, SystemsApiEndpoint, SystemsApiExposureRecord, SystemsApiMode, SystemsApiPublicUrl, SystemsApiRegistryMetadata, SystemsApiStatus, SystemsApiSummary, SystemsApiTool, SystemsApiToolHealth, SystemsApiToolHistoryEntry } from "../systems-api";

export type ApiRoute = {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  description: string;
};

export type HealthResponse = {
  ok: true;
  project: string;
  services: {
    controlPlane: readonly string[];
    dataPlane: readonly string[];
    federation: FederationSummary;
    observability: ObservabilitySummary;
    storage: readonly string[];
  };
};

export type ArchitectureResponse = {
  project: string;
  mission: string;
  principles: readonly string[];
  layers: readonly ArchitectureLayer[];
  routes: readonly ApiRoute[];
};

export type LegacyStatusResponse = {
  status: "online";
  project: string;
  storage_used_gb: number;
  files_count: number;
  federation_peers: number;
  nodes: number;
  workloads: number;
  tools: number;
  public_urls: number;
  updated_at: string;
};

export type StateResponse = {
  nodes: readonly NodeSpec[];
  workloads: readonly WorkloadSpec[];
  peers: readonly FederationPeer[];
  events: readonly ObservabilityEvent[];
  volumes: readonly StorageVolume[];
};

export type NodeListResponse = {
  nodes: readonly NodeSpec[];
};

export type WorkloadListResponse = {
  workloads: readonly WorkloadSpec[];
};

export type PeerListResponse = {
  peers: readonly FederationPeer[];
};

export type RegisterNodeResponse = {
  node: NodeSpec;
};

export type TrustPeerResponse = {
  peer: FederationPeer;
};

export type PlanWorkloadSuccessResponse = {
  workload: WorkloadSpec;
  plan: PlacementPlan;
  policy: PolicyDecision;
  quota: QuotaDecision;
  warning?: string;
};

export type PlanWorkloadErrorResponse = {
  error: string;
  policy: PolicyDecision;
  quota: QuotaDecision | null;
};

export type PlanWorkloadResponse = PlanWorkloadSuccessResponse | PlanWorkloadErrorResponse;

export type RegisterNodeRequestDTO = NodeRegistrationRequest;
export type WorkloadPlanRequestDTO = WorkloadSpec;
export type TrustPeerRequestDTO = FederationSignedRequest;

export type SystemsApiToolsResponseDTO = {
  tools: readonly SystemsApiTool[];
};

export type SystemsApiToolResponseDTO = {
  tool: SystemsApiTool;
};

export type SystemsApiToolHistoryResponseDTO = {
  history: readonly SystemsApiToolHistoryEntry[];
};

export type SystemsApiStatusResponseDTO = {
  status: SystemsApiStatus;
  tools: readonly SystemsApiTool[];
  publicUrls: readonly SystemsApiPublicUrl[];
};

export type SystemsApiEndpointsResponseDTO = {
  endpoints: readonly SystemsApiEndpoint[];
};

export type SystemsApiCapabilitiesResponseDTO = {
  capabilities: readonly SystemsApiCapability[];
};

export type SystemsApiSummaryResponseDTO = {
  summary: SystemsApiSummary;
};

export type SystemsApiRegistryMetadataResponseDTO = {
  registry: SystemsApiRegistryMetadata;
};

export type SystemsApiPublicUrlRequestDTO = {
  toolId: string;
  desiredHost?: string;
  refresh?: boolean;
};

export type SystemsApiPublicUrlResponseDTO = {
  publicUrl: SystemsApiPublicUrl;
  tool: SystemsApiTool;
};

export type SystemsApiExposureRequestDTO = {
  toolId: string;
  desiredHost?: string;
};

export type SystemsApiExposureResponseDTO = {
  exposure: SystemsApiExposureRecord;
};

export type SystemsApiDomainBindingRequestDTO = {
  toolId: string;
  domain: string;
  desiredHost?: string;
};

export type SystemsApiDomainBindingResponseDTO = {
  domainBinding: SystemsApiDomainBinding;
};

export type SystemsApiDomainVerificationResponseDTO = {
  challenge: SystemsApiDomainVerificationChallenge;
};

export type SystemsApiToolPatchRequestDTO = {
  name?: string;
  description?: string;
  mode?: SystemsApiMode;
  exposed?: boolean;
  health?: SystemsApiToolHealth;
  capabilities?: readonly string[];
};

export type SystemsApiDeployRequestDTO = SystemsApiDeployRequest;
export type SystemsApiDeployResponseDTO = SystemsApiDeployResponse;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isStringRecord(value: unknown): value is Record<string, string> {
  return isRecord(value) && Object.values(value).every(isString);
}

function isNodeCapacity(value: unknown): value is NodeCapacity {
  return isRecord(value) && isNumber(value.cpu) && isNumber(value.memoryMb) && isNumber(value.storageGb) && (value.publicIpv4 === undefined || isString(value.publicIpv4));
}

function isMode(value: unknown): value is SystemsApiMode {
  return value === "standalone" || value === "orchestrated";
}

function isToolHealth(value: unknown): value is SystemsApiToolHealth {
  return value === "healthy" || value === "degraded" || value === "offline";
}

export function isRegisterNodeRequest(value: unknown): value is RegisterNodeRequestDTO {
  return isRecord(value) && isString(value.name) && isString(value.region) && isString(value.zone) && (value.labels === undefined || isStringRecord(value.labels)) && isNodeCapacity(value.capacity);
}

export function isWorkloadPlanRequest(value: unknown): value is WorkloadPlanRequestDTO {
  return isRecord(value)
    && isString(value.id)
    && isString(value.name)
    && isString(value.image)
    && isNumber(value.replicas)
    && isNumber(value.cpuMillicores)
    && isNumber(value.memoryMb)
    && isStringRecord(value.env)
    && Array.isArray(value.ports) && value.ports.every(isNumber)
    && (value.runtime === "container" || value.runtime === "vm" || value.runtime === "function")
    && Array.isArray(value.storage) && value.storage.every(isString);
}

export function isTrustPeerRequest(value: unknown): value is TrustPeerRequestDTO {
  return isRecord(value)
    && isString(value.method)
    && isString(value.path)
    && isString(value.host)
    && isString(value.timestamp)
    && isString(value.nonce)
    && isString(value.keyId)
    && isString(value.signature);
}

export function isSystemsApiPublicUrlRequest(value: unknown): value is SystemsApiPublicUrlRequestDTO {
  return isRecord(value)
    && isString(value.toolId)
    && (value.desiredHost === undefined || isString(value.desiredHost))
    && (value.refresh === undefined || typeof value.refresh === "boolean");
}

export function isSystemsApiExposureRequest(value: unknown): value is SystemsApiExposureRequestDTO {
  return isRecord(value)
    && isString(value.toolId)
    && (value.desiredHost === undefined || isString(value.desiredHost));
}

export function isSystemsApiDomainBindingRequest(value: unknown): value is SystemsApiDomainBindingRequestDTO {
  return isRecord(value)
    && isString(value.toolId)
    && isString(value.domain)
    && (value.desiredHost === undefined || isString(value.desiredHost));
}

export function isSystemsApiDomainVerificationRequest(value: unknown): value is { domain: string; token: string } {
  return isRecord(value) && isString(value.domain) && isString(value.token);
}

export function isSystemsApiToolPatchRequest(value: unknown): value is SystemsApiToolPatchRequestDTO {
  return isRecord(value)
    && (value.name === undefined || isString(value.name))
    && (value.description === undefined || isString(value.description))
    && (value.mode === undefined || isMode(value.mode))
    && (value.exposed === undefined || typeof value.exposed === "boolean")
    && (value.health === undefined || isToolHealth(value.health))
    && (value.capabilities === undefined || Array.isArray(value.capabilities) && value.capabilities.every(isString));
}

export function isSystemsApiDeployRequest(value: unknown): value is SystemsApiDeployRequestDTO {
  return isRecord(value)
    && isString(value.toolId)
    && isString(value.repo)
    && (value.name === undefined || isString(value.name))
    && (value.branch === undefined || isString(value.branch))
    && (value.buildCommand === undefined || isString(value.buildCommand))
    && (value.startCommand === undefined || isString(value.startCommand))
    && (value.volumePath === undefined || isString(value.volumePath))
    && (value.port === undefined || isNumber(value.port))
    && (value.env === undefined || isStringRecord(value.env))
    && (value.customDomain === undefined || isString(value.customDomain))
    && (value.autoDeployEnabled === undefined || typeof value.autoDeployEnabled === "boolean")
    && (value.notifyUrl === undefined || isString(value.notifyUrl))
    && (value.deployNow === undefined || typeof value.deployNow === "boolean")
    && (value.commitSha === undefined || isString(value.commitSha));
}

export function isSystemsApiToolHistoryResponse(value: unknown): value is SystemsApiToolHistoryResponseDTO {
  return isRecord(value) && Array.isArray(value.history) && value.history.every((entry) => isRecord(entry) && isString(entry.toolId) && isString(entry.action) && isString(entry.summary) && isString(entry.at));
}
