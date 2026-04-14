// Knowledge graph panel module (static split from index.html)
function openKGPanel() {
  NexusApi.setPanelOpen("kg-panel", true);
  kgSearch();
}

function closeKGPanel() {
  NexusApi.setPanelOpen("kg-panel", false);
}

async function kgSearch() {
  const q = document.getElementById("kg-search-input").value.trim();
  const feed = document.getElementById("kg-feed");
  feed.innerHTML = '<div style="color:var(--muted);padding:8px;">Loading...</div>';
  try {
    const url = q.length >= 2 ? `/kg/query?q=${encodeURIComponent(q)}&limit=20` : "/kg/entities?limit=40";
    const r = await fetch(url);
    const d = await r.json();
    const items = d.results || d.entities || [];
    if (!items.length) {
      feed.innerHTML = '<div style="color:var(--muted);padding:8px;">No results.</div>';
      return;
    }
    feed.innerHTML = items.map((e) => {
      const facts = Object.entries(e.facts || {}).slice(0, 3).map(([k, v]) => `${k}: ${v}`).join(" · ");
      const rels = (e.relations || []).slice(0, 3).map((r2) => `${r2.relation}→${r2.entity || r2.to_entity}`).join(", ");
      return `<div style="padding:7px 9px;background:var(--surface2);border-radius:7px;">
        <div><span style="font-weight:600">${esc(e.name)}</span> <span style="color:var(--muted);font-size:.74rem;">[${esc(e.type || e.entity_type || "")}]</span></div>
        ${facts ? `<div style="color:var(--muted);font-size:.76rem;margin-top:2px;">${esc(facts)}</div>` : ""}
        ${rels ? `<div style="color:var(--muted);font-size:.76rem;">🔗 ${esc(rels)}</div>` : ""}
      </div>`;
    }).join("");
  } catch (e) {
    feed.innerHTML = `<div style="color:var(--red);padding:8px;">Error: ${e.message}</div>`;
  }
}

async function kgStore() {
  const name = document.getElementById("kg-add-name").value.trim();
  if (!name) {
    alert("Entity name required");
    return;
  }
  let facts = {};
  try {
    facts = JSON.parse(document.getElementById("kg-add-facts").value || "{}");
  } catch (_) {
    facts = {};
  }
  const r = await fetch("/kg/store", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, entity_type: document.getElementById("kg-add-type").value || "concept", facts }),
  });
  if (r.ok) {
    document.getElementById("kg-add-name").value = "";
    document.getElementById("kg-add-facts").value = "";
    kgSearch();
  } else {
    alert("Failed to store entity");
  }
}
