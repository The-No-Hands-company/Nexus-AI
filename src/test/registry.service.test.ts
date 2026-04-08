import { describe, expect, test } from "bun:test";
import { createSystemsApiTestHarness, emptySystemsApiRegistry } from "./systems-api-harness";

describe("Systems API registry/service behavior", () => {
  test("request and revoke exposure update registry state and history", async () => {
    const harness = await createSystemsApiTestHarness(emptySystemsApiRegistry);
    try {
      const { systemsApiService } = harness;

      systemsApiService.registerSystemsApiTool({
        id: "tool-gamma",
        name: "Gamma",
        description: "Gamma tool",
        exposed: false,
        health: "healthy",
        capabilities: ["exposure.lifecycle"],
      });

      const requested = systemsApiService.requestSystemsApiExposure({
        toolId: "tool-gamma",
        desiredHost: "gamma.example.com",
      });
      expect(requested?.status).toBe("active");
      expect(systemsApiService.getSystemsApiExposure("tool-gamma")?.status).toBe("active");

      const revoked = systemsApiService.revokeSystemsApiExposure("tool-gamma");
      expect(revoked?.status).toBe("revoked");
      expect(systemsApiService.getSystemsApiExposure("tool-gamma")?.status).toBe("revoked");
      expect(systemsApiService.listSystemsApiTools()[0]?.exposed).toBe(false);
      expect(systemsApiService.listSystemsApiToolHistory("tool-gamma").map((entry) => entry.action)).toEqual(
        expect.arrayContaining(["registered", "exposure-requested", "exposure-activated", "exposure-revoked"]),
      );
    } finally {
      harness.cleanup();
    }
  });
});
