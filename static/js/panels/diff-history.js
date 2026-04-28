// Diff viewer and history panel module (static split from index.html)
function openDiffViewer() {
  NexusApi.setPanelOpen("diff-viewer-panel", true);
}

function closeDiffViewer() {
  NexusApi.setPanelOpen("diff-viewer-panel", false);
}

async function runDiffViewer() {
  const original = document.getElementById("diff-original").value;
  const modified = document.getElementById("diff-modified").value;
  const filename = document.getElementById("diff-filename").value.trim() || "file";
  const traceId = document.getElementById("diff-trace-id").value.trim();
  const out = document.getElementById("diff-output");
  const stats = document.getElementById("diff-stats");
  out.textContent = "Computing...";
  stats.textContent = "";
  try {
    const body = { original, modified, filename };
    if (traceId) body.trace_id = traceId;
    const r = await fetch("/diff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!d.has_changes) {
      out.textContent = "No differences found.";
      stats.textContent = "";
      return;
    }
    stats.textContent = `+${d.additions} -${d.deletions} in ${d.chunks} chunk(s)`;
    const html = d.unified_diff.split("\n").map((line) => {
      const escaped = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
      if (line.startsWith("+++") || line.startsWith("---")) return `<span style="color:var(--muted)">${escaped}</span>`;
      if (line.startsWith("+")) return `<span style="color:#4caf50;background:rgba(76,175,80,.12)">${escaped}</span>`;
      if (line.startsWith("-")) return `<span style="color:#f44336;background:rgba(244,67,54,.12)">${escaped}</span>`;
      if (line.startsWith("@@")) return `<span style="color:#2196f3">${escaped}</span>`;
      return escaped;
    }).join("\n");
    out.innerHTML = html;
    if (traceId && d.saved) stats.textContent += " · saved";
  } catch (e) {
    out.textContent = `Error: ${e.message}`;
  }
}

async function loadDiffHistory() {
  const traceId = document.getElementById("diff-trace-id").value.trim();
  const out = document.getElementById("diff-output");
  out.textContent = "Loading...";
  try {
    const url = "/diff/history" + (traceId ? `?trace_id=${encodeURIComponent(traceId)}&limit=20` : "?limit=20");
    const r = await fetch(url);
    const d = await r.json();
    if (!d.diffs || !d.diffs.length) {
      out.textContent = "No diff history found.";
      return;
    }
    out.innerHTML = d.diffs.map((df) =>
      `<div style="border-bottom:1px solid var(--border);padding:6px 0;font-size:.75rem;">
        <b>${df.file_path || "?"}</b>
        <span style="color:#4caf50;margin-left:8px;">+${df.additions}</span>
        <span style="color:#f44336;margin-left:4px;">-${df.deletions}</span>
        <span style="color:var(--muted);margin-left:8px;">${(df.created_at || "").slice(0, 19)}</span>
        ${df.trace_id ? `<span style="color:var(--muted);margin-left:8px;">trace:${df.trace_id}</span>` : ""}
        <button onclick="loadDiffDetail(${df.id})" style="float:right;background:none;border:none;color:var(--accent);cursor:pointer;font-size:.75rem;">view</button>
      </div>`).join("");
  } catch (e) {
    out.textContent = `Error: ${e.message}`;
  }
}

async function loadDiffDetail(id) {
  const out = document.getElementById("diff-output");
  out.textContent = "Loading...";
  try {
    const r = await fetch(`/diff/${id}`);
    const d = await r.json();
    if (d.error) {
      out.textContent = d.error;
      return;
    }
    document.getElementById("diff-original").value = d.before_text || "";
    document.getElementById("diff-modified").value = d.after_text || "";
    document.getElementById("diff-filename").value = d.file_path || "file";
    await runDiffViewer();
  } catch (e) {
    out.textContent = `Error: ${e.message}`;
  }
}