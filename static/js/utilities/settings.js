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

function describeStrictProfile(name){
  const key=(name||'strict').toLowerCase();
  const descriptions={
    balanced:'Balanced: low-risk chat flows with less interruption, while destructive actions still require no-guess certainty.',
    strict:'Strict: safe-by-default with minimal friction, and no-guess execution for risky tasks.',
    paranoid:'Paranoid: enterprise/compliance mode with maximum verification before execution.',
    custom:'Custom: manual strict thresholds are active.',
  };
  return descriptions[key]||descriptions.strict;
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

  const strictSel=document.getElementById('s-strict-profile');
  const strictHint=document.getElementById('s-strict-hint');
  const strictProfiles=['balanced','strict','paranoid'];
  strictSel.innerHTML=strictProfiles
    .map(name=>`<option value="${name}">${name.charAt(0).toUpperCase()+name.slice(1)}</option>`)
    .join('');
  const strictValue=(cfg.strict_mode_profile||'strict').toLowerCase();
  if(!strictProfiles.includes(strictValue)){
    strictSel.insertAdjacentHTML('beforeend','<option value="custom">Custom</option>');
  }
  strictSel.value=strictProfiles.includes(strictValue)?strictValue:'custom';
  const updateStrictHint=()=>{ strictHint.textContent=describeStrictProfile(strictSel.value); };
  strictSel.onchange=updateStrictHint;
  updateStrictHint();
}

async function loadSettingsModal(){
  const [cfg,safety,keyStatus]=await Promise.all([
    fetch('/settings').then(r=>r.json()).catch(()=>({})),
    fetch('/safety/profiles').then(r=>r.json()).catch(()=>({active:'standard',profiles:{}})),
    fetch('/settings/provider-keys').then(r=>r.json()).catch(()=>({provider_keys:{}})),
  ]);
  populateSettings(cfg, window._providerCache||[], {
    safety_profile:safety.active||cfg.safety_profile||'standard',
    available_profiles:Object.keys(safety.profiles||{}),
    profiles:safety.profiles||{},
    policy:(safety.profiles||{})[safety.active||cfg.safety_profile||'standard']||{},
  });
  populateProviderKeys(keyStatus.provider_keys||{});
}

function populateProviderKeys(keyStatus) {
  const container = document.getElementById('s-provider-keys');
  if (!container) return;
  const providers = window._providerCache || [];
  container.innerHTML = providers
    .filter(p => p.id !== 'auto')
    .map(p => {
      const has = keyStatus[p.id]?.has_key;
      const source = keyStatus[p.id]?.source;
      return '<div style="display:flex;align-items:center;gap:6px">' +
        '<span style="min-width:90px;font-size:.73rem;font-weight:500;color:var(--text)">' + (p.label || p.id) + '</span>' +
        '<input type="password" id="pk-' + p.id + '" placeholder="' + (source === 'env' ? '(from environment)' : (has ? '(key stored)' : 'API key…')) + '"' +
        ' style="flex:1;padding:5px 8px;border:1px solid var(--border);border-radius:6px;background:var(--surface2);color:var(--text);font-size:.73rem;"' +
        ' onchange="document.getElementById(\'pk-status-' + p.id + '\').textContent=\'\'" />' +
        '<span id="pk-status-' + p.id + '" style="font-size:.65rem;color:var(--muted);min-width:50px">' +
          (source === 'env' ? '🔒 env' : (has ? '✓ stored' : '')) +
        '</span>' +
        '</div>';
    }).join('');
}

async function saveProviderKeys() {
  const providers = (window._providerCache || []).filter(p => p.id !== 'auto');
  for (const p of providers) {
    const input = document.getElementById('pk-' + p.id);
    if (!input) continue;
    const val = input.value.trim();
    if (!val && !input.placeholder.includes('stored') && !input.placeholder.includes('environment')) continue;
    try {
      await fetch('/settings/provider-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: p.id, key: val })
      });
      const st = document.getElementById('pk-status-' + p.id);
      if (st) st.textContent = val ? '✓ saved' : '✗ removed';
    } catch (_) {}
  }
}

async function openSettings(){
  document.getElementById('settings-overlay').classList.add('open');
  await loadSettingsModal();
}
function closeSettings(){document.getElementById('settings-overlay').classList.remove('open')}
async function saveSettings(){
  await saveProviderKeys();
  const resp=await fetch('/settings',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      provider:document.getElementById('s-provider').value,
      model:document.getElementById('s-model').value.trim(),
      temperature:parseFloat(document.getElementById('s-temp').value),
      safety_profile:document.getElementById('s-safety-profile').value,
      strict_mode_profile:document.getElementById('s-strict-profile').value
    })}).then(r=>r.json());
  const savedProfile=resp.safety_profile||'standard';
  const savedStrictProfile=(resp.strict_mode_profile||'strict').toLowerCase();
  document.getElementById('settings-status').textContent=
    `Saved — ${resp.provider}${resp.model?' / '+resp.model:''} / temp ${resp.temperature} / ${savedProfile} safety / ${savedStrictProfile} execution`;
  await loadSettingsModal();
  await refreshSessionSafetyUI();
  await refreshProviders();
}

// ── SESSION SAFETY OVERRIDE ────────────────────────────────────────────────────
async function refreshSessionSafetyUI() {
  if(!sid) return;
  const sel = document.getElementById('session-safety-sel');
  const d = await fetch(`/session/${sid}/safety`).then(r=>r.json()).catch(()=>null);
  if(!d) return;
  if(sel) sel.value = d.session_profile||'';
  updateSafetyBadge(d.effective_profile||d.global_profile||'standard', d.session_profile ? 'session' : 'global');
}

async function initSessionSafetySelector(profiles) {
  const sel = document.getElementById('session-safety-sel');
  if(!sel) return;
  sel.innerHTML = '<option value="">— global default —</option>'
    + profiles.map(p=>`<option value="${p}">${p.charAt(0).toUpperCase()+p.slice(1)}</option>`).join('');
  await refreshSessionSafetyUI();
  sel.onchange = async () => {
    const profile = sel.value || null;
    const resp = await fetch(`/session/${sid}/safety`,{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({safety_profile: profile})});
    const data = await resp.json().catch(()=>null);
    const effective = data?.effective_profile || profile || 'standard';
    updateSafetyBadge(effective, data?.session_profile ? 'session' : 'global');
  };
}
