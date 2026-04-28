// Debate panel module (static split from index.html)
function openDebatePanel() {
  NexusApi.setPanelOpen("debate-panel", true);
}

function closeDebatePanel() {
  NexusApi.setPanelOpen("debate-panel", false);
}

async function runDebate() {
  const claim = document.getElementById("debate-claim").value.trim();
  const rounds = parseInt(document.getElementById("debate-rounds").value || "2", 10);
  const status = document.getElementById("debate-status");
  const out = document.getElementById("debate-output");
  if (!claim) {
    status.textContent = "❌ Enter a claim.";
    return;
  }
  status.textContent = `Running ${rounds} round(s)...`;
  out.innerHTML = "";
  try {
    const { data: d } = await NexusApi.apiJson("/reason/debate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ claim, rounds }),
    });
    if (d.error || d.detail) {
      status.textContent = `❌ ${d.error || d.detail}`;
      return;
    }
    status.textContent = `✓ ${rounds} round(s) complete · verdict: ${d.verdict} (conf ${(d.confidence * 100).toFixed(0)}%)`;

    let html = `<div style="margin-bottom:12px;padding:10px;background:var(--surface2);border-radius:8px;">
      <b style="font-size:.85rem;">⚖️ Verdict: <span style="color:${d.verdict === "supported" ? "#4ade80" : d.verdict === "refuted" ? "#f87171" : "#facc15"}">${String(d.verdict || "").toUpperCase()}</span></b>
      <div style="margin-top:6px;font-size:.82rem;color:var(--text);">${d.synthesis || ""}</div>
    </div>`;

    (d.transcript || []).forEach((rnd) => {
      html += `<details style="margin-bottom:8px;"><summary style="cursor:pointer;font-size:.78rem;font-weight:700;color:var(--muted);">Round ${rnd.round}</summary>
        <div style="margin-top:6px;padding:8px;background:var(--surface2);border-radius:6px;font-size:.8rem;">
          <div style="color:#4ade80;margin-bottom:4px;">✅ Proponent: ${rnd.proponent || ""}</div>
          <div style="color:#f87171;margin-top:6px;">🔴 Critic: ${rnd.critic || ""}</div>
        </div></details>`;
    });

    html += `<div style="margin-top:8px;font-size:.76rem;color:var(--muted);">
      Strongest FOR: ${d.strongest_proponent_point || ""}<br>
      Strongest AGAINST: ${d.strongest_critic_point || ""}
    </div>`;
    out.innerHTML = html;
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
  }
}
