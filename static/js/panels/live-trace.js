// ── Live Trace Panel — Sprint K ───────────────────────────────────────────────
// Replaces polling with SSE for real-time step rendering.
"use strict";

let _ltEventSource  = null;
let _ltTraceId      = null;
let _ltEventCount   = 0;
let _ltStartTime    = null;
let _ltTurnBudgetHistory = [];
let _ltTurnBudgetHistoryWindow = 10;
let _ltConnectionMode = "live";
const LT_HISTORY_WINDOW_STORAGE_KEY = "nexus.liveTrace.historyWindow";
const LT_CONNECTION_MODE_STORAGE_KEY = "nexus.liveTrace.connectionMode";
const LT_REPLAY_TRACE_STORAGE_KEY = "nexus.liveTrace.replayTraceId";
const LT_AUTO_REPLAY_OPEN_STORAGE_KEY = "nexus.liveTrace.autoReplayOnOpen";

const LT_TYPE_META = {
  plan:       { icon: "📋", color: "#7c6af7", label: "Plan" },
  think:      { icon: "💭", color: "#5eead4", label: "Think" },
  tool:       { icon: "⚙️", color: "#f59e0b", label: "Tool" },
  clarify:    { icon: "❓", color: "#94a3b8", label: "Clarify" },
  done:       { icon: "✅", color: "#22c55e", label: "Done" },
  error:      { icon: "❌", color: "#ef4444", label: "Error" },
  fallback:   { icon: "↩️", color: "#f59e0b", label: "Fallback" },
  complexity: { icon: "🧠", color: "#7c6af7", label: "Complexity" },
  turn_budget:{ icon: "🎛️", color: "#f97316", label: "Turn Budget" },
  system:     { icon: "ℹ️", color: "#64748b", label: "System" },
  image:      { icon: "🎨", color: "#ec4899", label: "Image" },
};

function ltTurnBudgetTheme(pressure) {
  if (pressure === "hard") {
    return {
      borderColor: "color-mix(in srgb, var(--red) 55%, var(--border))",
      background: "color-mix(in srgb, var(--red) 12%, var(--surface2))",
      accent: "#ef4444",
    };
  }
  if (pressure === "soft") {
    return {
      borderColor: "color-mix(in srgb, var(--amber) 55%, var(--border))",
      background: "color-mix(in srgb, var(--amber) 12%, var(--surface2))",
      accent: "#f59e0b",
    };
  }
  return {
    borderColor: "var(--border)",
    background: "var(--surface2)",
    accent: "#94a3b8",
  };
}

function ltDescribeTurnBudget(evt) {
  const pressure = String(evt?.pressure || "none");
  const family = String(evt?.model_family || "balanced");
  const complexity = String(evt?.complexity || "unknown");
  const helperState = [evt?.disable_mcts ? "MCTS off" : "MCTS on", evt?.disable_ensemble ? "ensemble off" : "ensemble on"].join(" · ");
  return {
    pressureLabel: `Pressure: ${pressure} · ${complexity} · ${family}`,
    helpersLabel: `Helpers: ${helperState}`,
    modeLabel: `Tool mode: ${String(evt?.tool_budget_mode || "adaptive")}`,
    helperState,
    pressure,
  };
}

function ltPressureTickTheme(pressure) {
  if (pressure === "hard") {
    return { color: "#ef4444", height: "12px", title: "hard" };
  }
  if (pressure === "soft") {
    return { color: "#f59e0b", height: "9px", title: "soft" };
  }
  return { color: "#64748b", height: "6px", title: "none" };
}

