function openRagCorpusPanel() {
  NexusApi.setPanelOpen("rag-corpus-panel", true);
  loadRagCorpus();
}

function closeRagCorpusPanel() {
  NexusApi.setPanelOpen("rag-corpus-panel", false);
}

async function loadRagCorpus() {
  const status = document.getElementById("rc-status");
  const rowsEl = document.getElementById("rc-rows");
  const q = (document.getElementById("rc-query")?.value || "").trim();
  if (!status || !rowsEl) return;

  status.textContent = "Loading...";
  try {
    const params = new URLSearchParams({ limit: "300" });
    if (q) params.set("q", q);
    const { ok, data } = await NexusApi.apiJson(`/rag/documents?${params.toString()}`);
    if (!ok) {
      rowsEl.innerHTML = `<tr><td colspan="5" style="color:var(--red)">${esc(data?.error || "Failed to load corpus")}</td></tr>`;
      status.textContent = "Load failed";
      return;
    }
    const items = data.items || [];
    rowsEl.innerHTML = items.length
      ? items.map((d) => {
          const meta = d.metadata || {};
          return `<tr>
            <td style="max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(d.id || "")}</td>
            <td>${esc(meta.title || meta.source || "")}</td>
            <td style="max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(d.preview || "")}</td>
            <td>${esc(meta.org_id || "-")}</td>
            <td><button class="btn-ghost" style="height:28px;font-size:.74rem" onclick="deleteRagDocument('${encodeURIComponent(String(d.id || ''))}')">Delete</button></td>
          </tr>`;
        }).join("")
      : '<tr><td colspan="5" style="color:var(--muted)">No corpus documents found.</td></tr>';
    status.textContent = `${items.length} documents`;
  } catch (err) {
    status.textContent = "Load failed";
    rowsEl.innerHTML = `<tr><td colspan="5" style="color:var(--red)">${esc(String(err))}</td></tr>`;
  }
}

async function deleteRagDocument(encodedId) {
  const id = decodeURIComponent(encodedId || "");
  if (!id) return;
  if (!confirm(`Delete RAG document ${id}?`)) return;
  try {
    await NexusApi.apiJson(`/rag/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
  } catch (_) {
    // best effort; reload handles error display
  }
  await loadRagCorpus();
}
