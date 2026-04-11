import {
  describeStatus,
  disableSystemsApiTool as disableTool,
  enableSystemsApiTool as enableTool,
  getAddress,
  getDomainBinding,
  getTool,
  getDomainVerificationChallenge,
  getExposure,
  getPublicUrl,
  listAddresses,
  listDomainBindings,
  listExposures,
  listPublicUrls,
  listToolHistory,
  listTools,
  registerSystemsApiTool as registerTool,
  requestDomainBinding,
  requestExposure,
  requestSystemsApiAddress as requestAddressRecord,
  revokeDomainBinding,
  revokeSystemsApiAddress as revokeAddressRecords,
  revokeSystemsApiExposure as revokeExposure,
  updateTool as patchTool,
  verifyDomainBinding,
} from "./registry";
import { systemsApiDeployIntegration as deployIntegration } from "./deploy";
import type {
  SystemsApiAddress,
  SystemsApiAddressKind,
  SystemsApiApp,
  SystemsApiAppIntegrationMode,
  SystemsApiCapability,
  SystemsApiConnection,
  SystemsApiConnectionKind,
  SystemsApiDomainBinding,
  SystemsApiDomainVerificationChallenge,
  SystemsApiEndpoint,
  SystemsApiExposureRecord,
  SystemsApiMode,
  SystemsApiPublicUrl,
  SystemsApiStatus,
  SystemsApiSummary,
  SystemsApiTool,
  SystemsApiToolHistoryEntry,
  SystemsApiTopology,
} from "./types";

const addressKinds: readonly SystemsApiAddressKind[] = ["website", "email", "server", "custom"];

