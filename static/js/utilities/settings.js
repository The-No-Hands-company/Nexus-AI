// ── SETTINGS ───────────────────────────────────────────────────────────────────
function updateSafetyBadge(profile, scope='global'){
  const pill=document.getElementById('safety-pill');
  const label=document.getElementById('safety-label');
  const scopeEl=document.getElementById('safety-scope');
  if(!pill||!label||!scopeEl) return;
  const p=profile||'standard';
  const s=scope||'global';
  label.textContent=p;
  scopeEl.textContent=s;
  pill.setAttribute('data-profile',p);
  pill.setAttribute('data-scope',s);
  pill.title=`Safety profile: ${p} (${s}) — click Settings to change`;
}

function describeSafetyProfile(name, policy={}){
  const destructive = policy.allow_destructive_input ? 'allows sandbox destructive tasks' : 'blocks destructive tasks';
  const highStakes = policy.deny_high_stakes ? 'still blocks high-stakes workflows' : 'permits high-stakes workflows';
  return `${name}: ${destructive}; ${highStakes}.`;
}

function populateSettings(cfg,providers,safetySettings={}){
  const sel=document.getElementById('s-provider');
  sel.innerHTML=[{id:'auto',label:'Auto (try all)'},...providers]
    .map(p=>`<option value="${p.id}">${p.label||p.id}</option>`).join('');
  sel.value=cfg.provider||'auto';
  document.getElementById('s-model').value=cfg.model||'';
  const t=cfg.temperature??0.2;
  document.getElementById('s-temp').value=t;
  document.getElementById('s-temp-val').textContent=t;

  const safetySel=document.getElementById('s-safety-profile');
  const safetyHint=document.getElementById('s-safety-hint');
  const availableProfiles=(Array.isArray(safetySettings.available_profiles) && safetySettings.available_profiles.length)
    ? safetySettings.available_profiles
    : ['standard','strict','sandbox','research'];
  const profileMap=safetySettings.profiles||{};
  safetySel.innerHTML=availableProfiles
    .map(name=>`<option value="${name}">${name.charAt(0).toUpperCase()+name.slice(1)}</option>`)
    .join('');
  safetySel.value=cfg.safety_profile||safetySettings.safety_profile||'standard';
  updateSafetyBadge(safetySel.value);
  const updateHint=()=>{
    const active=safetySel.value;
    const fallbackPolicy=active===safetySettings.safety_profile ? (safetySettings.policy||{}) : {};
    safetyHint.textContent=describeSafetyProfile(active, profileMap[active]||fallbackPolicy);
    updateSafetyBadge(active);
  };
  safetySel.onchange=updateHint;
  updateHint();
}

async function loadSettingsModal(){
  const [cfg,safety]=await Promise.all([
    fetch('/settings').then(r=>r.json()).catch(()=>({})),
    fetch('/safety/profiles').then(r=>r.json()).catch(()=>({active:'standard',profiles:{}})),
  ]);
  populateSettings(cfg, window._providerCache||[], {
    safety_profile:safety.active||cfg.safety_profile||'standard',
    available_profiles:Object.keys(safety.profiles||{}),
    profiles:safety.profiles||{},
    policy:(safety.profiles||{})[safety.active||cfg.safety_profile||'standard']||{},
  });
}

async function openSettings(){
  document.getElementById('settings-overlay').classList.add('open');
  await loadSettingsModal();
}
function closeSettings(){document.getElementById('settings-overlay').classList.remove('open')}
async function saveSettings(){
  const resp=await fetch('/settings',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      provider:document.getElementById('s-provider').value,
      model:document.getElementById('s-model').value.trim(),
      temperature:parseFloat(document.getElementById('s-temp').value),
      safety_profile:document.getElementById('s-safety-profile').value
    })}).then(r=>r.json());
  const savedProfile=resp.safety_profile||'standard';
  document.getElementById('settings-status').textContent=
    `Saved — ${resp.provider}${resp.model?' / '+resp.model:''} / temp ${resp.temperature} / ${savedProfile} safety`;
  await loadSettingsModal();
  await refreshSessionSafetyUI();
  await refreshProviders();
}
