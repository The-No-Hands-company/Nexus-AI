// Hypothesis panel module (static split from index.html)
function openHypothesisPanel() {
  NexusApi.setPanelOpen("hypothesis-panel", true);
}

function closeHypothesisPanel() {
  NexusApi.setPanelOpen("hypothesis-panel", false);
}

async function runHypothesis() {
  const obs = document.getElementById("hypothesis-obs").value.trim();
  const maxH = parseInt(document.getElementById("hypothesis-max").value || "4", 10);
  const status = document.getElementById("hypothesis-status");
  const out = document.getElementById("hypothesis-output");
  if (!obs) {
    status.textContent = "❌ Enter an observation.";
    return;
  }
  status.textContent = `Generating & testing up to ${maxH} hypotheses...`;
  out.innerHTML = "";
  try {
    const { data: d } = await NexusApi.apiJson("/reason/hypothesis", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ observation: obs, max_hypotheses: maxH }),
    });
    if (d.error || d.detail) {
      status.textContent = `❌ ${d.error || d.detail}`;
      return;
    }
    const n = (d.hypotheses_tested || []).length;
    status.textContent = `✓ ${n} hypotheses tested · conf ${(d.overall_confidence * 100).toFixed(0)}%`;

    let html = `<div style="margin-bottom:12px;padding:10px;background:var(--surface2);border-radius:8px;">
      <b style="font-size:.85rem;">🎯 Conclusion</b>
      <div style="margin-top:6px;font-size:.82rem;color:var(--text);">${d.conclusion || ""}</div>
      ${d.uncertainty ? `<div style="margin-top:4px;font-size:.76rem;color:var(--muted);">Uncertainty: ${d.uncertainty}</div>` : ""}
    </div>`;

    (d.hypotheses_tested || []).forEach((h) => {
      const verdictColor = h.verdict === "accept" ? "#4ade80" : h.verdict === "reject" ? "#f87171" : "#facc15";
      html += `<details style="margin-bottom:8px;"><summary style="cursor:pointer;font-size:.78rem;font-weight:700;color:var(--muted);">
        H${h.id}: ${h.statement || ""} — <span style="color:${verdictColor}">${String(h.verdict || "").toUpperCase()}</span> (${(h.confidence * 100).toFixed(0)}%)</summary>
        <div style="margin-top:6px;padding:8px;background:var(--surface2);border-radius:6px;font-size:.78rem;">
          ${h.evidence_for?.length ? `<div style="color:#4ade80;">For: ${h.evidence_for.join("; ")}</div>` : ""}
          ${h.evidence_against?.length ? `<div style="color:#f87171;margin-top:4px;">Against: ${h.evidence_against.join("; ")}</div>` : ""}
          ${h.explanation ? `<div style="margin-top:4px;color:var(--text);">${h.explanation}</div>` : ""}
        </div></details>`;
    });

    if (d.next_steps?.length) {
      html += `<div style="margin-top:8px;font-size:.76rem;color:var(--muted);">Next steps: ${d.next_steps.join(" · ")}</div>`;
    }
    out.innerHTML = html;
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
  }
}
