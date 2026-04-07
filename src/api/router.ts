import { architecture } from "../architecture";
import { controlPlane, controlPlaneService, type NodeRegistrationRequest, type WorkloadSpec } from "../control-plane";
import { dataPlane } from "../data-plane";
import { federationService } from "../federation";
import { observabilityService } from "../observability";
import { storage } from "../storage";
import { apiRoutes } from "./index";

function json(data: unknown, status = 200): Response {
  return Response.json(data, { status });
}

function badRequest(message: string): Response {
  return json({ error: message }, 400);
}

function notFound(): Response {
  return json({ error: "Not found" }, 404);
}

async function readJson<T>(request: Request): Promise<T | null> {
  try {
    return (await request.json()) as T;
  } catch {
    return null;
  }
}

function isValidWorkload(body: WorkloadSpec | null): body is WorkloadSpec {
  return Boolean(body?.id && body.name && body.image && typeof body.replicas === "number");
}

function isValidNodeRegistration(body: NodeRegistrationRequest | null): body is NodeRegistrationRequest {
  return Boolean(body?.name && body.region && body.zone && body.capacity);
}

function planningResponse(result: ReturnType<typeof controlPlaneService.planWorkload>): Response {
  if (!result.ok) {
    return json(
      {
        error: result.error,
        policy: result.policy,
        quota: result.quota ?? null,
      },
      result.status,
    );
  }

  return json(
    {
      workload: result.workload,
      plan: result.plan,
      policy: result.policy,
      quota: result.quota,
      ...(result.warning ? { warning: result.warning } : {}),
    },
    result.status,
  );
}

export async function handleRequest(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const { pathname } = url;

  if (request.method === "GET" && pathname === "/health") {
    return json({
      ok: true,
      project: architecture.project,
      services: {
        controlPlane: controlPlane.services,
        dataPlane: dataPlane.runtimes,
        federation: federationService.describeFederation(),
        observability: observabilityService.describeObservability(),
        storage: storage.classes.map((item) => item.name),
      },
    });
  }

  if (request.method === "GET" && pathname === "/v1/architecture") {
    return json({
      ...architecture,
      routes: apiRoutes,
    });
  }

  if (request.method === "GET" && pathname === "/v1/state") {
    return json(controlPlaneService.snapshot());
  }

  if (request.method === "GET" && pathname === "/v1/nodes") {
    return json({ nodes: controlPlaneService.listNodes() });
  }

  if (request.method === "POST" && pathname === "/v1/nodes/register") {
    const body = await readJson<NodeRegistrationRequest>(request);
    if (!isValidNodeRegistration(body)) {
      return badRequest("Missing node registration fields");
    }

    return json({ node: controlPlaneService.registerNode(body) }, 201);
  }

  if (request.method === "GET" && pathname === "/v1/workloads") {
    return json({ workloads: controlPlaneService.listWorkloads() });
  }

  if (request.method === "POST" && pathname === "/v1/workloads/plan") {
    const body = await readJson<WorkloadSpec>(request);
    if (!isValidWorkload(body)) {
      return badRequest("Missing workload fields");
    }

    return planningResponse(controlPlaneService.planWorkload(body));
  }

  if (request.method === "GET" && pathname === "/v1/federation/peers") {
    return json({ peers: federationService.listPeers() });
  }

  if (request.method === "POST" && pathname.startsWith("/v1/federation/peers/") && pathname.endsWith("/trust")) {
    const domain = decodeURIComponent(pathname.slice("/v1/federation/peers/".length, -"/trust".length));
    if (!domain) {
      return badRequest("Missing peer domain");
    }

    const trust = await readJson<Record<string, unknown>>(request);
    return json({ peer: federationService.trustPeer(domain, trust ?? undefined) }, 201);
  }

  return notFound();
}
