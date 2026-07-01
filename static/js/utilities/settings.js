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
  var container = document.getElementById('s-provider-keys');
  if (!container) return;

  var providers = (window._providerCache && window._providerCache.length)
    ? window._providerCache
    : null;

  if (!providers || !providers.length) {
    container.innerHTML = '<span style="color:var(--muted);font-size:.72rem;">Loading providers...</span>';
    return;
  }

  // Separate configured vs unconfigured
  var configured = [];
  var unconfigured = [];
  for (var i = 0; i < providers.length; i++) {
    var p = providers[i];
    if (!p.id || p.id === 'auto') continue;
    var info = keyStatus[p.id] || {};
    if (info.has_key) {
      configured.push({ id: p.id, label: p.label || p.id, source: info.source || 'none' });
    } else {
      unconfigured.push({ id: p.id, label: p.label || p.id });
    }
  }

  var html = '';

  // Configured providers — compact badges
  if (configured.length > 0) {
    html += '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px">';
    for (var c = 0; c < configured.length; c++) {
      var cp = configured[c];
      var icon = cp.source === 'env' ? '\uD83D\uDD12' : '\u2713';
      html += '<span style="padding:3px 8px;border-radius:10px;background:var(--surface2);border:1px solid var(--border);font-size:.68rem;cursor:pointer" title="' + cp.source + '" onclick="document.getElementById(\'pk-select\').value=\'' + cp.id + '\';document.getElementById(\'pk-input-row\').style.display=\'flex\';document.getElementById(\'pk-input\').focus()">'
        + icon + ' ' + cp.label + '</span>';
    }
    html += '</div>';
  }

  // Dropdown + input for adding new keys
  html += '<div style="display:flex;gap:6px;align-items:center">'
    + '<select id="pk-select" style="flex:1;padding:6px 8px;border:1px solid var(--border);border-radius:7px;background:var(--surface2);color:var(--text);font-size:.75rem;max-width:180px" onchange="document.getElementById(\'pk-input\').value=\'\';document.getElementById(\'pk-status\').textContent=\'\';document.getElementById(\'pk-input-row\').style.display=this.value?\'flex\':\'none\'">'
    + '<option value="">+ Add key for...</option>';
  for (var u = 0; u < unconfigured.length; u++) {
    html += '<option value="' + unconfigured[u].id + '">' + unconfigured[u].label + '</option>';
  }
  html += '</select>'
    + '<span id="pk-input-row" style="display:none;flex:1;gap:6px;align-items:center">'
    + '<input type="password" id="pk-input" placeholder="Paste API key..." style="flex:1;padding:6px 8px;border:1px solid var(--border);border-radius:7px;background:var(--surface2);color:var(--text);font-size:.75rem" />'
    + '<button onclick="saveSingleKey()" style="padding:6px 12px;border:none;border-radius:7px;background:#6366f1;color:#fff;font-size:.72rem;font-weight:600;cursor:pointer;white-space:nowrap">Save</button>'
    + '</span>'
    + '</div>'
    + '<span id="pk-status" style="font-size:.65rem;color:var(--muted);margin-top:4px;display:inline-block"></span>';

  container.innerHTML = html;
}

function saveSingleKey() {
  var select = document.getElementById('pk-select');
  var input = document.getElementById('pk-input');
  var status = document.getElementById('pk-status');
  var provider = select.value;
  var key = input.value.trim();
  if (!provider) return;

  fetch('/settings/provider-keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider: provider, key: key })
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (key) {
      status.textContent = '\u2713 Key saved for ' + (d.provider || provider);
      status.style.color = '#4a9';
    } else {
      status.textContent = '\u2717 Key removed';
      status.style.color = 'var(--red)';
    }
    input.value = '';
    // Refresh the list after 1s
    setTimeout(function() {
      fetch('/settings/provider-keys').then(function(r) { return r.json(); }).then(function(d) {
        populateProviderKeys(d.provider_keys || {});
      });
    }, 800);
  }).catch(function(e) {
    status.textContent = 'Failed: ' + e.message;
    status.style.color = 'var(--red)';
  });
}

// saveProviderKeys is no longer needed — saveSingleKey handles individual saves

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
