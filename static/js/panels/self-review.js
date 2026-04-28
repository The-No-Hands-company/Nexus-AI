// Self-review panel module (static split from index.html)
function openSelfReviewPanel() {
  NexusApi.setPanelOpen("self-review-panel", true);
  loadSelfReviewHistory();
}

function closeSelfReviewPanel() {
  NexusApi.setPanelOpen("self-review-panel", false);
}

async function runSelfReview() {
  const limit = parseInt(document.getElementById("sr-limit").value, 10) || 20;
  const loading = document.getElementById("sr-loading");
  const out = document.getElementById("sr-output");
  loading.style.display = "block";
  out.innerHTML = "";
  try {
    const r = await fetch("/agent/self-review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ limit }),
    });
    const d = await r.json();
    loading.style.display = "none";
    if (d.message && !d.insights.length) {
      out.textContent = d.message;
      return;
    }
    let html = `<div style="font-size:.75rem;color:var(--muted);margin-bottom:10px;">Analyzed ${d.traces_analyzed} traces · provider: ${d.provider}</div>`;
    if (d.insights && d.insights.length) {
      html += '<div style="font-weight:700;font-size:.8rem;margin-bottom:6px;color:var(--text);">Insights</div>';
      html += d.insights.map((i) => `<div style="font-size:.8rem;padding:5px 0;border-bottom:1px solid var(--border);color:var(--text);">• ${i}</div>`).join("");
    }
    if (d.suggestions && d.suggestions.length) {
      html += '<div style="font-weight:700;font-size:.8rem;margin:12px 0 6px;color:var(--text);">Suggestions</div>';
      html += d.suggestions.map((s, i) => `<div style="font-size:.8rem;padding:5px 0;border-bottom:1px solid var(--border);color:var(--text);">${i + 1}. ${s}</div>`).join("");
    }
    out.innerHTML = html;
  } catch (e) {
    loading.style.display = "none";
    out.textContent = `Error: ${e.message}`;
  }
}

async function loadSelfReviewHistory() {
  const out = document.getElementById("sr-output");
  try {
    const r = await fetch("/agent/self-review/history?limit=5");
    const d = await r.json();
    if (!d.reviews || !d.reviews.length) return;
    out.innerHTML = `<div style="font-size:.73rem;color:var(--muted);margin-bottom:8px;">Past ${d.reviews.length} review(s)</div>` +
      d.reviews.map((rv) => `
        <div style="border:1px solid var(--border);border-radius:8px;padding:8px 10px;margin-bottom:8px;">
          <div style="font-size:.73rem;color:var(--muted);">${(rv.created_at || "").slice(0, 19)} · ${rv.traces_analyzed} traces</div>
          ${rv.suggestions.slice(0, 2).map((s) => `<div style="font-size:.78rem;padding-top:4px;">• ${s}</div>`).join("")}
        </div>`).join("");
  } catch (_) {
    // Keep panel silent on transient history fetch issues.
  }
}