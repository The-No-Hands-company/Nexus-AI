import { architecture } from "../architecture";
import { controlPlane, controlPlaneService } from "../control-plane";
import { dataPlane } from "../data-plane";
import { federationService } from "../federation";
import { observabilityService } from "../observability";
import { storage } from "../storage";
import { systemsApiService } from "../systems-api";
import { describeSystemsApiDeployIntegration, systemsApiDeployIntegration } from "../systems-api/deploy";
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
  type SystemsApiAddressesResponseDTO,
  type SystemsApiAddressRequestDTO,
  type SystemsApiAddressRevokeRequestDTO,
  type SystemsApiAddressResponseDTO,
  type SystemsApiAppsResponseDTO,
  type SystemsApiCapabilitiesResponseDTO,
  type SystemsApiConnectionsResponseDTO,
  type SystemsApiDeployRequestDTO,
  type SystemsApiDeployResponseDTO,
  type SystemsApiDomainBindingRequestDTO,
  type SystemsApiDomainResponseDTO,
  type SystemsApiDomainVerificationRequestDTO,
  type SystemsApiDomainVerificationResponseDTO,
  type SystemsApiEndpointsResponseDTO,
  type SystemsApiExposureRequestDTO,
  type SystemsApiExposureResponseDTO,
  type SystemsApiExposuresResponseDTO,
  type SystemsApiPublicUrlRequestDTO,
  type SystemsApiPublicUrlResponseDTO,
  type SystemsApiStatusResponseDTO,
  type SystemsApiSummaryResponseDTO,
  type SystemsApiTopologyResponseDTO,
  type SystemsApiToolHistoryResponseDTO,
  type SystemsApiToolPatchRequestDTO,
  type SystemsApiToolResponseDTO,
  type SystemsApiToolsResponseDTO,
  type TrustPeerResponse,
  type WorkloadListResponse,
  isRegisterNodeRequest,
  isSystemsApiAddressRequest,
  isSystemsApiAddressRevokeRequest,
  isSystemsApiDeployRequest,
  isSystemsApiDomainBindingRequest,
  isSystemsApiDomainVerificationRequest,
  isSystemsApiExposureRequest,
  isSystemsApiPublicUrlRequest,
  isSystemsApiToolPatchRequest,
  isTrustPeerRequest,
  isWorkloadPlanRequest,
} from "./dto";
import {
  toSystemsApiDomainResourceDTO,
  toSystemsApiDomainResourcesResponseDTO,
  toSystemsApiExposureResourceDTO,
  toSystemsApiExposureResourcesResponseDTO,
  toSystemsApiExposureStatusResponseDTO,
  type SystemsApiExposureStatusResponseDTO,
} from "./exposure-dto";

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
  return json({ ...architecture, routes: apiRoutes });
}

function handleState(): Response {
  return json(controlPlaneService.snapshot());
}

function handleNodesList(): Response {
  const body: NodeListResponse = { nodes: controlPlaneService.listNodes() };
  return json(body);
}

async function handleNodeRegister(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isRegisterNodeRequest(body)) return badRequest("Missing node registration fields");
  const response: RegisterNodeResponse = { node: controlPlaneService.registerNode(body) };
  return json(response, 201);
}

function handleWorkloadsList(): Response {
  const body: WorkloadListResponse = { workloads: controlPlaneService.listWorkloads() };
  return json(body);
}

async function handleWorkloadPlan(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isWorkloadPlanRequest(body)) return badRequest("Missing workload fields");
  const result = controlPlaneService.planWorkload(body);
  if (!result.ok) {
    const response: PlanWorkloadErrorResponse = { error: result.error, policy: result.policy, quota: result.quota ?? null };
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
  return json({ peers: federationService.listPeers() } satisfies PeerListResponse);
}

async function handlePeerTrust(request: Request, pathname: string): Promise<Response> {
  const domain = decodeURIComponent(pathname.slice("/v1/federation/peers/".length, -"/trust".length));
  if (!domain) return badRequest("Missing peer domain");
  const trust = await readJson(request);
  if (!isTrustPeerRequest(trust)) return badRequest("Missing trust fields");
  const response: TrustPeerResponse = { peer: federationService.trustPeer(domain, trust) };
  return json(response, 201);
}

function handleSystemsTools(): Response {
  return json({ tools: systemsApiService.listSystemsApiTools() } satisfies SystemsApiToolsResponseDTO);
}

function handleSystemsEndpoints(): Response {
  return json({ endpoints: systemsApiService.listSystemsApiEndpoints() } satisfies SystemsApiEndpointsResponseDTO);
}

