import { architecture } from "../architecture";
import { controlPlane, controlPlaneService } from "../control-plane";
import { dataPlane } from "../data-plane";
import { federationService } from "../federation";
import { observabilityService } from "../observability";
import { storage } from "../storage";
import { systemsApiService } from "../systems-api";

export type { ApiRoute } from "./dto";
export * from "./dto";

export const apiRoutes = [
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
  { method: "GET", path: "/api/v1/tools/:toolId", description: "Inspect a registered tool" },
  { method: "GET", path: "/api/v1/tools/:toolId/history", description: "Inspect a tool lifecycle history" },
  { method: "PATCH", path: "/api/v1/tools/:toolId", description: "Update registered tool metadata" },
  { method: "POST", path: "/api/v1/tools/:toolId/enable", description: "Enable a registered tool" },
  { method: "POST", path: "/api/v1/tools/:toolId/disable", description: "Disable a registered tool" },
  { method: "GET", path: "/api/v1/status", description: "Return normalized platform status" },
  { method: "POST", path: "/api/v1/public-url", description: "Request or refresh a public URL" },
] as const;

export const apiSurface = {
  architecture,
  controlPlane,
  dataPlane,
  federation: federationService.describeFederation(),
  observability: observabilityService.describeObservability(),
  storage,
  systemsApi: systemsApiService.describeSystemsApiStatus(),
  snapshot: controlPlaneService.snapshot,
};
