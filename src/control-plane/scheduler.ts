import type { NodeSpec, PlacementPlan, WorkloadSpec } from "./types";

export function planWorkload(nodes: NodeSpec[], workload: WorkloadSpec): PlacementPlan {
  const readyNodes = nodes.filter((node) => node.status === "ready");
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