function handleSystemsCapabilities(): Response {
  return json({ capabilities: systemsApiService.listSystemsApiCapabilities() } satisfies SystemsApiCapabilitiesResponseDTO);
}

function handleSystemsSummary(): Response {
  return json({ summary: systemsApiService.describeSystemsApi() } satisfies SystemsApiSummaryResponseDTO);
}

function handleSystemsDeployIntegration(): Response {
  return json({ integration: describeSystemsApiDeployIntegration() });
}

async function handleSystemsDeploy(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiDeployRequest(body)) return badRequest("Missing deploy fields");
  const authToken = request.headers.get("authorization")?.slice(7);
  if (!authToken) return json({ error: "Unauthorized" }, 401);
  const endpoint = systemsApiDeployIntegration.endpoint;
  const deployUrl = process.env.NEXUS_DEPLOY_URL?.replace(/\/$/, "") ?? "";
  if (!deployUrl) return json({ error: "Deploy backend not configured" }, 503);
  const response = await fetch(`${deployUrl}${endpoint}`, {
    method: "POST",
    headers: {
      authorization: `Bearer ${authToken}`,
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify(body),
  });
  const data = (await response.json().catch(() => null)) as SystemsApiDeployResponseDTO | null;
  return json(data ?? { error: "Deploy backend returned an invalid response" }, response.status);
}

function handleSystemsTool(toolId: string): Response {
  const tool = systemsApiService.getSystemsApiTool(toolId);
  if (!tool) return notFound();
  return json({ tool } satisfies SystemsApiToolResponseDTO);
}

function handleSystemsToolHistory(toolId: string): Response {
  const tool = systemsApiService.getSystemsApiTool(toolId);
  if (!tool) return notFound();
  return json({ history: systemsApiService.listSystemsApiToolHistory(toolId) } satisfies SystemsApiToolHistoryResponseDTO);
}

async function handleSystemsToolPatch(request: Request, toolId: string): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiToolPatchRequest(body)) return badRequest("Missing tool metadata fields");
  if (body.name === undefined && body.description === undefined && body.mode === undefined && body.exposed === undefined && body.health === undefined && body.capabilities === undefined) {
    return badRequest("Empty tool metadata patch");
  }
  const tool = systemsApiService.updateSystemsApiTool(toolId, body as SystemsApiToolPatchRequestDTO);
  if (!tool) return notFound();
  return json({ tool } satisfies SystemsApiToolResponseDTO);
}

function handleSystemsToolEnable(toolId: string): Response {
  const tool = systemsApiService.enableSystemsApiTool(toolId);
  if (!tool) return notFound();
  return json({ tool } satisfies SystemsApiToolResponseDTO);
}

function handleSystemsToolDisable(toolId: string): Response {
  const tool = systemsApiService.disableSystemsApiTool(toolId);
  if (!tool) return notFound();
  return json({ tool } satisfies SystemsApiToolResponseDTO);
}

function handleSystemsStatus(): Response {
  const body: SystemsApiExposureStatusResponseDTO = toSystemsApiExposureStatusResponseDTO(
    systemsApiService.describeSystemsApiStatus(),
    systemsApiService.listSystemsApiTools(),
    systemsApiService.listSystemsApiPublicUrls(),
    systemsApiService.listSystemsApiExposures(),
    systemsApiService.listSystemsApiDomainBindings(),
  );
  return json(body);
}

async function handleSystemsPublicUrl(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiPublicUrlRequest(body)) return badRequest("Missing public URL fields");
  const publicUrl = systemsApiService.issueSystemsApiPublicUrl(body);
  if (!publicUrl) return json({ error: "Tool not found" }, 404);
  const tool = systemsApiService.getSystemsApiTool(body.toolId);
  if (!tool) return json({ error: "Tool not found" }, 404);
  const response: SystemsApiPublicUrlResponseDTO = { publicUrl, tool };
  return json(response, 201);
}

function handleSystemsAddresses(): Response {
  return json({ addresses: systemsApiService.listSystemsApiAddresses() } satisfies SystemsApiAddressesResponseDTO);
}

function handleSystemsAddressGet(toolId: string): Response {
  const addresses = systemsApiService.listSystemsApiAddressesForTool(toolId);
  if (!addresses.length) return notFound();
  const response: SystemsApiAddressesResponseDTO = { addresses };
  return json(response);
}

async function handleSystemsAddressPost(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiAddressRequest(body)) return badRequest("Missing address fields");
  const address = systemsApiService.requestSystemsApiAddress(body);
  if (!address) return notFound();
  const response: SystemsApiAddressResponseDTO = { address };
  return json(response, 201);
}

