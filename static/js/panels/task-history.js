// ── Task History Panel — Sprint K ─────────────────────────────────────────────
"use strict";

let _thFilter     = "all";   // all | running | done | failed
let _thSearch     = "";
let _thSortNewest = true;
let _thSelected   = null;    // currently expanded trace_id

function openTaskHistoryPanel() {
  NexusApi.setPanelOpen("task-history-panel", true);
  thRefresh();
}

function closeTaskHistoryPanel() {
  NexusApi.setPanelOpen("task-history-panel", false);
}

// ── Filter / search ───────────────────────────────────────────────────────────
function thSetFilter(f) {
  _thFilter = f;
  document.querySelectorAll(".th-filter-btn").forEach(b => {
    b.style.background = b.dataset.filter === f ? "var(--accent)" : "transparent";
    b.style.color      = b.dataset.filter === f ? "#fff" : "var(--muted)";
  });
  thRefresh();
}

function thSetSearch(val) {
  _thSearch = val.toLowerCase();
  thRefresh();
}

function thToggleSort() {
  _thSortNewest = !_thSortNewest;
  const btn = document.getElementById("th-sort-btn");
  if (btn) btn.textContent = _thSortNewest ? "↓ Newest" : "↑ Oldest";
  thRefresh();
}

// ── Data fetch + render ───────────────────────────────────────────────────────
async function thRefresh() {
  const list = document.getElementById("th-list");
  if (!list) return;
  list.innerHTML = '<div style="color:var(--muted);padding:12px;font-size:.8rem;">Loading…</div>';

  try {
    const r = await fetch("/tasks?limit=100");
    if (!r.ok) throw new Error(r.statusText);
    const d = await r.json();
    let traces = (d.traces || []);

    // Status classification
    traces = traces.map(t => ({
      ...t,
      _status: _classifyStatus(t),
      _ts: t.started_at || t.created_at || "",
    }));

    // Filter
    if (_thFilter !== "all") traces = traces.filter(t => t._status === _thFilter);
    if (_thSearch) traces = traces.filter(t =>
      (t.task || "").toLowerCase().includes(_thSearch) ||
      (t.trace_id || "").toLowerCase().includes(_thSearch)
    );

    // Sort
    traces.sort((a, b) =>
      _thSortNewest
        ? b._ts.localeCompare(a._ts)
        : a._ts.localeCompare(b._ts)
    );

    // Update count badge
    const badge = document.getElementById("th-count");
    if (badge) badge.textContent = traces.length;

    if (!traces.length) {
      list.innerHTML = '<div style="color:var(--muted);padding:16px;text-align:center;font-size:.8rem;">No tasks match.</div>';
      return;
    }

    list.innerHTML = "";
    for (const t of traces) {
      list.appendChild(_buildTraceCard(t));
    }
  } catch (e) {
    list.innerHTML = `<div style="color:var(--red);padding:10px;font-size:.78rem;">Error: ${esc(e.message)}</div>`;
  }
}

function _classifyStatus(t) {
  const events = Array.isArray(t.events) ? t.events : [];
  if (events.some(e => e && e.type === "error")) return "failed";
  if (events.some(e => e && e.type === "done"))  return "done";
  if (t.steps > 0) return "running";
  return "done";
}

