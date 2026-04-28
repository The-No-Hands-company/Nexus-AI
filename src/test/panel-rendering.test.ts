import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const repoRoot = join(import.meta.dir, "..", "..");
const indexHtml = readFileSync(join(repoRoot, "static", "index.html"), "utf8");
const adminPanelScript = readFileSync(join(repoRoot, "static", "js", "panels", "admin-dashboard.js"), "utf8");
const liveTraceScript = readFileSync(join(repoRoot, "static", "js", "panels", "live-trace.js"), "utf8");

function esc(value: unknown): string {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function loadAdminHelpers() {
  const windowObject: Record<string, unknown> = {};
  return new Function(
    "window",
    "NexusApi",
    "esc",
    `${adminPanelScript}\nreturn window.NexusAdminDashboard;`,
  )(windowObject, { setPanelOpen() {}, apiJson: async () => ({ ok: true, data: {} }) }, esc) as {
    getTurnBudgetSeverity: (summary: Record<string, unknown>) => string;
    renderTurnBudgetSummary: (summary: Record<string, unknown>) => Record<string, unknown>;
  };
}

function loadLiveTraceHelpers() {
  const windowObject: Record<string, unknown> = {};
  const localStorageObject = {
    store: new Map<string, string>(),
    getItem(key: string) {
      return this.store.has(key) ? this.store.get(key)! : null;
    },
    setItem(key: string, value: string) {
      this.store.set(key, value);
    },
  };
  return new Function(
    "window",
    "NexusApi",
    "esc",
    "EventSource",
    "localStorage",
    `${liveTraceScript}\nreturn window.NexusLiveTrace;`,
  )(windowObject, { setPanelOpen() {} }, esc, function EventSource() {}, localStorageObject) as {
    ltTurnBudgetTheme: (pressure: string) => Record<string, string>;
    ltDescribeTurnBudget: (event: Record<string, unknown>) => Record<string, string>;
    ltPressureTickTheme: (pressure: string) => Record<string, string>;
    ltSummarizePressureHistory: (pressures: string[]) => string;
    ltRenderPressureHistory: (pressures: string[]) => string;
    ltSetHistoryWindow: (value: string | number) => void;
    ltLoadStoredHistoryWindow: () => number;
    ltStoreHistoryWindow: (value: string | number) => void;
    ltLoadStoredConnectionMode: () => string;
    ltStoreConnectionMode: (value: string) => void;
    ltSetConnectionMode: (value: string) => void;
    ltLoadStoredReplayTraceId: () => string;
    ltStoreReplayTraceId: (value: string) => void;
    ltRememberReplayTrace: (value: string) => void;
    ltLoadStoredAutoReplayOnOpen: () => boolean;
    ltStoreAutoReplayOnOpen: (enabled: boolean) => void;
    ltSetAutoReplayOnOpen: (enabled: boolean, options?: { persist?: boolean }) => void;
    ltShouldAutoReplayOnOpen: () => boolean;
  };
}

describe("frontend panel smoke rendering", () => {
  test("index.html includes turn-budget anchors in admin and live trace panels", () => {
    expect(indexHtml).toContain('id="ad-turn-card-rate"');
    expect(indexHtml).toContain('id="ad-turn-recent"');
    expect(indexHtml).toContain('id="lt-turn-budget-strip"');
    expect(indexHtml).toContain('id="lt-turn-budget-pressure"');
    expect(indexHtml).toContain('id="lt-turn-budget-mode"');
    expect(indexHtml).toContain('id="lt-turn-budget-history"');
    expect(indexHtml).toContain('id="lt-turn-budget-trend"');
    expect(indexHtml).toContain('id="lt-history-window"');
    expect(indexHtml).toContain('option value="20"');
    expect(indexHtml).toContain('option value="30"');
    expect(indexHtml).toContain('id="lt-mode-pref"');
    expect(indexHtml).toContain('id="lt-live-btn"');
    expect(indexHtml).toContain('id="lt-replay-btn"');
    expect(indexHtml).toContain('id="lt-trace-select"');
    expect(indexHtml).toContain('onchange="ltRememberReplayTrace(this.value)"');
    expect(indexHtml).toContain('id="lt-auto-replay-open"');
    expect(indexHtml).toContain('onchange="ltSetAutoReplayOnOpen(this.checked)"');
  });

  test("admin dashboard render helper marks hard-pressure windows as severe", () => {
    const admin = loadAdminHelpers();
    const rendered = admin.renderTurnBudgetSummary({
      downgrade_rate: 0.72,
      pressured_turns: 18,
      total_turns: 25,
      disable_mcts_count: 18,
      disable_ensemble_count: 7,
      pressure_counts: { hard: 7, soft: 11, none: 7 },
      model_family_counts: { compact: 12, reasoning: 9, balanced: 4 },
      recent: [
        {
          pressure: "hard",
          complexity: "high",
          model_family: "compact",
          disable_mcts: true,
          disable_ensemble: false,
          tool_budget_mode: "minimal",
        },
      ],
    });

    expect(admin.getTurnBudgetSeverity({ pressure_counts: { hard: 1 }, downgrade_rate: 0.05 })).toBe("hard");
    expect(rendered.severity).toBe("hard");
    expect(rendered.rateText).toBe("72.0% · 18/25");
    expect(String(rendered.recentRowsHtml)).toContain("MCTS off");
    expect(String(rendered.familiesText)).toContain("compact 12");
  });

  test("live trace helper describes turn-budget strip state for soft pressure", () => {
    const liveTrace = loadLiveTraceHelpers();
    const described = liveTrace.ltDescribeTurnBudget({
      pressure: "soft",
      complexity: "high",
      model_family: "reasoning",
      disable_mcts: true,
      disable_ensemble: false,
      tool_budget_mode: "adaptive",
    });
    const theme = liveTrace.ltTurnBudgetTheme("soft");

    expect(described.pressureLabel).toContain("soft");
    expect(described.pressureLabel).toContain("reasoning");
    expect(described.helpersLabel).toContain("MCTS off");
    expect(described.modeLabel).toContain("adaptive");
    expect(theme.accent).toBe("#f59e0b");
    expect(liveTrace.ltPressureTickTheme("hard").height).toBe("12px");
    expect(liveTrace.ltPressureTickTheme("none").height).toBe("6px");
    expect(liveTrace.ltSummarizePressureHistory(["hard", "soft", "hard", "hard", "hard"]))
      .toContain("sustained hard");
    expect(liveTrace.ltSummarizePressureHistory(["none", "none", "soft"]))
      .toContain("occasional soft");
    expect(liveTrace.ltRenderPressureHistory(["hard", "soft", "none"]))
      .toContain("display:inline-block");
    expect(liveTrace.ltLoadStoredHistoryWindow()).toBe(10);
    liveTrace.ltStoreHistoryWindow(20);
    expect(liveTrace.ltLoadStoredHistoryWindow()).toBe(20);
    liveTrace.ltSetHistoryWindow(20);
    expect(liveTrace.ltRenderPressureHistory(new Array(20).fill("hard")).match(/display:inline-block/g)?.length).toBe(20);
    liveTrace.ltSetHistoryWindow(30);
    expect(liveTrace.ltRenderPressureHistory(new Array(30).fill("soft")).match(/display:inline-block/g)?.length).toBe(30);
    expect(liveTrace.ltLoadStoredHistoryWindow()).toBe(30);
    expect(liveTrace.ltLoadStoredConnectionMode()).toBe("live");
    liveTrace.ltStoreConnectionMode("replay");
    expect(liveTrace.ltLoadStoredConnectionMode()).toBe("replay");
    liveTrace.ltSetConnectionMode("live");
    expect(liveTrace.ltLoadStoredConnectionMode()).toBe("live");
    liveTrace.ltSetConnectionMode("replay");
    expect(liveTrace.ltLoadStoredConnectionMode()).toBe("replay");
    expect(liveTrace.ltLoadStoredReplayTraceId()).toBe("");
    liveTrace.ltStoreReplayTraceId("trace-001");
    expect(liveTrace.ltLoadStoredReplayTraceId()).toBe("trace-001");
    liveTrace.ltRememberReplayTrace("trace-002");
    expect(liveTrace.ltLoadStoredReplayTraceId()).toBe("trace-002");
    expect(liveTrace.ltLoadStoredAutoReplayOnOpen()).toBe(false);
    liveTrace.ltStoreAutoReplayOnOpen(true);
    expect(liveTrace.ltLoadStoredAutoReplayOnOpen()).toBe(true);
    expect(liveTrace.ltShouldAutoReplayOnOpen()).toBe(true);
    liveTrace.ltSetConnectionMode("live");
    expect(liveTrace.ltShouldAutoReplayOnOpen()).toBe(false);
    liveTrace.ltSetConnectionMode("replay");
    liveTrace.ltSetAutoReplayOnOpen(false);
    expect(liveTrace.ltLoadStoredAutoReplayOnOpen()).toBe(false);
    expect(liveTrace.ltShouldAutoReplayOnOpen()).toBe(false);
  });
});
