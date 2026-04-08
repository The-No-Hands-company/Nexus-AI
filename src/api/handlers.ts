import { architecture } from "../architecture";
import { controlPlane, controlPlaneService } from "../control-plane";
import { dataPlane } from "../data-plane";
import { federationService } from "../federation";
import { observabilityService } from "../observability";
import { storage } from "../storage";
import { systemsApiService } from "../systems-api";
import { apiRoutes } from "./index";
import {
  type ArchitectureResponse,
  type HealthResponse,
  type LegacyStatusResponse,
  type NodeListResponse,
  type PeerListResponse,
  type PlanWorkloadErrorResponse,
  type PlanWorkloadSuccessResponse,
  type RegisterNodeResponse,
  type StateResponse,
  type SystemsApiCapabilitiesResponseDTO,
  type SystemsApiEndpointsResponseDTO,
  type SystemsApiPublicUrlResponseDTO,
  type SystemsApiStatusResponseDTO,
  type SystemsApiSummaryResponseDTO,
  type SystemsApiToolHistoryResponseDTO,
  type SystemsApiToolPatchRequestDTO,
  type SystemsApiToolResponseDTO,
  type SystemsApiToolsResponseDTO,
  type TrustPeerResponse,
  type WorkloadListResponse,
  isRegisterNodeRequest,
  isSystemsApiPublicUrlRequest,
  isSystemsApiToolPatchRequest,
  isTrustPeerRequest,
  isWorkloadPlanRequest,
} from "./dto";

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status });
}

function badRequest(message: string): Response {
  return json({ error: message }, 400);
}

function notFound(): Response {
  return json({ error: "Not found" }, 404);
}

async function readJson(request: Request): Promise<unknown | null> {
  try {
    return await request.json();
  } catch {
    return null;
  }
}

function handleHealth(): Response {
  const body: HealthResponse = {
    ok: true,
    project: architecture.project,
    services: {
      controlPlane: controlPlane.services,
      dataPlane: dataPlane.runtimes,
      federation: federationService.describeFederation(),
      observability: observabilityService.describeObservability(),
      storage: storage.classes.map((item) => item.name),
    },
  };

  return json(body);
}

function handleLegacyStatus(): Response {
  const snapshot = controlPlaneService.snapshot();
  const body: LegacyStatusResponse = {
    status: "online",
    project: architecture.project,
    storage_used_gb: snapshot.volumes.reduce((total, volume) => total + volume.sizeGb, 0),
    files_count: snapshot.volumes.length,
    federation_peers: snapshot.peers.length,
    nodes: snapshot.nodes.length,
    workloads: snapshot.workloads.length,
    tools: systemsApiService.listSystemsApiTools().length,
    public_urls: systemsApiService.listSystemsApiPublicUrls().length,
    updated_at: new Date().toISOString(),
  };

  return json(body);
}

function handleArchitecture(): Response {
  const body: ArchitectureResponse = {
    ...architecture,
    routes: apiRoutes,
  };

  return json(body);
}

function handleState(): Response {
  const body: StateResponse = controlPlaneService.snapshot();
  return json(body);
}

function handleNodesList(): Response {
  const body: NodeListResponse = { nodes: controlPlaneService.listNodes() };
  return json(body);
}

async function handleNodeRegister(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isRegisterNodeRequest(body)) {
    return badRequest("Missing node registration fields");
  }

  const response: RegisterNodeResponse = { node: controlPlaneService.registerNode(body) };
  return json(response, 201);
}

function handleWorkloadsList(): Response {
  const body: WorkloadListResponse = { workloads: controlPlaneService.listWorkloads() };
  return json(body);
}

async function handleWorkloadPlan(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isWorkloadPlanRequest(body)) {
    return badRequest("Missing workload fields");
  }

  const result = controlPlaneService.planWorkload(body);
  if (!result.ok) {
    const response: PlanWorkloadErrorResponse = {
      error: result.error,
      policy: result.policy,
      quota: result.quota ?? null,
    };
    return json(response, result.status);
  }

  const response: PlanWorkloadSuccessResponse = {
    workload: result.workload,
    plan: result.plan,
    policy: result.policy,
    quota: result.quota,
    ...(result.warning ? { warning: result.warning } : {}),
  };

  return json(response, result.status);
}

function handlePeersList(): Response {
  const body: PeerListResponse = { peers: federationService.listPeers() };
  return json(body);
}

async function handlePeerTrust(request: Request, pathname: string): Promise<Response> {
  const domain = decodeURIComponent(pathname.slice("/v1/federation/peers/".length, -"/trust".length));
  if (!domain) {
    return badRequest("Missing peer domain");
  }

  const trust = await readJson(request);
  if (!isTrustPeerRequest(trust)) {
    return badRequest("Missing trust fields");
  }

  const response: TrustPeerResponse = { peer: federationService.trustPeer(domain, trust) };
  return json(response, 201);
}

function handleSystemsTools(): Response {
  const body: SystemsApiToolsResponseDTO = {
    tools: systemsApiService.listSystemsApiTools(),
  };
  return json(body);
}

function handleSystemsEndpoints(): Response {
  const body: SystemsApiEndpointsResponseDTO = {
    endpoints: systemsApiService.listSystemsApiEndpoints(),
  };
  return json(body);
}

function handleSystemsCapabilities(): Response {
  const body: SystemsApiCapabilitiesResponseDTO = {
    capabilities: systemsApiService.listSystemsApiCapabilities(),
  };
  return json(body);
}

function handleSystemsSummary(): Response {
  const body: SystemsApiSummaryResponseDTO = {
    summary: systemsApiService.describeSystemsApi(),
  };
  return json(body);
}

