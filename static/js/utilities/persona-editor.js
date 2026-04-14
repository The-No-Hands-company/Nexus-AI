// ── CUSTOM PERSONA EDITOR ──────────────────────────────────────────────────────
async function openPersonaEditor() {
  document.getElementById('persona-editor-modal').classList.add('open');
  await refreshPersonaEditorList();
}
function closePersonaEditor() {
  document.getElementById('persona-editor-modal').classList.remove('open');
}

async function refreshPersonaEditorList() {
  const d    = await fetch('/personas/custom').then(r=>r.json()).catch(()=>({personas:[]}));
  const list = document.getElementById('existing-personas-list');
  if (!(d.personas||[]).length) {
    list.innerHTML = '<div style="color:var(--muted);font-size:.75rem">No custom personas yet.</div>';
    return;
  }
  list.innerHTML = (d.personas||[]).map(p => `
    <div class="cpersona-item">
      <div class="cpersona-icon">${p.icon||'🤖'}</div>
      <div class="cpersona-info">
        <div class="cpersona-name">${esc(p.name)}</div>
        <div class="cpersona-desc">${esc(p.description||'')}</div>
      </div>
      <button class="memory-del" onclick="deleteCustomPersona('${p.id}')">🗑</button>
    </div>`).join('');
}

async function saveCustomPersona() {
  const name   = document.getElementById('cpe-name').value.trim();
  const icon   = document.getElementById('cpe-icon').value.trim() || '🤖';
  const prompt = document.getElementById('cpe-prompt').value.trim();
  const temp   = parseFloat(document.getElementById('cpe-temp').value);
  const color  = document.getElementById('cpe-color').value;
  if (!name || !prompt) { alert('Name and system prompt are required.'); return; }
  await fetch('/personas/custom', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, icon, prompt_prefix: prompt,
                          description: prompt.slice(0,60)+'…',
                          temperature: temp, color, tier:'medium'})});
  ['cpe-name','cpe-icon','cpe-prompt'].forEach(id => document.getElementById(id).value='');
  await refreshPersonaEditorList();
  await loadPersonas();
  addSysMsg(`🎭 Persona "${name}" created`);
}

async function deleteCustomPersona(id) {
  await fetch(`/personas/custom/${id}`, {method:'DELETE'});
  await refreshPersonaEditorList();
  await loadPersonas();
}
