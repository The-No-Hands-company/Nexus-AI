// ── THEME ──────────────────────────────────────────────────────────────────────
const HLJS_THEME_DARK = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css';
const HLJS_THEME_LIGHT = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-light.min.css';
const BROWSER_THEME_DARK = '#09090e';
const BROWSER_THEME_LIGHT = '#e9edf3';

function normalizeTheme(theme) {
  return theme === 'light' ? 'light' : 'dark';
}

function detectSystemTheme() {
  try {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  } catch (_) {
    return 'dark';
  }
}

function getPreferredTheme() {
  const local = localStorage.getItem('theme');
  return local ? normalizeTheme(local) : detectSystemTheme();
}

function updateThemeControls(theme) {
  const themeBtn = document.getElementById('theme-btn');
  if (themeBtn) {
    themeBtn.textContent = theme === 'dark' ? '☀️' : '🌙';
    themeBtn.title = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
  }

  const lightBtn = document.getElementById('theme-light');
  const darkBtn = document.getElementById('theme-dark');
  if (lightBtn && darkBtn) {
    lightBtn.style.borderColor = theme === 'light' ? 'var(--accent)' : '';
    darkBtn.style.borderColor = theme === 'dark' ? 'var(--accent)' : '';
    lightBtn.style.color = theme === 'light' ? 'var(--text)' : '';
    darkBtn.style.color = theme === 'dark' ? 'var(--text)' : '';
  }
}

function updateBrowserTheme(theme) {
  const themeColor = theme === 'light' ? BROWSER_THEME_LIGHT : BROWSER_THEME_DARK;
  document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => {
    meta.setAttribute('content', themeColor);
  });
}

function updateCodeTheme(theme) {
  const hljsTheme = document.getElementById('hljs-theme-link');
  if (!hljsTheme) return;
  hljsTheme.setAttribute('href', theme === 'light' ? HLJS_THEME_LIGHT : HLJS_THEME_DARK);
}

function applyTheme(theme) {
  const resolvedTheme = normalizeTheme(theme);
  const isLight = resolvedTheme === 'light';

  document.body.classList.toggle('light', isLight);
  document.body.classList.toggle('light-theme', isLight);
  document.body.setAttribute('data-theme', resolvedTheme);
  document.documentElement.style.colorScheme = isLight ? 'light' : 'dark';

  updateThemeControls(resolvedTheme);
  updateBrowserTheme(resolvedTheme);
  updateCodeTheme(resolvedTheme);
}

function persistTheme(theme) {
  localStorage.setItem('theme', theme);
  fetch('/prefs', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({theme}),
  }).catch(() => {});
}

function setTheme(theme, options = {}) {
  const resolvedTheme = normalizeTheme(theme);
  applyTheme(resolvedTheme);
  if (options.persist !== false) persistTheme(resolvedTheme);
}

function toggleTheme() {
  const currentTheme = getPreferredTheme();
  const nextTheme = currentTheme === 'dark' ? 'light' : 'dark';
  setTheme(nextTheme, {persist: true});
  haptic('light');
}

applyTheme(getPreferredTheme());

window.addEventListener('storage', (evt) => {
  if (evt.key === 'theme' && evt.newValue) {
    applyTheme(normalizeTheme(evt.newValue));
  }
});

// ── THEME & FONT SIZE ─────────────────────────────────────────────────────────

function setFontSize(size) {
  document.body.className = document.body.className
    .replace(/\bfs-\d+\b/g, '').trim();
  document.body.classList.add('fs-'+size);
  fetch('/prefs', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({font_size: String(size)})});
}

async function loadPrefs() {
  const d = await fetch('/prefs').then(r=>r.json()).catch(()=>({}));
  if (d.theme) {
    setTheme(d.theme, {persist: false});
    localStorage.setItem('theme', normalizeTheme(d.theme));
  }
  if (d.font_size) setFontSize(parseInt(d.font_size));
}
