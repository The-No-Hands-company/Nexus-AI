import { buildPublicUrl, createExposureRecord, revokeExposureRecord, transitionExposureRecord } from "./exposure";
import { createDomainBinding, issueDomainVerificationChallenge as buildDomainVerificationChallenge, revokeDomainBinding as revokeDomainRecord, verifyDomainBinding as verifyDomainRecord } from "./domains";
import { getSystemsApiRegistryMetadata, loadSystemsApiRegistry, saveSystemsApiRegistry, type SystemsApiRegistryData } from "./store";
import type { SystemsApiDomainBinding, SystemsApiDomainVerificationChallenge, SystemsApiExposureRecord, SystemsApiExposureStatus, SystemsApiMode, SystemsApiPublicUrl, SystemsApiPublicUrlStatus, SystemsApiStatus, SystemsApiTool, SystemsApiToolExposure, SystemsApiToolHealth, SystemsApiToolHistoryAction, SystemsApiToolHistoryEntry } from "./types";

export type SystemsApiToolRegistrationInput = {
  id: string;
  name: string;
  description: string;
  mode?: SystemsApiMode;
  exposed?: boolean;
  health?: SystemsApiToolHealth;
  capabilities?: readonly string[];
  publicUrl?: string;
};

export type SystemsApiToolPatchInput = {
  name?: string;
  description?: string;
  mode?: SystemsApiMode;
  exposed?: boolean;
  health?: SystemsApiToolHealth;
  capabilities?: readonly string[];
};

