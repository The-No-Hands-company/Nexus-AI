console.log("MAIN START");
const { app, BrowserWindow, shell, session, Menu, Tray, nativeImage, powerMonitor, powerSaveBlocker, ipcMain, dialog } = require('electron');
const path = require('node:path');
const { screen } = require('electron');
const fs = require('node:fs');
const net = require('node:net');

const isDev = !app.isPackaged || process.env.NODE_ENV === 'development';

let mainWindow = null;
let tray = null;
let powerSaveBlockerId = null;
let backendUrl = process.env.NEXUS_AI_URL || 'http://127.0.0.1:8000';
process.on("uncaughtException", (err) => { console.error("Uncaught Exception:", err); process.exit(1); });
function getStaticDir() {
  if (app.isPackaged) {
    const resourceStatic = path.join(process.resourcesPath, 'static');
    if (fs.existsSync(resourceStatic)) return resourceStatic;
    const asarStatic = path.join(__dirname, 'static');
    if (fs.existsSync(asarStatic)) return asarStatic;
  }
  return path.join(__dirname, '..', '..', 'static');
}

function checkPort(host, port) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(1500);
    socket.on('connect', () => { socket.destroy(); resolve(true); });
    socket.on('error', () => resolve(false));
    socket.on('timeout', () => { socket.destroy(); resolve(false); });
    socket.connect(port, host);
  });
}

async function checkBackend() {
  try {
    const url = new URL(backendUrl);
    const host = url.hostname || '127.0.0.1';
    const port = parseInt(url.port) || 8000;
    return await checkPort(host, port);
  } catch {
    return false;
  }
}