const topologyApps: readonly SystemsApiApp[] = [
  {
    id: "nexus-cloud",
    name: "Nexus Cloud",
    description: "The sovereign control plane, registry, policy, and orchestration hub.",
    kind: "platform",
    integrationMode: "embedded",
    embeddedIn: null,
    exposes: ["discovery", "status", "policy", "registry", "public-url", "deploy"],
    consumes: ["vault", "network", "deploy", "hosting", "computer"],
    requiredApis: ["Discovery API", "Systems Registry API", "Policy API", "Status API", "Exposure API", "Public URL API"],
    standalone: true,
    cloudConnected: true,
    registeredAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "nexus",
    name: "Nexus",
    description: "The collaboration and federation plane for messages, channels, and presence.",
    kind: "application",
    integrationMode: "hybrid",
    embeddedIn: null,
    exposes: ["messages", "channels", "presence", "federation"],
    consumes: ["identity", "policy", "storage", "search", "notifications", "exposure"],
    requiredApis: ["Messaging API", "Presence API", "Federation API", "Notification API"],
    standalone: true,
    cloudConnected: true,
    registeredAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "nexus-ai",
    name: "Nexus AI",
    description: "The agent orchestration and tool intelligence layer.",
    kind: "application",
    integrationMode: "hybrid",
    embeddedIn: null,
    exposes: ["agents", "tool-routing", "workflows", "model-routing"],
    consumes: ["tool-registry", "vault", "identity", "status", "jobs", "deploy"],
    requiredApis: ["Tool Invocation API", "Agent Runtime API", "Model Routing API", "Job API"],
    standalone: true,
    cloudConnected: true,
    registeredAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "nexus-computer",
    name: "Nexus Computer",
    description: "The edge execution layer for local devices, agents, and remote tasks.",
    kind: "edge",
    integrationMode: "referenced",
    embeddedIn: "nexus-cloud",
    exposes: ["device-registry", "edge-heartbeat", "remote-task", "sync"],
    consumes: ["jobs", "identity", "vault", "network", "control-plane"],
    requiredApis: ["Device Registry API", "Edge Heartbeat API", "Remote Task API", "Sync API"],
    standalone: true,
    cloudConnected: true,
    registeredAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "nexus-deploy",
    name: "Nexus Deploy",
    description: "The build, release, and rollback delivery plane.",
    kind: "service",
    integrationMode: "hybrid",
    embeddedIn: null,
    exposes: ["build", "release", "rollback", "environment"],
    consumes: ["registry", "vault", "hosting", "network", "status"],
    requiredApis: ["Build API", "Release API", "Environment API", "Rollback API"],
    standalone: true,
    cloudConnected: true,
    registeredAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "nexus-hosting",
    name: "Nexus Hosting",
    description: "The site, route, and public runtime exposure plane.",
    kind: "service",
    integrationMode: "hybrid",
    embeddedIn: null,
    exposes: ["sites", "routes", "assets", "public-exposure"],
    consumes: ["deploy", "cloud", "network", "vault", "storage"],
    requiredApis: ["Site Registration API", "Route Manifest API", "Publish API", "Public Address API"],
    standalone: true,
    cloudConnected: true,
    registeredAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "nexus-network",
    name: "Nexus Network",
    description: "The connectivity, peer routing, tunnel, and federation fabric.",
    kind: "network",
    integrationMode: "embedded",
    embeddedIn: "nexus-cloud",
    exposes: ["peers", "routing", "tunnel", "reachability"],
    consumes: ["identity", "policy", "vault", "status"],
    requiredApis: ["Peer Registry API", "Connectivity API", "Tunnel Session API", "Federation API"],
    standalone: true,
    cloudConnected: true,
    registeredAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "nexus-vault",
    name: "Nexus Vault",
    description: "The secrets, tokens, signing, and trust anchor.",
    kind: "trust",
    integrationMode: "embedded",
    embeddedIn: "nexus-cloud",
    exposes: ["secrets", "tokens", "signing", "rotation"],
    consumes: ["identity", "policy", "audit", "registry"],
    requiredApis: ["Secrets API", "Token Mint API", "Signing API", "Rotation API"],
    standalone: true,
    cloudConnected: true,
    registeredAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
];

const topologyConnections: readonly SystemsApiConnection[] = [
  {
    id: "cloud-owns-registry",
    sourceAppId: "nexus-cloud",
    targetAppId: "nexus",
    kind: "depends-on",
    description: "Nexus Cloud is the registry and policy source of truth for Nexus.",
    embedded: false,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "cloud-owns-ai",
    sourceAppId: "nexus-cloud",
    targetAppId: "nexus-ai",
    kind: "depends-on",
    description: "Nexus AI discovers tools, jobs, and trust metadata through Nexus Cloud.",
    embedded: false,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "cloud-owns-computer",
    sourceAppId: "nexus-cloud",
    targetAppId: "nexus-computer",
    kind: "routes-through",
    description: "Nexus Computer receives edge tasks, sync, and device orchestration from Cloud.",
    embedded: true,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "cloud-owns-deploy",
    sourceAppId: "nexus-cloud",
    targetAppId: "nexus-deploy",
    kind: "depends-on",
    description: "Nexus Deploy is the formal delivery backend for Cloud-triggered deployments.",
    embedded: false,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "cloud-owns-hosting",
    sourceAppId: "nexus-cloud",
    targetAppId: "nexus-hosting",
    kind: "depends-on",
    description: "Nexus Hosting consumes registry, exposure, and deployment state from Cloud.",
    embedded: false,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "cloud-owns-network",
    sourceAppId: "nexus-cloud",
    targetAppId: "nexus-network",
    kind: "routes-through",
    description: "Nexus Network provides the peer, tunnel, and federation fabric for Cloud.",
    embedded: true,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "cloud-owns-vault",
    sourceAppId: "nexus-cloud",
    targetAppId: "nexus-vault",
    kind: "depends-on",
    description: "Nexus Vault is the trust and secrets foundation used by Cloud and tools.",
    embedded: true,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "ai-routes-to-tools",
    sourceAppId: "nexus-ai",
    targetAppId: "nexus",
    kind: "references",
    description: "Nexus AI invokes collaboration tools via the canonical Systems API surface.",
    embedded: false,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "hosting-uses-deploy",
    sourceAppId: "nexus-hosting",
    targetAppId: "nexus-deploy",
    kind: "depends-on",
    description: "Hosting consumes deployment outputs and release state from Deploy.",
    embedded: false,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
  {
    id: "network-routes-public-exposure",
    sourceAppId: "nexus-network",
    targetAppId: "nexus-hosting",
    kind: "routes-through",
    description: "Public reachability and tunnels should route through the network layer.",
    embedded: true,
    createdAt: new Date(0).toISOString(),
    updatedAt: new Date(0).toISOString(),
  },
];

function appIntegrationMode(kind: SystemsApiAppKind, embeddedIn: string | null): SystemsApiAppIntegrationMode {
  if (embeddedIn) return "embedded";
  if (kind === "platform" || kind === "application") return "hybrid";
  return "standalone";
}

export type SystemsApiPublicUrlRequest = {
  toolId: string;
  desiredHost?: string;
  refresh?: boolean;
};

export type SystemsApiAddressRequest = {
  toolId: string;
  kind: SystemsApiAddressKind;
  subject?: string;
  desiredHost?: string;
};

export type SystemsApiExposureRequest = {
  toolId: string;
  desiredHost?: string;
};

export type SystemsApiDomainBindingRequest = {
  toolId: string;
  domain: string;
  desiredHost?: string;
};

export type SystemsApiDomainVerificationRequest = {
  domain: string;
  token: string;
};

export type SystemsApiToolRegistrationInput = {
  id: string;
  name: string;
  description: string;
  mode?: SystemsApiMode;
  exposed?: boolean;
  health?: import("./types").SystemsApiToolHealth;
  capabilities?: readonly string[];
  publicUrl?: string;
};

export type SystemsApiToolPatchInput = {
  name?: string;
  description?: string;
  mode?: SystemsApiMode;
  exposed?: boolean;
  health?: import("./types").SystemsApiToolHealth;
  capabilities?: readonly string[];
};

const endpoints = [
  { method: "GET", path: "/api/v1/tools", description: "List registered tools" },
  { method: "GET", path: "/api/v1/tools/:toolId", description: "Inspect a registered tool" },
  { method: "GET", path: "/api/v1/tools/:toolId/history", description: "Inspect tool lifecycle history" },
  { method: "PATCH", path: "/api/v1/tools/:toolId", description: "Update registered tool metadata" },
  { method: "POST", path: "/api/v1/tools/:toolId/enable", description: "Enable a registered tool" },
  { method: "POST", path: "/api/v1/tools/:toolId/disable", description: "Disable a registered tool" },
  { method: "GET", path: "/api/v1/status", description: "Return normalized platform status" },
  { method: "POST", path: "/api/v1/public-url", description: "Request or refresh a public URL" },
  { method: "GET", path: "/api/v1/addresses", description: "List public address records" },
  { method: "GET", path: "/api/v1/addresses/:toolId", description: "Inspect public address records for a tool" },
  { method: "POST", path: "/api/v1/addresses", description: "Request a public address" },
  { method: "POST", path: "/api/v1/addresses/:toolId/revoke", description: "Revoke public address records for a tool" },
  { method: "GET", path: "/api/v1/exposures", description: "List exposure records" },
  { method: "GET", path: "/api/v1/exposures/:toolId", description: "Inspect an exposure record" },
  { method: "POST", path: "/api/v1/exposures", description: "Request a new exposure" },
  { method: "POST", path: "/api/v1/exposures/:toolId/revoke", description: "Revoke an exposure record" },
  { method: "GET", path: "/api/v1/domains", description: "List domain bindings" },
  { method: "POST", path: "/api/v1/domains", description: "Bind a custom domain" },
  { method: "GET", path: "/api/v1/domains/:domain", description: "Inspect a domain binding" },
  { method: "POST", path: "/api/v1/domains/:domain/verify", description: "Verify a domain binding" },
  { method: "DELETE", path: "/api/v1/domains/:domain", description: "Revoke a domain binding" },
  { method: "GET", path: "/api/v1/deployments/integration", description: "Inspect the Deploy backend integration" },
  { method: "POST", path: "/api/v1/deployments", description: "Request a managed Deploy deployment" },
] as const satisfies readonly SystemsApiEndpoint[];

const capabilities = [
  { id: "tools.discovery", description: "Discover tool metadata and exposure state" },
  { id: "tools.lifecycle", description: "Inspect and toggle tool exposure state" },
  { id: "tools.metadata", description: "Update tool metadata and capabilities" },
  { id: "tools.history", description: "Inspect tool lifecycle history" },
  { id: "status.health", description: "Read normalized health and platform summaries" },
  { id: "public-url.exposure", description: "Request public backend exposure" },
  { id: "addresses.issue", description: "Request website, email, server, and custom public addresses" },
  { id: "domains.binding", description: "Bind and verify custom domains" },
  { id: "domains.verification", description: "Generate and check domain verification challenges" },
  { id: "exposures.lifecycle", description: "Track exposure records and revocation state" },
  { id: "deploy.request", description: "Request and inspect managed deployments through Nexus Deploy" },
] as const satisfies readonly SystemsApiCapability[];

export function listSystemsApiEndpoints(): readonly SystemsApiEndpoint[] {
  return endpoints;
}

export function listSystemsApiCapabilities(): readonly SystemsApiCapability[] {
  return capabilities;
}

export function listSystemsApiTools(): readonly SystemsApiTool[] {
  return listTools();
}

export function getSystemsApiTool(toolId: string): SystemsApiTool | null {
  return getTool(toolId);
}

export function listSystemsApiToolHistory(toolId: string): readonly SystemsApiToolHistoryEntry[] {
  return listToolHistory(toolId);
}

export function listSystemsApiPublicUrls(): readonly SystemsApiPublicUrl[] {
  return listPublicUrls();
}

export function getSystemsApiPublicUrl(toolId: string): SystemsApiPublicUrl | null {
  return getPublicUrl(toolId);
}

export function listSystemsApiAddresses(): readonly SystemsApiAddress[] {
  return listAddresses();
}

export function listSystemsApiAddressesForTool(toolId: string): readonly SystemsApiAddress[] {
  return listAddresses().filter((item) => item.toolId === toolId);
}

export function getSystemsApiAddress(toolId: string, kind?: SystemsApiAddressKind): SystemsApiAddress | null {
  return getAddress(toolId, kind);
}

export function requestSystemsApiAddress(input: SystemsApiAddressRequest): SystemsApiAddress | null {
  return requestAddressRecord(input);
}

export function revokeSystemsApiAddress(input: { toolId: string; kind?: SystemsApiAddressKind }): readonly SystemsApiAddress[] {
  return revokeAddressRecords(input);
}

export function listSystemsApiExposures(): readonly SystemsApiExposureRecord[] {
  return listExposures();
}

export function getSystemsApiExposure(toolId: string): SystemsApiExposureRecord | null {
  return getExposure(toolId);
}

export function requestSystemsApiExposure(input: SystemsApiExposureRequest): SystemsApiExposureRecord | null {
  return requestExposure(input);
}

export function revokeSystemsApiExposure(toolId: string): SystemsApiExposureRecord | null {
  return revokeExposure(toolId);
}

export function listSystemsApiDomainBindings(): readonly SystemsApiDomainBinding[] {
  return listDomainBindings();
}

export function getSystemsApiDomainBinding(domain: string): SystemsApiDomainBinding | null {
  return getDomainBinding(domain);
}

export function requestSystemsApiDomainBinding(input: SystemsApiDomainBindingRequest): SystemsApiDomainBinding | null {
  return requestDomainBinding(input);
}

export function getSystemsApiDomainVerification(domain: string): SystemsApiDomainVerificationChallenge | null {
  return getDomainVerificationChallenge(domain);
}

export function verifySystemsApiDomain(domain: string, token: string): SystemsApiDomainBinding | null {
  return verifyDomainBinding(domain, token);
}

export function revokeSystemsApiDomain(domain: string): SystemsApiDomainBinding | null {
  return revokeDomainBinding(domain);
}

export function registerSystemsApiTool(input: SystemsApiToolRegistrationInput): SystemsApiTool {
  return registerTool(input);
}

export function updateSystemsApiTool(toolId: string, patch: SystemsApiToolPatchInput): SystemsApiTool | null {
  return patchTool(toolId, patch);
}

export function exposeSystemsApiTool(toolId: string, exposed: boolean): SystemsApiTool | null {
  return exposed ? enableTool(toolId) : disableTool(toolId);
}

export function issueSystemsApiPublicUrl(input: SystemsApiPublicUrlRequest): SystemsApiPublicUrl | null {
  const tool = getSystemsApiTool(input.toolId);
  if (!tool) return null;
  const subject = input.desiredHost?.replace(/^https?:\/\//, "") || input.toolId;
  const address = requestAddressRecord({
    toolId: input.toolId,
    kind: "website",
    subject,
    desiredHost: input.desiredHost,
  });
  if (!address) return null;
  return getPublicUrl(input.toolId);
}

export function describeSystemsApiStatus(): SystemsApiStatus {
  return describeStatus();
}

export function listSystemsApiApps(): readonly SystemsApiApp[] {
  return topologyApps;
}

export function listSystemsApiConnections(): readonly SystemsApiConnection[] {
  return topologyConnections;
}

export function describeSystemsApiTopology(): SystemsApiTopology {
  const embeddedAppCount = topologyApps.filter((app) => app.integrationMode === "embedded").length;
  const referencedAppCount = topologyApps.filter((app) => app.integrationMode === "referenced").length;
  const hybridAppCount = topologyApps.filter((app) => app.integrationMode === "hybrid").length;
  return {
    apps: topologyApps,
    connections: topologyConnections,
    summary: {
      appCount: topologyApps.length,
      connectionCount: topologyConnections.length,
      embeddedAppCount,
      referencedAppCount,
      hybridAppCount,
    },
    updatedAt: new Date().toISOString(),
  };
}

export function describeSystemsApi(): SystemsApiSummary {
  const status = describeSystemsApiStatus();
  return {
    version: status.version,
    scope: "canonical platform contract for Nexus tools and orchestrated services",
    endpoints,
    capabilities,
    toolCount: status.toolCount,
    status,
    addressKinds: status.addressKinds,
    deploy: deployIntegration,
  };
}

export function describeSystemsApiDeployIntegration(): typeof deployIntegration {
  return deployIntegration;
}

export const systemsApiDeployIntegration = deployIntegration;

export const systemsApiService = {
  describeSystemsApi,
  describeSystemsApiDeployIntegration,
  describeSystemsApiStatus,
  describeSystemsApiTopology,
  disableSystemsApiTool: disableTool,
  enableSystemsApiTool: enableTool,
  exposeSystemsApiTool,
  getSystemsApiAddress,
  getSystemsApiAddressForTool: listSystemsApiAddressesForTool,
  getSystemsApiDomainBinding,
  getSystemsApiDomainVerification,
  getSystemsApiExposure,
  getSystemsApiPublicUrl,
  getSystemsApiTool,
  issueSystemsApiAddress: requestSystemsApiAddress,
  issueSystemsApiPublicUrl,
  listSystemsApiAddresses,
  listSystemsApiAddressesForTool,
  listSystemsApiApps,
  listSystemsApiCapabilities,
  listSystemsApiConnections,
  listSystemsApiDomainBindings,
  listSystemsApiEndpoints,
  listSystemsApiExposures,
  listSystemsApiPublicUrls,
  listSystemsApiToolHistory,
  listSystemsApiTools,
  registerSystemsApiTool,
  requestSystemsApiAddress,
  requestSystemsApiDomainBinding,
  requestSystemsApiExposure,
  revokeSystemsApiAddress,
  revokeSystemsApiDomain,
  revokeSystemsApiExposure,
  updateSystemsApiTool,
  verifySystemsApiDomain,
};