export type SystemsApiPublicUrlRequest = {
  toolId: string;
  desiredHost?: string;
  refresh?: boolean;
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

const registry: SystemsApiRegistryData = loadSystemsApiRegistry();

function persist(): void {
  saveSystemsApiRegistry(registry);
}

function now(): string {
  return new Date().toISOString();
}

function currentMode(): SystemsApiMode {
  return process.env.SYSTEMS_API_MODE === "orchestrated" ? "orchestrated" : "standalone";
}

function exposureFromFlag(exposed: boolean): SystemsApiToolExposure {
  return exposed ? "public" : "private";
}

function findToolIndex(toolId: string): number {
  return registry.tools.findIndex((tool) => tool.id === toolId);
}

function pushHistory(toolId: string, action: SystemsApiToolHistoryAction, summary: string, at = now()): void {
  registry.history.push({ toolId, action, summary, at });
}

function updateToolRecord(toolId: string, updater: (tool: SystemsApiTool) => SystemsApiTool): SystemsApiTool | null {
  const existingIndex = findToolIndex(toolId);
  if (existingIndex < 0) return null;
  const next = updater(registry.tools[existingIndex]);
  registry.tools[existingIndex] = next;
  return next;
}

function buildTool(input: SystemsApiToolRegistrationInput, previous: SystemsApiTool | null = null): SystemsApiTool {
  return {
    id: input.id,
    name: input.name,
    description: input.description,
    mode: input.mode ?? previous?.mode ?? currentMode(),
    exposed: input.exposed ?? previous?.exposed ?? false,
    exposure: exposureFromFlag(input.exposed ?? previous?.exposed ?? false),
    health: input.health ?? previous?.health ?? "healthy",
    capabilities: input.capabilities ?? previous?.capabilities ?? [],
    publicUrl: input.publicUrl ?? previous?.publicUrl,
    registeredAt: previous?.registeredAt ?? now(),
    updatedAt: now(),
  };
}

function upsertToolRecord(tool: SystemsApiTool): SystemsApiTool {
  const existingIndex = findToolIndex(tool.id);
  if (existingIndex >= 0) registry.tools[existingIndex] = tool;
  else registry.tools.push(tool);
  return tool;
}

function upsertExposureRecord(record: SystemsApiExposureRecord): SystemsApiExposureRecord {
  const existingIndex = registry.exposures.findIndex((item) => item.toolId === record.toolId);
  if (existingIndex >= 0) registry.exposures[existingIndex] = record;
  else registry.exposures.push(record);
  return record;
}

function upsertPublicUrlRecord(record: SystemsApiPublicUrl): SystemsApiPublicUrl {
  const existingIndex = registry.publicUrls.findIndex((item) => item.toolId === record.toolId);
  if (existingIndex >= 0) registry.publicUrls[existingIndex] = record;
  else registry.publicUrls.push(record);
  return record;
}

function upsertDomainRecord(record: SystemsApiDomainBinding): SystemsApiDomainBinding {
  const existingIndex = registry.domains.findIndex((item) => item.domain === record.domain);
  if (existingIndex >= 0) registry.domains[existingIndex] = record;
  else registry.domains.push(record);
  return record;
}

export function listTools(): readonly SystemsApiTool[] {
  return registry.tools;
}

export function getTool(toolId: string): SystemsApiTool | null {
  return registry.tools.find((tool) => tool.id === toolId) ?? null;
}

export function listToolHistory(toolId: string): readonly SystemsApiToolHistoryEntry[] {
  return registry.history.filter((entry) => entry.toolId === toolId);
}

export function registerSystemsApiTool(input: SystemsApiToolRegistrationInput): SystemsApiTool {
  const existingIndex = findToolIndex(input.id);
  const previous = existingIndex >= 0 ? registry.tools[existingIndex] : null;
  const tool = buildTool(input, previous);
  const action: SystemsApiToolHistoryAction = previous ? "updated" : "registered";

  upsertToolRecord(tool);
  pushHistory(tool.id, action, action === "registered" ? `Registered ${tool.name}` : `Updated ${tool.name}`, tool.updatedAt);
  persist();
  return tool;
}

export function updateTool(toolId: string, patch: SystemsApiToolPatchInput): SystemsApiTool | null {
  const existingIndex = findToolIndex(toolId);
  if (existingIndex < 0) return null;

  const previous = registry.tools[existingIndex];
  const tool: SystemsApiTool = {
    ...previous,
    name: patch.name ?? previous.name,
    description: patch.description ?? previous.description,
    mode: patch.mode ?? previous.mode,
    exposed: patch.exposed ?? previous.exposed,
    exposure: exposureFromFlag(patch.exposed ?? previous.exposed),
    health: patch.health ?? previous.health,
    capabilities: patch.capabilities ?? previous.capabilities,
    updatedAt: now(),
  };

  upsertToolRecord(tool);
  pushHistory(toolId, "updated", `Edited metadata for ${tool.name}`, tool.updatedAt);
  persist();
  return tool;
}

export function enableSystemsApiTool(toolId: string): SystemsApiTool | null {
  const tool = updateToolRecord(toolId, (current) => ({
    ...current,
    exposed: true,
    exposure: "public",
    updatedAt: now(),
  }));

  if (!tool) return null;

  pushHistory(toolId, "enabled", `Enabled ${tool.name}`, tool.updatedAt);
  persist();
  return tool;
}

export function disableSystemsApiTool(toolId: string): SystemsApiTool | null {
  const tool = updateToolRecord(toolId, (current) => ({
    ...current,
    exposed: false,
    exposure: "private",
    updatedAt: now(),
  }));

  if (!tool) return null;

  pushHistory(toolId, "disabled", `Disabled ${tool.name}`, tool.updatedAt);
  persist();
  return tool;
}

export function requestExposure(input: SystemsApiExposureRequest): SystemsApiExposureRecord | null {
  const tool = getTool(input.toolId);
  if (!tool) return null;

  const publicUrl = buildPublicUrl(tool.id, input.desiredHost);
  const requested = createExposureRecord({ toolId: tool.id, desiredHost: input.desiredHost }, publicUrl, "requested");
  const record = transitionExposureRecord(requested, "active", publicUrl);
  upsertExposureRecord(record);

  updateToolRecord(tool.id, (current) => ({
    ...current,
    exposed: true,
    exposure: "public",
    publicUrl,
    updatedAt: now(),
  }));

  pushHistory(tool.id, "exposure-requested", `Requested exposure for ${tool.name}`, record.requestedAt);
  pushHistory(tool.id, "exposure-activated", `Activated exposure for ${tool.name}`, record.activatedAt ?? record.updatedAt);
  persist();
  return record;
}

export function revokeSystemsApiExposure(toolId: string): SystemsApiExposureRecord | null {
  const exposure = getExposure(toolId);
  const tool = getTool(toolId);
  if (!exposure) return null;

  const revoked = revokeExposureRecord(exposure);
  upsertExposureRecord(revoked);

  const publicUrlIndex = registry.publicUrls.findIndex((item) => item.toolId === toolId);
  if (publicUrlIndex >= 0) {
    registry.publicUrls[publicUrlIndex] = {
      ...registry.publicUrls[publicUrlIndex],
      status: "revoked",
      issuedAt: registry.publicUrls[publicUrlIndex].issuedAt,
      expiresAt: registry.publicUrls[publicUrlIndex].expiresAt,
    };
  }

  updateToolRecord(toolId, (current) => ({
    ...current,
    exposed: false,
    exposure: "private",
    updatedAt: now(),
  }));

  pushHistory(toolId, "exposure-revoked", `Revoked exposure for ${tool?.name ?? toolId}`, revoked.revokedAt ?? revoked.updatedAt);
  persist();
  return revoked;
}

export function requestPublicUrl(input: SystemsApiPublicUrlRequest): SystemsApiPublicUrl | null {
  const tool = getTool(input.toolId);
  if (!tool) return null;

  const publicUrl = buildPublicUrl(tool.id, input.desiredHost);
  const record: SystemsApiPublicUrl = {
    toolId: tool.id,
    url: publicUrl,
    status: "active",
    issuedAt: now(),
    expiresAt: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString(),
  };

  upsertPublicUrlRecord(record);
  requestExposure({ toolId: tool.id, desiredHost: input.desiredHost });
  pushHistory(tool.id, "public-url-issued", `Issued public URL for ${tool.name}`, record.issuedAt);
  persist();
  return record;
}

export function listPublicUrls(): readonly SystemsApiPublicUrl[] {
  return registry.publicUrls;
}

export function listExposures(): readonly SystemsApiExposureRecord[] {
  return registry.exposures;
}

export function getExposure(toolId: string): SystemsApiExposureRecord | null {
  return registry.exposures.find((item) => item.toolId === toolId) ?? null;
}

export function listDomainBindings(): readonly SystemsApiDomainBinding[] {
  return registry.domains;
}

export function getDomainBinding(domain: string): SystemsApiDomainBinding | null {
  return registry.domains.find((item) => item.domain === domain) ?? null;
}

export function requestDomainBinding(input: SystemsApiDomainBindingRequest): SystemsApiDomainBinding | null {
  const exposure = getExposure(input.toolId) ?? requestExposure({ toolId: input.toolId, desiredHost: input.desiredHost });
  if (!exposure) return null;

  const existing = getDomainBinding(input.domain);
  const binding = createDomainBinding({ toolId: input.toolId, domain: input.domain, desiredHost: input.desiredHost }, exposure.publicUrl, existing?.status ?? "pending");
  upsertDomainRecord(binding);
  pushHistory(input.toolId, "domain-bound", `Bound ${input.domain} to ${input.toolId}`, binding.requestedAt);
  persist();
  return binding;
}

export function getDomainVerificationChallenge(domain: string): SystemsApiDomainVerificationChallenge | null {
  const binding = getDomainBinding(domain);
  if (!binding) return null;
  return buildDomainVerificationChallenge(binding);
}

export function verifyDomainBinding(domain: string, token: string): SystemsApiDomainBinding | null {
  const existing = getDomainBinding(domain);
  if (!existing) return null;
  const verified = verifyDomainRecord(existing, token);
  if (!verified) return null;
  upsertDomainRecord(verified);
  pushHistory(verified.toolId, "domain-verified", `Verified ${domain}`, verified.verifiedAt ?? verified.updatedAt);
  persist();
  return verified;
}

export function revokeDomainBinding(domain: string): SystemsApiDomainBinding | null {
  const existing = getDomainBinding(domain);
  if (!existing) return null;
  const revoked = revokeDomainRecord(existing);
  upsertDomainRecord(revoked);
  pushHistory(revoked.toolId, "domain-revoked", `Revoked ${domain}`, revoked.revokedAt ?? revoked.updatedAt);
  persist();
  return revoked;
}

export function describeStatus(): SystemsApiStatus {
  const mode = currentMode();
  const toolCount = registry.tools.length;
  const exposedToolCount = registry.tools.filter((tool) => tool.exposed).length;
  const healthyToolCount = registry.tools.filter((tool) => tool.health === "healthy").length;
  const activeExposureCount = registry.exposures.filter((item) => item.status === "active").length;
  const verifiedDomainCount = registry.domains.filter((item) => item.status === "verified").length;
  return {
    version: "v1",
    mode,
    toolCount,
    exposedToolCount,
    healthyToolCount,
    publicUrlCount: registry.publicUrls.length,
    activeExposureCount,
    domainCount: registry.domains.length,
    verifiedDomainCount,
    registry: getSystemsApiRegistryMetadata(),
    updatedAt: now(),
  };
}
