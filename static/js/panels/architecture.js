// Architecture panel module (static split from index.html)
let _archVersions = [];

function openArchitecturePanel() {
  NexusApi.setPanelOpen("architecture-panel", true);
  refreshArchitectureList();
}

function closeArchitecturePanel() {
  NexusApi.setPanelOpen("architecture-panel", false);
}

async function createArchitectureSnapshot() {
  const name = (document.getElementById("arch-name")?.value || "default").trim() || "default";
  const notes = (document.getElementById("arch-notes")?.value || "").trim();
  const status = document.getElementById("arch-status");
  status.textContent = "Creating snapshot...";

  const data = await fetch("/architecture/blueprints", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, notes, use_runtime: true }),
  }).then((r) => r.json()).catch(() => null);

  if (!data || data.type === "validation_error") {
    status.style.color = "var(--red)";
    status.textContent = data?.error || "Failed to create snapshot.";
    return;
  }
  const bp = data.blueprint || {};
  status.style.color = "var(--teal)";
  status.textContent = `Created ${bp.name || name} v${bp.version || "?"} (${bp.nodes || 0} nodes, ${bp.edges || 0} edges)`;
  await refreshArchitectureList();
}

async function refreshArchitectureList() {
  const name = (document.getElementById("arch-name")?.value || "default").trim() || "default";
  const list = document.getElementById("arch-version-list");
  const summary = document.getElementById("arch-summary");
  list.innerHTML = '<div style="font-size:.74rem;color:var(--muted)">Loading...</div>';

  const data = await fetch(`/architecture/blueprints?name=${encodeURIComponent(name)}&limit=20`)
    .then((r) => r.json()).catch(() => ({ blueprints: [] }));
  _archVersions = data.blueprints || [];
  if (!_archVersions.length) {
    list.innerHTML = '<div style="font-size:.74rem;color:var(--muted)">No versions yet.</div>';
    summary.innerHTML = "Create a runtime snapshot to start version history.";
    return;
  }

  list.innerHTML = _archVersions.map((v) => {
    const ts = new Date(v.created_at || Date.now()).toLocaleString();
    return `<button onclick='selectArchitectureVersion(${JSON.stringify(name)}, ${v.version})'
      style="text-align:left;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px;cursor:pointer;color:var(--text)">
      <div style="font-weight:700;font-size:.76rem">v${v.version}</div>
      <div style="font-size:.66rem;color:var(--muted)">${esc(ts)}</div>
    </button>`;
  }).join("");

  await selectArchitectureVersion(name, _archVersions[0].version);
}

async function selectArchitectureVersion(name, version) {
  const summary = document.getElementById("arch-summary");
  summary.innerHTML = '<div style="font-size:.74rem;color:var(--muted)">Loading summary...</div>';

  const [bp, reg] = await Promise.all([
    fetch(`/architecture/blueprints/${encodeURIComponent(name)}?version=${version}`).then((r) => r.json()).catch(() => null),
    fetch(`/architecture/registry/${encodeURIComponent(name)}?version=${version}`).then((r) => r.json()).catch(() => null),
  ]);

  if (!bp || bp.type === "not_found") {
    summary.innerHTML = '<div style="color:var(--red)">Version not found.</div>';
    return;
  }

  const c = bp.snapshot?.counts || {};
  const rc = reg?.counts || {};
  summary.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:6px">
      <div><b>${esc(bp.name || name)}</b> v${bp.version}</div>
      <div style="font-size:.72rem;color:var(--muted)">${esc(new Date(bp.created_at || Date.now()).toLocaleString())}</div>
      <div style="font-size:.72rem;color:var(--muted)">${esc(bp.notes || "No notes")}</div>
      <hr style="border-color:var(--border)">
      <div>Foundation models: <b>${c.foundation_models || 0}</b></div>
      <div>Agents: <b>${c.agents || 0}</b></div>
      <div>Workflows: <b>${c.workflows || 0}</b></div>
      <div>Tools: <b>${c.tools || 0}</b></div>
      <hr style="border-color:var(--border)">
      <div>Registry nodes: <b>${rc.nodes || 0}</b></div>
      <div>Registry edges: <b>${rc.edges || 0}</b></div>
    </div>
  `;
}