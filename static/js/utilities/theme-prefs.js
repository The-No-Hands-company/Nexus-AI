// ── THEME ──────────────────────────────────────────────────────────────────────
let isDark = localStorage.getItem('theme') !== 'light';
function applyTheme() {
  document.body.classList.toggle('light', !isDark);
  document.getElementById('theme-btn').textContent = isDark ? '☀️' : '🌙';
}
function toggleTheme() {
  isDark = !isDark;
  localStorage.setItem('theme', isDark ? 'dark' : 'light');
  applyTheme(); haptic('light');
}
applyTheme();

// ── THEME & FONT SIZE ─────────────────────────────────────────────────────────
function setTheme(theme) {
  document.body.classList.toggle('light-theme', theme === 'light');
  fetch('/prefs', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({theme})});
  document.getElementById('theme-light').style.borderColor = theme==='light' ? 'var(--accent)' : '';
  document.getElementById('theme-dark').style.borderColor  = theme==='dark'  ? 'var(--accent)' : '';
  document.getElementById('theme-light').style.color = theme==='light' ? 'var(--text)' : '';
  document.getElementById('theme-dark').style.color  = theme==='dark'  ? 'var(--text)' : '';
}

function setFontSize(size) {
  document.body.className = document.body.className
    .replace(/\bfs-\d+\b/g, '').trim();
  document.body.classList.add('fs-'+size);
  fetch('/prefs', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({font_size: String(size)})});
}

async function loadPrefs() {
  const d = await fetch('/prefs').then(r=>r.json()).catch(()=>({}));
  if (d.theme) setTheme(d.theme);
  if (d.font_size) setFontSize(parseInt(d.font_size));
}
