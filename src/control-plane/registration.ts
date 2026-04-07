import type { NodeRegistrationRequest, NodeSpec } from "./types";

export function createRegisteredNode(input: NodeRegistrationRequest): NodeSpec {
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

export function registerNode(nodes: NodeSpec[], input: NodeRegistrationRequest): NodeSpec {
  const node = createRegisteredNode(input);
  nodes.push(node);
  return node;
}

export function refreshNodeHeartbeat(node: NodeSpec, lastSeenAt = new Date().toISOString()): NodeSpec {
  return {
    ...node,
    lastSeenAt,
    status: node.status === "offline" ? "pending" : node.status,
  };
}
