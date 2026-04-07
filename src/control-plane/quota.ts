import type { WorkloadSpec } from "./types";

export type QuotaDecision = {
  allowed: boolean;
  reason: string;
};

export function evaluateQuota(workload: WorkloadSpec): QuotaDecision {
  if (workload.cpuMillicores <= 0 || workload.memoryMb <= 0) {
    return { allowed: false, reason: "Workload must request positive CPU and memory" };
  }

  return { allowed: true, reason: "Quota check passed" };
}