function _buildTraceCard(t) {
  const card = document.createElement("div");
  card.className = "th-card";
  card.style.cssText = "padding:9px 12px;background:var(--surface2);border-radius:9px;cursor:pointer;border:1px solid transparent;transition:border-color .13s;";
  card.dataset.traceId = t.trace_id || "";

  const statusColor = { done: "#22c55e", failed: "#ef4444", running: "#f59e0b" }[t._status] || "#888";
  const statusIcon  = { done: "✓", failed: "✕", running: "…" }[t._status] || "?";
  const ts = t._ts ? new Date(t._ts).toLocaleString([], { month:"short", day:"numeric", hour:"2-digit", minute:"2-digit" }) : "";

  card.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;">
      <span style="width:18px;height:18px;border-radius:50%;background:${statusColor};display:inline-flex;align-items:center;justify-content:center;font-size:.65rem;color:#fff;font-weight:700;flex-shrink:0;">${statusIcon}</span>
      <div style="flex:1;min-width:0;">
        <div style="font-size:.8rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(t.task||'')}">${esc((t.task || "–").slice(0,72))}</div>
        <div style="font-size:.65rem;color:var(--muted);margin-top:2px;">${esc(t.trace_id||'').slice(0,16)} · ${t.steps||0} steps · ${ts}</div>
      </div>
      <div style="display:flex;gap:5px;flex-shrink:0;">
        <button onclick="event.stopPropagation();thExportTrace('${esc(t.trace_id||'')}')" title="Export" style="background:none;border:1px solid var(--border);border-radius:5px;padding:2px 7px;font-size:.65rem;color:var(--muted);cursor:pointer;">⬇</button>
        <button onclick="event.stopPropagation();thDeleteTrace('${esc(t.trace_id||'')}')" title="Delete" style="background:none;border:1px solid var(--border);border-radius:5px;padding:2px 7px;font-size:.65rem;color:var(--red);cursor:pointer;">🗑</button>
      </div>
    </div>
    <div class="th-detail" id="th-detail-${esc(t.trace_id||'')}" style="display:none;margin-top:8px;"></div>
  `;

  card.addEventListener("click", () => thToggleDetail(t.trace_id || "", card));
  card.addEventListener("mouseenter", () => card.style.borderColor = "var(--border)");
  card.addEventListener("mouseleave", () => card.style.borderColor = _thSelected === t.trace_id ? "var(--accent)" : "transparent");

  return card;
}

async function thToggleDetail(traceId, card) {
  const detail = document.getElementById(`th-detail-${traceId}`);
  if (!detail) return;

  if (_thSelected === traceId) {
    // Collapse
    detail.style.display = "none";
    card.style.borderColor = "transparent";
    _thSelected = null;
    return;
  }

  // Collapse previous
  if (_thSelected) {
    const prev = document.getElementById(`th-detail-${_thSelected}`);
    if (prev) prev.style.display = "none";
    const prevCard = document.querySelector(`[data-trace-id="${_thSelected}"]`);
    if (prevCard) prevCard.style.borderColor = "transparent";
  }

  _thSelected = traceId;
  card.style.borderColor = "var(--accent)";
  detail.style.display = "block";
  detail.innerHTML = '<div style="color:var(--muted);font-size:.72rem;">Loading trace…</div>';

  try {
    const r = await fetch(`/tasks/${encodeURIComponent(traceId)}`);
    const d = await r.json();
    const events = d.events || [];
    detail.innerHTML = _renderTraceDetail(events, traceId);
  } catch (e) {
    detail.innerHTML = `<div style="color:var(--red);font-size:.72rem;">Error: ${esc(e.message)}</div>`;
  }
}

function _renderTraceDetail(events, traceId) {
  if (!events.length) return '<div style="color:var(--muted);font-size:.72rem;">No events recorded.</div>';

  const TYPE_COLOR = {
    plan: "#7c6af7", think: "#5eead4", tool: "#f59e0b",
    done: "#22c55e", error: "#ef4444", complexity: "#94a3b8",
  };
  const TYPE_ICON = {
    plan:"📋", think:"💭", tool:"⚙️", done:"✓", error:"✕",
    clarify:"❓", respond:"💬", fallback:"↩️",
  };

  // Build timeline items
  const items = events
    .filter(e => e && e.type && !["system","complexity"].includes(e.type))
    .map((e, i) => {
      const color = TYPE_COLOR[e.type] || "#888";
      const icon  = TYPE_ICON[e.type]  || "·";
      let label = "";
      if (e.type === "plan")   label = e.title || "Plan";
      else if (e.type === "tool") label = `${e.action || ""} — ${(e.label||"").slice(0,40)}`;
      else if (e.type === "done") label = (e.content||"").slice(0,60);
      else if (e.type === "think") label = (e.thought||"").slice(0,60);
      else if (e.type === "error") label = (e.message||"").slice(0,60);
      else label = JSON.stringify(e).slice(0,60);

      return `<div style="display:flex;gap:7px;align-items:flex-start;padding:3px 0;font-size:.7rem;">
        <span style="color:${color};flex-shrink:0;width:16px;text-align:center;">${icon}</span>
        <span style="color:var(--muted);flex-shrink:0;">${i+1}.</span>
        <span style="flex:1;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(label)}">${esc(label)}</span>
      </div>`;
    }).join("");

  const replayBtn = `<button onclick="thReplayTrace('${esc(traceId)}')" style="font-size:.7rem;padding:3px 9px;border-radius:5px;background:var(--accent);color:#fff;border:none;cursor:pointer;">⏮ Replay in Trace Viewer</button>`;
  const resumeBtn = `<button onclick="resumeTrace('${esc(traceId)}')" style="font-size:.7rem;padding:3px 9px;border-radius:5px;background:var(--surface);color:var(--text);border:1px solid var(--border);cursor:pointer;">▶ Resume</button>`;

  return `
    <div style="border-top:1px solid var(--border);padding-top:7px;max-height:200px;overflow-y:auto;">${items}</div>
    <div style="display:flex;gap:6px;margin-top:8px;">${replayBtn}${resumeBtn}</div>
  `;
}

function thReplayTrace(traceId) {
  closeTaskHistoryPanel();
  openTracePanel();
  replayTrace(traceId);
}

async function thExportTrace(traceId) {
  try {
    const r = await fetch(`/tasks/${encodeURIComponent(traceId)}/export`);
    const blob = await r.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `trace-${traceId.slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  } catch(e) {
    alert("Export failed: " + e.message);
  }
}

async function thDeleteTrace(traceId) {
  if (!confirm(`Delete trace ${traceId.slice(0,12)}…?`)) return;
  try {
    await fetch(`/tasks/${encodeURIComponent(traceId)}`, { method: "DELETE" });
    if (_thSelected === traceId) _thSelected = null;
    await thRefresh();
  } catch(e) {
    alert("Delete failed: " + e.message);
  }
}
