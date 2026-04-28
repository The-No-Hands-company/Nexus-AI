// ── MESSAGE REACTIONS ─────────────────────────────────────────────────────────
function addReactionButtons(wrap, msgIdx) {
  const row = document.createElement('div');
  row.className = 'reaction-row';
  let upActive = false, downActive = false;

  const upBtn   = document.createElement('button');
  upBtn.className = 'reaction-btn'; upBtn.textContent = '👍';
  upBtn.onclick   = async () => {
    if (upActive) return;
    upActive = true; downActive = false;
    upBtn.classList.add('active-up'); downBtn.classList.remove('active-down');
    await fetch('/reactions', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({chat_id: activeChatId, msg_idx: msgIdx, reaction:'up',
                             text: wrap.querySelector('.bubble')?.innerText?.slice(0,200)||''})});
  };

  const downBtn = document.createElement('button');
  downBtn.className = 'reaction-btn'; downBtn.textContent = '👎';
  downBtn.onclick   = async () => {
    if (downActive) return;
    downActive = true; upActive = false;
    downBtn.classList.add('active-down'); upBtn.classList.remove('active-up');
    await fetch('/reactions', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({chat_id: activeChatId, msg_idx: msgIdx, reaction:'down',
                             text: wrap.querySelector('.bubble')?.innerText?.slice(0,200)||''})});
  };

  row.appendChild(upBtn); row.appendChild(downBtn);
  wrap.appendChild(row);
}

// ── OVERFLOW MENU ──────────────────────────────────────────────────────────────
function toggleOverflow() {
  const menu = document.getElementById('overflow-menu');
  const isOpen = menu.style.display !== 'none';
  menu.style.display = isOpen ? 'none' : 'flex';
}
document.addEventListener('click', e => {
  const wrap = document.querySelector('.overflow-menu-wrap');
  if (wrap && !wrap.contains(e.target)) {
    const menu = document.getElementById('overflow-menu');
    if (menu) menu.style.display = 'none';
  }
});

// ── CUSTOM INSTRUCTIONS ───────────────────────────────────────────────────────
async function openCIModal() {
  const d = await fetch('/instructions').then(r=>r.json()).catch(()=>({instructions:''}));
  document.getElementById('ci-text').value = d.instructions || '';
  document.getElementById('ci-modal').classList.add('open');
}
function closeCIModal() { document.getElementById('ci-modal').classList.remove('open'); }
async function saveCIModal() {
  const val = document.getElementById('ci-text').value.trim();
  await fetch('/instructions', {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({instructions: val})});
  closeCIModal();
  addSysMsg('📋 Custom instructions saved');
}
