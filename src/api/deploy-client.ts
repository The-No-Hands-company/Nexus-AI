import { cloudConfig } from "../config";
import type { SystemsApiDeployRequest, SystemsApiDeployResponse } from "../systems-api";

export async function requestManagedDeploy(input: SystemsApiDeployRequest): Promise<{ status: number; data: SystemsApiDeployResponse | null }> {
  const response = await fetch(`${cloudConfig.deployUrl.replace(/\/$/, "")}/api/v1/deployments`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${cloudConfig.deployToken}`,
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify(input),
  });
  const data = await response.json().catch(() => null);
  return { status: response.status, data: data as SystemsApiDeployResponse | null };
}
