// Job Queue & Dead-Letter Panel — monitor background tasks and retry failures
let _jqTimer = null;
let _jqTab = "active";  // active | dlq

function openJobQueuePanel() {
  NexusApi.setPanelOpen("job-queue-panel", true);
  refreshJobQueue();
  if (_jqTimer) clearInterval(_jqTimer);
  _jqTimer = setInterval(refreshJobQueue, 5000);
}

function closeJobQueuePanel() {
  NexusApi.setPanelOpen("job-queue-panel", false);
  if (_jqTimer) { clearInterval(_jqTimer); _jqTimer = null; }
}

async function refreshJobQueue() {
  await Promise.all([refreshActiveJobs(), refreshDLQ()]);
}

async function refreshActiveJobs() {
  const feed = document.getElementById("jq-active-feed");
  try {
    const r = await fetch("/tasks?limit=50");
    const d = await r.json();
    const tasks = d.tasks || d || [];
    if (!tasks.length) {
      feed.innerHTML = '<div style="color:var(--muted);font-size:.75rem;padding:6px 4px">No tasks in queue.</div>';
      return;
    }
    feed.innerHTML = tasks.map(t => {
      const statusColor = t.status === "done" ? "var(--green)" : t.status === "failed" ? "var(--red)" : t.status === "running" ? "var(--blue)" : "var(--yellow)";
      return `<div style="border:1px solid var(--border);border-radius:8px;padding:8px 9px;margin-bottom:6px;background:var(--surface2)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span style="font-size:.72rem;color:var(--muted)">${esc_s(t.task_id?.substring(0,14) || "")}…</span>
          <span style="font-size:.7rem;color:${statusColor};font-weight:600">${esc_s(t.status)}</span>
        </div>
        <div style="font-size:.75rem;margin-bottom:2px">${esc_s((t.description || "").substring(0, 100))}</div>
        <div style="font-size:.66rem;color:var(--muted);display:flex;justify-content:space-between">
          <span>Priority: ${t.priority || "-"}</span>
          <span>${esc_s(t.created_at || "")}</span>
        </div>
        ${t.error ? `<div style="font-size:.66rem;color:var(--red);margin-top:4px">${esc_s(t.error.substring(0,120))}</div>` : ""}
      </div>`;
    }).join("");
  } catch (_) {
    feed.innerHTML = '<div style="color:var(--red);font-size:.75rem;padding:6px 4px">Failed to load tasks.</div>';
  }
}

async function refreshDLQ() {
  const feed = document.getElementById("jq-dlq-feed");
  const badge = document.getElementById("jq-dlq-badge");
  try {
    const r = await fetch("/jobs/dlq");
    const d = await r.json();
    const items = d.entries || [];
    if (badge) {
      badge.textContent = items.length;
      badge.style.display = items.length > 0 ? "" : "none";
    }
    if (!items.length) {
      feed.innerHTML = '<div style="color:var(--muted);font-size:.75rem;padding:6px 4px">Dead-letter queue is empty.</div>';
      return;
    }
    feed.innerHTML = items.map(e => `<div style="border:1px solid var(--red);border-radius:8px;padding:8px 9px;margin-bottom:6px;background:var(--surface2)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <span style="font-size:.72rem;color:var(--muted)">${esc_s(e.id?.substring(0,14) || "")}…</span>
        <span style="font-size:.7rem;color:var(--red);font-weight:600">Retries: ${e.retry_count}/${e.max_retries}</span>
      </div>
      <div style="font-size:.75rem;margin-bottom:2px">${esc_s((e.description || "").substring(0,100))}</div>
      <div style="font-size:.66rem;color:var(--red);margin-bottom:4px">${esc_s((e.error || "").substring(0,120))}</div>
      <div style="display:flex;gap:6px;justify-content:flex-end">
        <button class="panel-btn" style="background:var(--yellow);color:#000" onclick="retryDLQEntry('${e.id}')">Retry</button>
        <button class="panel-btn" style="background:var(--red);color:#fff" onclick="deleteDLQEntry('${e.id}')">Delete</button>
      </div>
    </div>`).join("");
  } catch (_) {
    feed.innerHTML = '<div style="color:var(--red);font-size:.75rem;padding:6px 4px">Failed to load DLQ.</div>';
  }
}

async function retryDLQEntry(id) {
  try {
    await fetch(`/jobs/dlq/${id}/retry`, { method: "POST" });
    refreshJobQueue();
  } catch (e) {
    alert("Retry failed: " + e.message);
  }
}

async function deleteDLQEntry(id) {
  try {
    await fetch(`/jobs/dlq/${id}`, { method: "DELETE" });
    refreshJobQueue();
  } catch (e) {
    alert("Delete failed: " + e.message);
  }
}

async function purgeDLQ() {
  if (!confirm("Delete ALL dead-letter entries?")) return;
  try {
    await fetch("/jobs/dlq", { method: "DELETE" });
    refreshJobQueue();
  } catch (e) {
    alert("Purge failed: " + e.message);
  }
}

function switchJQTab(tab) {
  _jqTab = tab;
  document.getElementById("jq-active-tab").style.background = tab === "active" ? "var(--blue)" : "var(--surface2)";
  document.getElementById("jq-dlq-tab").style.background = tab === "dlq" ? "var(--red)" : "var(--surface2)";
  document.getElementById("jq-active-section").style.display = tab === "active" ? "" : "none";
  document.getElementById("jq-dlq-section").style.display = tab === "dlq" ? "" : "none";
}

function esc_s(s) { return String(s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
