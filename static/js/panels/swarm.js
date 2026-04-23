// Swarm panel module — Activity feed + Canvas graph + Task assignment
"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let _swarmTimer        = null;
let _swarmGraphTimer   = null;
let _swarmProgressTimer = null;
let _lastSwarmTotal    = 0;
let _swarmActiveTab    = "activity";
let _swarmPaused       = false;
let _swarmSelectedTrace = "";
let _swarmCachedTasks   = [];

// Graph physics state
let _graphNodes        = [];
let _graphEdges        = [];
let _graphAnimFrame    = null;
let _graphDragNode     = null;
let _graphCanvas       = null;
let _graphCtx          = null;
let _graphTooltipNode  = null;

const SWARM_ACTION_COLORS = {
  write_file:   "#4a9",
  read_file:    "#69b",
  run_command:  "#d96",
  web_search:   "#79d",
  query_db:     "#a8a",
  inspect_db:   "#a8a",
  commit_push:  "#5b5",
  clone_repo:   "#5b5",
  sub_agent:    "#b75",
};

const AGENT_STATE_COLOR = {
  idle:    "#4a9",
  busy:    "#d96",
  errored: "#e55",
  unknown: "#888",
};

// ── Panel open / close ────────────────────────────────────────────────────────

function openSwarmPanel() {
  NexusApi.setPanelOpen("swarm-panel", true);
  _populateAgentSelect();
  swarmTab(_swarmActiveTab);
}

function closeSwarmPanel() {
  NexusApi.setPanelOpen("swarm-panel", false);
  _stopSwarmPolling();
  _stopGraphPolling();
  _stopProgressPolling();
  _stopGraphAnim();
}

// ── Tab switching ─────────────────────────────────────────────────────────────

function swarmTab(name) {
  _swarmActiveTab = name;
  const tabs  = ["activity", "graph", "assign", "progress", "diff"];
  for (const t of tabs) {
    const pane = document.getElementById(`swarm-pane-${t}`);
    const btn  = document.getElementById(`swarm-tab-${t}`);
    if (!pane || !btn) continue;
    const active = (t === name);
    pane.style.display = active ? (t === "assign" ? "flex" : "flex") : "none";
    btn.style.background = active ? "var(--accent)" : "transparent";
    btn.style.color      = active ? "#fff"           : "var(--muted)";
  }

  if (name === "activity") {
    _swarmNewEventCount = 0;
    const badge = document.getElementById("swarm-new-badge");
    if (badge) badge.style.display = "none";
    _startSwarmPolling();
    _stopGraphPolling();
    _stopProgressPolling();
    _stopGraphAnim();
  } else if (name === "graph") {
    _stopSwarmPolling();
    _stopProgressPolling();
    _initGraph();
    _startGraphPolling();
  } else if (name === "progress") {
    _stopSwarmPolling();
    _stopGraphPolling();
    _stopGraphAnim();
    _startProgressPolling();
  } else if (name === "diff") {
    _stopSwarmPolling();
    _stopGraphPolling();
    _stopGraphAnim();
    _stopProgressPolling();
    swarmRefreshDiffOptions();
  } else {
    _stopSwarmPolling();
    _stopGraphPolling();
    _stopProgressPolling();
    _stopGraphAnim();
  }
}

// ── Pause / Resume ────────────────────────────────────────────────────────────

async function swarmTogglePause() {
  try {
    const action = _swarmPaused ? "resume" : "pause";
    const r = await fetch(`/swarm/${action}`, { method: "POST" });
    if (!r.ok) return;
    const d = await r.json();
    _swarmPaused = d.paused;
    _updatePauseBadge();
  } catch (_) {}
}

function _updatePauseBadge() {
  const badge = document.getElementById("swarm-pause-badge");
  const btn   = document.getElementById("swarm-pause-btn");
  if (badge) badge.style.display = _swarmPaused ? "inline" : "none";
  if (btn)   btn.textContent     = _swarmPaused ? "▶" : "⏸";
}

// ── Activity feed ─────────────────────────────────────────────────────────────

