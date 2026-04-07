import { state } from "../state";
import type { ObservabilityEvent, SignalKind } from "./index";

export type ObservabilitySummary = {
  signals: SignalKind[];
  eventCount: number;
};

export function listSignals(): SignalKind[] {
  return ["metrics", "logs", "traces", "audit"];
}

export function describeObservability(): ObservabilitySummary {
  return {
    signals: listSignals(),
    eventCount: state.events.length,
  };
}

export function listEvents(): ObservabilityEvent[] {
  return state.events;
}

export function recordEvent(event: ObservabilityEvent): ObservabilityEvent {
  state.events.push(event);
  return event;
}

export const observabilityService = {
  describeObservability,
  listEvents,
  listSignals,
  recordEvent,
};
