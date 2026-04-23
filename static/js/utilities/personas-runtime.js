// ── PERSONAS ──────────────────────────────────────────────────────────────────
let activePersona = {id:'assistant',icon:'🤖',label:'Assistant',color:'#7c6af7'};

async function loadPersonas(){
  const d=await fetch('/personas').then(r=>r.json()).catch(()=>({personas:[],active:'assistant'}));
  renderPersonaStrip(d.personas||[],d.active||'assistant');
  const found=(d.personas||[]).find(p=>p.id===d.active);
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
  if(!d) return;
  await loadPersonas();
  const personas=await fetch('/personas').then(r=>r.json()).then(d=>d.personas).catch(()=>[]);
  const p=personas.find(x=>x.id===id);
  if(p) setActivePersonaUI(p);
}

function setActivePersonaUI(p){
  activePersona=p;
  document.querySelector('meta[name=theme-color]')?.setAttribute('content',p.color);
  document.documentElement.style.setProperty('--accent',p.color);
  const accentD=p.color+'cc';
  document.documentElement.style.setProperty('--accent-d',accentD);
}
