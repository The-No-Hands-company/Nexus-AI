// Ensemble panel module (static split from index.html)
async function openEnsemblePanel() {
  NexusApi.setPanelOpen("ensemble-panel", true);
  try {
    const r = await fetch("/settings/ensemble");
    const d = await r.json();
    document.getElementById("ens-toggle").checked = !!d.ensemble_mode;
    const thr = parseFloat(d.ensemble_threshold || 0.4);
    document.getElementById("ens-threshold").value = thr;
    document.getElementById("ens-thr-val").textContent = thr.toFixed(2);
    document.getElementById("ens-status").textContent = d.ensemble_mode ? "🟢 Ensemble active" : "⚪ Ensemble disabled";
  } catch (_) {
    document.getElementById("ens-status").textContent = "Could not load settings";
  }
}

function closeEnsemblePanel() {
  NexusApi.setPanelOpen("ensemble-panel", false);
}

async function saveEnsembleSettings() {
  const mode = document.getElementById("ens-toggle").checked;
  const threshold = parseFloat(document.getElementById("ens-threshold").value);
  try {
    const r = await fetch("/settings/ensemble", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ensemble_mode: mode, ensemble_threshold: threshold }),
    });
    const d = await r.json();
    document.getElementById("ens-status").textContent = d.ensemble_mode ? "🟢 Ensemble active" : "⚪ Ensemble disabled";
  } catch (_) {
    document.getElementById("ens-status").textContent = "Save failed";
  }
}