function handleSystemsTool(toolId: string): Response {
  const tool = systemsApiService.getSystemsApiTool(toolId);
  if (!tool) {
    return notFound();
  }

  const body: SystemsApiToolResponseDTO = { tool };
  return json(body);
}

function handleSystemsToolHistory(toolId: string): Response {
  const tool = systemsApiService.getSystemsApiTool(toolId);
  if (!tool) {
    return notFound();
  }

  const body: SystemsApiToolHistoryResponseDTO = {
    history: systemsApiService.listSystemsApiToolHistory(toolId),
  };
  return json(body);
}

async function handleSystemsToolPatch(request: Request, toolId: string): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiToolPatchRequest(body)) {
    return badRequest("Missing tool metadata fields");
  }

  if (
    body.name === undefined &&
    body.description === undefined &&
    body.mode === undefined &&
    body.exposed === undefined &&
    body.health === undefined &&
    body.capabilities === undefined
  ) {
    return badRequest("Empty tool metadata patch");
  }

  const tool = systemsApiService.updateSystemsApiTool(toolId, body as SystemsApiToolPatchRequestDTO);
  if (!tool) {
    return notFound();
  }

  const response: SystemsApiToolResponseDTO = { tool };
  return json(response);
}

function handleSystemsToolEnable(toolId: string): Response {
  const tool = systemsApiService.enableSystemsApiTool(toolId);
  if (!tool) {
    return notFound();
  }

  const body: SystemsApiToolResponseDTO = { tool };
  return json(body);
}

function handleSystemsToolDisable(toolId: string): Response {
  const tool = systemsApiService.disableSystemsApiTool(toolId);
  if (!tool) {
    return notFound();
  }

  const body: SystemsApiToolResponseDTO = { tool };
  return json(body);
}

function handleSystemsStatus(): Response {
  const body: SystemsApiStatusResponseDTO = {
    status: systemsApiService.describeSystemsApiStatus(),
    tools: systemsApiService.listSystemsApiTools(),
    publicUrls: systemsApiService.listSystemsApiPublicUrls(),
  };
  return json(body);
}

async function handleSystemsPublicUrl(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiPublicUrlRequest(body)) {
    return badRequest("Missing public URL fields");
  }

  const publicUrl = systemsApiService.issueSystemsApiPublicUrl(body);
  if (!publicUrl) {
    return json({ error: "Tool not found" }, 404);
  }

  const tool = systemsApiService.getSystemsApiTool(body.toolId);
  if (!tool) {
    return json({ error: "Tool not found" }, 404);
  }

  const response: SystemsApiPublicUrlResponseDTO = { publicUrl, tool };
  return json(response, 201);
}

async function handleSystemsToolRoute(request: Request, pathname: string): Promise<Response> {
  const prefix = "/api/v1/tools/";
  const suffix = pathname.slice(prefix.length);
  if (!suffix) {
    return notFound();
  }

  if (request.method === "GET" && suffix.endsWith("/history")) {
    const toolId = decodeURIComponent(suffix.slice(0, -"/history".length));
    return toolId ? handleSystemsToolHistory(toolId) : badRequest("Missing tool id");
  }

  if (request.method === "GET" && !suffix.includes("/")) {
    return handleSystemsTool(decodeURIComponent(suffix));
  }

  if (request.method === "PATCH" && !suffix.includes("/")) {
    return handleSystemsToolPatch(request, decodeURIComponent(suffix));
  }

  if (request.method === "POST" && suffix.endsWith("/enable")) {
    const toolId = decodeURIComponent(suffix.slice(0, -"/enable".length));
    return toolId ? handleSystemsToolEnable(toolId) : badRequest("Missing tool id");
  }

  if (request.method === "POST" && suffix.endsWith("/disable")) {
    const toolId = decodeURIComponent(suffix.slice(0, -"/disable".length));
    return toolId ? handleSystemsToolDisable(toolId) : badRequest("Missing tool id");
  }

  return notFound();
}

export async function handleApiRequest(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const { pathname } = url;

  if (request.method === "GET" && pathname === "/health") return handleHealth();
  if (request.method === "GET" && pathname === "/api/status") return handleLegacyStatus();
  if (request.method === "GET" && pathname === "/v1/architecture") return handleArchitecture();
  if (request.method === "GET" && pathname === "/v1/state") return handleState();
  if (request.method === "GET" && pathname === "/v1/nodes") return handleNodesList();
  if (request.method === "POST" && pathname === "/v1/nodes/register") return handleNodeRegister(request);
  if (request.method === "GET" && pathname === "/v1/workloads") return handleWorkloadsList();
  if (request.method === "POST" && pathname === "/v1/workloads/plan") return handleWorkloadPlan(request);
  if (request.method === "GET" && pathname === "/v1/federation/peers") return handlePeersList();
  if (request.method === "POST" && pathname.startsWith("/v1/federation/peers/") && pathname.endsWith("/trust")) {
    return handlePeerTrust(request, pathname);
  }
  if (request.method === "GET" && pathname === "/api/v1/tools") return handleSystemsTools();
  if (request.method === "GET" && pathname === "/api/v1/endpoints") return handleSystemsEndpoints();
  if (request.method === "GET" && pathname === "/api/v1/capabilities") return handleSystemsCapabilities();
  if (request.method === "GET" && pathname === "/api/v1/summary") return handleSystemsSummary();
  if (request.method === "GET" && pathname === "/api/v1/status") return handleSystemsStatus();
  if (request.method === "POST" && pathname === "/api/v1/public-url") return handleSystemsPublicUrl(request);
  if (pathname.startsWith("/api/v1/tools/")) {
    return await handleSystemsToolRoute(request, pathname);
  }

  return notFound();
}
