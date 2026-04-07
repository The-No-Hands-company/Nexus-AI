export type ControlPlaneIdentity = {
  subject: string;
  issuer: string;
  audience: string;
  keyId: string;
  issuedAt: string;
  expiresAt: string;
};

export function createControlPlaneIdentity(subject: string, issuer = "nexus-cloud", audience = "nexus-control-plane"): ControlPlaneIdentity {
  const issuedAt = new Date();
  return {
    subject,
    issuer,
    audience,
    keyId: `cp_${crypto.randomUUID()}`,
    issuedAt: issuedAt.toISOString(),
    expiresAt: new Date(issuedAt.getTime() + 1000 * 60 * 60 * 24 * 30).toISOString(),
  };
}

export function isControlPlaneIdentityExpired(identity: ControlPlaneIdentity, at = new Date()): boolean {
  return at.getTime() > Date.parse(identity.expiresAt);
}
