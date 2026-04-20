const { app, BrowserWindow, shell, session } = require('electron');
const { URL } = require('node:url');

const DEFAULT_URL = 'http://127.0.0.1:8000';

function errorPageHtml(targetUrl) {
  const safeUrl = String(targetUrl || DEFAULT_URL).replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Nexus AI Desktop</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
    main { max-width: 640px; margin: 8vh auto; padding: 2rem; border: 1px solid #334155; border-radius: 12px; background: #111827; }
    h1 { margin-top: 0; }
    code { background: #1f2937; padding: 0.2rem 0.4rem; border-radius: 4px; }
  </style>
</head>
<body>
  <main>
    <h1>Nexus AI is not reachable</h1>
    <p>The desktop wrapper could not load <code>${safeUrl}</code>.</p>
    <p>Check that the backend is running or set <code>NEXUS_AI_URL</code> to a reachable URL.</p>
  </main>
</body>
</html>`;
}

function getBaseUrl() {
  const raw = (process.env.NEXUS_AI_URL || DEFAULT_URL).trim();
  try {
    const parsed = new URL(raw);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      return new URL(DEFAULT_URL);
    }
    return parsed;
  } catch {
    return new URL(DEFAULT_URL);
  }
}

function isAllowedNavigation(target, allowedOrigin) {
  try {
    return new URL(target).origin === allowedOrigin;
  } catch {
    return false;
  }
}

function createWindow() {
  const baseUrl = getBaseUrl();
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 980,
    minHeight: 680,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedNavigation(url, baseUrl.origin)) {
      return { action: 'allow' };
    }
    shell.openExternal(url).catch(() => {});
    return { action: 'deny' };
  });

  win.webContents.on('will-navigate', (event, url) => {
    if (!isAllowedNavigation(url, baseUrl.origin)) {
      event.preventDefault();
      shell.openExternal(url).catch(() => {});
    }
  });

  win.webContents.on('did-fail-load', (_event, errorCode) => {
    if (errorCode < 0) {
      win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(errorPageHtml(baseUrl.toString()))}`).catch(() => {});
    }
  });

  win.webContents.on('render-process-gone', () => {
    win.reload();
  });

  win.loadURL(baseUrl.toString()).catch(() => {
    win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(errorPageHtml(baseUrl.toString()))}`).catch(() => {});
  });
}

app.whenReady().then(() => {
  app.setAppUserModelId('ai.nexus.desktop');
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(false);
  });

  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
