import { buildPublicAddress, createAddressRecord, revokeAddressRecord } from "./address";
import { buildPublicUrl, createExposureRecord, revokeExposureRecord, transitionExposureRecord } from "./exposure";
import { createDomainBinding, issueDomainVerificationChallenge as buildDomainVerificationChallenge, revokeDomainBinding as revokeDomainRecord, verifyDomainBinding as verifyDomainRecord } from "./domains";
import { getSystemsApiRegistryMetadata, loadSystemsApiRegistry, saveSystemsApiRegistry, type SystemsApiRegistryData } from "./store";
import type {
  SystemsApiAddress,
  SystemsApiAddressKind,
  SystemsApiAddressStatus,
  SystemsApiDomainBinding,
  SystemsApiDomainVerificationChallenge,
  SystemsApiExposureRecord,
  SystemsApiExposureStatus,
  SystemsApiMode,
  SystemsApiPublicUrl,
  SystemsApiPublicUrlStatus,
  SystemsApiStatus,
  SystemsApiTool,
  SystemsApiToolExposure,
  SystemsApiToolHealth,
  SystemsApiToolHistoryAction,
  SystemsApiToolHistoryEntry,
} from "./types";

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

const registry: SystemsApiRegistryData = loadSystemsApiRegistry();

function persist(): void {
  saveSystemsApiRegistry(registry);
}

function cloneRegistryData(data: SystemsApiRegistryData): SystemsApiRegistryData {
  return {
    tools: data.tools.map((item) => ({ ...item })),
    publicUrls: data.publicUrls.map((item) => ({ ...item })),
    addresses: data.addresses.map((item) => ({ ...item })),
    history: data.history.map((item) => ({ ...item })),
    exposures: data.exposures.map((item) => ({ ...item })),
    domains: data.domains.map((item) => ({ ...item })),
  };
}