function ltSummarizePressureHistory(pressures) {
  const history = Array.isArray(pressures) ? pressures : [];
  const hardCount = history.filter((p) => p === "hard").length;
  const softCount = history.filter((p) => p === "soft").length;
  const tail = history.slice(-3);
  const hardStreak = tail.length === 3 && tail.every((p) => p === "hard");
  if (hardStreak || hardCount >= 4) {
    return `Trend: sustained hard (${hardCount}/${history.length || _ltTurnBudgetHistoryWindow})`;
  }
  if (hardCount > 0) {
    return `Trend: intermittent hard (${hardCount}/${history.length || _ltTurnBudgetHistoryWindow})`;
  }
  if (softCount >= 4) {
    return `Trend: sustained soft (${softCount}/${history.length || _ltTurnBudgetHistoryWindow})`;
  }
  if (softCount > 0) {
    return `Trend: occasional soft (${softCount}/${history.length || _ltTurnBudgetHistoryWindow})`;
  }
  return "Trend: stable";
}

function ltRenderPressureHistory(pressures) {
  const history = Array.isArray(pressures) ? pressures.slice(-_ltTurnBudgetHistoryWindow) : [];
  if (!history.length) {
    return '<span style="font-size:.68rem;color:var(--muted)">No pressure samples yet</span>';
  }
  return history
    .map((pressure) => {
      const theme = ltPressureTickTheme(String(pressure || "none"));
      return `<span title="${theme.title}" style="display:inline-block;width:7px;height:${theme.height};background:${theme.color};border-radius:2px;opacity:.95"></span>`;
    })
    .join("");
}

function ltUpdatePressureHistory(pressure) {
  const normalized = pressure === "hard" || pressure === "soft" ? pressure : "none";
  _ltTurnBudgetHistory.push(normalized);
  if (_ltTurnBudgetHistory.length > 30) {
    _ltTurnBudgetHistory = _ltTurnBudgetHistory.slice(-30);
  }
  const historyEl = document.getElementById("lt-turn-budget-history");
  const trendEl = document.getElementById("lt-turn-budget-trend");
  if (historyEl) {
    historyEl.innerHTML = ltRenderPressureHistory(_ltTurnBudgetHistory);
  }
  if (trendEl) {
    trendEl.textContent = ltSummarizePressureHistory(_ltTurnBudgetHistory);
    trendEl.style.color = normalized === "hard"
      ? "#ef4444"
      : normalized === "soft"
        ? "#f59e0b"
        : "var(--muted)";
  }
}

function ltRefreshPressureHistoryWindow() {
  const historyEl = document.getElementById("lt-turn-budget-history");
  const trendEl = document.getElementById("lt-turn-budget-trend");
  if (historyEl) {
    historyEl.innerHTML = ltRenderPressureHistory(_ltTurnBudgetHistory);
  }
  if (trendEl) {
    const visibleHistory = _ltTurnBudgetHistory.slice(-_ltTurnBudgetHistoryWindow);
    trendEl.textContent = ltSummarizePressureHistory(visibleHistory);
  }
}

function ltLoadStoredHistoryWindow() {
  try {
    if (typeof localStorage === "undefined") return 10;
    const raw = Number(localStorage.getItem(LT_HISTORY_WINDOW_STORAGE_KEY) || 10);
    return [10, 20, 30].includes(raw) ? raw : 10;
  } catch (_) {
    return 10;
  }
}

function ltStoreHistoryWindow(value) {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(LT_HISTORY_WINDOW_STORAGE_KEY, String(value));
  } catch (_) {}
}

function ltLoadStoredConnectionMode() {
  try {
    if (typeof localStorage === "undefined") return "live";
    const raw = String(localStorage.getItem(LT_CONNECTION_MODE_STORAGE_KEY) || "live");
    return raw === "replay" ? "replay" : "live";
  } catch (_) {
    return "live";
  }
}

function ltStoreConnectionMode(value) {
  try {
    if (typeof localStorage === "undefined") return;
    const normalized = value === "replay" ? "replay" : "live";
    localStorage.setItem(LT_CONNECTION_MODE_STORAGE_KEY, normalized);
  } catch (_) {}
}

function ltLoadStoredReplayTraceId() {
  try {
    if (typeof localStorage === "undefined") return "";
    return String(localStorage.getItem(LT_REPLAY_TRACE_STORAGE_KEY) || "");
  } catch (_) {
    return "";
  }
}

