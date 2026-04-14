// Trace viewer panel module (static split from index.html)
function openTracePanel() {
  NexusApi.setPanelOpen("trace-panel", true);
  refreshTraces();
}

function closeTracePanel() {
  NexusApi.setPanelOpen("trace-panel", false);
}

async function refreshTraces() {
  const feed = document.getElementById("trace-feed");
  feed.innerHTML = '<div style="color:var(--muted);padding:8px;">Loading...</div>';
  try {
    const r = await fetch("/tasks?limit=30");
    const d = await r.json();
    if (!d.traces || !d.traces.length) {
      feed.innerHTML = '<div style="color:var(--muted);padding:8px;">No traces recorded yet.</div>';
      return;
    }
    feed.innerHTML = d.traces.map((t) => `
      <div style="padding:7px 9px;background:var(--surface2);border-radius:7px;">
        <div style="font-size:.74rem;color:var(--muted);">${esc(t.trace_id)} · ${t.steps || 0} steps · ${(t.started_at || "").slice(0, 16)}</div>
        <div style="font-size:.83rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(t.task || "")}">${esc(t.task || "-")}</div>
        <div style="display:flex;gap:6px;margin-top:5px;">
          <button onclick="replayTrace('${esc(t.trace_id)}')" style="font-size:.74rem;padding:3px 8px;border-radius:5px;background:var(--accent);color:#fff;border:none;cursor:pointer;">⏮ Replay</button>
          <button onclick="resumeTrace('${esc(t.trace_id)}')" style="font-size:.74rem;padding:3px 8px;border-radius:5px;background:var(--surface);color:var(--text);border:1px solid var(--border);cursor:pointer;">▶ Resume</button>
        </div>
      </div>`).join("");
  } catch (e) {
    feed.innerHTML = `<div style="color:var(--red);padding:8px;">Error: ${e.message}</div>`;
  }
}

function replayTrace(traceId) {
  const feed = document.getElementById("trace-feed");
  feed.innerHTML = `<div style="color:var(--muted);padding:8px;">⏮ Replaying ${esc(traceId)}...</div>`;
  const es = new EventSource(`/tasks/${encodeURIComponent(traceId)}/replay`);
  es.onmessage = (e) => {
    try {
      const evt = JSON.parse(e.data);
      const row = document.createElement("div");
      row.style.cssText = "padding:5px 8px;background:var(--surface2);border-radius:5px;font-size:.78rem;";
      row.textContent = `[${evt.type || "event"}] ${esc(evt.action || evt.content || evt.message || "")}`.slice(0, 120);
      feed.appendChild(row);
      feed.scrollTop = feed.scrollHeight;
    } catch (_) {
      // Ignore malformed replay events.
    }
  };
  es.onerror = () => es.close();
}

async function resumeTrace(traceId) {
  closeTracePanel();
  await fetch(`/tasks/${encodeURIComponent(traceId)}/resume`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  addMessage("system", `▶ Resuming trace ${traceId} - watch for output above.`);
}
