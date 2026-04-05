export type NodeStatus = "pending" | "ready" | "draining" | "offline";

export type NodeCapacity = {
  cpu: number;
  memoryMb: number;
  storageGb: number;
  publicIpv4?: string;
};

export type NodeSpec = {
  id: string;
  name: string;
  region: string;
  zone: string;
  labels: Record<string, string>;
  capacity: NodeCapacity;
  status: NodeStatus;
  lastSeenAt?: string;
};

export type NodeRegistrationRequest = {
  name: string;
  region: string;
  zone: string;
  labels?: Record<string, string>;
  capacity: NodeCapacity;
};

export type WorkloadRuntime = "container" | "vm" | "function";

export type WorkloadSpec = {
  id: string;
  name: string;
  image: string;
  replicas: number;
  cpuMillicores: number;
  memoryMb: number;
  env: Record<string, string>;
  ports: number[];
  runtime: WorkloadRuntime;
  storage: string[];
};

export type PlacementDecision = {
  nodeId: string;
  replicas: number;
  reason: string;
};

export type PlacementPlan = {
  workloadId: string;
  decisions: PlacementDecision[];
};

export const controlPlane = {
  services: ["identity", "registration", "scheduler", "policy", "quota", "placement"] as const,
};
