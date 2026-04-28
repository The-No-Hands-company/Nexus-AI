// ── SOURCE CARDS ──────────────────────────────────────────────────────────────
function renderSourceCards(sources) {
  if (!sources?.length) return '';
  const cards = sources.map((s, i) => `
    <a class="source-card" href="${esc(s.url)}" target="_blank" rel="noopener">
      <img class="source-favicon"
           src="https://www.google.com/s2/favicons?domain=${esc(s.domain)}&sz=16"
           onerror="this.style.display='none'" alt="">
      <div class="source-info">
        <div class="source-domain">${esc(s.domain)}</div>
        <div class="source-title">${esc(s.title)}</div>
        <div class="source-snippet">${esc(s.snippet)}</div>
      </div>
      <div class="source-num">[${i+1}]</div>
    </a>`).join('');
  return `<div class="search-sources">${cards}</div>`;
}

// Extract sources JSON from web_search results
function extractSources(toolResult) {
  const m = toolResult.match(/\[SOURCES_JSON\](.*?)\[\/SOURCES_JSON\]/s);
  if (!m) return null;
  try { return JSON.parse(m[1]); } catch { return null; }
}
