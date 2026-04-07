import type { FederationTrust } from "../architecture";
import type { FederationPeer, FederationSignedRequest } from "./index";

function readString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

export function createPeerTrust(domain: string, trust?: FederationSignedRequest | Record<string, unknown>): FederationTrust {
  return {
    identity: domain,
    issuer: readString(trust && "keyId" in trust ? trust.keyId : undefined, domain),
    audience: "nexus-cloud",
    publicKeyHint: readString(trust && "signature" in trust ? trust.signature : undefined, "manual").slice(0, 16),
    signatureScheme: "ed25519",
    expiresAt: new Date(Date.now() + 1000 * 60 * 60 * 24 * 30).toISOString(),
  };
}

export function upsertPeer(peers: FederationPeer[], domain: string, trust?: FederationSignedRequest | Record<string, unknown>): FederationPeer {
  const peer: FederationPeer = {
    domain,
    trust: createPeerTrust(domain, trust),
    status: "healthy",
    lastSeenAt: new Date().toISOString(),
    version: "0.1.0",
  };

  const existingIndex = peers.findIndex((item) => item.domain === domain);
  if (existingIndex >= 0) {
    peers[existingIndex] = peer;
  } else {
    peers.push(peer);
  }

  return peer;
}
