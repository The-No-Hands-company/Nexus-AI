// ── PWA SERVICE WORKER ────────────────────────────────────────────────────────
if('serviceWorker' in navigator){
  navigator.serviceWorker.register('/sw.js').catch(()=>{});
}
let deferredInstall=null;
window.addEventListener('beforeinstallprompt',e=>{
  e.preventDefault(); deferredInstall=e;
  document.getElementById('install-banner').classList.add('show');
});
document.getElementById('install-btn')?.addEventListener('click',async()=>{
  if(!deferredInstall) return;
  deferredInstall.prompt();
  const {outcome}=await deferredInstall.userChoice;
  deferredInstall=null;
  document.getElementById('install-banner').classList.remove('show');
});
function dismissInstall(){
  document.getElementById('install-banner').classList.remove('show');
  localStorage.setItem('install-dismissed','1');
}
if(localStorage.getItem('install-dismissed')){
  // don't show again this session
}

// ── HAPTIC HELPER ─────────────────────────────────────────────────────────────
function haptic(type='light'){
  if(!navigator.vibrate) return;
  if(type==='light') navigator.vibrate(10);
  else if(type==='medium') navigator.vibrate(25);
  else if(type==='success') navigator.vibrate([10,50,10]);
}

// ── SWIPE TO OPEN SIDEBAR ─────────────────────────────────────────────────────
(()=>{
  let startX=0, startY=0;
  document.addEventListener('touchstart',e=>{
    startX=e.touches[0].clientX;
    startY=e.touches[0].clientY;
  },{passive:true});
  document.addEventListener('touchend',e=>{
    const dx=e.changedTouches[0].clientX-startX;
    const dy=Math.abs(e.changedTouches[0].clientY-startY);
    if(dy>40) return;
    if(dx>60 && startX<40 && !sidebarOpen){toggleSidebar();haptic('light')}
    if(dx<-60 && sidebarOpen){closeSidebar();haptic('light')}
  },{passive:true});
})();

// ── PUSH NOTIFICATIONS (browser) ───────────────────────────────────────────
async function enableTaskNotifications() {
  if (!("Notification" in window)) {
    alert("This browser does not support notifications.");
    return false;
  }
  if (Notification.permission === "granted") {
    addSysMsg("🔔 Task notifications already enabled");
    return true;
  }
  const permission = await Notification.requestPermission();
  const ok = permission === "granted";
  if (ok) addSysMsg("🔔 Task notifications enabled");
  else addSysMsg("🔕 Notification permission denied");
  return ok;
}

function notifyTaskComplete(title, body) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (!document.hidden) return;
  try {
    new Notification(title || "Nexus AI", {
      body: body || "A long-running task has completed.",
      icon: "/static/icon-192.png",
    });
  } catch (_) {
    // best-effort only
  }
}
