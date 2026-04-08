import { describeStatus, disableSystemsApiTool as disableTool, enableSystemsApiTool as enableTool, getDomainBinding, getDomainVerificationChallenge, getExposure, getTool, listDomainBindings, listExposures, listPublicUrls, listToolHistory, listTools, registerSystemsApiTool as registerTool, requestDomainBinding, requestExposure, requestPublicUrl, revokeDomainBinding, revokeSystemsApiExposure as revokeExposure, updateTool as patchTool, verifyDomainBinding, type SystemsApiDomainBindingRequest, type SystemsApiDomainVerificationRequest, type SystemsApiExposureRequest, type SystemsApiPublicUrlRequest, type SystemsApiToolPatchInput, type SystemsApiToolRegistrationInput } from "./registry";
import type { SystemsApiCapability, SystemsApiDomainBinding, SystemsApiDomainVerificationChallenge, SystemsApiEndpoint, SystemsApiExposureRecord, SystemsApiMode, SystemsApiPublicUrl, SystemsApiStatus, SystemsApiSummary, SystemsApiTool, SystemsApiToolHistoryEntry } from "./types";

const endpoints = [
  { method: "GET", path: "/api/v1/tools", description: "List registered tools" },
  { method: "GET", path: "/api/v1/tools/:toolId", description: "Inspect a registered tool" },
  { method: "GET", path: "/api/v1/tools/:toolId/history", description: "Inspect tool lifecycle history" },
  { method: "PATCH", path: "/api/v1/tools/:toolId", description: "Update registered tool metadata" },
  { method: "POST", path: "/api/v1/tools/:toolId/enable", description: "Enable a registered tool" },
  { method: "POST", path: "/api/v1/tools/:toolId/disable", description: "Disable a registered tool" },
  { method: "GET", path: "/api/v1/status", description: "Return normalized platform status" },
  { method: "POST", path: "/api/v1/public-url", description: "Request or refresh a public URL" },
  { method: "GET", path: "/api/v1/exposures", description: "List exposure records" },
  { method: "GET", path: "/api/v1/exposures/:toolId", description: "Inspect an exposure record" },
  { method: "POST", path: "/api/v1/exposures", description: "Request a new exposure" },
  { method: "POST", path: "/api/v1/exposures/:toolId/revoke", description: "Revoke an exposure record" },
  { method: "GET", path: "/api/v1/domains", description: "List domain bindings" },
  { method: "POST", path: "/api/v1/domains", description: "Bind a custom domain" },
  { method: "GET", path: "/api/v1/domains/:domain", description: "Inspect a domain binding" },
  { method: "POST", path: "/api/v1/domains/:domain/verify", description: "Verify a domain binding" },
  { method: "DELETE", path: "/api/v1/domains/:domain", description: "Revoke a domain binding" },
] satisfies readonly SystemsApiEndpoint[];

const capabilities = [
  { id: "tools.discovery", description: "Discover tool metadata and exposure state" },
  { id: "tools.lifecycle", description: "Inspect and toggle tool exposure state" },
  { id: "tools.metadata", description: "Update tool metadata and capabilities" },
  { id: "tools.history", description: "Inspect tool lifecycle history" },
  { id: "status.health", description: "Read normalized health and platform summaries" },
  { id: "public-url.exposure", description: "Request public backend exposure" },
  { id: "domains.binding", description: "Bind and verify custom domains" },
  { id: "domains.verification", description: "Generate and check domain verification challenges" },
  { id: "exposures.lifecycle", description: "Track exposure records and revocation state" },
] satisfies readonly SystemsApiCapability[];

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
  return requestPublicUrl(input);
}

export function describeSystemsApiStatus(): SystemsApiStatus {
  return describeStatus();
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
  };
}

export const systemsApiService = {
  describeSystemsApi,
  describeSystemsApiStatus,
  disableSystemsApiTool: disableTool,
  enableSystemsApiTool: enableTool,
  exposeSystemsApiTool,
  getSystemsApiDomainBinding,
  getSystemsApiDomainVerification,
  getSystemsApiExposure,
  getSystemsApiTool,
  issueSystemsApiPublicUrl,
  listSystemsApiCapabilities,
  listSystemsApiDomainBindings,
  listSystemsApiEndpoints,
  listSystemsApiExposures,
  listSystemsApiPublicUrls,
  listSystemsApiToolHistory,
  listSystemsApiTools,
  registerSystemsApiTool,
  requestSystemsApiDomainBinding,
  requestSystemsApiExposure,
  revokeSystemsApiDomain,
  revokeSystemsApiExposure,
  updateSystemsApiTool,
  verifySystemsApiDomain,
};