function clearSwarmFeed() {
  const el = document.getElementById("swarm-feed");
  if (el) el.innerHTML = "";
  const cnt = document.getElementById("swarm-count");
  if (cnt) cnt.textContent = "0 events";
  _lastSwarmTotal = 0;
}

// ── SSE live feed (replaces polling) ─────────────────────────────────────────
let _swarmEventSource = null;
let _swarmNewEventCount = 0;

function _startSwarmPolling() {
  if (_swarmEventSource) return;
  _connectSwarmSSE();
}

function _stopSwarmPolling() {
  if (_swarmEventSource) {
    _swarmEventSource.close();
    _swarmEventSource = null;
  }
  if (_swarmTimer) { clearInterval(_swarmTimer); _swarmTimer = null; }
}

function _connectSwarmSSE() {
  if (_swarmEventSource) return;
  _swarmEventSource = new EventSource("/swarm/live");

  _swarmEventSource.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      _appendSwarmEvent(ev);
      // New-events badge when panel is in background
      if (document.hidden || _swarmActiveTab !== "activity") {
        _swarmNewEventCount++;
        const badge = document.getElementById("swarm-new-badge");
        if (badge) {
          badge.textContent = _swarmNewEventCount > 99 ? "99+" : String(_swarmNewEventCount);
          badge.style.display = "inline";
        }
      }
    } catch (_) {}
  };

  _swarmEventSource.onerror = () => {
    // SSE failed — fall back to polling
    if (_swarmEventSource) { _swarmEventSource.close(); _swarmEventSource = null; }
    if (!_swarmTimer) {
      _pollSwarm();
      _swarmTimer = setInterval(_pollSwarm, 3000);
    }
  };
}

