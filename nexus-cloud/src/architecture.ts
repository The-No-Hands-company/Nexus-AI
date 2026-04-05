export type ArchitectureLayer = {
  name: string;
  description: string;
};

export type FederationTrust = {
  identity: string;
  issuer: string;
  audience: string;
  publicKeyHint: string;
  signatureScheme: string;
  expiresAt: string;
};

export const architecture = {
  project: "Nexus Cloud",
  mission: "A self-hosted, federated cloud scaffold for sovereign infrastructure.",
  principles: [
    "Sovereign by default",
    "Federated when needed",
    "Portable workloads",
    "Simple operator control",
    "No vendor lock-in",
  ],
  layers: [
    {
      name: "Control plane",
      description: "Identity, auth, node registration, scheduling, policy, and placement.",
    },
    {
      name: "Data plane",
      description: "Workload execution, networking, storage attachment, and runtime isolation.",
    },
    {
      name: "Federation layer",
      description: "Trust relationships, discovery, signed requests, and cross-cluster routing.",
    },
    {
      name: "Storage layer",
      description: "Object, block, and snapshot storage with replication and retention policies.",
    },
    {
      name: "Observability",
      description: "Metrics, logs, traces, audit trails, and operator dashboards.",
    },
  ] satisfies ArchitectureLayer[],
};
