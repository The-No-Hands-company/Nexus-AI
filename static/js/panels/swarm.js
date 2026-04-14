// Swarm panel module (static split from index.html)
let _swarmTimer = null;
let _lastSwarmTotal = 0;

const SWARM_ACTION_COLORS = {
  write_file: "#4a9",
  read_file: "#69b",
  run_command: "#d96",
  web_search: "#79d",
  query_db: "#a8a",
  inspect_db: "#a8a",
  commit_push: "#5b5",
  clone_repo: "#5b5",
  sub_agent: "#b75",
};

function openSwarmPanel() {
  NexusApi.setPanelOpen("swarm-panel", true);
  _startSwarmPolling();
}

function closeSwarmPanel() {
  NexusApi.setPanelOpen("swarm-panel", false);
  _stopSwarmPolling();
}

function clearSwarmFeed() {
  document.getElementById("swarm-feed").innerHTML = "";
  document.getElementById("swarm-count").textContent = "0 events";
}

function _startSwarmPolling() {
  if (_swarmTimer) return;
  _pollSwarm();
  _swarmTimer = setInterval(_pollSwarm, 2000);
}

function _stopSwarmPolling() {
  if (_swarmTimer) {
    clearInterval(_swarmTimer);
    _swarmTimer = null;
  }
}

async function _pollSwarm() {
  try {
    const r = await fetch("/swarm/activity?limit=60");
    if (!r.ok) return;
    const d = await r.json();
    const feed = document.getElementById("swarm-feed");
    const countEl = document.getElementById("swarm-count");
    if (d.total === _lastSwarmTotal) return;
    const newEvents = d.events.slice(Math.max(0, d.events.length - (d.total - _lastSwarmTotal)));
    _lastSwarmTotal = d.total;
    for (const ev of newEvents) {
      const row = document.createElement("div");
      const clr = SWARM_ACTION_COLORS[ev.action] || "#888";
      const ts = ev.ts ? new Date(ev.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";
      row.style.cssText = "display:flex;align-items:center;gap:6px;padding:3px 6px;border-radius:6px;background:var(--surface2);font-size:.72rem;";
      row.innerHTML = `<span style="color:${clr};font-weight:700;min-width:90px;">${esc(ev.action || "?")}</span><span style="flex:1;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(ev.label || "")}</span><span style="color:var(--muted);font-size:.65rem;">${ts}</span>`;
      feed.appendChild(row);
    }
    feed.scrollTop = feed.scrollHeight;
    countEl.textContent = d.total + " event" + (d.total === 1 ? "" : "s");
  } catch (_) {
    // Ignore transient poll errors.
  }
}