const createWindow = () => {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;
  const startWidth = Math.min(1280, width - 100);
  const startHeight = Math.min(820, height - 100);

  mainWindow = new BrowserWindow({
    width: startWidth,
    height: startHeight,
    minWidth: 980,
    minHeight: 680,
    center: true,
    title: 'Nexus AI',
    icon: path.join(__dirname, '..', '..', 'static', 'icon-512.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
    },
  });

  loadApp();

  if (isDev) {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on('closed', () => {
    console.log("Window closed");
    mainWindow = null;
  });

  mainWindow.on('minimize', (event) => {
    event.preventDefault();
    mainWindow.hide();
  });

  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  console.log("Window created, ID:", mainWindow.id);
  return mainWindow;
};

async function loadApp() {
  const backendAlive = await checkBackend();
  if (backendAlive) {
    mainWindow.loadURL(backendUrl);
  } else {
    const staticDir = getStaticDir();
    const indexPath = path.join(staticDir, 'index.html');
    if (fs.existsSync(indexPath)) {
      mainWindow.loadFile(indexPath);
      mainWindow.webContents.executeJavaScript(`
        if (typeof window.NexusAPI !== 'undefined') {
          window.NexusAPI.setBackendUrl('${backendUrl}');
        }
      `);
    } else {
      mainWindow.loadURL(backendUrl);
    }
  }
}

const createTray = () => {
  const iconPath = path.join(__dirname, '..', '..', 'static', 'icon-512.png');
  try {
    const icon = nativeImage.createFromPath(iconPath);
    tray = new Tray(icon.resize({ width: 16, height: 16 }));

    const contextMenu = Menu.buildFromTemplate([
      {
        label: 'Show Nexus AI',
        click: () => {
          if (mainWindow) {
            if (mainWindow.isMinimized()) mainWindow.restore();
            if (!mainWindow.isVisible()) mainWindow.show();
          }
        }
      },
      { type: 'separator' },
      {
        label: 'Quit Nexus AI',
        click: () => {
          app.isQuitting = true;
          app.quit();
        }
      }
    ]);

    tray.setToolTip('Nexus AI Assistant');
    tray.setContextMenu(contextMenu);

    tray.on('double-click', () => {
      if (mainWindow) {
        if (mainWindow.isMinimized()) mainWindow.restore();
        if (!mainWindow.isVisible()) mainWindow.show();
      }
    });
  } catch (error) {
    console.error('Failed to create tray icon:', error);
  }
};

const createMenu = () => {
  const isMac = process.platform === 'darwin';

  const template = [
    {
      label: isMac ? 'Nexus AI' : 'File',
      submenu: [
        isMac ? { role: 'about' } : { label: 'About Nexus AI', click: () => shell.openExternal('https://nexus-ai.example.com') },
        isMac ? { type: 'separator' } : { type: 'separator' },
        isMac ? { role: 'services' } : { type: 'separator' },
        isMac ? { type: 'separator' } : { type: 'separator' },
        isMac ? { role: 'hide' } : { label: 'Hide', accelerator: 'CmdOrCtrl+H', role: 'hide' },
        isMac ? { role: 'hideOthers' } : { label: 'Hide Others', accelerator: 'CmdOrCtrl+Shift+H', role: 'hideOthers' },
        isMac ? { role: 'unhide' } : { label: 'Show All', role: 'unhide' },
        isMac ? { type: 'separator' } : { type: 'separator' },
        { label: 'Exit', accelerator: isMac ? 'Cmd+Q' : 'Alt+F4', click: () => { app.quit(); } }
      ]
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        ...(isMac ? [
          { role: 'pasteAndMatchStyle' },
          { role: 'deleteAndSelect' },
          { role: 'selectAll' }
        ] : [
          { role: 'delete' },
          { role: 'selectAll' }
        ])
      ]
    },
    {
      label: 'View',
      submenu: [
        { label: 'Reload', accelerator: 'CmdOrCtrl+R', click: () => { if (mainWindow) mainWindow.reload(); } },
        { label: 'Force Reload', accelerator: 'CmdOrCtrl+Shift+R', click: () => { if (mainWindow) mainWindow.webContents.reloadIgnoringCache(); } },
        { label: 'Toggle Developer Tools', accelerator: 'CmdOrCtrl+Alt+I', click: () => { if (mainWindow) mainWindow.webContents.toggleDevTools(); } },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'zoom' },
        ...(isMac ? [
          { type: 'separator' },
          { role: 'front' },
          { type: 'separator' },
          { role: 'window' }
        ] : [
          { label: 'Bring All to Front', role: 'front' }
        ])
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Learn More About Nexus AI',
          click: () => shell.openExternal('https://nexus-ai.example.com')
        },
        {
          label: 'Check for Updates...',
          click: () => {
            dialog.showMessageBox({
              type: 'info',
              title: 'Check for Updates',
              message: 'Update checking functionality would be implemented here in a production build.',
              buttons: ['OK']
            });
          }
        },
        {
          label: 'Report an Issue',
          click: () => shell.openExternal('https://github.com/your-repo/nexus-ai/issues')
        }
      ]
    }
  ];

  const menu = Menu.buildFromTemplate(template);
  Menu.setApplicationMenu(menu);
};

const setupPowerSaveBlocker = () => {
  powerMonitor.on('on-ac', () => {
    if (!powerSaveBlockerId) {
      try {
        powerSaveBlockerId = powerSaveBlocker.start('prevent-display-sleep');
      } catch (error) {
        console.error('Failed to start power save blocker:', error);
      }
    }
  });

  powerMonitor.on('on-battery', () => {
    if (powerSaveBlockerId) {
      try {
        powerSaveBlocker.stop(powerSaveBlockerId);
        powerSaveBlockerId = null;
      } catch (error) {
        console.error('Failed to stop power save blocker:', error);
      }
    }
  });
};
app.commandLine.appendSwitch("disable-gpu");
app.disableHardwareAcceleration();

