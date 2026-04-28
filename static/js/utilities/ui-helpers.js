// ── TOKEN HANDLING ─────────────────────────────────────────────────────────
function showTokenBar(){document.getElementById('token-bar').style.display='flex'}
async function submitToken(){
  const val=document.getElementById('token-input').value.trim();
  if(!val||!sid) return;
  await fetch(`/session/${sid}/token`,{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({token:val})});
  document.getElementById('token-input').value='';
  document.getElementById('token-bar').style.display='none';
  addSysMsg('🔑 Token stored for this session');
}

// ── TOKEN COUNTER ──────────────────────────────────────────────────────────────
function estimateTokens(text) {
  return Math.ceil((text || '').length / 4);
}

function addTokenCount(wrap, inputText, outputText) {
  const inToks  = estimateTokens(inputText);
  const outToks = estimateTokens(outputText);
  const el = document.createElement('div');
  el.className = 'token-count';
  el.innerHTML = `<span class="tc-in">↑ ~${inToks} tokens</span>
                  <span class="tc-out">↓ ~${outToks} tokens</span>`;
  wrap.appendChild(el);
}

function showTokenCount(inputTokens, outputTokens) {
  const bar = document.getElementById('token-bar-msg');
  if (inputTokens == null && outputTokens == null) { bar.classList.remove('visible'); return; }
  document.getElementById('tok-in').textContent  = inputTokens  != null ? `↑ ${inputTokens} tokens`  : '';
  document.getElementById('tok-out').textContent = outputTokens != null ? `↓ ${outputTokens} tokens` : '';
  bar.classList.add('visible');
}

function updateLiveTokenCount(data) {
  if (!data) return;
  const inTokens = Number(data.in_tokens);
  const outTokens = Number(data.out_tokens);
  const inVal = Number.isFinite(inTokens) ? inTokens : null;
  const outVal = Number.isFinite(outTokens) ? outTokens : null;
  showTokenCount(inVal, outVal);
}

// ── SHORTCUTS MODAL HELPERS ───────────────────────────────────────────────────
function openShortcuts()  { document.getElementById('shortcuts-overlay').classList.add('open'); }
function closeShortcuts() { document.getElementById('shortcuts-overlay').classList.remove('open'); }
