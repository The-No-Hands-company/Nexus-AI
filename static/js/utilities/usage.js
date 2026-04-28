// ── USAGE DASHBOARD ───────────────────────────────────────────────────────────
async function openUsageModal() {
  document.getElementById('usage-modal').classList.add('open');
  await loadUsageStats();
}
function closeUsageModal() { document.getElementById('usage-modal').classList.remove('open'); }

async function loadUsageStats() {
  const days = document.getElementById('usage-days')?.value || 7;
  const body = document.getElementById('usage-modal-body');
  body.innerHTML = '<div style="color:var(--muted);font-size:.8rem">Loading…</div>';
  const d = await fetch(`/usage?days=${days}`).then(r=>r.json()).catch(()=>null);
  if (!d || d.error) { body.innerHTML = '<div style="color:var(--muted)">No usage data yet.</div>'; return; }

  const stats = d.stats || {};
  const total = stats.total || {};
  const byProv = stats.by_provider || [];
  const daily  = d.daily || [];
  const maxCalls = Math.max(1, ...byProv.map(p=>p.calls));
  const maxDaily = Math.max(1, ...daily.map(d=>d.calls));

  // Summary stats
  let html = `<div class="usage-grid">
    <div class="usage-stat"><div class="usage-stat-val">${total.calls||0}</div><div class="usage-stat-lbl">Total requests</div></div>
    <div class="usage-stat"><div class="usage-stat-val">${fmtNum(total.in_tok||0)}</div><div class="usage-stat-lbl">~Input tokens</div></div>
    <div class="usage-stat"><div class="usage-stat-val">${fmtNum(total.out_tok||0)}</div><div class="usage-stat-lbl">~Output tokens</div></div>
    <div class="usage-stat"><div class="usage-stat-val">${byProv.length}</div><div class="usage-stat-lbl">Providers used</div></div>
  </div>`;

  // By provider
  if (byProv.length) {
    html += '<div style="font-size:.7rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">By Provider</div>';
    byProv.forEach(p => {
      const pct  = Math.round(p.calls / maxCalls * 100);
      const cost = p.est_cost_usd > 0 ? ` · $${p.est_cost_usd.toFixed(4)}` : ' · free';
      html += `<div class="usage-bar-row">
        <div class="usage-bar-label">${esc(p.provider)}</div>
        <div class="usage-bar-track"><div class="usage-bar-fill" style="width:${pct}%"></div></div>
        <div class="usage-bar-val">${p.calls} req${cost}</div>
      </div>`;
    });
    if (stats.total_est_cost_usd !== undefined) {
      html += `<div style="font-size:.7rem;color:var(--muted);text-align:right;margin-top:6px">
        Total estimated cost: <strong style="color:var(--text)">$${(stats.total_est_cost_usd||0).toFixed(4)}</strong>
      </div>`;
    }
  }

  // Daily chart
  if (daily.length > 1) {
    html += '<div style="font-size:.7rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:14px;margin-bottom:4px">Daily requests</div>';
    html += '<div class="usage-day-chart">';
    daily.forEach(d => {
      const h = Math.max(4, Math.round(d.calls / maxDaily * 56));
      html += `<div class="usage-day-bar" style="height:${h}px" title="${d.day}: ${d.calls} req"></div>`;
    });
    const d0 = daily[0]?.day||""; const dN = daily[daily.length-1]?.day||"";
    html += `</div><div style="display:flex;justify-content:space-between;font-size:.62rem;color:var(--muted);margin-top:3px"><span>${d0}</span><span>${dN}</span></div>`;
  }

  body.innerHTML = html;
}

function fmtNum(n) {
  if (n >= 1000000) return (n/1000000).toFixed(1)+'M';
  if (n >= 1000)    return (n/1000).toFixed(1)+'K';
  return n;
}
