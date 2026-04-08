import { getSystemsApiRegistryMetadata, loadSystemsApiRegistry, saveSystemsApiRegistry, type SystemsApiRegistryData } from "./store";
import type { SystemsApiMode, SystemsApiPublicUrl, SystemsApiStatus, SystemsApiTool, SystemsApiToolExposure, SystemsApiToolHealth, SystemsApiToolHistoryEntry } from "./types";

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

function buildPublicUrl(toolId: string, desiredHost?: string): string {
  const host = desiredHost?.trim() || `${toolId}.nexus.local`;
  return host.startsWith("http://") || host.startsWith("https://") ? host : `https://${host}`;
}

function findToolIndex(toolId: string): number {
  return registry.tools.findIndex((tool) => tool.id === toolId);
}

function pushHistory(entry: SystemsApiToolHistoryEntry): void {
  registry.history.push(entry);
}

function updateToolRecord(toolId: string, updater: (tool: SystemsApiTool) => SystemsApiTool): SystemsApiTool | null {
  const existingIndex = findToolIndex(toolId);
  if (existingIndex < 0) {
    return null;
  }

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

export function listTools(): readonly SystemsApiTool[] {
  return registry.tools;
}

export function getTool(toolId: string): SystemsApiTool | null {
  return registry.tools.find((tool) => tool.id === toolId) ?? null;
}

export function listToolHistory(toolId: string): readonly SystemsApiToolHistoryEntry[] {
  return registry.history.filter((entry) => entry.toolId === toolId);
}

export function upsertTool(input: SystemsApiToolRegistrationInput): SystemsApiTool {
  const existingIndex = findToolIndex(input.id);
  const previous = existingIndex >= 0 ? registry.tools[existingIndex] : null;
  const tool = buildTool(input, previous);
  const action = previous ? "updated" : "registered";

  if (existingIndex >= 0) {
    registry.tools[existingIndex] = tool;
  } else {
    registry.tools.push(tool);
  }

  pushHistory({
    toolId: tool.id,
    action,
    summary: action === "registered" ? `Registered ${tool.name}` : `Updated ${tool.name}`,
    at: tool.updatedAt,
  });
  persist();
  return tool;
}

export function patchTool(toolId: string, patch: SystemsApiToolPatchInput): SystemsApiTool | null {
  const existingIndex = findToolIndex(toolId);
  if (existingIndex < 0) {
    return null;
  }

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

  registry.tools[existingIndex] = tool;
  pushHistory({
    toolId,
    action: "updated",
    summary: `Edited metadata for ${tool.name}`,
    at: tool.updatedAt,
  });
  persist();
  return tool;
}

export function setToolExposure(toolId: string, exposed: boolean): SystemsApiTool | null {
  const tool = updateToolRecord(toolId, (current) => ({
    ...current,
    exposed,
    exposure: exposureFromFlag(exposed),
    updatedAt: now(),
  }));

  if (!tool) {
    return null;
  }

  pushHistory({
    toolId,
    action: exposed ? "enabled" : "disabled",
    summary: exposed ? `Enabled ${tool.name}` : `Disabled ${tool.name}`,
    at: tool.updatedAt,
  });
  persist();
  return tool;
}

export function requestPublicUrl(input: SystemsApiPublicUrlRequest): SystemsApiPublicUrl | null {
  const tool = getTool(input.toolId);
  if (!tool) {
    return null;
  }

  const url = buildPublicUrl(tool.id, input.desiredHost);
  const record: SystemsApiPublicUrl = {
    toolId: tool.id,
    url,
    status: "active",
    issuedAt: now(),
    expiresAt: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString(),
  };

  const existingIndex = registry.publicUrls.findIndex((item) => item.toolId === tool.id);
  if (existingIndex >= 0 && !input.refresh) {
    registry.publicUrls[existingIndex] = {
      ...registry.publicUrls[existingIndex],
      url,
      status: "active",
      issuedAt: now(),
      expiresAt: record.expiresAt,
    };
  } else if (existingIndex >= 0) {
    registry.publicUrls[existingIndex] = record;
  } else {
    registry.publicUrls.push(record);
  }

  updateToolRecord(tool.id, (current) => ({
    ...current,
    exposed: true,
    exposure: "public",
    publicUrl: url,
    updatedAt: now(),
  }));

  pushHistory({
    toolId: tool.id,
    action: "public-url-issued",
    summary: `Issued public URL for ${tool.name}`,
    at: record.issuedAt,
  });
  persist();
  return record;
}

export function listPublicUrls(): readonly SystemsApiPublicUrl[] {
  return registry.publicUrls;
}

export function describeStatus(): SystemsApiStatus {
  const mode = currentMode();
  const toolCount = registry.tools.length;
  const exposedToolCount = registry.tools.filter((tool) => tool.exposed).length;
  const healthyToolCount = registry.tools.filter((tool) => tool.health === "healthy").length;
  return {
    version: "v1",
    mode,
    toolCount,
    exposedToolCount,
    healthyToolCount,
    publicUrlCount: registry.publicUrls.length,
    registry: getSystemsApiRegistryMetadata(),
    updatedAt: now(),
  };
}
