// ── ARTIFACT RENDERER ──────────────────────────────────────────────────────
function makeArtifact(path, content){
  const id='artifact-'+(++artifactCount);
  const blob=new Blob([content],{type:'text/html'});
  const url=URL.createObjectURL(blob);
  const ext=(path||'').split('.').pop()||'html';
  return `<div class="artifact-wrap">
    <div class="artifact-header">
      <span>✨ ${esc(path||'artifact.html')}</span>
      <div class="artifact-actions">
        <button class="artifact-btn" onclick="toggleArtifact('${id}')">⤢ Expand</button>
        <button class="artifact-btn" onclick="window.open('${url}','_blank')">↗ Open</button>
        <button class="artifact-btn" onclick="copyArtifact('${id}')">⎘ Copy</button>
      </div>
    </div>
    <iframe id="${id}" class="artifact-frame" src="${url}" sandbox="allow-scripts allow-same-origin"></iframe>
  </div>`;
}
function toggleArtifact(id){
  const f=document.getElementById(id);
  f.classList.toggle('expanded');
  f.style.maxHeight=f.classList.contains('expanded')?'800px':'500px';
}
function copyArtifact(id){
  const f=document.getElementById(id);
  const src=f.srcdoc||'';
  navigator.clipboard.writeText(src).catch(()=>{});
}

function addSysMsg(text){
  const msgs=document.getElementById('messages'),typing=document.getElementById('typing');
  const el=document.createElement('div');el.className='sys-msg';el.textContent=text;
  msgs.insertBefore(el,typing);scrollBottom();
}
