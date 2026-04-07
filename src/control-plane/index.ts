export * from "./identity";
export * from "./service";
export * from "./types";

export const controlPlane = {
  services: ["identity", "registration", "scheduler", "policy", "quota", "placement"] as const,
};