function ltStoreReplayTraceId(value) {
  try {
    if (typeof localStorage === "undefined") return;
    const normalized = String(value || "").trim();
    localStorage.setItem(LT_REPLAY_TRACE_STORAGE_KEY, normalized);
  } catch (_) {}
}

function ltRememberReplayTrace(value) {
  const normalized = String(value || "").trim();
  _ltTraceId = normalized || null;
  ltStoreReplayTraceId(normalized);
}

function ltApplyStoredReplayTrace() {
  if (typeof document === "undefined") return;
  const sel = document.getElementById("lt-trace-select");
  if (!sel) return false;
  const stored = ltLoadStoredReplayTraceId();
  if (!stored) {
    sel.value = "";
    return false;
  }
  const options = Array.from(sel.options || []);
  const exists = options.some((option) => option.value === stored);
  sel.value = exists ? stored : "";
  if (exists) {
    _ltTraceId = stored;
  }
  return exists;
}

function ltLoadStoredAutoReplayOnOpen() {
  try {
    if (typeof localStorage === "undefined") return false;
    return String(localStorage.getItem(LT_AUTO_REPLAY_OPEN_STORAGE_KEY) || "0") === "1";
  } catch (_) {
    return false;
  }
}

function ltStoreAutoReplayOnOpen(enabled) {
  try {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(LT_AUTO_REPLAY_OPEN_STORAGE_KEY, enabled ? "1" : "0");
  } catch (_) {}
}

function ltSetAutoReplayOnOpen(enabled, options) {
  const normalized = Boolean(enabled);
  if (!options || options.persist !== false) {
    ltStoreAutoReplayOnOpen(normalized);
  }
  if (typeof document === "undefined") return;
  const checkbox = document.getElementById("lt-auto-replay-open");
  if (checkbox) {
    checkbox.checked = normalized;
  }
}

function ltShouldAutoReplayOnOpen() {
  return ltLoadStoredConnectionMode() === "replay" && ltLoadStoredAutoReplayOnOpen();
}

function ltApplyConnectionModeUi(mode) {
  if (typeof document === "undefined") return;
  const normalized = mode === "replay" ? "replay" : "live";
  const liveBtn = document.getElementById("lt-live-btn");
  const replayBtn = document.getElementById("lt-replay-btn");
  const modePref = document.getElementById("lt-mode-pref");
  const traceSelect = document.getElementById("lt-trace-select");
  if (modePref) {
    modePref.textContent = `Mode: ${normalized}`;
    modePref.style.borderColor = normalized === "replay"
      ? "color-mix(in srgb, var(--amber) 55%, var(--border))"
      : "color-mix(in srgb, var(--accent) 45%, var(--border))";
    modePref.style.color = normalized === "replay" ? "#f59e0b" : "var(--accent)";
  }
  if (liveBtn) {
    liveBtn.style.background = normalized === "live" ? "var(--accent)" : "var(--surface2)";
    liveBtn.style.color = normalized === "live" ? "#fff" : "var(--muted)";
    liveBtn.style.border = normalized === "live" ? "none" : "1px solid var(--border)";
    liveBtn.style.fontWeight = normalized === "live" ? "600" : "500";
  }
  if (replayBtn) {
    replayBtn.style.background = normalized === "replay" ? "color-mix(in srgb, var(--amber) 20%, var(--surface2))" : "var(--surface2)";
    replayBtn.style.color = normalized === "replay" ? "#f59e0b" : "var(--text)";
    replayBtn.style.border = normalized === "replay"
      ? "1px solid color-mix(in srgb, var(--amber) 50%, var(--border))"
      : "1px solid var(--border)";
    replayBtn.style.fontWeight = normalized === "replay" ? "600" : "500";
  }
  if (traceSelect) {
    traceSelect.style.borderColor = normalized === "replay"
      ? "color-mix(in srgb, var(--amber) 45%, var(--border))"
      : "var(--border)";
  }
}

function ltSetConnectionMode(value) {
  const normalized = value === "replay" ? "replay" : "live";
  _ltConnectionMode = normalized;
  ltStoreConnectionMode(normalized);
  ltApplyConnectionModeUi(normalized);
}

