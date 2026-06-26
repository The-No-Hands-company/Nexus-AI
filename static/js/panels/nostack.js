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
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
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
    list.innerHTML = "";
    _nostackSkills.forEach((s) => {
      const item = document.createElement("div");
      item.style.border = "1px solid var(--border)";
      item.style.borderRadius = "7px";
      item.style.padding = "7px 9px";
      item.style.background = "var(--surface2)";
      item.style.cursor = "pointer";
      item.style.transition = "background .15s";

      item.addEventListener("click", () => showNostackSkillDetail(s.name));
      item.addEventListener("mouseenter", () => { item.style.background = "var(--surface)"; });
      item.addEventListener("mouseleave", () => { item.style.background = "var(--surface2)"; });

      const nameEl = document.createElement("div");
      nameEl.style.fontSize = ".74rem";
      nameEl.style.fontWeight = "600";
      nameEl.style.color = "var(--text)";
      nameEl.textContent = s.name;

      const descEl = document.createElement("div");
      descEl.style.fontSize = ".65rem";
      descEl.style.color = "var(--muted)";
      descEl.style.marginTop = "1px";
      descEl.textContent = s.description || "No description";

      item.appendChild(nameEl);
      item.appendChild(descEl);
      list.appendChild(item);
    });
  } catch (err) {
    console.error("loadNostackSkills failed:", err);
    list.innerHTML = '<div style="color:var(--red);font-size:.72rem;padding:8px 4px;">Failed to load skills. Please check your connection and try again.</div>';
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
    // SECURITY: _nostackSelectedSkill is user-influenced; encodeURIComponent protects
    // URL construction, but the backend must validate/allowlist this skill name and
    // enforce authorization before execution.
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
  } catch (err) {
    console.error("runNostackSkill failed:", err);
    result.innerHTML = '<span style="color:var(--red);">Request failed. Please try again.</span>';
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

  // Client-side input validation (defense-in-depth; backend also validates)
  const maxSkills = 20;
  const maxSkillLength = 64;
  const skillPattern = /^[A-Za-z0-9_. -]+$/;
  const status = document.getElementById("nostack-sprint-status");

  if (!skills.length) {
    status.innerHTML = '<span style="color:var(--red);">Enter at least one valid skill.</span>';
    return;
  }
  if (skills.length > maxSkills) {
    status.innerHTML = '<span style="color:var(--red);">Too many skills. Maximum is ' + maxSkills + '.</span>';
    return;
  }
  const invalidSkill = skills.find((s) => s.length > maxSkillLength || !skillPattern.test(s));
  if (invalidSkill) {
    status.innerHTML = '<span style="color:var(--red);">Invalid skill "' + esc(invalidSkill) + '". Use letters, numbers, spaces, ".", "_" or "-".</span>';
    return;
  }

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
  } catch (err) {
    console.error("runNostackSprint failed:", err);
    status.innerHTML = '<span style="color:var(--red);">Request failed. Please try again.</span>';
  }
}
