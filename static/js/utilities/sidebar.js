const SIDEBAR_PREF_KEY = 'nexus.sidebar.open';

function persistSidebarState(isOpen){
  try{ localStorage.setItem(SIDEBAR_PREF_KEY, isOpen ? '1' : '0'); }catch(_){ }
}

function restoreSidebarState(){
  const sidebar = document.getElementById('sidebar');
  if(!sidebar) return;
  let preferredOpen = false;
  try{ preferredOpen = localStorage.getItem(SIDEBAR_PREF_KEY) === '1'; }catch(_){ }
  const isMobile = window.matchMedia('(max-width: 700px)').matches;
  sidebarOpen = preferredOpen && !isMobile;
  sidebar.classList.toggle('hidden', !sidebarOpen);
  document.getElementById('sidebar-overlay')?.classList.toggle('active', isMobile && sidebarOpen);
}

// ── SIDEBAR ────────────────────────────────────────────────────────────────────
function toggleSidebar(){
  sidebarOpen=!sidebarOpen;
  document.getElementById('sidebar').classList.toggle('hidden',!sidebarOpen);
  const isMobile = window.matchMedia('(max-width: 700px)').matches;
  document.getElementById('sidebar-overlay').classList.toggle('active',isMobile && sidebarOpen);
  persistSidebarState(sidebarOpen);
}
function closeSidebar(){
  sidebarOpen=false;
  document.getElementById('sidebar').classList.add('hidden');
  document.getElementById('sidebar-overlay').classList.remove('active');
  persistSidebarState(false);
}
async function loadChatList(){
  const d=await fetch('/chats').then(r=>r.json()).catch(()=>({chats:[]}));
  renderChatList(d.chats||[]);
}
function renderChatList(chats){
  const el=document.getElementById('chat-list');
  if(!chats.length){el.innerHTML='<div class="no-chats">No saved chats yet.<br>Hit 💾 to save one.</div>';return}
  el.innerHTML=chats.map(c=>{
    const date=new Date(c.updated_at).toLocaleDateString('en',{month:'short',day:'numeric'});
    const active=c.id===activeChatId?'active':'';
    return `<div class="chat-item ${active}" onclick="loadChat('${c.id}')">
      <span class="chat-item-title" id="chat-title-${c.id}" ondblclick="event.stopPropagation();startRename('${c.id}')" title="Double-click to rename">${esc(c.title)}</span>
      <span class="chat-item-date">${date}</span>
      <div class="chat-actions">
  <button class="chat-act-btn" onclick="event.stopPropagation();togglePin('${c.id}','${c.pinned?'true':'false'}')" title="${c.pinned?'Unstar':'Star'}" style="${c.pinned?'color:var(--amber)':''}">${c.pinned?'★':'☆'}</button>
        <button class="chat-act-btn" onclick="event.stopPropagation();startRename('${c.id}')" title="Rename">✏️</button>
        <button class="chat-act-btn" onclick="event.stopPropagation();exportChat('${c.id}')" title="Export">⬇</button>
        <button class="chat-act-btn" onclick="event.stopPropagation();shareChat('${c.id}')" title="Share">🔗</button>
        <button class="chat-act-btn" onclick="event.stopPropagation();deleteChat('${c.id}')" title="Delete" style="color:var(--red)">🗑</button>
      </div>
    </div>`;
  }).join('');
}

// ── AUTO-SAVE ─────────────────────────────────────────────────────────────────
let _autoSaveTimer = null;

function triggerAutoSave(delay = 1500) {
  clearTimeout(_autoSaveTimer);
  _autoSaveTimer = setTimeout(autoSave, delay);
}

async function autoSave() {
  const msgs = document.getElementById('messages');
  const hasContent = [...msgs.children].some(c => c.id !== 'typing');
  if (!hasContent) return;

  const dot = document.getElementById('autosave-dot');
  dot.className = 'saving';

  const resp = await fetch('/chats', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({session_id: sid, chat_id: activeChatId})
  }).then(r => r.json()).catch(() => null);

  if (resp?.chat_id) {
    activeChatId = resp.chat_id;
    dot.className = 'saved';
    setTimeout(() => { dot.className = ''; }, 2000);
    await Promise.all([loadChatList(), loadMemoryCount()]);
  } else {
    dot.className = '';
  }
}

