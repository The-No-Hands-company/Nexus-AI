// Nostack Virtual Team panel module
"use strict";

let _nostackSkills = [];
let _nostackSelectedSkill = null;

function openNostackPanel() {
  NexusApi.setPanelOpen("nostack-panel", true);
  if (!_nostackSkills.length) {
    loadNostackSkills();
  }
}

function closeNostackPanel() {
  NexusApi.setPanelOpen("nostack-panel", false);
}

function esc(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

async function loadNostackSkills() {
  const list = document.getElementById("nostack-skills-list");
  list.innerHTML = '<div style="color:var(--muted);font-size:.72rem;padding:8px 4px;">Loading skills…</div>';
  try {
    const r = await fetch("/nostack/skills");
    const d = await r.json();
    _nostackSkills = d.skills || [];
    if (!_nostackSkills.length) {
      list.innerHTML = '<div style="color:var(--muted);font-size:.72rem;padding:8px 4px;">No skills found.</div>';
      return;
    }
    list.innerHTML = _nostackSkills.map((s) =>
      '<div onclick="showNostackSkillDetail(\'' + esc(s.name) + '\')" style="border:1px solid var(--border);border-radius:7px;padding:7px 9px;background:var(--surface2);cursor:pointer;transition:background .15s;" onmouseenter="this.style.background=\'var(--surface)\'" onmouseleave="this.style.background=\'var(--surface2)\'">' +
        '<div style="font-size:.74rem;font-weight:600;color:var(--text);">' + esc(s.name) + '</div>' +
        '<div style="font-size:.65rem;color:var(--muted);margin-top:1px;">' + esc(s.description || "No description") + '</div>' +
      '</div>'
    ).join("");
  } catch (_) {
    list.innerHTML = '<div style="color:var(--red);font-size:.72rem;padding:8px 4px;">Failed to load skills.</div>';
  }
}

function showNostackSkillDetail(name) {
  _nostackSelectedSkill = name;
  document.getElementById("nostack-skill-detail-name").textContent = name;
  document.getElementById("nostack-skill-task").value = "";
  document.getElementById("nostack-skill-result").innerHTML = "";
  document.getElementById("nostack-skill-detail").style.display = "block";
}

async function runNostackSkill() {
  if (!_nostackSelectedSkill) return;
  const task = document.getElementById("nostack-skill-task").value.trim();
  if (!task) {
    document.getElementById("nostack-skill-result").innerHTML = '<span style="color:var(--red);">Enter a task.</span>';
    return;
  }
  const result = document.getElementById("nostack-skill-result");
  result.innerHTML = '<span style="color:var(--muted);">Running…</span>';
  try {
    const r = await fetch(`/nostack/skills/${encodeURIComponent(_nostackSelectedSkill)}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task }),
    });
    const d = await r.json();
    if (!r.ok) {
      result.innerHTML = '<pre style="margin:0;font-size:.68rem;color:var(--red);white-space:pre-wrap;">' + esc(d.error || "Failed") + '</pre>';
      return;
    }
    const out = d.output || d.result || JSON.stringify(d, null, 2);
    result.innerHTML = '<pre style="margin:0;font-size:.68rem;color:#4a9;white-space:pre-wrap;">' + esc(out) + '</pre>';
  } catch (e) {
    result.innerHTML = '<span style="color:var(--red);">Request failed.</span>';
  }
}

async function runNostackSprint() {
  const task = document.getElementById("nostack-sprint-task").value.trim();
  const skillsRaw = document.getElementById("nostack-sprint-skills").value.trim();
  if (!task) {
    document.getElementById("nostack-sprint-status").innerHTML = '<span style="color:var(--red);">Enter a task.</span>';
    return;
  }
  if (!skillsRaw) {
    document.getElementById("nostack-sprint-status").innerHTML = '<span style="color:var(--red);">Enter skills.</span>';
    return;
  }
  const skills = skillsRaw.split(",").map((s) => s.trim()).filter(Boolean);
  const status = document.getElementById("nostack-sprint-status");
  status.innerHTML = '<span style="color:var(--muted);">Running sprint…</span>';
  try {
    const r = await fetch("/nostack/sprint", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task, skills }),
    });
    const d = await r.json();
    if (!r.ok) {
      status.innerHTML = '<span style="color:var(--red);">' + esc(d.error || "Failed") + '</span>';
      return;
    }
    const out = d.output || d.result || JSON.stringify(d, null, 2);
    status.innerHTML = '<pre style="margin:0;font-size:.68rem;color:#4a9;white-space:pre-wrap;">' + esc(out) + '</pre>';
  } catch (e) {
    status.innerHTML = '<span style="color:var(--red);">Request failed.</span>';
  }
}
