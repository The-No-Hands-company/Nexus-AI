// Benchmark leaderboard UI panel
function openBenchmarkLeaderboardPanel() {
  NexusApi.setPanelOpen("benchmark-leaderboard-panel", true);
  loadBenchmarkLeaderboard();
}

function closeBenchmarkLeaderboardPanel() {
  NexusApi.setPanelOpen("benchmark-leaderboard-panel", false);
}

function _blFmtNum(v, digits) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return n.toFixed(digits);
}

function _blFmtPct(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return `${(n * 100).toFixed(1)}%`;
}

async function loadBenchmarkLeaderboard() {
  const sortBy = (document.getElementById("bl-sort")?.value || "task_type").trim();
  const provider = (document.getElementById("bl-provider")?.value || "").trim();
  const limitRaw = Number(document.getElementById("bl-limit")?.value || 20);
  const limit = Number.isFinite(limitRaw) ? Math.min(200, Math.max(1, Math.floor(limitRaw))) : 20;

  const status = document.getElementById("bl-status");
  const body = document.getElementById("bl-body");
  if (!body) return;

  status.textContent = "Loading...";
  body.innerHTML = '<tr><td colspan="11" style="padding:10px;border:1px solid var(--border);color:var(--muted);">Loading leaderboard...</td></tr>';

  const params = new URLSearchParams({ sort_by: sortBy, limit: String(limit) });
  if (provider) params.set("provider", provider);

  try {
    const { ok, data } = await NexusApi.apiJson(`/benchmark/leaderboard?${params.toString()}`);
    if (!ok) {
      const msg = data?.error || "Failed to load leaderboard";
      body.innerHTML = `<tr><td colspan="11" style="padding:10px;border:1px solid var(--border);color:var(--red);">${esc(msg)}</td></tr>`;
      status.textContent = "Load failed";
      return;
    }

    const entries = Array.isArray(data?.entries) ? data.entries : [];
    if (!entries.length) {
      body.innerHTML = '<tr><td colspan="11" style="padding:10px;border:1px solid var(--border);color:var(--muted);">No benchmark entries yet.</td></tr>';
      status.textContent = "0 entries";
      return;
    }

    body.innerHTML = entries.map((e, idx) => `
      <tr>
        <td style="padding:7px 8px;border:1px solid var(--border);">${idx + 1}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(e.model)}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);">${esc(e.provider)}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);">${esc(e.task_type)}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);text-align:right;">${_blFmtNum(e.quality_score, 3)}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);text-align:right;">${_blFmtPct(e.approval_rate)}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);text-align:right;">${_blFmtNum(e.avg_latency_ms, 1)}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);text-align:right;">${_blFmtNum(e.p95_latency_ms, 1)}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);text-align:right;">${_blFmtPct(e.safety_pass_rate)}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);text-align:right;">${_blFmtNum(e.cost_per_1k_tokens, 4)}</td>
        <td style="padding:7px 8px;border:1px solid var(--border);text-align:right;">${Number(e.total_requests || 0)}</td>
      </tr>
    `).join("");

    status.textContent = `${entries.length} entries`;
  } catch (err) {
    body.innerHTML = `<tr><td colspan="11" style="padding:10px;border:1px solid var(--border);color:var(--red);">${esc(String(err))}</td></tr>`;
    status.textContent = "Load failed";
  }
}
