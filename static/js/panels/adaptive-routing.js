// Adaptive routing panel module (static split from index.html)
function openAdaptiveRoutingPanel() {
  NexusApi.setPanelOpen("adaptive-routing-panel", true);
  loadAdaptiveRouting();
}

function closeAdaptiveRoutingPanel() {
  NexusApi.setPanelOpen("adaptive-routing-panel", false);
}

async function loadAdaptiveRouting() {
  const status = document.getElementById("ar-status");
  try {
    const { data: d } = await NexusApi.apiJson("/settings/adaptive-routing");
    document.getElementById("ar-enabled").checked = d.enabled !== false;
    document.getElementById("ar-threshold").value = d.confidence_threshold ?? 0.6;
    document.getElementById("ar-tries").value = d.escalation_tries ?? 2;
    status.textContent = "Loaded.";
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
  }
}

async function saveAdaptiveRouting() {
  const status = document.getElementById("ar-status");
  const body = {
    enabled: document.getElementById("ar-enabled").checked,
    confidence_threshold: parseFloat(document.getElementById("ar-threshold").value),
    escalation_tries: parseInt(document.getElementById("ar-tries").value, 10),
  };
  try {
    const { data: d } = await NexusApi.apiJson("/settings/adaptive-routing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (d.error) {
      status.textContent = `❌ ${d.error}`;
      return;
    }
    status.textContent = `✓ Saved — threshold ${d.confidence_threshold}, tries ${d.escalation_tries}`;
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
  }
}
