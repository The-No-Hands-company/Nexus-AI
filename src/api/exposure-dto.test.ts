import { describe, expect, test } from "bun:test";
import type { SystemsApiDomainBinding, SystemsApiExposureRecord, SystemsApiPublicUrl, SystemsApiStatus, SystemsApiTool } from "../systems-api";
import { toSystemsApiExposureResourceDTO, toSystemsApiExposureStatusResponseDTO, toSystemsApiExposureTargetDTO } from "./exposure-dto";

const timestamp = "2026-04-08T00:00:00.000Z";
const revokedAt = "2026-04-08T01:00:00.000Z";

const activeExposure: SystemsApiExposureRecord = {
  id: "exp_active",
  toolId: "tool-alpha",
  canonicalUrl: "https://tool-alpha.nexus.local",
  publicUrl: "https://alpha.example.com",
  desiredHost: "alpha.example.com",
  status: "active",
  requestedAt: timestamp,
  activatedAt: timestamp,
  updatedAt: timestamp,
};

const revokedExposure: SystemsApiExposureRecord = {
  ...activeExposure,
  id: "exp_revoked",
  status: "revoked",
  revokedAt,
  updatedAt: revokedAt,
};

const verifiedDomain: SystemsApiDomainBinding = {
  domain: "alpha.example.com",
  toolId: "tool-alpha",
  canonicalUrl: "https://tool-alpha.nexus.local",
  publicUrl: "https://alpha.example.com",
  verificationToken: "token-alpha",
  verificationIssuedAt: timestamp,
  verificationExpiresAt: revokedAt,
  status: "verified",
  requestedAt: timestamp,
  verifiedAt: revokedAt,
  updatedAt: revokedAt,
};

const pendingDomain: SystemsApiDomainBinding = {
  ...verifiedDomain,
  domain: "beta.example.com",
  publicUrl: "https://beta.example.com",
  verificationToken: "token-beta",
  status: "pending",
  verifiedAt: undefined,
  revokedAt: undefined,
  updatedAt: timestamp,
};

const tool: SystemsApiTool = {
  id: "tool-alpha",
  name: "Alpha",
  description: "Alpha tool",
  mode: "standalone",
  exposed: true,
  exposure: "public",
  health: "healthy",
  capabilities: ["exposure.lifecycle"],
  publicUrl: "https://alpha.example.com",
  registeredAt: timestamp,
  updatedAt: timestamp,
};

const publicUrl: SystemsApiPublicUrl = {
  toolId: "tool-alpha",
  url: "https://alpha.example.com",
  status: "active",
  issuedAt: timestamp,
  expiresAt: revokedAt,
};

const status: SystemsApiStatus = {
  version: "v1",
  mode: "standalone",
  toolCount: 1,
  exposedToolCount: 1,
  healthyToolCount: 1,
  publicUrlCount: 1,
  activeExposureCount: 1,
  domainCount: 2,
  verifiedDomainCount: 1,
  registry: {
    path: "/tmp/registry.json",
    exists: true,
    sizeBytes: 123,
    lastWriteAt: timestamp,
    ageSeconds: 12,
  },
  updatedAt: timestamp,
};

describe("exposure DTOs", () => {
  test("maps an active exposure for GET /api/v1/exposures/:toolId", () => {
    expect(toSystemsApiExposureTargetDTO(activeExposure)).toEqual({
      toolId: "tool-alpha",
      publicUrl: "https://alpha.example.com",
      domain: null,
      verificationToken: null,
      status: "active",
      target: "https://tool-alpha.nexus.local",
      expiresAt: "2026-05-08T00:00:00.000Z",
      revokedAt: null,
    });
  });

  test("maps a revoked exposure for POST /api/v1/exposures/:toolId/revoke", () => {
    expect(toSystemsApiExposureResourceDTO(revokedExposure)).toEqual({
      target: {
        toolId: "tool-alpha",
        publicUrl: "https://alpha.example.com",
        domain: null,
        verificationToken: null,
        status: "revoked",
        target: "https://tool-alpha.nexus.local",
        expiresAt: "2026-05-08T00:00:00.000Z",
        revokedAt,
      },
    });
  });

  test("keeps exposure and domain summaries aligned with revoked state", () => {
    const response = toSystemsApiExposureStatusResponseDTO(
      status,
      [tool],
      [publicUrl],
      [activeExposure, revokedExposure],
      [verifiedDomain, pendingDomain],
    );

    expect(response.summary).toEqual({
      total: 4,
      active: 1,
      verified: 1,
      pending: 1,
      revoked: 1,
    });

    expect(response.exposures[1]).toEqual({
      target: {
        toolId: "tool-alpha",
        publicUrl: "https://alpha.example.com",
        domain: null,
        verificationToken: null,
        status: "revoked",
        target: "https://tool-alpha.nexus.local",
        expiresAt: "2026-05-08T00:00:00.000Z",
        revokedAt,
      },
    });
  });
});
