import type {
  SystemsApiDomainBinding,
  SystemsApiDomainBindingStatus,
  SystemsApiExposureRecord,
  SystemsApiExposureStatus,
  SystemsApiPublicUrl,
  SystemsApiStatus,
  SystemsApiTool,
} from "../systems-api";

export type SystemsApiExposureResourceStatus = SystemsApiExposureStatus | SystemsApiDomainBindingStatus;

export type SystemsApiExposureResourceDTO = {
  toolId: string;
  publicUrl: string;
  domain: string | null;
  verificationToken: string | null;
  status: SystemsApiExposureResourceStatus;
  target: string;
  expiresAt: string | null;
  revokedAt: string | null;
};

export type SystemsApiExposureResourcesResponseDTO = {
  exposures: readonly SystemsApiExposureResourceDTO[];
};

export type SystemsApiExposureResourceResponseDTO = {
  exposure: SystemsApiExposureResourceDTO;
};

export type SystemsApiDomainResourcesResponseDTO = {
  domains: readonly SystemsApiExposureResourceDTO[];
};

export type SystemsApiDomainResourceResponseDTO = {
  domain: SystemsApiExposureResourceDTO;
};

export type SystemsApiExposureStatusResponseDTO = {
  status: SystemsApiStatus;
  tools: readonly SystemsApiTool[];
  publicUrls: readonly SystemsApiPublicUrl[];
  exposures: readonly SystemsApiExposureResourceDTO[];
  domains: readonly SystemsApiExposureResourceDTO[];
};

function exposureExpiresAt(requestedAt: string): string {
  const timestamp = Date.parse(requestedAt);
  if (Number.isNaN(timestamp)) {
    return requestedAt;
  }
  return new Date(timestamp + 1000 * 60 * 60 * 24 * 30).toISOString();
}

export function toSystemsApiExposureResourceDTO(record: SystemsApiExposureRecord): SystemsApiExposureResourceDTO {
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

export function toSystemsApiDomainResourceDTO(binding: SystemsApiDomainBinding): SystemsApiExposureResourceDTO {
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

export function toSystemsApiExposureResourcesResponseDTO(exposures: readonly SystemsApiExposureRecord[]): SystemsApiExposureResourcesResponseDTO {
  return { exposures: exposures.map(toSystemsApiExposureResourceDTO) };
}

export function toSystemsApiDomainResourcesResponseDTO(domains: readonly SystemsApiDomainBinding[]): SystemsApiDomainResourcesResponseDTO {
  return { domains: domains.map(toSystemsApiDomainResourceDTO) };
}
