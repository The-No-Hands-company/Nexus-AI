function openAdminDashboardPanel() {
  NexusApi.setPanelOpen("admin-dashboard-panel", true);
  loadAdminDashboard();
}

function closeAdminDashboardPanel() {
  NexusApi.setPanelOpen("admin-dashboard-panel", false);
}

function getTurnBudgetSeverity(summary) {
  const hard = Number(summary?.pressure_counts?.hard || 0);
  const soft = Number(summary?.pressure_counts?.soft || 0);
  const hardRate = Number(summary?.downgrade_rate || 0);
  if (hard > 0 || hardRate >= 0.6) return "hard";
  if (soft > 0 || hardRate >= 0.2) return "soft";
  return "none";
}

function getTurnBudgetSeverityTheme(severity) {
  if (severity === "hard") {
    return {
      borderColor: "color-mix(in srgb, var(--red) 55%, var(--border))",
      background: "color-mix(in srgb, var(--red) 12%, var(--surface2))",
      boxShadow: "0 0 0 1px color-mix(in srgb, var(--red) 22%, transparent) inset",
    };
  }
  if (severity === "soft") {
    return {
      borderColor: "color-mix(in srgb, var(--amber) 55%, var(--border))",
      background: "color-mix(in srgb, var(--amber) 12%, var(--surface2))",
      boxShadow: "0 0 0 1px color-mix(in srgb, var(--amber) 18%, transparent) inset",
    };
  }
  return {
    borderColor: "var(--border)",
    background: "var(--surface2)",
    boxShadow: "none",
  };
}

function applyTurnBudgetSeverityCards(severity) {
  [
    "ad-turn-card-rate",
    "ad-turn-card-pressure",
    "ad-turn-card-pruning",
    "ad-turn-card-families",
  ].forEach((id) => {
    const card = document.getElementById(id);
    if (!card) return;
    const theme = getTurnBudgetSeverityTheme(severity);
    card.dataset.severity = severity;
    card.style.borderColor = theme.borderColor;
    card.style.background = theme.background;
    card.style.boxShadow = theme.boxShadow;
  });
}

function renderTurnBudgetSummary(summary) {
  const pressureCounts = summary?.pressure_counts || {};
  const familyCounts = summary?.model_family_counts || {};
  const recent = Array.isArray(summary?.recent) ? summary.recent : [];
  const downgradeRate = Number(summary?.downgrade_rate || 0);
  const totalTurns = Number(summary?.total_turns || 0);
  const severity = getTurnBudgetSeverity(summary || {});
  const familySummary = Object.entries(familyCounts)
    .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
    .slice(0, 3)
    .map(([name, count]) => `${name} ${Number(count || 0)}`)
    .join(" · ");

  return {
    severity,
    rateText: totalTurns
      ? `${(downgradeRate * 100).toFixed(1)}% · ${Number(summary?.pressured_turns || 0)}/${totalTurns}`
      : "No recent turns",
    pressureText: `soft ${Number(pressureCounts.soft || 0)} · hard ${Number(pressureCounts.hard || 0)} · none ${Number(pressureCounts.none || 0)}`,
    pruningText: `MCTS ${Number(summary?.disable_mcts_count || 0)} · Ensemble ${Number(summary?.disable_ensemble_count || 0)}`,
    familiesText: familySummary || "No family data",
    recentRowsHtml: recent.length
      ? recent.slice().reverse().map((item) => {
          const helpers = [item.disable_mcts ? "MCTS off" : "MCTS on", item.disable_ensemble ? "ensemble off" : "ensemble on"].join(" · ");
          return `<tr><td>${esc(item.pressure || "none")}</td><td>${esc(item.complexity || "-")}</td><td>${esc(item.model_family || "-")}</td><td>${esc(helpers)}</td><td>${esc(item.tool_budget_mode || "adaptive")}</td></tr>`;
        }).join("")
      : '<tr><td colspan="5" style="color:var(--muted)">No recent turn-budget events in this window.</td></tr>',
    totalTurns,
  };
}

