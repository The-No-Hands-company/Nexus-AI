import type { FederationTrust } from "../architecture";

export type FederationPeerStatus = "unknown" | "healthy" | "degraded" | "blocked";

export type FederationPeer = {
  domain: string;
  trust: FederationTrust;
  status: FederationPeerStatus;
  lastSeenAt?: string;
  version?: string;
};

export type FederationSignedRequest = {
  method: string;
  path: string;
  host: string;
  timestamp: string;
  nonce: string;
  keyId: string;
  signature: string;
};

export const federation = {
  protocol: "nexus-federation-v1",
  signedRequests: true,
  identityFormat: "node@cluster",
};