function _appendSwarmEvent(ev) {
  const feed = document.getElementById("swarm-feed");
  const countEl = document.getElementById("swarm-count");
  if (!feed) return;

  _lastSwarmTotal++;
  const clr = SWARM_ACTION_COLORS[ev.action] || "#888";
  const ts  = ev.ts
    ? new Date(ev.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  const row = document.createElement("div");
  row.style.cssText = "display:flex;align-items:center;gap:6px;padding:3px 6px;border-radius:6px;background:var(--surface2);font-size:.72rem;animation:fadeUp .1s ease;";
  row.innerHTML = `<span style="color:${clr};font-weight:700;min-width:90px;">${esc(ev.action || "?")}</span><span style="flex:1;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(ev.label || "")}</span><span style="color:var(--muted);font-size:.65rem;">${ts}</span>`;
  feed.appendChild(row);

  // Keep feed to last 200 rows
  while (feed.children.length > 200) feed.removeChild(feed.firstChild);

  feed.scrollTop = feed.scrollHeight;
  if (countEl) countEl.textContent = _lastSwarmTotal + " event" + (_lastSwarmTotal === 1 ? "" : "s");
}

function _startProgressPolling() {
  if (_swarmProgressTimer) return;
  swarmRefreshProgress();
  _swarmProgressTimer = setInterval(swarmRefreshProgress, 2500);
}

function _stopProgressPolling() {
  if (_swarmProgressTimer) {
    clearInterval(_swarmProgressTimer);
    _swarmProgressTimer = null;
  }
}

async function _pollSwarm() {
  try {
    const r = await fetch("/swarm/activity?limit=60");
    if (!r.ok) return;
    const d = await r.json();
    const feed   = document.getElementById("swarm-feed");
    const countEl = document.getElementById("swarm-count");
    if (!feed) return;
    if (d.total === _lastSwarmTotal) return;
    const newEvents = d.events.slice(Math.max(0, d.events.length - (d.total - _lastSwarmTotal)));
    _lastSwarmTotal = d.total;
    for (const ev of newEvents) {
      const row = document.createElement("div");
      const clr = SWARM_ACTION_COLORS[ev.action] || "#888";
      const ts  = ev.ts
        ? new Date(ev.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
        : "";
      row.style.cssText = "display:flex;align-items:center;gap:6px;padding:3px 6px;border-radius:6px;background:var(--surface2);font-size:.72rem;";
      row.innerHTML = `<span style="color:${clr};font-weight:700;min-width:90px;">${esc(ev.action || "?")}</span><span style="flex:1;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(ev.label || "")}</span><span style="color:var(--muted);font-size:.65rem;">${ts}</span>`;
      feed.appendChild(row);
    }
    feed.scrollTop = feed.scrollHeight;
    if (countEl) countEl.textContent = d.total + " event" + (d.total === 1 ? "" : "s");
  } catch (_) {}
}

function swarmRecordProgressEvent(evt) {
  if (!_swarmSelectedTrace) return;
  if (evt.trace_id && evt.trace_id !== _swarmSelectedTrace) return;
  if (_swarmActiveTab !== "progress") return;
  swarmRefreshProgress();
}

async function swarmRefreshProgress() {
  const traceSel = document.getElementById("swarm-progress-trace");
  const summaryEl = document.getElementById("swarm-progress-summary");
  const feed = document.getElementById("swarm-progress-feed");
  if (!traceSel || !summaryEl || !feed) return;

  try {
    const r = await fetch("/tasks?limit=40");
    if (!r.ok) return;
    const d = await r.json();
    _swarmCachedTasks = d.traces || [];

    if (!_swarmCachedTasks.length) {
      traceSel.innerHTML = '<option value="">No traces available</option>';
      summaryEl.textContent = "No autonomy traces yet.";
      feed.innerHTML = '<div style="color:var(--muted);font-size:.75rem;">Run an autonomy task to populate subtasks.</div>';
      return;
    }

    traceSel.innerHTML = _swarmCachedTasks.map((t) => {
      const id = esc(t.trace_id || "");
      const task = esc((t.task || "").slice(0, 56));
      const selected = (_swarmSelectedTrace ? _swarmSelectedTrace === t.trace_id : false) ? "selected" : "";
      return `<option value="${id}" ${selected}>${id} — ${task}</option>`;
    }).join("");

    if (!_swarmSelectedTrace) {
      _swarmSelectedTrace = _swarmCachedTasks[0].trace_id;
      traceSel.value = _swarmSelectedTrace;
    }

    traceSel.onchange = () => {
      _swarmSelectedTrace = traceSel.value;
      swarmRefreshProgress();
    };

    const selId = _swarmSelectedTrace || traceSel.value;
    if (!selId) return;
    const traceResp = await fetch(`/tasks/${encodeURIComponent(selId)}`);
    if (!traceResp.ok) return;
    const traceData = await traceResp.json();
    const events = traceData.events || [];
    _renderProgressTimeline(events, summaryEl, feed);
  } catch (_) {}
}

function _renderProgressTimeline(events, summaryEl, feed) {
  const items = [];
  let running = 0;
  let done = 0;
  let failed = 0;

  for (const evt of events) {
    if (!evt || typeof evt !== "object") continue;
    const t = String(evt.type || "");
    if (t === "plan" && Array.isArray(evt.steps)) {
      evt.steps.forEach((step, idx) => {
        items.push({ label: String(step || `Step ${idx + 1}`), status: "pending" });
      });
      continue;
    }
    if (t === "subtask") {
      const label = String(evt.subtask?.description || evt.description || evt.message || "Subtask");
      const found = items.find((i) => i.label === label);
      if (found) found.status = "running";
      else items.push({ label, status: "running" });
      continue;
    }
    if (t === "subtask_done") {
      const label = String(evt.subtask?.description || evt.description || evt.message || "Subtask");
      const found = items.find((i) => i.label === label);
      if (found) found.status = "done";
      else items.push({ label, status: "done" });
      continue;
    }
    if (t === "error") {
      const label = String(evt.message || "Subtask error");
      items.push({ label, status: "failed" });
    }
  }

  for (const it of items) {
    if (it.status === "running") running += 1;
    else if (it.status === "done") done += 1;
    else if (it.status === "failed") failed += 1;
  }
  const pending = Math.max(0, items.length - running - done - failed);
  summaryEl.textContent = `Subtasks: ${items.length} · done ${done} · running ${running} · pending ${pending} · failed ${failed}`;

  if (!items.length) {
    feed.innerHTML = '<div style="color:var(--muted);font-size:.75rem;">No subtask-level events captured for this trace yet.</div>';
    return;
  }

  feed.innerHTML = items.map((it, idx) => {
    const palette = it.status === "done"
      ? { icon: "✓", color: "#22c55e" }
      : it.status === "running"
        ? { icon: "…", color: "#f59e0b" }
        : it.status === "failed"
          ? { icon: "✕", color: "#ef4444" }
          : { icon: "○", color: "var(--muted)" };
    return `<div style="display:flex;gap:8px;align-items:flex-start;padding:6px 8px;background:var(--surface2);border-radius:7px;font-size:.75rem;">
      <span style="min-width:18px;color:${palette.color};font-weight:700;">${palette.icon}</span>
      <div style="flex:1;line-height:1.35;">${esc(it.label)}</div>
      <span style="font-size:.68rem;color:var(--muted);">#${idx + 1}</span>
    </div>`;
  }).join("");
}

async function swarmRefreshDiffOptions() {
  const left = document.getElementById("swarm-diff-left");
  const right = document.getElementById("swarm-diff-right");
  if (!left || !right) return;
  try {
    const r = await fetch("/tasks?limit=30");
    if (!r.ok) return;
    const d = await r.json();
    const traces = d.traces || [];
    if (!traces.length) {
      left.innerHTML = '<option value="">No traces</option>';
      right.innerHTML = '<option value="">No traces</option>';
      return;
    }
    const options = traces.map((t) => `<option value="${esc(t.trace_id || "")}">${esc(t.trace_id || "")}</option>`).join("");
    left.innerHTML = options;
    right.innerHTML = options;
    if (traces.length > 1) right.selectedIndex = 1;
  } catch (_) {}
}

async function swarmRunDiffCompare() {
  const left = document.getElementById("swarm-diff-left");
  const right = document.getElementById("swarm-diff-right");
  const out = document.getElementById("swarm-diff-output");
  if (!left || !right || !out) return;

  const leftId = (left.value || "").trim();
  const rightId = (right.value || "").trim();
  if (!leftId || !rightId) {
    out.textContent = "Select two traces to compare.";
    return;
  }
  if (leftId === rightId) {
    out.textContent = "Pick two different traces for comparison.";
    return;
  }

  out.textContent = "Computing diff...";
  try {
    const r = await fetch(`/tasks/${encodeURIComponent(leftId)}/diff?other_trace_id=${encodeURIComponent(rightId)}`);
    const d = await r.json();
    if (!r.ok) {
      out.textContent = d.error || "Failed to diff traces.";
      return;
    }
    out.textContent = d.diff || "No differences found.";
  } catch (e) {
    out.textContent = `Error: ${e.message}`;
  }
}

// ── Graph: initialise canvas ──────────────────────────────────────────────────

function _initGraph() {
  _graphCanvas = document.getElementById("swarm-graph-canvas");
  if (!_graphCanvas) return;
  _graphCtx = _graphCanvas.getContext("2d");
  _resizeCanvas();
  _graphCanvas.onmousemove  = _graphMouseMove;
  _graphCanvas.onmousedown  = _graphMouseDown;
  _graphCanvas.onmouseup    = _graphMouseUp;
  _graphCanvas.onmouseleave = _graphMouseUp;
  _graphCanvas.ontouchstart = _graphTouchStart;
  _graphCanvas.ontouchmove  = _graphTouchMove;
  _graphCanvas.ontouchend   = _graphMouseUp;
  swarmGraphRefresh();
}

function _resizeCanvas() {
  if (!_graphCanvas) return;
  const rect = _graphCanvas.parentElement.getBoundingClientRect();
  _graphCanvas.width  = rect.width  || 420;
  _graphCanvas.height = rect.height || 240;
}

// ── Graph: data refresh ───────────────────────────────────────────────────────

function _startGraphPolling() {
  if (_swarmGraphTimer) return;
  _swarmGraphTimer = setInterval(swarmGraphRefresh, 4000);
}

function _stopGraphPolling() {
  if (_swarmGraphTimer) { clearInterval(_swarmGraphTimer); _swarmGraphTimer = null; }
}

async function swarmGraphRefresh() {
  try {
    const [rHealth, rBus] = await Promise.all([
      fetch("/swarm/health"),
      fetch("/agents/bus/log?limit=40"),
    ]);
    if (!rHealth.ok) return;
    const health = await rHealth.json();
    const bus    = rBus.ok ? await rBus.json() : { messages: [], active_agents: [] };

    _swarmPaused = health.paused;
    _updatePauseBadge();

    // Build nodes map (preserve positions of existing nodes)
    const posMap = {};
    for (const n of _graphNodes) posMap[n.id] = { x: n.x, y: n.y, vx: n.vx, vy: n.vy };

    const W = _graphCanvas ? _graphCanvas.width  : 420;
    const H = _graphCanvas ? _graphCanvas.height : 240;
    const cx = W / 2, cy = H / 2, r = Math.min(W, H) * 0.35;
    const agentList = health.agents || [];

    _graphNodes = agentList.map((a, i) => {
      const angle = (2 * Math.PI * i) / Math.max(agentList.length, 1);
      const prev  = posMap[a.id] || {};
      return {
        id:    a.id,
        state: a.state || "unknown",
        x:     prev.x  ?? cx + r * Math.cos(angle),
        y:     prev.y  ?? cy + r * Math.sin(angle),
        vx:    prev.vx ?? 0,
        vy:    prev.vy ?? 0,
        r:     22,
      };
    });

    // Add a central "bus" hub node
    const hubPrev = posMap["__bus__"] || {};
    _graphNodes.push({
      id: "__bus__", state: "hub",
      x: hubPrev.x ?? cx, y: hubPrev.y ?? cy,
      vx: hubPrev.vx ?? 0, vy: hubPrev.vy ?? 0,
      r: 16, pinned: true,
    });

    // Edges from bus messages (from→to)
    const edgeSet = new Set();
    _graphEdges = [];
    for (const msg of (bus.messages || [])) {
      const key = `${msg.from_id}→${msg.to_id}`;
      if (!edgeSet.has(key)) {
        edgeSet.add(key);
        _graphEdges.push({ from: msg.from_id, to: msg.to_id, topic: msg.topic || "" });
      }
    }

    // Update summary bar
    const sumEl = document.getElementById("swarm-graph-summary");
    if (sumEl) {
      const s = health.summary || {};
      sumEl.textContent = `${health.total || 0} agents — idle: ${s.idle||0}  busy: ${s.busy||0}  errored: ${s.errored||0}${health.paused ? "  ⏸ PAUSED" : ""}`;
    }

    _startGraphAnim();
  } catch (_) {}
}

// ── Graph: force-directed physics ─────────────────────────────────────────────

function _startGraphAnim() {
  if (_graphAnimFrame) return;
  _graphAnimFrame = requestAnimationFrame(_graphTick);
}

function _stopGraphAnim() {
  if (_graphAnimFrame) { cancelAnimationFrame(_graphAnimFrame); _graphAnimFrame = null; }
}

function _graphTick() {
  if (!_graphCtx || !_graphCanvas) { _graphAnimFrame = null; return; }

  const W = _graphCanvas.width, H = _graphCanvas.height;
  const nodeMap = Object.fromEntries(_graphNodes.map(n => [n.id, n]));

  // Apply forces
  for (const n of _graphNodes) {
    if (n.pinned) { n.vx = 0; n.vy = 0; continue; }

    // Repulsion from other nodes
    for (const m of _graphNodes) {
      if (m === n) continue;
      const dx = n.x - m.x, dy = n.y - m.y;
      const d2 = dx * dx + dy * dy + 0.01;
      const force = 800 / d2;
      n.vx += force * dx / Math.sqrt(d2);
      n.vy += force * dy / Math.sqrt(d2);
    }

    // Spring attraction toward center (hub)
    const hub = nodeMap["__bus__"];
    if (hub) {
      const dx = n.x - hub.x, dy = n.y - hub.y;
      const d  = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const ideal = 90;
      const spring = (d - ideal) * 0.012;
      n.vx -= spring * dx / d;
      n.vy -= spring * dy / d;
    }

    // Drag
    n.vx *= 0.82;
    n.vy *= 0.82;

    // Integrate
    if (n !== _graphDragNode) {
      n.x += n.vx;
      n.y += n.vy;
    }

    // Bounds
    n.x = Math.max(n.r + 2, Math.min(W - n.r - 2, n.x));
    n.y = Math.max(n.r + 2, Math.min(H - n.r - 2, n.y));
  }

  _graphDraw(W, H, nodeMap);

  _graphAnimFrame = requestAnimationFrame(_graphTick);
}

function _graphDraw(W, H, nodeMap) {
  const ctx = _graphCtx;
  // Detect theme
  const isDark = document.documentElement.getAttribute("data-theme") !== "light";
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = isDark ? "rgba(18,20,28,0)" : "rgba(255,255,255,0)";
  ctx.fillRect(0, 0, W, H);

  // Draw edges
  for (const e of _graphEdges) {
    const src = nodeMap[e.from], dst = nodeMap[e.to];
    if (!src || !dst) continue;
    ctx.beginPath();
    ctx.moveTo(src.x, src.y);
    ctx.lineTo(dst.x, dst.y);
    ctx.strokeStyle = isDark ? "rgba(150,150,200,0.22)" : "rgba(100,100,150,0.18)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);
    ctx.stroke();
    ctx.setLineDash([]);

    // Arrow head toward dst
    const ang = Math.atan2(dst.y - src.y, dst.x - src.x);
    const arrX = dst.x - (dst.r + 4) * Math.cos(ang);
    const arrY = dst.y - (dst.r + 4) * Math.sin(ang);
    ctx.beginPath();
    ctx.moveTo(arrX, arrY);
    ctx.lineTo(arrX - 8 * Math.cos(ang - 0.4), arrY - 8 * Math.sin(ang - 0.4));
    ctx.lineTo(arrX - 8 * Math.cos(ang + 0.4), arrY - 8 * Math.sin(ang + 0.4));
    ctx.closePath();
    ctx.fillStyle = isDark ? "rgba(150,150,200,0.35)" : "rgba(100,100,150,0.3)";
    ctx.fill();
  }

  // Draw nodes
  for (const n of _graphNodes) {
    const isHub    = n.id === "__bus__";
    const color    = isHub ? (isDark ? "#7a8fcf" : "#5566bb") : (AGENT_STATE_COLOR[n.state] || "#888");
    const isHover  = _graphTooltipNode === n;

    // Outer glow for hover / busy
    if (isHover || n.state === "busy") {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r + 5, 0, Math.PI * 2);
      ctx.fillStyle = color + "30";
      ctx.fill();
    }

    // Node circle
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
    const grad = ctx.createRadialGradient(n.x - n.r * 0.3, n.y - n.r * 0.3, 1, n.x, n.y, n.r);
    grad.addColorStop(0, color + "dd");
    grad.addColorStop(1, color + "88");
    ctx.fillStyle = grad;
    ctx.fill();
    ctx.strokeStyle = isHover ? color : (isDark ? "rgba(255,255,255,0.15)" : "rgba(0,0,0,0.15)");
    ctx.lineWidth = isHover ? 2 : 1;
    ctx.stroke();

    // Label
    const label = isHub ? "bus" : (n.id.length > 10 ? n.id.slice(0, 9) + "…" : n.id);
    ctx.fillStyle = "#fff";
    ctx.font      = `${isHub ? "bold " : ""}${n.r < 18 ? 8 : 9}px system-ui,sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, n.x, n.y);
  }
}

// ── Graph: mouse / touch interaction ─────────────────────────────────────────

function _graphHitTest(x, y) {
  for (const n of _graphNodes) {
    const dx = n.x - x, dy = n.y - y;
    if (dx * dx + dy * dy <= (n.r + 4) * (n.r + 4)) return n;
  }
  return null;
}

function _canvasCoords(canvas, e) {
  const rect = canvas.getBoundingClientRect();
  const scaleX = canvas.width  / rect.width;
  const scaleY = canvas.height / rect.height;
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top)  * scaleY,
  };
}

function _graphMouseMove(e) {
  const { x, y } = _canvasCoords(this, e);
  const hit = _graphHitTest(x, y);
  const tip  = document.getElementById("swarm-graph-tooltip");

  if (hit && hit.id !== "__bus__") {
    _graphTooltipNode = hit;
    this.style.cursor = "grab";
    if (tip) {
      const stateLabel = hit.state || "unknown";
      tip.textContent  = `${hit.id}  [${stateLabel}]`;
      tip.style.display = "block";
      const rect = this.getBoundingClientRect();
      tip.style.left = `${e.clientX - rect.left + 12}px`;
      tip.style.top  = `${e.clientY - rect.top  - 10}px`;
    }
  } else {
    _graphTooltipNode = null;
    this.style.cursor = "default";
    if (tip) tip.style.display = "none";
  }

  if (_graphDragNode) {
    const { x: dx, y: dy } = _canvasCoords(this, e);
    _graphDragNode.x = dx;
    _graphDragNode.y = dy;
    _graphDragNode.vx = 0;
    _graphDragNode.vy = 0;
  }
}

function _graphMouseDown(e) {
  const { x, y } = _canvasCoords(this, e);
  const hit = _graphHitTest(x, y);
  if (hit && !hit.pinned) { _graphDragNode = hit; this.style.cursor = "grabbing"; }
}

function _graphMouseUp() {
  _graphDragNode = null;
  if (this && this.style) this.style.cursor = "default";
}

function _graphTouchStart(e) {
  e.preventDefault();
  if (!e.touches.length) return;
  const t = e.touches[0];
  const { x, y } = _canvasCoords(this, { clientX: t.clientX, clientY: t.clientY });
  const hit = _graphHitTest(x, y);
  if (hit && !hit.pinned) _graphDragNode = hit;
}

function _graphTouchMove(e) {
  e.preventDefault();
  if (!_graphDragNode || !e.touches.length) return;
  const t = e.touches[0];
  const { x, y } = _canvasCoords(this, { clientX: t.clientX, clientY: t.clientY });
  _graphDragNode.x = x;
  _graphDragNode.y = y;
  _graphDragNode.vx = 0;
  _graphDragNode.vy = 0;
}

// ── Task assignment ───────────────────────────────────────────────────────────

async function _populateAgentSelect() {
  const sel = document.getElementById("swarm-assign-agent");
  if (!sel) return;
  try {
    const r = await fetch("/marketplace/agents");
    if (!r.ok) return;
    const d = await r.json();
    sel.innerHTML = '<option value="">— select agent —</option>';
    for (const a of (d.agents || [])) {
      const opt = document.createElement("option");
      opt.value = a.id;
      opt.textContent = `${a.icon || ""} ${a.name || a.id}`.trim();
      sel.appendChild(opt);
    }
  } catch (_) {}
}

async function swarmAssignTask() {
  const agentId = (document.getElementById("swarm-assign-agent")?.value || "").trim();
  const task    = (document.getElementById("swarm-assign-task")?.value  || "").trim();
  const topic   = (document.getElementById("swarm-assign-topic")?.value || "").trim();
  const resultEl = document.getElementById("swarm-assign-result");

  if (!agentId) { _showAssignResult("Please select an agent.", false); return; }
  if (!task)    { _showAssignResult("Task description is required.",  false); return; }

  try {
    const r = await fetch("/agents/bus", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ from_id: "ui_user", to_id: agentId, content: task, topic }),
    });
    const d = await r.json();
    if (r.ok) {
      _showAssignResult(`✓ Task dispatched to ${agentId} (msg: ${d.msg_id || "?"})`, true);
      document.getElementById("swarm-assign-task").value  = "";
      document.getElementById("swarm-assign-topic").value = "";
      // Auto-switch to activity to see the result
      setTimeout(() => swarmTab("activity"), 1200);
    } else {
      _showAssignResult(`Error: ${d.error || r.statusText}`, false);
    }
  } catch (e) {
    _showAssignResult(`Network error: ${e.message}`, false);
  }
}

function _showAssignResult(msg, ok) {
  const el = document.getElementById("swarm-assign-result");
  if (!el) return;
  el.style.display     = "block";
  el.style.borderLeft  = `3px solid ${ok ? "var(--accent)" : "#e55"}`;
  el.textContent       = msg;
}

