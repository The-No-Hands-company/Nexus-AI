import { architecture } from "../architecture";
import { controlPlane, controlPlaneService } from "../control-plane";
import { dataPlane } from "../data-plane";
import { federationService } from "../federation";
import { observabilityService } from "../observability";
import { storage } from "../storage";
import { systemsApiService } from "../systems-api";
import { apiRouteManifest } from "./routes";

export type { ApiRoute } from "./dto";
export * from "./dto";

export const apiRoutes = apiRouteManifest;

export const cloudContract = {
  scope: "public-access-and-domain-issuance",
  canonicalDocs: "/docs/cloud-contract.md",
  discovery: [
    "/api/v1/topology",
    "/api/v1/apps",
    "/api/v1/connections",
    "/api/v1/status",
    "/api/v1/summary",
  ],
  issuance: [
    "/api/v1/public-url",
    "/api/v1/addresses",
    "/api/v1/exposures",
    "/api/v1/domains",
  ],
  deployBridge: [
    "/api/v1/deployments",
    "/api/v1/deployments/integration",
  ],
} as const;

export const apiSurface = {
  architecture,
  controlPlane,
  dataPlane,
  federation: federationService.describeFederation(),
  observability: observabilityService.describeObservability(),
  storage,
  systemsApi: systemsApiService.describeSystemsApiStatus(),
  systemsTopology: systemsApiService.describeSystemsApiTopology(),
  cloudContract,
  snapshot: controlPlaneService.snapshot,
};