async function loadAdminDashboard() {
  const status = document.getElementById("ad-status");
  const usersEl = document.getElementById("ad-users");
  const quotaEl = document.getElementById("ad-quota");
  const usageEl = document.getElementById("ad-usage");
  const turnRateEl = document.getElementById("ad-turn-rate");
  const turnPressureEl = document.getElementById("ad-turn-pressure");
  const turnPruningEl = document.getElementById("ad-turn-pruning");
  const turnFamiliesEl = document.getElementById("ad-turn-families");
  const turnRecentEl = document.getElementById("ad-turn-recent");
  const days = Number(document.getElementById("ad-days")?.value || 7);

  if (!status || !usersEl || !quotaEl || !usageEl || !turnRateEl || !turnPressureEl || !turnPruningEl || !turnFamiliesEl || !turnRecentEl) return;
  status.textContent = "Loading...";
  turnRecentEl.innerHTML = '<tr><td colspan="5" style="color:var(--muted)">Loading…</td></tr>';

  try {
    const sinceTs = Math.max(0, Math.floor(Date.now() / 1000) - (Math.max(1, Math.min(365, days)) * 86400));
    const [usersRes, quotaRes, usageRes, turnBudgetRes] = await Promise.all([
      NexusApi.apiJson("/admin/users"),
      NexusApi.apiJson("/admin/quota"),
      NexusApi.apiJson(`/usage?days=${Math.max(1, Math.min(365, days))}`),
      NexusApi.apiJson(`/admin/turn-budget-summary?limit=200&since_ts=${sinceTs}`),
    ]);

    const users = usersRes.ok ? (usersRes.data.users || []) : [];
    const quotas = quotaRes.ok ? (quotaRes.data.items || []) : [];
    const perUser = usageRes.ok ? (usageRes.data.per_user || []) : [];
    const turnBudget = turnBudgetRes.ok ? (turnBudgetRes.data || {}) : {};
    usersEl.innerHTML = users.length
      ? users.map((u) => `<tr><td>${esc(u.username || "")}</td><td>${esc(u.role || "user")}</td><td>${esc(u.email || "")}</td></tr>`).join("")
      : '<tr><td colspan="3" style="color:var(--muted)">No users found.</td></tr>';

    quotaEl.innerHTML = quotas.length
      ? quotas.map((q) => `<tr><td>${esc(q.username || "")}</td><td>${Number(q.daily_limit_tokens || 0)}</td><td>${Number(q.weekly_limit_tokens || 0)}</td><td>${Number(q.monthly_limit_tokens || 0)}</td></tr>`).join("")
      : '<tr><td colspan="4" style="color:var(--muted)">No quota records.</td></tr>';

    usageEl.innerHTML = perUser.length
      ? perUser.map((u) => `<tr><td>${esc(u.username || "")}</td><td>${Number(u.calls || 0)}</td><td>${Number(u.in_tok || 0) + Number(u.out_tok || 0)}</td><td>${Number(u.cost_usd || 0).toFixed(4)}</td></tr>`).join("")
      : '<tr><td colspan="4" style="color:var(--muted)">No usage records.</td></tr>';

    const renderedTurnBudget = renderTurnBudgetSummary(turnBudget);
    applyTurnBudgetSeverityCards(renderedTurnBudget.severity);
    turnRateEl.textContent = renderedTurnBudget.rateText;
    turnPressureEl.textContent = renderedTurnBudget.pressureText;
    turnPruningEl.textContent = renderedTurnBudget.pruningText;
    turnFamiliesEl.textContent = renderedTurnBudget.familiesText;
    turnRecentEl.innerHTML = renderedTurnBudget.recentRowsHtml;

    status.textContent = `Users ${users.length} · Quotas ${quotas.length} · Usage rows ${perUser.length} · Turn budgets ${renderedTurnBudget.totalTurns}`;
  } catch (err) {
    status.textContent = "Load failed";
    usersEl.innerHTML = `<tr><td colspan="3" style="color:var(--red)">${esc(String(err))}</td></tr>`;
    quotaEl.innerHTML = '<tr><td colspan="4" style="color:var(--muted)">-</td></tr>';
    usageEl.innerHTML = '<tr><td colspan="4" style="color:var(--muted)">-</td></tr>';
    turnRateEl.textContent = "Load failed";
    turnPressureEl.textContent = "-";
    turnPruningEl.textContent = "-";
    turnFamiliesEl.textContent = "-";
    applyTurnBudgetSeverityCards("hard");
    turnRecentEl.innerHTML = `<tr><td colspan="5" style="color:var(--red)">${esc(String(err))}</td></tr>`;
  }
}

window.NexusAdminDashboard = {
  getTurnBudgetSeverity,
  getTurnBudgetSeverityTheme,
  renderTurnBudgetSummary,
};
