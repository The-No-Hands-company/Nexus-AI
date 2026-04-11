import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { createSystemsApiTestHarness } from "../test/systems-api-harness";
import { apiRouteManifest } from "./routes";

describe("Systems API topology surface", () => {
  let handleRequest: (request: Request) => Promise<Response>;
  let cleanup: () => void;

  beforeAll(async () => {
    const harness = await createSystemsApiTestHarness();
    handleRequest = harness.handleRequest;
    cleanup = harness.cleanup;
  });

  afterAll(() => {
    cleanup?.();
  });

  test("manifest includes the canonical topology endpoints", () => {
    expect(apiRouteManifest.map((route) => route.path)).toEqual(
      expect.arrayContaining(["/api/v1/apps", "/api/v1/connections", "/api/v1/topology"]),
    );
  });

  test("GET /api/v1/topology returns the canonical app graph", async () => {
    const response = await handleRequest(new Request("http://localhost/api/v1/topology", { method: "GET" }));
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.topology.summary.appCount).toBeGreaterThanOrEqual(7);
    expect(body.topology.summary.connectionCount).toBeGreaterThanOrEqual(1);
    expect(body.topology.apps.some((app: { id: string }) => app.id === "nexus-cloud")).toBe(true);
    expect(body.topology.apps.some((app: { id: string }) => app.id === "nexus-vault")).toBe(true);
  });

  test("GET /api/v1/apps and /api/v1/connections expose the same graph slices", async () => {
    const appsResponse = await handleRequest(new Request("http://localhost/api/v1/apps", { method: "GET" }));
    const connectionsResponse = await handleRequest(new Request("http://localhost/api/v1/connections", { method: "GET" }));

    expect(appsResponse.status).toBe(200);
    expect(connectionsResponse.status).toBe(200);

    const appsBody = await appsResponse.json();
    const connectionsBody = await connectionsResponse.json();

    expect(appsBody.apps.map((app: { id: string }) => app.id)).toEqual(
      expect.arrayContaining(["nexus-cloud", "nexus", "nexus-ai", "nexus-computer", "nexus-deploy", "nexus-hosting", "nexus-network", "nexus-vault"]),
    );
    expect(connectionsBody.connections.map((connection: { id: string }) => connection.id)).toEqual(
      expect.arrayContaining(["cloud-owns-registry", "cloud-owns-vault", "hosting-uses-deploy"]),
    );
  });
});