app.whenReady().then(() => {
  if (process.platform === 'win32') {
    app.setAppUserModelId('ai.nexus.desktop');
  }

  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === 'microphone' || permission === 'camera') {
      callback(true);
    } else {
      callback(false);
    }
  });

  session.defaultSession.setDevicePermissionHandler((details) => {
    if (details.deviceType === 'audioInput' || details.deviceType === 'videoInput' ||
        details.deviceType === 'audioOutput') {
      return true;
    }
    return false;
  });

  createWindow();
  createTray();
  createMenu();
  setupPowerSaveBlocker();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  console.log("window-all-closed handler called");
  if (process.platform !== 'darwin') {
    if (powerSaveBlockerId) {
      powerSaveBlocker.stop(powerSaveBlockerId);
      powerSaveBlockerId = null;
    }
    app.quit();
  }
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (powerSaveBlockerId) {
    try {
      powerSaveBlocker.stop(powerSaveBlockerId);
      powerSaveBlockerId = null;
    } catch (error) {
      console.error('Error stopping power save blocker:', error);
    }
  }
});

ipcMain.handle('get-app-path', () => app.getAppPath());
ipcMain.handle('get-user-data-path', () => app.getPath('userData'));
ipcMain.handle('is-app-packaged', () => app.isPackaged);
ipcMain.handle('get-backend-url', () => backendUrl);

ipcMain.on('set-backend-url', (_event, url) => {
  try {
    new URL(url);
    backendUrl = url;
  } catch {}
});

ipcMain.on('open-external', (_event, url) => {
  if (typeof url === 'string' && (url.startsWith('http://') || url.startsWith('https://'))) {
    shell.openExternal(url);
  }
});

ipcMain.handle('show-open-dialog', async () => {
  const result = await dialog.showOpenDialog({ properties: ['openFile', 'multiSelections'] });
  return result.filePaths;
});

ipcMain.handle('show-save-dialog', async () => {
  const result = await dialog.showSaveDialog({ properties: ['createDirectory'] });
  return result.filePath;
});

ipcMain.on('minimize-window', () => {
  if (mainWindow) mainWindow.minimize();
});

ipcMain.on('maximize-window', () => {
  if (mainWindow) {
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize();
    } else {
      mainWindow.maximize();
    }
  }
});

ipcMain.on('close-window', () => {
  if (mainWindow) mainWindow.close();
});


// ── Nostack skill IPC handlers ───────────────────────────────────────

const http = require('node:http');
const https = require('node:https');

function nexusRequest(method, path, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, backendUrl);
    const lib = url.protocol === 'https:' ? https : http;
    const payload = body ? JSON.stringify(body) : undefined;
    const options = {
      method, hostname: url.hostname, port: url.port, path: url.pathname,
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    };
    const req = lib.request(options, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve(data); }
      });
    });
    req.on('error', reject);
    if (payload) req.write(payload);
    req.end();
  });
}

ipcMain.handle('nostack-list-skills', async () => {
  try { return await nexusRequest('GET', '/nostack/skills'); }
  catch (e) { return { error: e.message, skills: [], total: 0 }; }
});

ipcMain.handle('nostack-get-skill', async (_event, name) => {
  try { return await nexusRequest('GET', `/nostack/skills/${name}`); }
  catch (e) { return { error: e.message }; }
});

ipcMain.handle('nostack-run-skill', async (_event, name, task) => {
  try {
    return await nexusRequest('POST', `/nostack/skills/${name}/run`, { task: task || '' });
  } catch (e) { return { error: e.message }; }
});

ipcMain.handle('nostack-run-sprint', async (_event, task, skills) => {
  try {
    return await nexusRequest('POST', '/nostack/sprint', { task: task || '', skills: skills || [] });
  } catch (e) { return { error: e.message }; }
});

ipcMain.handle('nexus-chat', async (_event, messages) => {
  try {
    return await nexusRequest('POST', '/v1/chat/completions', {
      model: 'nexus-ai/auto', messages: messages || [], stream: false,
    });
  } catch (e) { return { error: e.message }; }
});

ipcMain.handle('nexus-agent-task', async (_event, task, images) => {
  try {
    return await nexusRequest('POST', '/agent', { task: task || '', images: images || [] });
  } catch (e) { return { error: e.message }; }
});

process.on('uncaughtException', (err) => {
  console.error('Uncaught Exception:', err);
  process.exit(1);
});
process.on('unhandledRejection', (reason, promise) => {
  console.error('Unhandled Rejection:', reason);
  process.exit(1);
});
