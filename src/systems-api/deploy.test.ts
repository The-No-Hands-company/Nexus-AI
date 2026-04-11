import { describe, expect, test } from "bun:test";
import { describeSystemsApiDeployIntegration, systemsApiDeployIntegration } from "./deploy";

describe("Systems API Deploy integration", () => {
  test("exposes a minimal formal contract for Nexus Deploy", () => {
    expect(systemsApiDeployIntegration).toEqual({
      endpoint: "/api/v1/deployments",
      auth: "bearer",
      purpose: "Request managed Deploy deployments from Nexus Cloud",
    });
    expect(describeSystemsApiDeployIntegration()).toEqual(systemsApiDeployIntegration);
  });
});
