// HITL Approvals Panel — human-in-the-loop approval workflow UI
let _hitlTimer = null;

function openHitlPanel() {
  NexusApi.setPanelOpen("hitl-panel", true);
  refreshHitlApprovals();
  if (_hitlTimer) clearInterval(_hitlTimer);
  _hitlTimer = setInterval(refreshHitlApprovals, 3000);
}

function closeHitlPanel() {
  NexusApi.setPanelOpen("hitl-panel", false);
  if (_hitlTimer) { clearInterval(_hitlTimer); _hitlTimer = null; }
}

async function refreshHitlApprovals() {
  const feed = document.getElementById("hitl-feed");
  const badge = document.getElementById("hitl-pending-badge");
  try {
    const [ar, sr] = await Promise.all([
      fetch("/approvals").then(r => r.json()),
      fetch("/settings/hitl").then(r => r.json()),
    ]);
    const items = ar.items || [];
    const mode = sr.hitl_approval_mode || "off";
    document.getElementById("hitl-mode-display").textContent = mode.toUpperCase();

    const pending = items.filter(i => i.status === "pending");
    if (badge) {
      badge.textContent = pending.length;
      badge.style.display = pending.length > 0 ? "" : "none";
    }

    if (!items.length) {
      feed.innerHTML = '<div style="color:var(--muted);font-size:.75rem;padding:6px 4px">No approval requests yet.</div>';
      return;
    }
    feed.innerHTML = items.map(i => {
      const isPending = i.status === "pending";
      const statusColor = isPending ? "var(--yellow)" : i.status === "approved" ? "var(--green)" : "var(--red)";
      const ts = i.created_at || "";
      return `<div style="border:1px solid var(--border);border-radius:8px;padding:10px;margin-bottom:8px;background:var(--surface2)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span style="font-size:.75rem;color:var(--muted)">${esc(i.id?.substring(0,12) || "")}…</span>
          <span style="font-size:.72rem;color:${statusColor};font-weight:600">${esc(i.status)}</span>
        </div>
        <div style="font-size:.78rem;margin-bottom:4px"><strong>Session:</strong> ${esc(i.session_id || "-")}</div>
        <div style="font-size:.72rem;color:var(--muted);margin-bottom:6px;max-height:80px;overflow:auto;background:var(--bg);padding:4px 6px;border-radius:4px">
          <pre style="margin:0;font-size:.68rem;white-space:pre-wrap;word-break:break-all">${esc(JSON.stringify(i.action || {}, null, 1))}</pre>
        </div>
        <div style="font-size:.68rem;color:var(--muted);margin-bottom:6px">${esc(ts)}</div>
        ${i.note ? `<div style="font-size:.7rem;color:var(--muted);margin-bottom:6px;font-style:italic">Note: ${esc(i.note)}</div>` : ""}
        ${isPending ? `<div style="display:flex;gap:8px">
          <button class="panel-btn" style="background:var(--green);color:#fff" onclick="approveHitl('${i.id}')">Approve</button>
          <button class="panel-btn" style="background:var(--red);color:#fff" onclick="rejectHitl('${i.id}')">Reject</button>
        </div>` : ""}
      </div>`;
    }).join("");
  } catch (_) {
    feed.innerHTML = '<div style="color:var(--red);font-size:.75rem;padding:6px 4px">Failed to load approvals.</div>';
  }
}

async function approveHitl(id) {
  await resolveHitl(id, true, "");
}

async function rejectHitl(id) {
  const note = prompt("Rejection reason (optional):") || "";
  await resolveHitl(id, false, note);
}

async function resolveHitl(id, approved, note) {
  try {
    await fetch(`/approvals/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, note }),
    });
    refreshHitlApprovals();
  } catch (e) {
    alert("Failed to resolve approval: " + e.message);
  }
}

async function updateHitlMode() {
  const mode = document.getElementById("hitl-mode-select").value;
  try {
    await fetch("/settings/hitl", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ hitl_approval_mode: mode }),
    });
    document.getElementById("hitl-mode-display").textContent = mode.toUpperCase();
  } catch (e) {
    alert("Failed to update HITL mode: " + e.message);
  }
}

function esc(s) { return String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
