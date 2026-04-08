import { beforeAll, afterAll, describe, expect, test } from "bun:test";
import { apiRouteManifest } from "./routes";
import { createSystemsApiTestHarness } from "../test/systems-api-harness";

const routePaths = apiRouteManifest.map((route) => route.path);

describe("API route handlers", () => {
  let handleRequest: (request: Request) => Promise<Response>;
  let systemsApiService: typeof import("../systems-api").systemsApiService;
  let cleanup: () => void;

  beforeAll(async () => {
    const harness = await createSystemsApiTestHarness();
    handleRequest = harness.handleRequest;
    systemsApiService = harness.systemsApiService;
    cleanup = harness.cleanup;
  });

  afterAll(() => {
    cleanup?.();
  });

  test("shares a canonical manifest that includes the exposure lifecycle routes", () => {
    expect(routePaths).toContain("/api/v1/exposures/:toolId");
    expect(routePaths).toContain("/api/v1/exposures/:toolId/revoke");
  });

  test("serves GET /api/v1/exposures/:toolId and POST /api/v1/exposures/:toolId/revoke end-to-end", async () => {
    systemsApiService.registerSystemsApiTool({
      id: "tool-alpha",
      name: "Alpha",
      description: "Alpha tool",
      exposed: false,
      health: "healthy",
      capabilities: ["exposure.lifecycle"],
    });
    const exposure = systemsApiService.requestSystemsApiExposure({
      toolId: "tool-alpha",
      desiredHost: "alpha.example.com",
    });
    expect(exposure).not.toBeNull();

    const getResponse = await handleRequest(new Request("http://localhost/api/v1/exposures/tool-alpha", { method: "GET" }));
    expect(getResponse.status).toBe(200);
    expect(await getResponse.json()).toEqual({
      exposure: {
        target: {
          toolId: "tool-alpha",
          publicUrl: "https://alpha.example.com",
          domain: null,
          verificationToken: null,
          status: "active",
          target: "https://tool-alpha.nexus.local",
          expiresAt: expect.any(String),
          revokedAt: null,
        },
      },
    });

    const revokeResponse = await handleRequest(new Request("http://localhost/api/v1/exposures/tool-alpha/revoke", { method: "POST" }));
    expect(revokeResponse.status).toBe(200);
    expect(await revokeResponse.json()).toEqual({
      exposure: {
        target: {
          toolId: "tool-alpha",
          publicUrl: "https://alpha.example.com",
          domain: null,
          verificationToken: null,
          status: "revoked",
          target: "https://tool-alpha.nexus.local",
          expiresAt: expect.any(String),
          revokedAt: expect.any(String),
        },
      },
    });

    const afterRevokeResponse = await handleRequest(new Request("http://localhost/api/v1/exposures/tool-alpha", { method: "GET" }));
    expect(afterRevokeResponse.status).toBe(200);
    expect(await afterRevokeResponse.json()).toEqual({
      exposure: {
        target: {
          toolId: "tool-alpha",
          publicUrl: "https://alpha.example.com",
          domain: null,
          verificationToken: null,
          status: "revoked",
          target: "https://tool-alpha.nexus.local",
          expiresAt: expect.any(String),
          revokedAt: expect.any(String),
        },
      },
    });

    const missingGetResponse = await handleRequest(new Request("http://localhost/api/v1/exposures/missing-tool", { method: "GET" }));
    expect(missingGetResponse.status).toBe(404);

    const missingRevokeResponse = await handleRequest(new Request("http://localhost/api/v1/exposures/missing-tool/revoke", { method: "POST" }));
    expect(missingRevokeResponse.status).toBe(404);
  });

  test("serves GET /api/v1/exposures as a lifecycle list and reflects revocation", async () => {
    systemsApiService.registerSystemsApiTool({
      id: "tool-beta",
      name: "Beta",
      description: "Beta tool",
      exposed: false,
      health: "healthy",
      capabilities: ["exposure.lifecycle"],
    });

    const created = systemsApiService.requestSystemsApiExposure({
      toolId: "tool-beta",
      desiredHost: "beta.example.com",
    });
    expect(created).not.toBeNull();

    const beforeResponse = await handleRequest(new Request("http://localhost/api/v1/exposures", { method: "GET" }));
    expect(beforeResponse.status).toBe(200);
    expect(await beforeResponse.json()).toEqual({
      exposures: expect.arrayContaining([
        {
          target: {
            toolId: "tool-alpha",
            publicUrl: "https://alpha.example.com",
            domain: null,
            verificationToken: null,
            status: "revoked",
            target: "https://tool-alpha.nexus.local",
            expiresAt: expect.any(String),
            revokedAt: expect.any(String),
          },
        },
        {
          target: {
            toolId: "tool-beta",
            publicUrl: "https://beta.example.com",
            domain: null,
            verificationToken: null,
            status: "active",
            target: "https://tool-beta.nexus.local",
            expiresAt: expect.any(String),
            revokedAt: null,
          },
        },
      ]),
    });

    const revokeResponse = await handleRequest(new Request("http://localhost/api/v1/exposures/tool-beta/revoke", { method: "POST" }));
    expect(revokeResponse.status).toBe(200);

    const afterResponse = await handleRequest(new Request("http://localhost/api/v1/exposures", { method: "GET" }));
    expect(afterResponse.status).toBe(200);
    expect(await afterResponse.json()).toEqual({
      exposures: expect.arrayContaining([
        {
          target: {
            toolId: "tool-alpha",
            publicUrl: "https://alpha.example.com",
            domain: null,
            verificationToken: null,
            status: "revoked",
            target: "https://tool-alpha.nexus.local",
            expiresAt: expect.any(String),
            revokedAt: expect.any(String),
          },
        },
        {
          target: {
            toolId: "tool-beta",
            publicUrl: "https://beta.example.com",
            domain: null,
            verificationToken: null,
            status: "revoked",
            target: "https://tool-beta.nexus.local",
            expiresAt: expect.any(String),
            revokedAt: expect.any(String),
          },
        },
      ]),
    });
  });
});
