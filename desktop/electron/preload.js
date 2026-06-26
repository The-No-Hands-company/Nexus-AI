const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    getAppPath: () => ipcRenderer.invoke('get-app-path'),
    getUserDataPath: () => ipcRenderer.invoke('get-user-data-path'),

    showOpenDialog: () => ipcRenderer.invoke('show-open-dialog'),
    showSaveDialog: () => ipcRenderer.invoke('show-save-dialog'),

    isAppPackaged: () => ipcRenderer.invoke('is-app-packaged'),
    getPlatform: () => process.platform,
    getAppVersion: () => process.versions.electron,

    openExternal: (url) => ipcRenderer.send('open-external', url),

    onAppEvent: (callback) => {
        const handler = (event, ...args) => callback(...args);
        ipcRenderer.on('app-event', handler);
        return () => ipcRenderer.removeListener('app-event', handler);
    },

    minimizeWindow: () => ipcRenderer.send('minimize-window'),
    maximizeWindow: () => ipcRenderer.send('maximize-window'),
    closeWindow: () => ipcRenderer.send('close-window'),
});

contextBridge.exposeInMainWorld('NexusAPI', {
    getBackendUrl: () => ipcRenderer.invoke('get-backend-url'),
    setBackendUrl: (url) => ipcRenderer.send('set-backend-url', url),

    // nostack skill API
    listSkills: () => ipcRenderer.invoke('nostack-list-skills'),
    getSkill: (name) => ipcRenderer.invoke('nostack-get-skill', name),
    runSkill: (name, task) => ipcRenderer.invoke('nostack-run-skill', name, task),
    runSprint: (task, skills) => ipcRenderer.invoke('nostack-run-sprint', task, skills),

    // Chat API
    chat: (messages) => ipcRenderer.invoke('nexus-chat', messages),
    agentTask: (task, images) => ipcRenderer.invoke('nexus-agent-task', task, images),
});
