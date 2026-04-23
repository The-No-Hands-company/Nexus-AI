// ── Live Trace Panel — Sprint K ───────────────────────────────────────────────
// Replaces polling with SSE for real-time step rendering.
"use strict";

let _ltEventSource  = null;
let _ltTraceId      = null;
let _ltEventCount   = 0;
let _ltStartTime    = null;

const LT_TYPE_META = {
  plan:       { icon: "📋", color: "#7c6af7", label: "Plan" },
  think:      { icon: "💭", color: "#5eead4", label: "Think" },
  tool:       { icon: "⚙️", color: "#f59e0b", label: "Tool" },
  clarify:    { icon: "❓", color: "#94a3b8", label: "Clarify" },
  done:       { icon: "✅", color: "#22c55e", label: "Done" },
  error:      { icon: "❌", color: "#ef4444", label: "Error" },
  fallback:   { icon: "↩️", color: "#f59e0b", label: "Fallback" },
  complexity: { icon: "🧠", color: "#7c6af7", label: "Complexity" },
  system:     { icon: "ℹ️", color: "#64748b", label: "System" },
  image:      { icon: "🎨", color: "#ec4899", label: "Image" },
};

function openLiveTracePanel() {
  NexusApi.setPanelOpen("live-trace-panel", true);
  _ltRefreshTraceList();
}

function closeLiveTracePanel() {
  NexusApi.setPanelOpen("live-trace-panel", false);
  _ltDisconnect();
}

// ── SSE connection ────────────────────────────────────────────────────────────
function ltConnectLive() {
  // Connect to the live SSE stream for agent events
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
async function _ltRefreshTraceList() {
  const sel = document.getElementById("lt-trace-select");
  if (!sel) return;
  try {
    const r = await fetch("/tasks?limit=30");
    const d = await r.json();
    const traces = d.traces || [];
    sel.innerHTML = '<option value="">— Select trace to replay —</option>' +
      traces.map(t => `<option value="${esc(t.trace_id||'')}">${esc((t.trace_id||'').slice(0,14))} — ${esc((t.task||'').slice(0,40))}</option>`).join('');
  } catch(_) {}
}

function ltClearFeed() { _ltClearFeed(); }
