import type { SystemsApiDeployRequest, SystemsApiDeployResponse } from "./types";

export type SystemsApiDeployIntegration = {
  endpoint: string;
  auth: "bearer";
  purpose: string;
};

export const systemsApiDeployIntegration: SystemsApiDeployIntegration = {
  endpoint: "/api/v1/deployments",
  auth: "bearer",
  purpose: "Request managed Deploy deployments from Nexus Cloud",
};

export function describeSystemsApiDeployIntegration(): SystemsApiDeployIntegration {
  return systemsApiDeployIntegration;
}

export async function requestSystemsApiDeploy(
  baseUrl: string,
  token: string,
  input: SystemsApiDeployRequest,
): Promise<{ status: number; data: SystemsApiDeployResponse | null }> {
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}${systemsApiDeployIntegration.endpoint}`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify(input),
  });
  const data = await response.json().catch(() => null);
  return { status: response.status, data: data as SystemsApiDeployResponse | null };
}

export type { SystemsApiDeployRequest, SystemsApiDeployResponse };