function ltSetHistoryWindow(value) {
  const parsed = Number(value);
  if (![10, 20, 30].includes(parsed)) return;
  _ltTurnBudgetHistoryWindow = parsed;
  ltStoreHistoryWindow(parsed);
  const select = typeof document !== "undefined" ? document.getElementById("lt-history-window") : null;
  if (select && String(select.value) !== String(parsed)) {
    select.value = String(parsed);
  }
  if (typeof document !== "undefined") {
    ltRefreshPressureHistoryWindow();
  }
}

function ltUpdateTurnBudgetStrip(evt) {
  const pressureEl = document.getElementById("lt-turn-budget-pressure");
  const helpersEl = document.getElementById("lt-turn-budget-helpers");
  const modeEl = document.getElementById("lt-turn-budget-mode");
  if (!pressureEl || !helpersEl || !modeEl) return;
  const described = ltDescribeTurnBudget(evt || {});
  const theme = ltTurnBudgetTheme(described.pressure);
  [pressureEl, helpersEl, modeEl].forEach((el) => {
    el.style.borderColor = theme.borderColor;
    el.style.background = theme.background;
  });
  pressureEl.style.color = theme.accent;
  helpersEl.style.color = "var(--text)";
  modeEl.style.color = "var(--text)";
  pressureEl.textContent = described.pressureLabel;
  helpersEl.textContent = described.helpersLabel;
  modeEl.textContent = described.modeLabel;
}

function openLiveTracePanel() {
  NexusApi.setPanelOpen("live-trace-panel", true);
  ltSetConnectionMode(ltLoadStoredConnectionMode());
  ltSetHistoryWindow(ltLoadStoredHistoryWindow());
  ltSetAutoReplayOnOpen(ltLoadStoredAutoReplayOnOpen(), { persist: false });
  _ltRefreshTraceList({ autoReplayOnOpen: true });
}

function closeLiveTracePanel() {
  NexusApi.setPanelOpen("live-trace-panel", false);
  _ltDisconnect();
}

// ── SSE connection ────────────────────────────────────────────────────────────
function ltConnectLive() {
  // Connect to the live SSE stream for agent events
  ltSetConnectionMode("live");
  _ltDisconnect();
  _ltClearFeed();
  _ltStartTime = Date.now();
  _ltEventCount = 0;
  _ltTraceId = null;

  const feed = document.getElementById("lt-feed");
  const statusEl = document.getElementById("lt-status");
  if (statusEl) {
    statusEl.textContent = "● Live";
    statusEl.style.color = "#22c55e";
  }

  // Subscribe to SSE agent event stream
  _ltEventSource = new EventSource("/agent/stream/live");

  _ltEventSource.onmessage = (e) => {
    try {
      const evt = JSON.parse(e.data);
      _ltRenderEvent(evt);
    } catch (_) {}
  };

  _ltEventSource.onerror = () => {
    if (statusEl) {
      statusEl.textContent = "○ Disconnected";
      statusEl.style.color = "var(--muted)";
    }
  };

  _ltEventSource.onopen = () => {
    if (statusEl) {
      statusEl.textContent = "● Live";
      statusEl.style.color = "#22c55e";
    }
  };
}

function ltReplaySelected() {
  const sel = document.getElementById("lt-trace-select");
  if (!sel || !sel.value) return;
  ltRememberReplayTrace(sel.value);
  ltSetConnectionMode("replay");
  _ltDisconnect();
  _ltClearFeed();
  _ltStartTime = Date.now();
  _ltEventCount = 0;

  const statusEl = document.getElementById("lt-status");
  if (statusEl) { statusEl.textContent = "⏮ Replaying"; statusEl.style.color = "#f59e0b"; }

  _ltEventSource = new EventSource(`/tasks/${encodeURIComponent(sel.value)}/replay`);
  _ltEventSource.onmessage = (e) => {
    try { _ltRenderEvent(JSON.parse(e.data)); } catch (_) {}
  };
  _ltEventSource.onerror = () => {
    _ltEventSource.close();
    _ltEventSource = null;
    if (statusEl) { statusEl.textContent = "✓ Replay complete"; statusEl.style.color = "#22c55e"; }
  };
}

