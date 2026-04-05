import type { NodeSpec, WorkloadSpec } from "./control-plane";
import type { FederationPeer } from "./federation";
import type { ObservabilityEvent } from "./observability";
import type { StorageVolume } from "./storage";

export const state = {
  nodes: [] as NodeSpec[],
  workloads: [] as WorkloadSpec[],
  peers: [] as FederationPeer[],
  events: [] as ObservabilityEvent[],
  volumes: [] as StorageVolume[],
};

export function snapshot() {
  return {
    nodes: state.nodes,
    workloads: state.workloads,
    peers: state.peers,
    events: state.events,
    volumes: state.volumes,
  };
}