// ── RENAME CHAT ────────────────────────────────────────────────────────────────
function startRename(cid) {
  const titleEl = document.getElementById('chat-title-' + cid);
  if (!titleEl) return;
  const current = titleEl.textContent;

  const input = document.createElement('input');
  input.className = 'chat-rename-input';
  input.value = current;
  input.onclick = e => e.stopPropagation();

  const finishRename = async () => {
    const newTitle = input.value.trim();
    if (!newTitle || newTitle === current) {
      titleEl.style.display = '';
      input.remove();
      return;
    }
    titleEl.style.display = '';
    titleEl.textContent = newTitle;
    input.remove();
    await fetch('/chats', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({session_id: sid, chat_id: cid, title: newTitle})
    });
    await loadChatList();
  };

  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); finishRename(); }
    if (e.key === 'Escape') { titleEl.style.display = ''; input.remove(); }
  });
  input.addEventListener('blur', finishRename);

  titleEl.style.display = 'none';
  titleEl.parentNode.insertBefore(input, titleEl.nextSibling);
  setTimeout(() => input.focus(), 10);
}

async function loadChat(cid){
  const d=await fetch(`/chats/${cid}`).then(r=>r.json());
  if(d.error) return;
  activeChatId=cid;
  const s=await fetch('/session',{method:'POST'}).then(r=>r.json());
  sid=s.session_id;
  await fetch('/agent',{method:'POST',headers:{'Content-Type':'application/json','X-Nexus-Session-Id':sid||''},
    body:JSON.stringify({task:'__restore__',session_id:sid,_history:d.messages||[]})}).catch(()=>{});
  clearMessages();showChat();
  const history=d.messages||[];
  for(const m of history){
    if(m.role==='user'&&typeof m.content==='string'
       &&!m.content.startsWith('Tool result:')&&!m.content.startsWith('Continue')
       &&!m.content.startsWith('[MEMORY')){
      addBubble('user',esc(m.content).replace(/\n/g,'<br>'));
    } else if(m.role==='assistant'&&m.content&&!m.content.startsWith('{')){
      addBubble('agent',renderMd(m.content));
    }
  }
  await refreshSessionSafetyUI();
  triggerAutoSave(500);
  closeSidebar();loadChatList();
}

async function deleteChat(cid){
  await fetch(`/chats/${cid}`,{method:'DELETE'});
  if(activeChatId===cid) activeChatId=null;
  await loadChatList();
}

async function exportChat(cid){
  window.open(`/chats/${cid}/export`,'_blank');
}

async function shareChat(cid){
  const d=await fetch(`/chats/${cid}/share`,{method:'POST'}).then(r=>r.json());
  if(d.url){
    const url=location.origin+d.url;
    await navigator.clipboard.writeText(url).catch(()=>{});
    alert(`Share link copied!\n${url}`);
  }
}

// ── PIN CHAT ───────────────────────────────────────────────────────────────────
async function togglePin(cid, currentlyPinned) {
  const newVal = currentlyPinned !== 'true';
  await fetch(`/chats/${cid}/pin`, {method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({pinned: newVal})});
  await loadChatList();
}

window.addEventListener('resize', () => {
  const isMobile = window.matchMedia('(max-width: 700px)').matches;
  const sidebar = document.getElementById('sidebar');
  if(!sidebar) return;
  if(isMobile && sidebarOpen){
    document.getElementById('sidebar-overlay')?.classList.add('active');
  } else {
    document.getElementById('sidebar-overlay')?.classList.remove('active');
  }
});

if(document.readyState === 'loading'){
  document.addEventListener('DOMContentLoaded', restoreSidebarState);
} else {
  restoreSidebarState();
}