function _ltDisconnect() {
  if (_ltEventSource) { _ltEventSource.close(); _ltEventSource = null; }
  const statusEl = document.getElementById("lt-status");
  if (statusEl) { statusEl.textContent = "○ Idle"; statusEl.style.color = "var(--muted)"; }
}

function ltStop() { _ltDisconnect(); }

function _ltClearFeed() {
  const feed = document.getElementById("lt-feed");
  if (feed) feed.innerHTML = "";
  _ltEventCount = 0;
  const cnt = document.getElementById("lt-event-count");
  if (cnt) cnt.textContent = "0 events";
  const bar = document.getElementById("lt-timeline-bar");
  if (bar) bar.innerHTML = "";
  _ltConnectionMode = ltLoadStoredConnectionMode();
  ltApplyConnectionModeUi(_ltConnectionMode);
  _ltTurnBudgetHistoryWindow = ltLoadStoredHistoryWindow();
  const select = typeof document !== "undefined" ? document.getElementById("lt-history-window") : null;
  if (select) {
    select.value = String(_ltTurnBudgetHistoryWindow);
  }
  _ltTurnBudgetHistory = [];
  ltUpdateTurnBudgetStrip({ pressure: "none", complexity: "idle", model_family: "balanced", disable_mcts: false, disable_ensemble: false, tool_budget_mode: "adaptive" });
  ltUpdatePressureHistory("none");
}

// ── Event rendering ───────────────────────────────────────────────────────────
function _ltRenderEvent(evt) {
  if (!evt || !evt.type) return;
  _ltEventCount++;

  const feed = document.getElementById("lt-feed");
  if (!feed) return;

  const meta     = LT_TYPE_META[evt.type] || { icon: "·", color: "#888", label: evt.type };
  const elapsed  = _ltStartTime ? ((Date.now() - _ltStartTime) / 1000).toFixed(1) + "s" : "";

  // Build label
  let detail = "";
  if (evt.type === "plan")   detail = evt.title || "";
  else if (evt.type === "tool") detail = `${evt.icon||""} ${evt.action||""} — ${(evt.label||"").slice(0,50)}`;
  else if (evt.type === "done") detail = (evt.content||"").slice(0,80);
  else if (evt.type === "think") detail = (evt.thought||"").slice(0,80);
  else if (evt.type === "error") detail = (evt.message||"").slice(0,80);
  else if (evt.type === "complexity") detail = `Complexity: ${evt.level||"?"}`;
  else if (evt.type === "turn_budget") detail = ltDescribeTurnBudget(evt).pressureLabel;
  else if (evt.type === "fallback") detail = evt.chain || "";
  else detail = JSON.stringify(evt).slice(0,60);

  const row = document.createElement("div");
  row.style.cssText = "display:flex;align-items:flex-start;gap:8px;padding:5px 8px;border-radius:7px;background:var(--surface2);font-size:.74rem;animation:fadeUp .12s ease;";

  // Timeline dot
  const dot = document.createElement("span");
  dot.style.cssText = `width:8px;height:8px;border-radius:50%;background:${meta.color};flex-shrink:0;margin-top:4px;`;
  row.appendChild(dot);

  // Content
  const content = document.createElement("div");
  content.style.flex = "1";
  content.innerHTML = `
    <div style="display:flex;align-items:center;gap:6px;">
      <span style="color:${meta.color};font-weight:700;font-size:.65rem;text-transform:uppercase;letter-spacing:.04em;">${meta.label}</span>
      <span style="color:var(--muted);font-size:.62rem;">${elapsed}</span>
    </div>
    <div style="color:var(--text);margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(detail)}">${esc(detail)}</div>
  `;

  // Expand button for plan steps / tool results
  if (evt.type === "plan" && Array.isArray(evt.steps) && evt.steps.length) {
    const steps = document.createElement("div");
    steps.style.cssText = "margin-top:5px;display:flex;flex-direction:column;gap:2px;";
    evt.steps.forEach((s, i) => {
      const si = document.createElement("div");
      si.style.cssText = "font-size:.68rem;color:var(--muted);padding:2px 0 2px 8px;border-left:2px solid var(--border);";
      si.textContent = `${i+1}. ${s}`;
      steps.appendChild(si);
    });
    content.appendChild(steps);
  }

  if (evt.type === "tool" && evt.result) {
    const res = document.createElement("div");
    res.style.cssText = "font-size:.65rem;color:var(--muted);margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
    res.textContent = `→ ${String(evt.result).slice(0,80)}`;
    content.appendChild(res);
  }

  row.appendChild(content);

  // Counter badge
  const num = document.createElement("span");
  num.style.cssText = "font-size:.6rem;color:var(--muted);flex-shrink:0;margin-top:4px;";
  num.textContent = `#${_ltEventCount}`;
  row.appendChild(num);

  feed.appendChild(row);
  feed.scrollTop = feed.scrollHeight;

  if (evt.type === "turn_budget") {
    ltUpdateTurnBudgetStrip(evt);
    ltUpdatePressureHistory(String(evt.pressure || "none"));
  }

  // Update counter
  const cnt = document.getElementById("lt-event-count");
  if (cnt) cnt.textContent = `${_ltEventCount} event${_ltEventCount !== 1 ? "s" : ""}`;

  // Update timeline bar
  _ltAddTimelineTick(meta.color, meta.label);

  // Auto-scroll to bottom
  if (evt.type === "done" || evt.type === "error") {
    const statusEl = document.getElementById("lt-status");
    if (statusEl) {
      statusEl.textContent = evt.type === "done" ? "✓ Complete" : "✕ Error";
      statusEl.style.color = evt.type === "done" ? "#22c55e" : "#ef4444";
    }
  }
}

