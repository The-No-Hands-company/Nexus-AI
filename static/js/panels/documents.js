// Documents panel module (static split from index.html)
function openDocumentsPanel() {
  NexusApi.setPanelOpen("documents-panel", true);
}

function closeDocumentsPanel() {
  NexusApi.setPanelOpen("documents-panel", false);
}

async function runDocumentUnderstand() {
  const path = document.getElementById("doc-path").value.trim();
  const question = document.getElementById("doc-question").value.trim() || "Summarise this document.";
  const ftype = document.getElementById("doc-type").value;
  const status = document.getElementById("doc-status");
  const out = document.getElementById("doc-output");
  if (!path) {
    status.textContent = "❌ Enter a file path.";
    return;
  }
  status.textContent = "Processing...";
  out.innerHTML = "";
  try {
    const body = { path, question };
    if (ftype) body.file_type = ftype;
    const { data: d } = await NexusApi.apiJson("/documents/understand", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (d.error) {
      status.textContent = `❌ ${d.error}`;
      return;
    }
    status.textContent = `✓ ${d.type || "?"} · ${d.excerpt_chars} chars · ${d.provider}`;
    out.innerHTML = `<div style="margin-bottom:8px;font-size:.75rem;color:var(--muted);">Q: ${d.question}</div>` +
      `<div style="font-size:.84rem;color:var(--text);white-space:pre-wrap;">${d.answer}</div>`;
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
  }
}

async function runDocumentIngest() {
  const path = document.getElementById("doc-path").value.trim();
  const ftype = document.getElementById("doc-type").value;
  const status = document.getElementById("doc-status");
  const out = document.getElementById("doc-output");
  if (!path) {
    status.textContent = "❌ Enter a file path.";
    return;
  }
  status.textContent = "Ingesting...";
  out.innerHTML = "";
  try {
    const body = { path };
    if (ftype) body.file_type = ftype;
    const { data: d } = await NexusApi.apiJson("/documents/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (d.error) {
      status.textContent = `❌ ${d.error}`;
      return;
    }
    status.textContent = `✓ Ingested ${d.ingested_chunks} chunk(s)`;
    out.innerHTML = `<div style="font-size:.82rem;color:var(--text);">Document <b>${d.filename}</b> (${d.type}) ingested as ${d.ingested_chunks} RAG chunks.</div>`;
  } catch (e) {
    status.textContent = `❌ ${e.message}`;
  }
}