export function resetSystemsApiRegistryForTests(next: SystemsApiRegistryData = { tools: [], publicUrls: [], addresses: [], history: [], exposures: [], domains: [] }): void {
  const snapshot = cloneRegistryData(next);
  registry.tools = snapshot.tools;
  registry.publicUrls = snapshot.publicUrls;
  registry.addresses = snapshot.addresses;
  registry.history = snapshot.history;
  registry.exposures = snapshot.exposures;
  registry.domains = snapshot.domains;
  persist();
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

function upsertAddressRecord(record: SystemsApiAddress): SystemsApiAddress {
  const existingIndex = registry.addresses.findIndex((item) => item.toolId === record.toolId && item.kind === record.kind && item.subject === record.subject);
  if (existingIndex >= 0) registry.addresses[existingIndex] = record;
  else registry.addresses.push(record);
  return record;
}

function upsertDomainRecord(record: SystemsApiDomainBinding): SystemsApiDomainBinding {
  const existingIndex = registry.domains.findIndex((item) => item.domain === record.domain);
  if (existingIndex >= 0) registry.domains[existingIndex] = record;
  else registry.domains.push(record);
  return record;
}

function hasActiveWebsiteAddress(toolId: string): boolean {
  return registry.addresses.some((item) => item.toolId === toolId && item.kind === "website" && item.status === "active");
}

function hasActiveAddress(toolId: string): boolean {
  return registry.addresses.some((item) => item.toolId === toolId && item.status === "active");
}

function revokePublicUrlRecord(toolId: string): SystemsApiPublicUrl | null {
  const publicUrl = getPublicUrl(toolId);
  if (!publicUrl) return null;
  const revoked: SystemsApiPublicUrl = {
    ...publicUrl,
    status: "revoked",
  };
  upsertPublicUrlRecord(revoked);
  pushHistory(toolId, "public-url-revoked", `Revoked public URL for ${toolId}`, now());
  return revoked;
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

export function requestSystemsApiAddress(input: SystemsApiAddressRequest): SystemsApiAddress | null {
  const tool = getTool(input.toolId);
  if (!tool) return null;

  const publicAddress = buildPublicAddress(input);
  const record = createAddressRecord(input, publicAddress, "active");
  upsertAddressRecord(record);

  updateToolRecord(tool.id, (current) => ({
    ...current,
    exposed: true,
    exposure: "public",
    publicUrl: input.kind === "website" ? publicAddress : current.publicUrl,
    updatedAt: now(),
  }));

  if (input.kind === "website") {
    const publicUrl: SystemsApiPublicUrl = {
      toolId: tool.id,
      url: publicAddress,
      status: "active",
      issuedAt: record.requestedAt,
      expiresAt: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString(),
    };
    upsertPublicUrlRecord(publicUrl);

    const existingExposure = getExposure(tool.id);
    const exposure = existingExposure
      ? transitionExposureRecord(existingExposure, "active", publicAddress, record.requestedAt)
      : createExposureRecord({ toolId: tool.id, desiredHost: input.desiredHost }, publicAddress, "active", record.requestedAt);
    upsertExposureRecord(exposure);

    pushHistory(tool.id, "public-url-issued", `Issued public URL for ${tool.name}`, record.requestedAt);
    pushHistory(tool.id, "exposure-requested", `Requested exposure for ${tool.name}`, exposure.requestedAt);
    pushHistory(tool.id, "exposure-activated", `Activated exposure for ${tool.name}`, exposure.activatedAt ?? exposure.updatedAt);
  }

  pushHistory(tool.id, "address-issued", `Issued ${input.kind} address ${publicAddress}`, record.requestedAt);
  persist();
  return record;
}

export function revokeSystemsApiAddress(input: { toolId: string; kind?: SystemsApiAddressKind }): readonly SystemsApiAddress[] {
  const matches = registry.addresses.filter((item) => item.toolId === input.toolId && (input.kind === undefined || item.kind === input.kind));
  if (!matches.length) return [];

  const revoked = matches.map((address) => {
    const next = revokeAddressRecord(address);
    upsertAddressRecord(next);
    pushHistory(input.toolId, "address-revoked", `Revoked ${next.kind} address ${next.publicAddress}`, next.revokedAt ?? next.updatedAt);
    return next;
  });

  const needsPublicUrlRevoke = revoked.some((item) => item.kind === "website");
  if (needsPublicUrlRevoke) {
    revokePublicUrlRecord(input.toolId);
  }

  if (!hasActiveAddress(input.toolId)) {
    updateToolRecord(input.toolId, (current) => ({
      ...current,
      exposed: false,
      exposure: "private",
      publicUrl: undefined,
      updatedAt: now(),
    }));
  }

  persist();
  return revoked;
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

export function requestPublicUrl(input: SystemsApiPublicUrlRequest): SystemsApiPublicUrl | null {
  const tool = getTool(input.toolId);
  if (!tool) return null;

  const requestedAddress = requestSystemsApiAddress({
    toolId: tool.id,
    kind: "website",
    subject: input.desiredHost?.replace(/^https?:\/\//, "") || tool.id,
    desiredHost: input.desiredHost,
  });
  if (!requestedAddress) return null;

  return getPublicUrl(tool.id);
}

export function listPublicUrls(): readonly SystemsApiPublicUrl[] {
  return registry.publicUrls;
}

export function getPublicUrl(toolId: string): SystemsApiPublicUrl | null {
  return registry.publicUrls.find((item) => item.toolId === toolId) ?? null;
}

export function listAddresses(): readonly SystemsApiAddress[] {
  return registry.addresses;
}

export function getAddress(toolId: string, kind?: SystemsApiAddressKind): SystemsApiAddress | null {
  return registry.addresses.find((item) => item.toolId === toolId && (kind === undefined || item.kind === kind)) ?? null;
}

export function listExposures(): readonly SystemsApiExposureRecord[] {
  return registry.exposures;
}

export function getExposure(toolId: string): SystemsApiExposureRecord | null {
  return registry.exposures.find((item) => item.toolId === toolId) ?? null;
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
    };
  }

  for (const address of registry.addresses.filter((item) => item.toolId === toolId)) {
    const revokedAddress = revokeAddressRecord(address);
    upsertAddressRecord(revokedAddress);
    pushHistory(toolId, "address-revoked", `Revoked ${revokedAddress.kind} address ${revokedAddress.publicAddress}`, revokedAddress.revokedAt ?? revokedAddress.updatedAt);
  }

  for (const domain of registry.domains.filter((item) => item.toolId === toolId)) {
    const revokedDomain = revokeDomainRecord(domain);
    upsertDomainRecord(revokedDomain);
    pushHistory(toolId, "domain-revoked", `Revoked ${revokedDomain.domain}`, revokedDomain.revokedAt ?? revokedDomain.updatedAt);
  }

  updateToolRecord(toolId, (current) => ({
    ...current,
    exposed: false,
    exposure: "private",
    publicUrl: undefined,
    updatedAt: now(),
  }));

  pushHistory(toolId, "exposure-revoked", `Revoked exposure for ${tool?.name ?? toolId}`, revoked.revokedAt ?? revoked.updatedAt);
  persist();
  return revoked;
}

export function listDomainBindings(): readonly SystemsApiDomainBinding[] {
  return registry.domains;
}

export function getDomainBinding(domain: string): SystemsApiDomainBinding | null {
  return registry.domains.find((item) => item.domain === domain) ?? null;
}

export function requestDomainBinding(input: SystemsApiDomainBindingRequest): SystemsApiDomainBinding | null {
  const publicUrl = getPublicUrl(input.toolId);
  if (!publicUrl || publicUrl.status !== "active") return null;

  const existing = getDomainBinding(input.domain);
  const binding = createDomainBinding({ toolId: input.toolId, domain: input.domain, desiredHost: input.desiredHost }, publicUrl.url, existing?.status ?? "pending");
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
    addressCount: registry.addresses.length,
    addressKinds: ["website", "email", "server", "custom"],
    activeExposureCount,
    domainCount: registry.domains.length,
    verifiedDomainCount,
    registry: getSystemsApiRegistryMetadata(),
    updatedAt: now(),
  };
}
