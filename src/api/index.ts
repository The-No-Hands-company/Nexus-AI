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
