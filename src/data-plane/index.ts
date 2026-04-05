export type RuntimeKind = "container" | "vm" | "function";

export type DataPlaneUnit = {
  id: string;
  kind: RuntimeKind;
  state: "pending" | "running" | "stopped" | "failed";
  nodeId: string;
  image?: string;
  workloadId?: string;
};

export type StorageMount = {
  volumeId: string;
  mountPath: string;
  readOnly: boolean;
};

export type WorkloadRuntimeSnapshot = {
  workloadId: string;
  unitIds: string[];
  mounts: StorageMount[];
};

export const dataPlane = {
  runtimes: ["container", "vm", "function"] as const,
};
