import { describeStatus, getTool, listPublicUrls, listToolHistory, listTools, patchTool, requestPublicUrl, setToolExposure, upsertTool, type SystemsApiPublicUrlRequest, type SystemsApiToolPatchInput, type SystemsApiToolRegistrationInput } from "./registry";
import type { SystemsApiCapability, SystemsApiEndpoint, SystemsApiStatus, SystemsApiSummary, SystemsApiTool, SystemsApiToolHistoryEntry } from "./types";

const endpoints = [
  { method: "GET", path: "/api/v1/tools", description: "List registered tools" },
  { method: "GET", path: "/api/v1/tools/:toolId", description: "Inspect a registered tool" },
  { method: "GET", path: "/api/v1/tools/:toolId/history", description: "Inspect tool lifecycle history" },
  { method: "PATCH", path: "/api/v1/tools/:toolId", description: "Update registered tool metadata" },
  { method: "POST", path: "/api/v1/tools/:toolId/enable", description: "Enable a registered tool" },
  { method: "POST", path: "/api/v1/tools/:toolId/disable", description: "Disable a registered tool" },
  { method: "GET", path: "/api/v1/status", description: "Return normalized platform status" },
  { method: "POST", path: "/api/v1/public-url", description: "Request or refresh a public URL" },
] satisfies readonly SystemsApiEndpoint[];

const capabilities = [
  { id: "tools.discovery", description: "Discover tool metadata and exposure state" },
  { id: "tools.lifecycle", description: "Inspect and toggle tool exposure state" },
  { id: "tools.metadata", description: "Update tool metadata and capabilities" },
  { id: "tools.history", description: "Inspect tool lifecycle history" },
  { id: "status.health", description: "Read normalized health and platform summaries" },
  { id: "public-url.exposure", description: "Request public backend exposure" },
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

export function listSystemsApiPublicUrls() {
  return listPublicUrls();
}

export function registerSystemsApiTool(input: SystemsApiToolRegistrationInput): SystemsApiTool {
  return upsertTool(input);
}

export function updateSystemsApiTool(toolId: string, patch: SystemsApiToolPatchInput): SystemsApiTool | null {
  return patchTool(toolId, patch);
}

export function exposeSystemsApiTool(toolId: string, exposed: boolean): SystemsApiTool | null {
  return setToolExposure(toolId, exposed);
}

export function enableSystemsApiTool(toolId: string): SystemsApiTool | null {
  return setToolExposure(toolId, true);
}

export function disableSystemsApiTool(toolId: string): SystemsApiTool | null {
  return setToolExposure(toolId, false);
}

export function issueSystemsApiPublicUrl(input: SystemsApiPublicUrlRequest) {
  return requestPublicUrl(input);
}

export function describeSystemsApiStatus(): SystemsApiStatus {
  const status = describeStatus();
  return {
    ...status,
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
  };
}

export const systemsApiService = {
  describeSystemsApi,
  describeSystemsApiStatus,
  disableSystemsApiTool,
  enableSystemsApiTool,
  exposeSystemsApiTool,
  getSystemsApiTool,
  issueSystemsApiPublicUrl,
  listSystemsApiCapabilities,
  listSystemsApiEndpoints,
  listSystemsApiPublicUrls,
  listSystemsApiToolHistory,
  listSystemsApiTools,
  registerSystemsApiTool,
  updateSystemsApiTool,
};
