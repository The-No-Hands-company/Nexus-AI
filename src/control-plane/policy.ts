import type { NodeSpec, WorkloadSpec } from "./types";

export type PolicyDecision = {
  allowed: boolean;
  reason: string;
};

export function evaluatePlacementPolicy(workload: WorkloadSpec, nodes: NodeSpec[]): PolicyDecision {
  if (workload.replicas < 1) {
    return { allowed: false, reason: "Workload must request at least one replica" };
  }

  if (nodes.length === 0) {
    return { allowed: false, reason: "No nodes are registered" };
  }

  return { allowed: true, reason: "Placement policy passed" };
}
