// ── PERSONAS ──────────────────────────────────────────────────────────────────
let activePersona = {id:'assistant',icon:'🤖',label:'Assistant',color:'#7c6af7'};
let personaCache = [];
const PERSONA_PREF_KEY = 'nexus.persona.active';

async function loadPersonas(){
  const savedActive = localStorage.getItem(PERSONA_PREF_KEY) || 'assistant';
  const d=await fetch('/personas').then(r=>r.json()).catch(()=>({personas:personaCache,active:savedActive}));
  const personas = d.personas || [];
  const activeId = d.active || savedActive;
  personaCache = personas;
  renderPersonaStrip(personas,activeId);
  const found=personas.find(p=>p.id===activeId) || personas[0];
  if(found) setActivePersonaUI(found);
}

function renderPersonaStrip(personas,activeId){
  const strip=document.getElementById('persona-strip');
  strip.innerHTML=personas.map(p=>`
    <button class="persona-btn ${p.id===activeId?'active':''}" id="pb-${p.id}"
      onclick="switchPersona('${p.id}')"
      style="${p.id===activeId?`background:${p.color};border-color:${p.color}`:''}">
      <span class="p-icon">${p.icon}</span>${p.label}
    </button>`).join('');
    // Only show the strip when there is more than one persona to choose from
    strip.style.display = personas.length > 1 ? 'flex' : 'none';
}
async function switchPersona(id){
  haptic('light');
  const d=await fetch(`/personas/${id}`,{method:'POST'}).then(r=>r.json()).catch(()=>null);
  if(!d){
    const fallback = personaCache.find(x=>x.id===id);
    if(fallback) setActivePersonaUI(fallback);
    return;
  }
  localStorage.setItem(PERSONA_PREF_KEY, id);
  await loadPersonas();
}

function setActivePersonaUI(p){
  activePersona=p;
  document.querySelectorAll('meta[name="theme-color"]').forEach((meta)=>meta.setAttribute('content',p.color));
  document.documentElement.style.setProperty('--accent',p.color);
  const accentD=p.color+'cc';
  document.documentElement.style.setProperty('--accent-d',accentD);
}
