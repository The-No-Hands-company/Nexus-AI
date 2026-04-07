import type { FederationTrust } from "../architecture";
import { state } from "../state";
import type { FederationPeer, FederationSignedRequest } from "./index";
import { upsertPeer as persistPeer } from "./peers";

export type FederationSummary = {
  protocol: string;
  signedRequests: boolean;
  identityFormat: string;
  peerCount: number;
};

export function describeFederation(): FederationSummary {
  return {
    protocol: "nexus-federation-v1",
    signedRequests: true,
    identityFormat: "node@cluster",
    peerCount: state.peers.length,
  };
}

export function listPeers(): FederationPeer[] {
  return state.peers;
}

export function trustPeer(domain: string, trust?: FederationSignedRequest | Record<string, unknown>): FederationPeer {
  return persistPeer(state.peers, domain, trust);
}

export const federationService = {
  describeFederation,
  listPeers,
  trustPeer,
};
