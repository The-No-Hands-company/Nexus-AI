function openFinetuneDashboardPanel() {
  NexusApi.setPanelOpen("finetune-dashboard-panel", true);
  loadFinetuneDashboard();
}

function closeFinetuneDashboardPanel() {
  NexusApi.setPanelOpen("finetune-dashboard-panel", false);
}

async function loadFinetuneDashboard() {
  const status = document.getElementById("ft-status");
  const rowsEl = document.getElementById("ft-rows");
  const filter = (document.getElementById("ft-filter")?.value || "").trim();
  if (!status || !rowsEl) return;

  status.textContent = "Loading...";
  const q = new URLSearchParams({ limit: "200" });
  if (filter) q.set("status", filter);

  try {
    const { ok, data } = await NexusApi.apiJson(`/finetune/jobs?${q.toString()}`);
    if (!ok) {
      rowsEl.innerHTML = `<tr><td colspan="6" style="color:var(--red)">${esc(data?.error || "Failed to load jobs")}</td></tr>`;
      status.textContent = "Load failed";
      return;
    }
    const items = data.items || [];
    rowsEl.innerHTML = items.length
      ? items.map((j) => `<tr><td>${esc(j.id || "")}</td><td>${esc(j.status || "")}</td><td>${esc(j.model || "")}</td><td>${esc(j.training_file || "")}</td><td>${j.created_at || ""}</td><td>${j.finished_at || ""}</td></tr>`).join("")
      : '<tr><td colspan="6" style="color:var(--muted)">No fine-tune jobs found.</td></tr>';
    status.textContent = `${items.length} jobs`;
  } catch (err) {
    status.textContent = "Load failed";
    rowsEl.innerHTML = `<tr><td colspan="6" style="color:var(--red)">${esc(String(err))}</td></tr>`;
  }
}
