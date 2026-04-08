import type {
  SystemsApiDomainBinding,
  SystemsApiDomainBindingStatus,
  SystemsApiExposureRecord,
  SystemsApiExposureStatus,
  SystemsApiPublicUrl,
  SystemsApiStatus,
  SystemsApiTool,
} from "../systems-api";

export type SystemsApiExposureTargetStatus = SystemsApiExposureStatus | SystemsApiDomainBindingStatus;

export type SystemsApiExposureTargetDTO = {
  toolId: string;
  publicUrl: string;
  domain: string | null;
  verificationToken: string | null;
  status: SystemsApiExposureTargetStatus;
  target: string;
  expiresAt: string | null;
  revokedAt: string | null;
};

export type SystemsApiExposureResourceDTO = {
  target: SystemsApiExposureTargetDTO;
};

export type SystemsApiExposureResourcesResponseDTO = {
  exposures: readonly SystemsApiExposureResourceDTO[];
};

export type SystemsApiExposureResourceResponseDTO = {
  exposure: SystemsApiExposureResourceDTO;
};

export type SystemsApiDomainsResponseDTO = {
  domains: readonly SystemsApiExposureResourceDTO[];
};

export type SystemsApiDomainResponseDTO = {
  domain: SystemsApiExposureResourceDTO;
};

export type SystemsApiExposureStatusSummaryDTO = {
  total: number;
  active: number;
  verified: number;
  pending: number;
  revoked: number;
};

export type SystemsApiExposureStatusResponseDTO = {
  status: SystemsApiStatus;
  tools: readonly SystemsApiTool[];
  publicUrls: readonly SystemsApiPublicUrl[];
  exposures: readonly SystemsApiExposureResourceDTO[];
  domains: readonly SystemsApiExposureResourceDTO[];
  summary: SystemsApiExposureStatusSummaryDTO;
};

function exposureExpiresAt(requestedAt: string): string {
  const timestamp = Date.parse(requestedAt);
  if (Number.isNaN(timestamp)) {
    return requestedAt;
  }
  return new Date(timestamp + 1000 * 60 * 60 * 24 * 30).toISOString();
}

export function toSystemsApiExposureTargetDTO(record: SystemsApiExposureRecord): SystemsApiExposureTargetDTO {
  return {
    toolId: record.toolId,
    publicUrl: record.publicUrl,
    domain: null,
    verificationToken: null,
    status: record.status,
    target: record.canonicalUrl,
    expiresAt: exposureExpiresAt(record.requestedAt),
    revokedAt: record.revokedAt ?? null,
  };
}

export function toSystemsApiDomainTargetDTO(binding: SystemsApiDomainBinding): SystemsApiExposureTargetDTO {
  return {
    toolId: binding.toolId,
    publicUrl: binding.publicUrl,
    domain: binding.domain,
    verificationToken: binding.verificationToken,
    status: binding.status,
    target: binding.canonicalUrl,
    expiresAt: binding.verificationExpiresAt,
    revokedAt: binding.revokedAt ?? null,
  };
}

export function toSystemsApiExposureResourceDTO(record: SystemsApiExposureRecord): SystemsApiExposureResourceDTO {
  return { target: toSystemsApiExposureTargetDTO(record) };
}

export function toSystemsApiDomainResourceDTO(binding: SystemsApiDomainBinding): SystemsApiExposureResourceDTO {
  return { target: toSystemsApiDomainTargetDTO(binding) };
}

export function toSystemsApiExposureResourcesResponseDTO(exposures: readonly SystemsApiExposureRecord[]): SystemsApiExposureResourcesResponseDTO {
  return { exposures: exposures.map(toSystemsApiExposureResourceDTO) };
}

export function toSystemsApiDomainResourcesResponseDTO(domains: readonly SystemsApiDomainBinding[]): SystemsApiDomainsResponseDTO {
  return { domains: domains.map(toSystemsApiDomainResourceDTO) };
}

export function toSystemsApiExposureStatusResponseDTO(
  status: SystemsApiStatus,
  tools: readonly SystemsApiTool[],
  publicUrls: readonly SystemsApiPublicUrl[],
  exposures: readonly SystemsApiExposureRecord[],
  domains: readonly SystemsApiDomainBinding[],
): SystemsApiExposureStatusResponseDTO {
  const exposureResources = exposures.map(toSystemsApiExposureResourceDTO);
  const domainResources = domains.map(toSystemsApiDomainResourceDTO);
  const summary: SystemsApiExposureStatusSummaryDTO = {
    total: exposureResources.length + domainResources.length,
    active: exposureResources.filter((item) => item.target.status === "active").length,
    verified: domainResources.filter((item) => item.target.status === "verified").length,
    pending: exposureResources.filter((item) => item.target.status === "requested" || item.target.status === "suspended" || item.target.status === "pending").length + domainResources.filter((item) => item.target.status === "pending").length,
    revoked: exposureResources.filter((item) => item.target.status === "revoked").length + domainResources.filter((item) => item.target.status === "revoked").length,
  };

  return {
    status,
    tools,
    publicUrls,
    exposures: exposureResources,
    domains: domainResources,
    summary,
  };
}
