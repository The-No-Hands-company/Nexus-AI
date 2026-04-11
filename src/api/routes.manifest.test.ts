import { describe, expect, test } from "bun:test";
import { apiRouteManifest } from "./routes";
import type { ApiRoute } from "./dto";

describe("API route manifest", () => {
  test("matches the documented router surface exactly", () => {
    const expected: ApiRoute[] = [
      { method: "GET", path: "/health", description: "Basic service health" },
      { method: "GET", path: "/api/status", description: "Legacy node status summary" },
      { method: "GET", path: "/v1/architecture", description: "Project architecture summary" },
      { method: "GET", path: "/v1/state", description: "Read current scaffold state" },
      { method: "POST", path: "/v1/nodes/register", description: "Register a node with the control plane" },
      { method: "POST", path: "/v1/workloads/plan", description: "Produce a placement plan for a workload" },
      { method: "GET", path: "/v1/federation/peers", description: "List known federation peers" },
      { method: "POST", path: "/v1/federation/peers/:domain/trust", description: "Upsert a trust record for a peer" },
      { method: "GET", path: "/api/v1/tools", description: "List registered tools" },
      { method: "GET", path: "/api/v1/endpoints", description: "List Systems API endpoints" },
      { method: "GET", path: "/api/v1/capabilities", description: "List Systems API capabilities" },
      { method: "GET", path: "/api/v1/summary", description: "Describe the Systems API contract" },
      { method: "GET", path: "/api/v1/apps", description: "List the canonical Nexus app catalog" },
      { method: "GET", path: "/api/v1/connections", description: "List canonical Nexus app connections" },
      { method: "GET", path: "/api/v1/topology", description: "Describe the full Nexus app topology" },
      { method: "GET", path: "/api/v1/tools/:toolId", description: "Inspect a registered tool" },
      { method: "GET", path: "/api/v1/tools/:toolId/history", description: "Inspect a tool lifecycle history" },
      { method: "PATCH", path: "/api/v1/tools/:toolId", description: "Update registered tool metadata" },
      { method: "POST", path: "/api/v1/tools/:toolId/enable", description: "Enable a registered tool" },
      { method: "POST", path: "/api/v1/tools/:toolId/disable", description: "Disable a registered tool" },
      { method: "GET", path: "/api/v1/status", description: "Return normalized platform status" },
      { method: "POST", path: "/api/v1/public-url", description: "Compatibility alias for website address issuance" },
      { method: "GET", path: "/api/v1/addresses", description: "List general public address records" },
      { method: "GET", path: "/api/v1/addresses/:toolId", description: "Inspect general public address records for a tool" },
      { method: "POST", path: "/api/v1/addresses", description: "Request a general public address" },
      { method: "POST", path: "/api/v1/addresses/:toolId/revoke", description: "Revoke general public address records for a tool" },
      { method: "GET", path: "/api/v1/exposures", description: "List exposure records" },
      { method: "GET", path: "/api/v1/exposures/:toolId", description: "Inspect an exposure record" },
      { method: "POST", path: "/api/v1/exposures", description: "Request a new exposure" },
      { method: "POST", path: "/api/v1/exposures/:toolId/revoke", description: "Revoke an exposure record" },
      { method: "GET", path: "/api/v1/domains", description: "List domain bindings" },
      { method: "POST", path: "/api/v1/domains", description: "Bind a custom domain" },
      { method: "GET", path: "/api/v1/domains/:domain", description: "Inspect a domain binding" },
      { method: "POST", path: "/api/v1/domains/:domain/verify", description: "Verify a domain binding" },
      { method: "DELETE", path: "/api/v1/domains/:domain", description: "Revoke a domain binding" },
      { method: "POST", path: "/api/v1/deployments", description: "Request a managed Deploy deployment" },
      { method: "GET", path: "/api/v1/deployments/integration", description: "Inspect the Deploy backend integration" },
    ];
    const actual = apiRouteManifest.map((route) => ({ ...route })) as any[];
    expect(actual).toEqual(expected as any[]);
  });
});
