function openAdminDashboardPanel() {
  NexusApi.setPanelOpen("admin-dashboard-panel", true);
  loadAdminDashboard();
}

function closeAdminDashboardPanel() {
  NexusApi.setPanelOpen("admin-dashboard-panel", false);
}

async function loadAdminDashboard() {
  const status = document.getElementById("ad-status");
  const usersEl = document.getElementById("ad-users");
  const quotaEl = document.getElementById("ad-quota");
  const usageEl = document.getElementById("ad-usage");
  const days = Number(document.getElementById("ad-days")?.value || 7);

  if (!status || !usersEl || !quotaEl || !usageEl) return;
  status.textContent = "Loading...";

  try {
    const [usersRes, quotaRes, usageRes] = await Promise.all([
      NexusApi.apiJson("/admin/users"),
      NexusApi.apiJson("/admin/quota"),
      NexusApi.apiJson(`/usage?days=${Math.max(1, Math.min(365, days))}`),
    ]);

    const users = usersRes.ok ? (usersRes.data.users || []) : [];
    const quotas = quotaRes.ok ? (quotaRes.data.items || []) : [];
    const perUser = usageRes.ok ? (usageRes.data.per_user || []) : [];

    usersEl.innerHTML = users.length
      ? users.map((u) => `<tr><td>${esc(u.username || "")}</td><td>${esc(u.role || "user")}</td><td>${esc(u.email || "")}</td></tr>`).join("")
      : '<tr><td colspan="3" style="color:var(--muted)">No users found.</td></tr>';

    quotaEl.innerHTML = quotas.length
      ? quotas.map((q) => `<tr><td>${esc(q.username || "")}</td><td>${Number(q.daily_limit_tokens || 0)}</td><td>${Number(q.weekly_limit_tokens || 0)}</td><td>${Number(q.monthly_limit_tokens || 0)}</td></tr>`).join("")
      : '<tr><td colspan="4" style="color:var(--muted)">No quota records.</td></tr>';

    usageEl.innerHTML = perUser.length
      ? perUser.map((u) => `<tr><td>${esc(u.username || "")}</td><td>${Number(u.calls || 0)}</td><td>${Number(u.in_tok || 0) + Number(u.out_tok || 0)}</td><td>${Number(u.cost_usd || 0).toFixed(4)}</td></tr>`).join("")
      : '<tr><td colspan="4" style="color:var(--muted)">No usage records.</td></tr>';

    status.textContent = `Users ${users.length} · Quotas ${quotas.length} · Usage rows ${perUser.length}`;
  } catch (err) {
    status.textContent = "Load failed";
    usersEl.innerHTML = `<tr><td colspan="3" style="color:var(--red)">${esc(String(err))}</td></tr>`;
    quotaEl.innerHTML = '<tr><td colspan="4" style="color:var(--muted)">-</td></tr>';
    usageEl.innerHTML = '<tr><td colspan="4" style="color:var(--muted)">-</td></tr>';
  }
}
