import { architecture } from "../architecture";
import { controlPlane } from "../control-plane";
import { dataPlane } from "../data-plane";
import { federation } from "../federation";
import { observability } from "../observability";
import { storage } from "../storage";
import { snapshot, state } from "../state";

export type ApiRoute = {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  description: string;
};

export const apiRoutes: ApiRoute[] = [
  { method: "GET", path: "/health", description: "Basic service health" },
  { method: "GET", path: "/v1/architecture", description: "Project architecture summary" },
  { method: "GET", path: "/v1/state", description: "Read current scaffold state" },
  { method: "POST", path: "/v1/nodes/register", description: "Register a node with the control plane" },
  { method: "POST", path: "/v1/workloads/plan", description: "Produce a placement plan for a workload" },
  { method: "GET", path: "/v1/federation/peers", description: "List known federation peers" },
  { method: "POST", path: "/v1/federation/peers/:domain/trust", description: "Upsert a trust record for a peer" },
];

export const apiSurface = {
  architecture,
  controlPlane,
  dataPlane,
  federation,
  observability,
  storage,
  state,
  snapshot,
};
