import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import type { SystemsApiMode, SystemsApiPublicUrl, SystemsApiPublicUrlStatus, SystemsApiTool, SystemsApiToolExposure, SystemsApiToolHealth, SystemsApiToolHistoryEntry } from "./types";

export type SystemsApiRegistryData = {
  tools: SystemsApiTool[];
  publicUrls: SystemsApiPublicUrl[];
  history: SystemsApiToolHistoryEntry[];
};

export type SystemsApiRegistryMetadata = {
  path: string;
  exists: boolean;
  sizeBytes: number;
  lastWriteAt: string | null;
  ageSeconds: number | null;
};

const REGISTRY_PATH = join(process.cwd(), "data", "systems-api-registry.json");

const EMPTY_REGISTRY: SystemsApiRegistryData = {
  tools: [],
  publicUrls: [],
  history: [],
};

function ensureStorageDir(): void {
  mkdirSync(dirname(REGISTRY_PATH), { recursive: true });
}

function sanitizeMode(value: unknown): SystemsApiMode | undefined {
  return value === "standalone" || value === "orchestrated" ? value : undefined;
}

function sanitizeHealth(value: unknown): SystemsApiToolHealth | undefined {
  return value === "healthy" || value === "degraded" || value === "offline" ? value : undefined;
}

function sanitizeExposure(value: unknown): SystemsApiToolExposure | undefined {
  return value === "private" || value === "public" || value === "pending" ? value : undefined;
}

function sanitizePublicUrlStatus(value: unknown): SystemsApiPublicUrlStatus | undefined {
  return value === "active" || value === "pending" || value === "revoked" ? value : undefined;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function toStringArray(value: unknown): readonly string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function sanitizeTool(value: unknown): SystemsApiTool | null {
  if (!isObject(value)) return null;
  const id = typeof value.id === "string" ? value.id : "";
  const name = typeof value.name === "string" ? value.name : "";
  const description = typeof value.description === "string" ? value.description : "";
  const registeredAt = typeof value.registeredAt === "string" ? value.registeredAt : new Date().toISOString();
  const updatedAt = typeof value.updatedAt === "string" ? value.updatedAt : registeredAt;
  if (!id || !name || !description) return null;
  return {
    id,
    name,
    description,
    mode: sanitizeMode(value.mode) ?? "standalone",
    exposed: Boolean(value.exposed),
    exposure: sanitizeExposure(value.exposure) ?? (Boolean(value.exposed) ? "public" : "private"),
    health: sanitizeHealth(value.health) ?? "healthy",
    capabilities: toStringArray(value.capabilities),
    publicUrl: typeof value.publicUrl === "string" ? value.publicUrl : undefined,
    registeredAt,
    updatedAt,
  };
}

function sanitizePublicUrl(value: unknown): SystemsApiPublicUrl | null {
  if (!isObject(value)) return null;
  const toolId = typeof value.toolId === "string" ? value.toolId : "";
  const url = typeof value.url === "string" ? value.url : "";
  const issuedAt = typeof value.issuedAt === "string" ? value.issuedAt : new Date().toISOString();
  const expiresAt = typeof value.expiresAt === "string" ? value.expiresAt : issuedAt;
  if (!toolId || !url) return null;
  return {
    toolId,
    url,
    status: sanitizePublicUrlStatus(value.status) ?? "active",
    issuedAt,
    expiresAt,
  };
}

function sanitizeHistoryEntry(value: unknown): SystemsApiToolHistoryEntry | null {
  if (!isObject(value)) return null;
  const toolId = typeof value.toolId === "string" ? value.toolId : "";
  const action = value.action === "registered" || value.action === "updated" || value.action === "enabled" || value.action === "disabled" || value.action === "public-url-issued" ? value.action : "updated";
  const summary = typeof value.summary === "string" ? value.summary : "";
  const at = typeof value.at === "string" ? value.at : new Date().toISOString();
  if (!toolId || !summary) return null;
  return { toolId, action, summary, at };
}

function sanitizeRegistry(value: unknown): SystemsApiRegistryData {
  if (!isObject(value)) return EMPTY_REGISTRY;
  const tools = Array.isArray(value.tools) ? value.tools.map(sanitizeTool).filter((item): item is SystemsApiTool => item !== null) : [];
  const publicUrls = Array.isArray(value.publicUrls) ? value.publicUrls.map(sanitizePublicUrl).filter((item): item is SystemsApiPublicUrl => item !== null) : [];
  const history = Array.isArray(value.history) ? value.history.map(sanitizeHistoryEntry).filter((item): item is SystemsApiToolHistoryEntry => item !== null) : [];
  return { tools, publicUrls, history };
}

export function loadSystemsApiRegistry(): SystemsApiRegistryData {
  if (!existsSync(REGISTRY_PATH)) return EMPTY_REGISTRY;
  try {
    const raw = readFileSync(REGISTRY_PATH, "utf8");
    return sanitizeRegistry(JSON.parse(raw));
  } catch {
    return EMPTY_REGISTRY;
  }
}

export function saveSystemsApiRegistry(registry: SystemsApiRegistryData): void {
  ensureStorageDir();
  writeFileSync(REGISTRY_PATH, `${JSON.stringify(registry, null, 2)}\n`);
}

export function getSystemsApiRegistryPath(): string {
  return REGISTRY_PATH;
}

export function getSystemsApiRegistryMetadata(): SystemsApiRegistryMetadata {
  if (!existsSync(REGISTRY_PATH)) {
    return {
      path: REGISTRY_PATH,
      exists: false,
      sizeBytes: 0,
      lastWriteAt: null,
      ageSeconds: null,
    };
  }

  const stats = statSync(REGISTRY_PATH);
  return {
    path: REGISTRY_PATH,
    exists: true,
    sizeBytes: stats.size,
    lastWriteAt: stats.mtime.toISOString(),
    ageSeconds: Math.max(0, Math.floor((Date.now() - stats.mtimeMs) / 1000)),
  };
}
