import type { WorkloadSpec } from "./types";

export function upsertWorkload(workloads: WorkloadSpec[], workload: WorkloadSpec): WorkloadSpec {
  const existingIndex = workloads.findIndex((item) => item.id === workload.id);
  if (existingIndex >= 0) {
    workloads[existingIndex] = workload;
  } else {
    workloads.push(workload);
  }

  return workload;
}

export function listWorkloads(workloads: WorkloadSpec[]): WorkloadSpec[] {
  return workloads;
}
