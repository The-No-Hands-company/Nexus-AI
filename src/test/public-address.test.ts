import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { createSystemsApiTestHarness } from "../test/systems-api-harness";
import { systemsApiService } from "../systems-api";

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

describe("public address issuance flow", () => {
  test("issues web exposure, records addresses, and binds domains", async () => {
    const toolId = "tool-public-url";
    const name = "Public URL Tool";

    systemsApiService.registerSystemsApiTool({
      id: toolId,
      name,
      description: "Exposes a web URL",
      exposed: false,
      capabilities: ["public-url.exposure"],
    });

    const body = { toolId, desiredHost: "public.example.com" };
    const publicUrlResponse = await handleRequest(
      new Request("http://localhost/api/v1/public-url", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      }),
    );

    expect(publicUrlResponse.status).toBe(201);
    const publicUrlBody = await publicUrlResponse.json();
    expect(publicUrlBody.publicUrl?.url).toBeTruthy();
    expect(publicUrlBody.tool.id).toBe(toolId);

    const addressesList = await handleRequest(new Request("http://localhost/api/v1/addresses"));
    expect(addressesList.status).toBe(200);
    const addressesJson = await addressesList.json();
    expect(Array.isArray(addressesJson.addresses)).toBe(true);
    expect(addressesJson.addresses.some((item: any) => item.toolId === toolId && item.kind === "website")).toBe(true);

    const exposuresList = await handleRequest(new Request("http://localhost/api/v1/exposures"));
    expect(exposuresList.status).toBe(200);
    const exposuresJson = await exposuresList.json();
    expect(exposuresJson.exposures.some((item: any) => item.target.toolId === toolId && item.target.status === "active")).toBe(true);

    const domainResponse = await handleRequest(
      new Request("http://localhost/api/v1/domains", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ toolId, domain: "example.com" }),
      }),
    );
    expect(domainResponse.status).toBe(201);
    const domainJson = await domainResponse.json();
    const domainTarget = domainJson.domain?.target;
    expect(domainTarget).toBeTruthy();
    expect(domainTarget.status).toBe("pending");
    expect(domainTarget.publicUrl).toBe(publicUrlBody.publicUrl.url);

    const domainFetch = await handleRequest(new Request("http://localhost/api/v1/domains/example.com"));
    expect(domainFetch.status).toBe(200);
    const domainFetchJson = await domainFetch.json();
    expect(domainFetchJson.domain?.target.status).toBe("pending");

    const registry = systemsApiService.describeSystemsApiStatus();
    expect(registry.addressCount).toBeGreaterThanOrEqual(1);
    expect(registry.publicUrlCount).toBeGreaterThanOrEqual(1);
    expect(registry.domainCount).toBeGreaterThanOrEqual(1);
  });
});
