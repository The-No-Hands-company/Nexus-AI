import { architecture } from "./architecture";
import { apiRoutes } from "./api";
import { controlPlane, type NodeRegistrationRequest, type NodeSpec, type PlacementPlan, type WorkloadSpec } from "./control-plane";
import { dataPlane } from "./data-plane";
import { federation, type FederationPeer, type FederationSignedRequest } from "./federation";
import { observability } from "./observability";
import { snapshot, state } from "./state";
import { storage } from "./storage";

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

function buildNode(input: NodeRegistrationRequest): NodeSpec {
  return {
    id: `node_${crypto.randomUUID()}`,
    name: input.name,
    region: input.region,
    zone: input.zone,
    labels: input.labels ?? {},
    capacity: input.capacity,
    status: "ready",
    lastSeenAt: new Date().toISOString(),
  };
}

function upsertWorkload(workload: WorkloadSpec): WorkloadSpec {
  const existingIndex = state.workloads.findIndex((item) => item.id === workload.id);
  if (existingIndex >= 0) {
    state.workloads[existingIndex] = workload;
  } else {
    state.workloads.push(workload);
  }
  return workload;
}

function planWorkload(workload: WorkloadSpec): PlacementPlan {
  const readyNodes = state.nodes.filter((node) => node.status === "ready");
  if (readyNodes.length === 0) {
    return { workloadId: workload.id, decisions: [] };
  }

  const base = Math.floor(workload.replicas / readyNodes.length);
  const remainder = workload.replicas % readyNodes.length;

  const decisions = readyNodes
    .map((node, index) => ({
      nodeId: node.id,
      replicas: base + (index < remainder ? 1 : 0),
      reason: `Balanced across ${readyNodes.length} ready node(s)`,
    }))
    .filter((decision) => decision.replicas > 0);

  return { workloadId: workload.id, decisions };
}

function upsertPeer(domain: string, trust?: FederationSignedRequest | Record<string, unknown>): FederationPeer {
  const existingIndex = state.peers.findIndex((peer) => peer.domain === domain);
  const peer: FederationPeer = {
    domain,
    trust: {
      identity: domain,
      issuer: trust && "keyId" in trust ? String(trust.keyId) : domain,
      audience: "nexus-cloud",
      publicKeyHint: trust && "signature" in trust ? String(trust.signature).slice(0, 16) : "manual",
      signatureScheme: "ed25519",
      expiresAt: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString(),
    },
    status: "healthy",
    lastSeenAt: new Date().toISOString(),
    version: "0.1.0",
  };

  if (existingIndex >= 0) {
    state.peers[existingIndex] = peer;
  } else {
    state.peers.push(peer);
  }

  return peer;
}

async function handle(request: Request): Promise<Response> {
  const url = new URL(request.url);
  const { pathname } = url;

  if (request.method === "GET" && pathname === "/health") {
    return json({
      ok: true,
      project: architecture.project,
      services: {
        controlPlane: controlPlane.services,
        dataPlane: dataPlane.runtimes,
        federation: federation.protocol,
        observability: observability.signals,
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
    return json(snapshot());
  }

  if (request.method === "GET" && pathname === "/v1/nodes") {
    return json({ nodes: state.nodes });
  }

  if (request.method === "POST" && pathname === "/v1/nodes/register") {
    const body = await readJson<NodeRegistrationRequest>(request);
    if (!body?.name || !body.region || !body.zone || !body.capacity) {
      return badRequest("Missing node registration fields");
    }

    const node = buildNode(body);
    state.nodes.push(node);
    return json({ node }, 201);
  }

  if (request.method === "GET" && pathname === "/v1/workloads") {
    return json({ workloads: state.workloads });
  }

  if (request.method === "POST" && pathname === "/v1/workloads/plan") {
    const body = await readJson<WorkloadSpec>(request);
    if (!body?.id || !body.name || !body.image || typeof body.replicas !== "number") {
      return badRequest("Missing workload fields");
    }

    const workload = upsertWorkload(body);
    const plan = planWorkload(workload);
    return plan.decisions.length === 0
      ? json({ workload, plan, warning: "No ready nodes available" }, 503)
      : json({ workload, plan });
  }

  if (request.method === "GET" && pathname === "/v1/federation/peers") {
    return json({ peers: state.peers });
  }

  if (request.method === "POST" && pathname.startsWith("/v1/federation/peers/") && pathname.endsWith("/trust")) {
    const domain = decodeURIComponent(pathname.slice("/v1/federation/peers/".length, -"/trust".length));
    if (!domain) {
      return badRequest("Missing peer domain");
    }

    const trust = await readJson<FederationSignedRequest>(request);
    const peer = upsertPeer(domain, trust ?? undefined);
    return json({ peer }, 201);
  }

  return notFound();
}

export const port = Number(process.env.PORT ?? "8787");
export const server = Bun.serve({
  port,
  fetch: handle,
});