async function handleSystemsAddressRevoke(request: Request, toolId: string): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiAddressRevokeRequest(body)) return badRequest("Missing address revoke fields");
  const revoked = systemsApiService.revokeSystemsApiAddress({ toolId, kind: body.kind });
  return json({ addresses: revoked } satisfies SystemsApiAddressesResponseDTO);
}

function handleSystemsExposures(): Response {
  return json(toSystemsApiExposureResourcesResponseDTO(systemsApiService.listSystemsApiExposures()));
}

function handleSystemsExposureGet(toolId: string): Response {
  const exposure = systemsApiService.getSystemsApiExposure(toolId);
  if (!exposure) return notFound();
  return json({ exposure: toSystemsApiExposureResourceDTO(exposure) } satisfies SystemsApiExposureResponseDTO);
}

async function handleSystemsExposurePost(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiExposureRequest(body)) return badRequest("Missing exposure fields");
  const exposure = systemsApiService.requestSystemsApiExposure(body);
  if (!exposure) return notFound();
  return json({ exposure: toSystemsApiExposureResourceDTO(exposure) } satisfies SystemsApiExposureResponseDTO, 201);
}

function handleSystemsExposureRevoke(toolId: string): Response {
  const exposure = systemsApiService.revokeSystemsApiExposure(toolId);
  if (!exposure) return notFound();
  return json({ exposure: toSystemsApiExposureResourceDTO(exposure) } satisfies SystemsApiExposureResponseDTO);
}

function handleSystemsDomains(): Response {
  return json(toSystemsApiDomainResourcesResponseDTO(systemsApiService.listSystemsApiDomainBindings()));
}

async function handleSystemsDomainPost(request: Request): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiDomainBindingRequest(body)) return badRequest("Missing domain binding fields");
  const domain = systemsApiService.requestSystemsApiDomainBinding(body);
  if (!domain) return notFound();
  return json({ domain: toSystemsApiDomainResourceDTO(domain) } satisfies SystemsApiDomainResponseDTO, 201);
}

function handleSystemsDomainGet(domain: string): Response {
  const binding = systemsApiService.getSystemsApiDomainBinding(domain);
  if (!binding) return notFound();
  return json({ domain: toSystemsApiDomainResourceDTO(binding) } satisfies SystemsApiDomainResponseDTO);
}

async function handleSystemsDomainVerify(request: Request, domain: string): Promise<Response> {
  const body = await readJson(request);
  if (!isSystemsApiDomainVerificationRequest(body)) return badRequest("Missing verification token");
  const verified = systemsApiService.verifySystemsApiDomain(domain, body.token);
  if (!verified) return notFound();
  const challenge = systemsApiService.getSystemsApiDomainVerification(domain);
  if (!challenge) return notFound();
  return json({ challenge } satisfies SystemsApiDomainVerificationResponseDTO);
}

function handleSystemsDomainDelete(domain: string): Response {
  const revoked = systemsApiService.revokeSystemsApiDomain(domain);
  if (!revoked) return notFound();
  return json({ domain: toSystemsApiDomainResourceDTO(revoked) } satisfies SystemsApiDomainResponseDTO);
}

