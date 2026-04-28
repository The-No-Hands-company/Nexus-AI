// Memory and projects utilities split from index.html
let activeProjectId = null;
let projectsData = [];
let peSelectedColor = "#7c6af7";

async function openMemoryModal() {
  document.getElementById("memory-modal").classList.add("open");
  await refreshMemoryModal();
}

function closeMemoryModal() {
  document.getElementById("memory-modal").classList.remove("open");
}

async function refreshMemoryModal() {
  const body = document.getElementById("memory-modal-body");
  const d = await fetch("/memory").then((r) => r.json()).catch(() => ({ memories: [] }));
  const mems = d.memories || [];
  if (!mems.length) {
    body.innerHTML = '<div style="color:var(--muted);font-size:.8rem;text-align:center;padding:20px">No memories yet. Save a chat to create one.</div>';
    document.getElementById("mem-count").textContent = "0";
    return;
  }
  document.getElementById("mem-count").textContent = mems.length;
  body.innerHTML = mems.map((m) => {
    const date = new Date(m.created_at * 1000).toLocaleDateString("en", { month: "short", day: "numeric" });
    return `<div class="memory-entry" id="me-${m.id}">
      <div class="memory-date">${date}</div>
      <div class="memory-text" id="mt-${m.id}" contenteditable="false">${esc(m.summary)}</div>
      <button class="msg-action-btn" onclick="editMemoryEntry(${m.id})" title="Edit">✏️</button>
      <button class="memory-del" onclick="deleteMemoryEntry(${m.id})" title="Delete">🗑</button>
    </div>`;
  }).join("");
}

function editMemoryEntry(id) {
  const el = document.getElementById(`mt-${id}`);
  if (!el) return;
  if (el.contentEditable === "true") {
    el.contentEditable = "false";
    fetch(`/memory/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ summary: el.textContent.trim() }),
    });
  } else {
    el.contentEditable = "true";
    el.focus();
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
  }
}

async function deleteMemoryEntry(id) {
  await fetch(`/memory/${id}`, { method: "DELETE" });
  document.getElementById(`me-${id}`)?.remove();
  const remaining = document.querySelectorAll(".memory-entry").length;
  document.getElementById("mem-count").textContent = remaining;
  if (!remaining) refreshMemoryModal();
}

async function clearAllMemory() {
  if (!confirm("Clear all memory entries?")) return;
  await fetch("/memory", { method: "DELETE" });
  await refreshMemoryModal();
}

async function openProjectsModal() {
  document.getElementById("projects-modal").classList.add("open");
  await refreshProjectsModal();
}

function closeProjectsModal() {
  document.getElementById("projects-modal").classList.remove("open");
}

async function refreshProjectsModal() {
  const d = await fetch("/projects").then((r) => r.json()).catch(() => ({ projects: [] }));
  projectsData = d.projects || [];
  const body = document.getElementById("projects-modal-body");
  if (!projectsData.length) {
    body.innerHTML = '<div style="color:var(--muted);font-size:.8rem;padding:10px">No projects yet. Hit + New project to create one.</div>';
    return;
  }
  body.innerHTML = projectsData.map((p) => `
    <div class="project-item ${p.id === activeProjectId ? "active" : ""}" onclick="selectProject('${p.id}')">
      <div class="project-dot" style="background:${p.color}"></div>
      <div class="project-name">${esc(p.name)}</div>
      <div class="project-actions">
        <button class="chat-act-btn" onclick="event.stopPropagation();editProject('${p.id}')">✏️</button>
        <button class="chat-act-btn" onclick="event.stopPropagation();deleteProject('${p.id}')" style="color:var(--red)">🗑</button>
      </div>
    </div>`).join("");
}

function selectProject(id) {
  activeProjectId = activeProjectId === id ? null : id;
  refreshProjectsModal();
  const p = projectsData.find((x) => x.id === id);
  if (p && activeProjectId) {
    addSysMsg(`🗂️ Project: ${p.name}`);
    if (p.instructions) addSysMsg(`📋 ${p.instructions.slice(0, 80)}…`);
  }
  closeProjectsModal();
}

function newProject() {
  openProjectEdit(null);
}

function editProject(id) {
  openProjectEdit(id);
}

function openProjectEdit(id) {
  const p = id ? projectsData.find((x) => x.id === id) : null;
  document.getElementById("pe-id").value = id || "";
  document.getElementById("pe-name").value = p?.name || "";
  document.getElementById("pe-instructions").value = p?.instructions || "";
  document.getElementById("pe-title").textContent = id ? "Edit Project" : "New Project";
  peSelectedColor = p?.color || "#7c6af7";
  document.querySelectorAll(".color-swatch").forEach((s) => {
    s.style.border = s.dataset.color === peSelectedColor ? "2px solid white" : "2px solid transparent";
    s.onclick = () => {
      peSelectedColor = s.dataset.color;
      document.querySelectorAll(".color-swatch").forEach((x) => {
        x.style.border = x.dataset.color === peSelectedColor ? "2px solid white" : "2px solid transparent";
      });
    };
  });
  document.getElementById("project-edit-modal").classList.add("open");
}

function closeProjectEdit() {
  document.getElementById("project-edit-modal").classList.remove("open");
}

async function saveProjectEdit() {
  const id = document.getElementById("pe-id").value || undefined;
  const name = document.getElementById("pe-name").value.trim();
  if (!name) return;
  await fetch("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id,
      name,
      instructions: document.getElementById("pe-instructions").value.trim(),
      color: peSelectedColor,
    }),
  });
  closeProjectEdit();
  await refreshProjectsModal();
}

async function deleteProject(id) {
  if (!confirm("Delete this project?")) return;
  await fetch(`/projects/${id}`, { method: "DELETE" });
  if (activeProjectId === id) activeProjectId = null;
  await refreshProjectsModal();
}

function showMemoryBadge(){
  const badge=document.createElement('div');
  badge.style.cssText='font-size:.65rem;color:var(--teal);text-align:center;padding:6px;';
  badge.textContent='🧠 Memory loaded from previous sessions';
  document.getElementById('welcome').insertBefore(badge,
    document.getElementById('welcome').querySelector('.chips'));
}

async function loadMemoryCount(){
  const d=await fetch('/memory').then(r=>r.json()).catch(()=>({memories:[]}));
  document.getElementById('mem-count').textContent=(d.memories||[]).length;
}

async function clearMemory(){
  if(!confirm('Clear all memory?')) return;
  await fetch('/memory',{method:'DELETE'});
  await loadMemoryCount();
}
