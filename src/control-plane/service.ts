import { snapshot as snapshotState, state } from "../state";
import { evaluatePlacementPolicy, type PolicyDecision } from "./policy";
import { evaluateQuota, type QuotaDecision } from "./quota";
import { upsertWorkload } from "./placement";
import { planWorkload as buildPlacementPlan } from "./scheduler";
import { registerNode as addNode } from "./registration";
import type { NodeRegistrationRequest, NodeSpec, PlacementPlan, WorkloadSpec } from "./types";

export type ControlPlaneSnapshot = ReturnType<typeof snapshotState>;

export type ControlPlanePlanningSuccess = {
  ok: true;
  status: 200 | 503;
  workload: WorkloadSpec;
  plan: PlacementPlan;
  policy: PolicyDecision;
  quota: QuotaDecision;
  warning?: string;
};

export type ControlPlanePlanningFailure = {
  ok: false;
  status: 409 | 422;
  error: string;
  policy: PolicyDecision;
  quota?: QuotaDecision;
};

export type ControlPlanePlanningResult = ControlPlanePlanningSuccess | ControlPlanePlanningFailure;

export function listNodes(): NodeSpec[] {
  return state.nodes;
}

export function listWorkloads(): WorkloadSpec[] {
  return state.workloads;
}

export function snapshot(): ControlPlaneSnapshot {
  return snapshotState();
}

export function registerNode(input: NodeRegistrationRequest): NodeSpec {
  return addNode(state.nodes, input);
}

export function planWorkload(workload: WorkloadSpec): ControlPlanePlanningResult {
  const policy = evaluatePlacementPolicy(workload, state.nodes);
  if (!policy.allowed) {
    return { ok: false, status: 409, error: policy.reason, policy };
  }

  const quota = evaluateQuota(workload);
  if (!quota.allowed) {
    return { ok: false, status: 422, error: quota.reason, policy, quota };
  }

  const persisted = upsertWorkload(state.workloads, workload);
  const plan = buildPlacementPlan(state.nodes, persisted);

  if (plan.decisions.length === 0) {
    return {
      ok: true,
      status: 503,
      workload: persisted,
      plan,
      policy,
      quota,
      warning: "No ready nodes available",
    };
  }

  return {
    ok: true,
    status: 200,
    workload: persisted,
    plan,
    policy,
    quota,
  };
}

export const controlPlaneService = {
  listNodes,
  listWorkloads,
  planWorkload,
  registerNode,
  snapshot,
};
