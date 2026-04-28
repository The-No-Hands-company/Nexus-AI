// Scheduler panel module (static split from index.html)
let _schedulerTimer = null;

function openSchedulerPanel() {
  NexusApi.setPanelOpen("scheduler-panel", true);
  refreshSchedulerJobs();
  if (_schedulerTimer) clearInterval(_schedulerTimer);
  _schedulerTimer = setInterval(refreshSchedulerJobs, 4000);
}

function closeSchedulerPanel() {
  NexusApi.setPanelOpen("scheduler-panel", false);
  if (_schedulerTimer) {
    clearInterval(_schedulerTimer);
    _schedulerTimer = null;
  }
}

async function refreshSchedulerJobs() {
  const feed = document.getElementById("scheduler-feed");
  try {
    const r = await fetch("/scheduler/jobs");
    const d = await r.json();
    const jobs = d.jobs || [];
    if (!jobs.length) {
      feed.innerHTML = '<div style="color:var(--muted);font-size:.75rem;padding:6px 4px">No scheduled jobs yet.</div>';
      return;
    }
    feed.innerHTML = jobs.map((j) => `
      <div style="border:1px solid var(--border);border-radius:8px;padding:8px 9px;background:var(--surface2)">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:4px">
          <strong style="font-size:.78rem">${esc(j.name)}</strong>
          <span style="font-size:.66rem;color:var(--muted)">${esc(j.status)}</span>
        </div>
        <div style="font-size:.7rem;color:var(--muted);margin-bottom:2px">${esc(j.task || "")}</div>
        <div style="font-size:.68rem;color:var(--muted);display:flex;justify-content:space-between;gap:8px">
          <span>Every: ${esc(j.schedule || "-")}</span>
          <span>Runs: ${j.run_count || 0}</span>
        </div>
        <div style="margin-top:6px;text-align:right">
          <button class="panel-btn" onclick="cancelSchedulerJob('${j.id}')">Cancel</button>
        </div>
      </div>
    `).join("");
  } catch (_) {
    feed.innerHTML = '<div style="color:var(--red);font-size:.75rem;padding:6px 4px">Failed to load jobs.</div>';
  }
}

async function createSchedulerJob() {
  const task = document.getElementById("sch-task").value.trim();
  const schedule = document.getElementById("sch-schedule").value.trim() || "5m";
  const name = document.getElementById("sch-name").value.trim() || "background-task";
  if (!task) {
    alert("Task is required");
    return;
  }
  const r = await fetch("/scheduler/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, task, schedule }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({ error: "Failed to create job" }));
    alert(d.error || "Failed to create job");
    return;
  }
  document.getElementById("sch-task").value = "";
  document.getElementById("sch-name").value = "";
  await refreshSchedulerJobs();
}

async function cancelSchedulerJob(jobId) {
  await fetch(`/scheduler/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  await refreshSchedulerJobs();
}