function _ltAddTimelineTick(color, label) {
  const bar = document.getElementById("lt-timeline-bar");
  if (!bar) return;
  const tick = document.createElement("div");
  tick.title = label;
  tick.style.cssText = `width:8px;height:100%;background:${color};opacity:.7;border-radius:2px;flex-shrink:0;transition:opacity .15s;cursor:pointer;`;
  tick.addEventListener("mouseenter", () => tick.style.opacity = "1");
  tick.addEventListener("mouseleave", () => tick.style.opacity = ".7");
  bar.appendChild(tick);
  bar.scrollLeft = bar.scrollWidth;
}

// ── Trace list (for replay) ───────────────────────────────────────────────────
async function _ltRefreshTraceList(options) {
  const sel = document.getElementById("lt-trace-select");
  if (!sel) return;
  try {
    const r = await fetch("/tasks?limit=30");
    const d = await r.json();
    const traces = d.traces || [];
    sel.innerHTML = '<option value="">— Select trace to replay —</option>' +
      traces.map(t => `<option value="${esc(t.trace_id||'')}">${esc((t.trace_id||'').slice(0,14))} — ${esc((t.task||'').slice(0,40))}</option>`).join('');
    const restoredTrace = ltApplyStoredReplayTrace();
    if (options?.autoReplayOnOpen && restoredTrace && ltShouldAutoReplayOnOpen()) {
      ltReplaySelected();
    }
  } catch(_) {}
}

function ltClearFeed() { _ltClearFeed(); }

window.NexusLiveTrace = {
  ltTurnBudgetTheme,
  ltDescribeTurnBudget,
  ltPressureTickTheme,
  ltSummarizePressureHistory,
  ltRenderPressureHistory,
  ltSetHistoryWindow,
  ltLoadStoredHistoryWindow,
  ltStoreHistoryWindow,
  ltLoadStoredConnectionMode,
  ltStoreConnectionMode,
  ltSetConnectionMode,
  ltLoadStoredReplayTraceId,
  ltStoreReplayTraceId,
  ltRememberReplayTrace,
  ltLoadStoredAutoReplayOnOpen,
  ltStoreAutoReplayOnOpen,
  ltSetAutoReplayOnOpen,
  ltShouldAutoReplayOnOpen,
};
