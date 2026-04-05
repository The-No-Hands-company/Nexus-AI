export type StorageKind = "object" | "block" | "snapshot";

export type StorageClass = {
  name: string;
  kind: StorageKind;
  replicated: boolean;
  encryptedAtRest: boolean;
};

export type StorageVolume = {
  id: string;
  className: string;
  sizeGb: number;
  attachedToNodeId?: string;
};

export const storage = {
  classes: [
    { name: "standard", kind: "object", replicated: true, encryptedAtRest: true },
    { name: "block", kind: "block", replicated: true, encryptedAtRest: true },
    { name: "snapshot", kind: "snapshot", replicated: false, encryptedAtRest: true },
  ] satisfies StorageClass[],
};
