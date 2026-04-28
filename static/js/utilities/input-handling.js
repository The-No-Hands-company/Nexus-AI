// ── VOICE INPUT ────────────────────────────────────────────────────────────────
function setupVoice(){
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){
    document.getElementById('voice-btn').style.opacity='.3';
    document.getElementById('voice-btn').title='Voice not supported in this browser';
    return;
  }
  voiceRecognition=new SR();
  voiceRecognition.continuous=false;
  voiceRecognition.interimResults=true;
  voiceRecognition.lang='en-US';

  voiceRecognition.onresult=e=>{
    let interim='',final='';
    for(const r of e.results){
      if(r.isFinal) final+=r[0].transcript;
      else interim+=r[0].transcript;
    }
    ta.value=(final||interim).trim();
    ta.dispatchEvent(new Event('input'));
  };
  voiceRecognition.onend=()=>setListening(false);
  voiceRecognition.onerror=()=>setListening(false);
}
function toggleVoice(){
  if(!voiceRecognition) return;
  if(isListening){voiceRecognition.stop();setListening(false)}
  else{voiceRecognition.start();setListening(true)}
}
function setListening(v){
  isListening=v;
  document.getElementById('voice-btn').classList.toggle('listening',v);
}

// ── TEXTAREA ───────────────────────────────────────────────────────────────────
var ta=document.getElementById('task');
ta.addEventListener('input',()=>{ta.style.height='auto';ta.style.height=Math.min(ta.scrollHeight,130)+'px'});
ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
ta.addEventListener('paste', async (e) => {
  const cb = e.clipboardData;
  if (!cb || !cb.items) return;

  const imageFiles = [];
  for (const item of cb.items) {
    if (item.kind === 'file' && item.type && item.type.startsWith('image/')) {
      const f = item.getAsFile();
      if (f) imageFiles.push(f);
    }
  }

  if (!imageFiles.length) return;

  // Keep pasted text behavior untouched when no image is present.
  e.preventDefault();
  await processFiles(imageFiles);
});
function fillTask(t){ta.value=t;ta.dispatchEvent(new Event('input'));ta.focus();if(drawerOpen)toggleDrawer()}

// ── FILE HANDLING ──────────────────────────────────────────────────────────────
function setupDrop(){
  const ov=document.getElementById('drop-overlay');let dc=0;
  document.addEventListener('dragenter',e=>{if(e.dataTransfer?.types.includes('Files')){dc++;ov.classList.add('active')}});
  document.addEventListener('dragleave',()=>{if(--dc<=0){dc=0;ov.classList.remove('active')}});
  document.addEventListener('dragover',e=>e.preventDefault());
  document.addEventListener('drop',e=>{e.preventDefault();dc=0;ov.classList.remove('active');
    if(e.dataTransfer?.files?.length) processFiles(Array.from(e.dataTransfer.files))});
}
function handleFileInput(e){processFiles(Array.from(e.target.files));e.target.value=''}
const TEXT_EXTS=new Set(['txt','md','js','ts','jsx','tsx','py','json','yaml','yml',
  'toml','html','css','sh','go','rs','rb','php','java','c','cpp','h','sql']);
async function processFiles(list){
  for(const f of list){
    const ext=f.name.split('.').pop()?.toLowerCase()||'';
    if(f.type.startsWith('image/')){
      attachedFiles.push({name:f.name,type:f.type,content:await readB64(f)});
    } else {
      try{attachedFiles.push({name:f.name,type:'text/plain',content:await readTxt(f)})}
      catch{alert(`Can't read: ${f.name}`);continue}
    }
  }
  renderFileChips();
}
const readTxt=f=>new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result);r.onerror=()=>rej(r.error);r.readAsText(f)});
const readB64=f=>new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result.split(',')[1]);r.onerror=()=>rej(r.error);r.readAsDataURL(f)});
function renderFileChips(){
  const w=document.getElementById('file-chips');
  if(!attachedFiles.length){w.style.display='none';return}
  w.style.display='flex';
  w.innerHTML=attachedFiles.map((f,i)=>
    `<div class="file-chip">${f.type.startsWith('image/')?'🖼️':'📄'}
     <span class="fname">${esc(f.name)}</span>
     <span class="rm" onclick="removeFile(${i})">×</span></div>`).join('');
}
function removeFile(i){attachedFiles.splice(i,1);renderFileChips()}
