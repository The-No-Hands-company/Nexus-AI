// Search and command palette utilities split from index.html
function toggleSearch() {
  const wrap = document.getElementById("search-wrap");
  wrap.classList.toggle("open");
  if (wrap.classList.contains("open")) {
    if (!sidebarOpen) toggleSidebar();
    document.getElementById("search-input").focus();
  }
}

let _searchTimer = null;
async function searchChats(q) {
  clearTimeout(_searchTimer);
  const resultsEl = document.getElementById("search-results");
  if (!q.trim()) {
    resultsEl.innerHTML = "";
    return;
  }
  _searchTimer = setTimeout(async () => {
    const d = await fetch(`/chats/search?q=${encodeURIComponent(q)}`).then((r) => r.json()).catch(() => ({ results: [] }));
    const hits = d.results || [];
    if (!hits.length) {
      resultsEl.innerHTML = '<div style="color:var(--muted);font-size:.75rem;padding:4px 0">No results</div>';
      return;
    }
    resultsEl.innerHTML = hits.map((h) => `
      <div class="search-hit" onclick="loadChat('${h.id}');toggleSearch()">
        <div class="search-hit-title">${esc(h.title)}</div>
        ${h.snippet ? `<div class="search-hit-snippet">${esc(h.snippet)}</div>` : ""}
      </div>`).join("");
  }, 250);
}

let _cmdIdx = 0;
let _cmdItems = [];

function _commandPool() {
  const chats = [...document.querySelectorAll(".chat-item .chat-item-title")].map((el) => {
    const raw = el.parentElement?.getAttribute("onclick") || "";
    const m = raw.match(/loadChat\('([^']+)'\)/);
    const cid = m ? m[1] : "";
    return { label: `Open chat: ${el.textContent.trim()}`, tag: "chat", run: () => cid && loadChat(cid) };
  });
  return [
    { label: "New chat", tag: "app", run: () => newChat() },
    { label: "Toggle sidebar", tag: "app", run: () => toggleSidebar() },
    { label: "Open search", tag: "app", run: () => toggleSearch() },
    { label: "Open scheduler", tag: "panel", run: () => openSchedulerPanel() },
    { label: "Open swarm view", tag: "panel", run: () => openSwarmPanel() },
    { label: "Open architecture panel", tag: "panel", run: () => openArchitecturePanel() },
    { label: "Open diff viewer", tag: "panel", run: () => openDiffViewer() },
    { label: "Open self-improvement loop", tag: "panel", run: () => openSelfReviewPanel() },
    { label: "Open document understanding", tag: "panel", run: () => openDocumentsPanel() },
    { label: "Open debate arena", tag: "panel", run: () => openDebatePanel() },
    { label: "Open hypothesis testing", tag: "panel", run: () => openHypothesisPanel() },
    { label: "Open adaptive routing settings", tag: "panel", run: () => openAdaptiveRoutingPanel() },
    { label: "Open safety audit log", tag: "panel", run: () => openSafetyAudit() },
    { label: "Open safety scanner", tag: "panel", run: () => openSafetyScanner() },
    { label: "Open usage dashboard", tag: "panel", run: () => openUsageModal() },
    { label: "Open provider health", tag: "panel", run: () => openHealthModal() },
    { label: "Open memory", tag: "panel", run: () => openMemoryModal() },
    { label: "Open projects", tag: "panel", run: () => openProjectsModal() },
    { label: "Open custom instructions", tag: "panel", run: () => openCIModal() },
    { label: "Open knowledge graph", tag: "panel", run: () => openKGPanel() },
    { label: "Open trace viewer", tag: "panel", run: () => openTracePanel() },
    { label: "Open ensemble settings", tag: "panel", run: () => openEnsemblePanel() },
    { label: "Open persona editor", tag: "panel", run: () => openPersonaEditor() },
    { label: "Open settings", tag: "panel", run: () => openSettings() },
    { label: "Open command shortcuts", tag: "panel", run: () => openShortcuts() },
    { label: "Save chat now", tag: "action", run: () => autoSave() },
    { label: "Stop generation", tag: "action", run: () => stopStream() },
    { label: "Clear memory", tag: "action", run: () => clearMemory() },
    ...chats,
  ];
}

function openCommandPalette() {
  const overlay = document.getElementById("command-palette");
  const input = document.getElementById("cmd-input");
  overlay.classList.add("open");
  _cmdItems = _commandPool();
  _cmdIdx = 0;
  input.value = "";
  renderCommandPalette("");
  setTimeout(() => input.focus(), 0);
}

function closeCommandPalette() {
  document.getElementById("command-palette").classList.remove("open");
}

function renderCommandPalette(q) {
  const query = (q || "").trim().toLowerCase();
  const results = _cmdItems.filter((x) => !query || x.label.toLowerCase().includes(query)).slice(0, 24);
  const root = document.getElementById("cmd-results");
  if (!results.length) {
    root.innerHTML = '<div class="cmd-item"><span>No matches</span><span class="cmd-tag">hint</span></div>';
    return;
  }
  root.innerHTML = results.map((r, i) =>
    `<div class="cmd-item ${i === _cmdIdx ? "active" : ""}" data-cmd-idx="${i}"><span>${esc(r.label)}</span><span class="cmd-tag">${esc(r.tag)}</span></div>`
  ).join("");
  [...root.querySelectorAll(".cmd-item")].forEach((el) => {
    el.addEventListener("click", () => {
      const idx = parseInt(el.getAttribute("data-cmd-idx") || "0", 10);
      results[idx]?.run?.();
      closeCommandPalette();
    });
  });
  const input = document.getElementById("cmd-input");
  input.onkeydown = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      _cmdIdx = Math.min(_cmdIdx + 1, results.length - 1);
      renderCommandPalette(input.value);
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      _cmdIdx = Math.max(_cmdIdx - 1, 0);
      renderCommandPalette(input.value);
    }
    if (e.key === "Enter") {
      e.preventDefault();
      results[_cmdIdx]?.run?.();
      closeCommandPalette();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      closeCommandPalette();
    }
  };
}

document.getElementById("cmd-input")?.addEventListener("input", (e) => {
  _cmdIdx = 0;
  renderCommandPalette(e.target.value || "");
});
