function openBenchmarkDashboardPanel() {
  NexusApi.setPanelOpen("benchmark-dashboard-panel", true);
  loadBenchmarkDashboard();
}

function closeBenchmarkDashboardPanel() {
  NexusApi.setPanelOpen("benchmark-dashboard-panel", false);
}

async function loadBenchmarkDashboard() {
  const status = document.getElementById("bd-status");
  const latestEl = document.getElementById("bd-latest");
  const historyEl = document.getElementById("bd-history");
  const tradeoffEl = document.getElementById("bd-tradeoff");
  if (!status || !latestEl || !historyEl || !tradeoffEl) return;
  status.textContent = "Loading...";

  try {
    const [latestRes, historyRes, tradeoffRes] = await Promise.all([
      NexusApi.apiJson("/benchmark/results"),
      NexusApi.apiJson("/benchmark/history?limit=200"),
      NexusApi.apiJson("/benchmark/tradeoff?days=30&limit=200"),
    ]);
    const latest = latestRes.ok ? (latestRes.data.results || []) : [];
    const history = historyRes.ok ? (historyRes.data.results || []) : [];
    const summary = historyRes.ok ? (historyRes.data.summary || {}) : {};
    const tradeoff = tradeoffRes.ok ? (tradeoffRes.data.entries || []) : [];

    latestEl.innerHTML = latest.length
      ? latest.slice(0, 25).map((r) => `<tr><td>${esc(r.provider || "")}</td><td>${esc(r.model || "")}</td><td>${esc(r.probe || r.task_type || "chat")}</td><td>${r.ok ? "ok" : "fail"}</td><td>${r.latency_ms != null ? Number(r.latency_ms).toFixed(1) : "-"}</td></tr>`).join("")
      : '<tr><td colspan="5" style="color:var(--muted)">No benchmark results yet.</td></tr>';

    historyEl.innerHTML = history.length
      ? history.slice(0, 60).map((r) => `<tr><td>${esc(r.provider || "")}</td><td>${esc(r.model || "")}</td><td>${esc(r.task_type || "chat")}</td><td>${Number(r.quality_score || 0).toFixed(3)}</td><td>${Number(r.latency_ms || 0).toFixed(1)}</td></tr>`).join("")
      : '<tr><td colspan="5" style="color:var(--muted)">No benchmark history yet.</td></tr>';

    tradeoffEl.innerHTML = tradeoff.length
      ? tradeoff.slice(0, 80).map((r) => `<tr><td>${esc(r.provider || "")}</td><td>${esc(r.model || "")}</td><td>${Number(r.avg_quality || 0).toFixed(3)}</td><td>${Number(r.cost_per_1k_tokens || 0).toFixed(5)}</td><td>${Number(r.avg_latency_ms || 0).toFixed(1)}</td><td>${Number(r.value_score || 0).toFixed(4)}</td></tr>`).join("")
      : '<tr><td colspan="6" style="color:var(--muted)">No tradeoff data yet.</td></tr>';

    status.textContent = `Latest ${latest.length} · History ${history.length} · Tradeoff ${tradeoff.length} · Avg ${Number(summary.avg_latency_ms || 0).toFixed(1)} ms · Trend ${summary.trend || "stable"}`;
  } catch (err) {
    status.textContent = "Load failed";
    latestEl.innerHTML = `<tr><td colspan="5" style="color:var(--red)">${esc(String(err))}</td></tr>`;
    historyEl.innerHTML = '<tr><td colspan="5" style="color:var(--muted)">-</td></tr>';
    tradeoffEl.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">-</td></tr>';
  }
}