async function handleSystemsToolRoute(request: Request, pathname: string): Promise<Response> {
  const prefix = "/api/v1/tools/";
  const suffix = pathname.slice(prefix.length);
  if (!suffix) return notFound();
  if (request.method === "GET" && suffix.endsWith("/history")) {
    const toolId = decodeURIComponent(suffix.slice(0, -"/history".length));
    return toolId ? handleSystemsToolHistory(toolId) : badRequest("Missing tool id");
  }
  if (request.method === "GET" && !suffix.includes("/")) return handleSystemsTool(decodeURIComponent(suffix));
  if (request.method === "PATCH" && !suffix.includes("/")) return handleSystemsToolPatch(request, decodeURIComponent(suffix));
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

async function handleSystemsAddressRoute(request: Request, pathname: string): Promise<Response> {
  const prefix = "/api/v1/addresses/";
  const suffix = pathname.slice(prefix.length);
  if (!suffix) return notFound();
  if (request.method === "GET" && !suffix.includes("/")) return handleSystemsAddressGet(decodeURIComponent(suffix));
  if (request.method === "POST" && suffix.endsWith("/revoke")) {
    const toolId = decodeURIComponent(suffix.slice(0, -"/revoke".length));
    return handleSystemsAddressRevoke(request, toolId);
  }
  return notFound();
}

async function handleSystemsExposureRoute(request: Request, pathname: string): Promise<Response> {
  const prefix = "/api/v1/exposures/";
  const suffix = pathname.slice(prefix.length);
  if (!suffix) return notFound();
  if (request.method === "GET" && !suffix.includes("/")) return handleSystemsExposureGet(decodeURIComponent(suffix));
  if (request.method === "POST" && suffix.endsWith("/revoke")) {
    const toolId = decodeURIComponent(suffix.slice(0, -"/revoke".length));
    return toolId ? handleSystemsExposureRevoke(toolId) : badRequest("Missing tool id");
  }
  return notFound();
}

function handleSystemsApps(): Response {
  return json({ apps: systemsApiService.listSystemsApiApps() } satisfies SystemsApiAppsResponseDTO);
}

function handleSystemsConnections(): Response {
  return json({ connections: systemsApiService.listSystemsApiConnections() } satisfies SystemsApiConnectionsResponseDTO);
}

function handleSystemsTopology(): Response {
  return json({ topology: systemsApiService.describeSystemsApiTopology() } satisfies SystemsApiTopologyResponseDTO);
}

async function handleSystemsRoute(request: Request, pathname: string): Promise<Response> {
  if (request.method === "GET" && pathname === "/api/v1/apps") return handleSystemsApps();
  if (request.method === "GET" && pathname === "/api/v1/connections") return handleSystemsConnections();
  if (request.method === "GET" && pathname === "/api/v1/topology") return handleSystemsTopology();
  if (request.method === "GET" && pathname === "/api/v1/addresses") return handleSystemsAddresses();
  if (request.method === "POST" && pathname === "/api/v1/addresses") return handleSystemsAddressPost(request);
  if (pathname.startsWith("/api/v1/addresses/")) return await handleSystemsAddressRoute(request, pathname);
  if (request.method === "GET" && pathname === "/api/v1/exposures") return handleSystemsExposures();
  if (request.method === "POST" && pathname === "/api/v1/exposures") return handleSystemsExposurePost(request);
  if (pathname.startsWith("/api/v1/exposures/")) return await handleSystemsExposureRoute(request, pathname);
  if (request.method === "GET" && pathname === "/api/v1/domains") return handleSystemsDomains();
  if (request.method === "POST" && pathname === "/api/v1/domains") return handleSystemsDomainPost(request);
  if (pathname.startsWith("/api/v1/domains/")) {
    const suffix = pathname.slice("/api/v1/domains/".length);
    if (request.method === "GET" && !suffix.includes("/")) return handleSystemsDomainGet(decodeURIComponent(suffix));
    if (request.method === "POST" && suffix.endsWith("/verify")) {
      const domain = decodeURIComponent(suffix.slice(0, -"/verify".length));
      return handleSystemsDomainVerify(request, domain);
    }
    if (request.method === "DELETE" && !suffix.includes("/")) return handleSystemsDomainDelete(decodeURIComponent(suffix));
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
  if (request.method === "POST" && pathname.startsWith("/v1/federation/peers/") && pathname.endsWith("/trust")) return handlePeerTrust(request, pathname);
  if (request.method === "GET" && pathname === "/api/v1/tools") return handleSystemsTools();
  if (request.method === "GET" && pathname === "/api/v1/endpoints") return handleSystemsEndpoints();
  if (request.method === "GET" && pathname === "/api/v1/capabilities") return handleSystemsCapabilities();
  if (request.method === "GET" && pathname === "/api/v1/summary") return handleSystemsSummary();
  if (request.method === "GET" && pathname === "/api/v1/status") return handleSystemsStatus();
  if (request.method === "GET" && pathname === "/api/v1/deployments/integration") return handleSystemsDeployIntegration();
  if (request.method === "POST" && pathname === "/api/v1/deployments") return handleSystemsDeploy(request);
  if (request.method === "POST" && pathname === "/api/v1/public-url") return handleSystemsPublicUrl(request);
  if (pathname.startsWith("/api/v1/tools/")) return await handleSystemsToolRoute(request, pathname);
  if (pathname === "/api/v1/apps" || pathname === "/api/v1/connections" || pathname === "/api/v1/topology" || pathname === "/api/v1/addresses" || pathname.startsWith("/api/v1/addresses/") || pathname === "/api/v1/exposures" || pathname.startsWith("/api/v1/exposures/") || pathname === "/api/v1/domains" || pathname.startsWith("/api/v1/domains/")) {
    return await handleSystemsRoute(request, pathname);
  }
  return notFound();
}
