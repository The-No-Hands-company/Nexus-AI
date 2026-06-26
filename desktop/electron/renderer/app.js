(function () {
  'use strict';

  const NexusAPI = window.NexusAPI;
  const electronAPI = window.electronAPI;

  let messages = [];
  let generatedImages = [];
  let nostackSkills = [];
  let selectedSkillName = null;
  let connectionPolling = null;

  /* ── DOM refs ────────────────────────────────────────── */

  const el = {
    tabs: document.querySelectorAll('.tab-btn'),
    panels: document.querySelectorAll('.tab-panel'),
    connectionStatus: document.getElementById('connection-status'),
    connectionText: document.querySelector('.status-text'),

    messageList: document.getElementById('message-list'),
    chatInput: document.getElementById('chat-input'),
    chatSendBtn: document.getElementById('chat-send-btn'),
    chatLoading: document.getElementById('chat-loading'),

    skillsGrid: document.getElementById('skills-grid'),
    skillsCount: document.getElementById('skills-count'),
    skillDetails: document.getElementById('skill-details'),
    skillDetailName: document.getElementById('skill-detail-name'),
    skillDetailCommand: document.getElementById('skill-detail-command'),
    skillDetailDesc: document.getElementById('skill-detail-desc'),
    skillTaskInput: document.getElementById('skill-task-input'),
    skillRunBtn: document.getElementById('skill-run-btn'),
    skillRunResult: document.getElementById('skill-run-result'),

    sprintTaskInput: document.getElementById('sprint-task-input'),
    sprintSkillsInput: document.getElementById('sprint-skills-input'),
    sprintRunBtn: document.getElementById('sprint-run-btn'),
    sprintResult: document.getElementById('sprint-result'),

    imagePromptInput: document.getElementById('image-prompt-input'),
    imageGenBtn: document.getElementById('image-gen-btn'),
    imageGenLoading: document.getElementById('image-gen-loading'),
    imagesGrid: document.getElementById('images-grid'),

    settingsBackendUrl: document.getElementById('settings-backend-url'),
    settingsSaveUrl: document.getElementById('settings-save-url'),
    infoVersion: document.getElementById('info-version'),
    infoPlatform: document.getElementById('info-platform'),
    infoElectron: document.getElementById('info-electron'),
    infoPackaged: document.getElementById('info-packaged'),
  };

  /* ── Connection ───────────────────────────────────────── */

  async function checkConnection() {
    try {
      const result = await NexusAPI.checkHealth();
      return result && result.connected;
    } catch (e) {
      return false;
    }
  }

  function updateConnectionStatus(connected) {
    el.connectionStatus.classList.remove('status-connected', 'status-disconnected', 'status-checking');
    if (connected) {
      el.connectionStatus.classList.add('status-connected');
      el.connectionText.textContent = 'Connected';
    } else {
      el.connectionStatus.classList.add('status-disconnected');
      el.connectionText.textContent = 'Disconnected';
    }
  }

  async function pollConnection() {
    el.connectionStatus.classList.add('status-checking');
    el.connectionText.textContent = 'Checking...';
    const ok = await checkConnection();
    updateConnectionStatus(ok);
  }

  function startConnectionPolling() {
    pollConnection();
    connectionPolling = setInterval(pollConnection, 15000);
  }

  /* ── Tabs ─────────────────────────────────────────────── */

  function switchTab(tabName) {
    el.tabs.forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    el.panels.forEach(panel => {
      panel.classList.toggle('active', panel.id === 'tab-' + tabName);
    });

    if (tabName === 'skills') loadSkills();
    if (tabName === 'settings') loadSettings();
  }

  el.tabs.forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  /* ── Chat ─────────────────────────────────────────────── */

  function addMessage(text, sender) {
    const msg = { id: Date.now().toString() + Math.random().toString(36).slice(2, 8), text, sender, timestamp: new Date() };
    messages.push(msg);
    renderMessage(msg);
    el.messageList.scrollTop = el.messageList.scrollHeight;
  }

  function renderMessage(msg) {
    const div = document.createElement('div');
    div.className = 'message ' + msg.sender + '-msg';
    div.dataset.id = msg.id;
    const p = document.createElement('p');
    p.textContent = msg.text;
    div.appendChild(p);
    el.messageList.appendChild(div);
  }

  function showChatLoading(show) {
    el.chatLoading.classList.toggle('hidden', !show);
  }

  function clearWelcome() {
    const welcome = el.messageList.querySelector('.welcome-msg');
    if (welcome) welcome.remove();
  }

  async function sendMessage() {
    const text = el.chatInput.value.trim();
    if (!text) return;

    clearWelcome();
    el.chatInput.value = '';
    addMessage(text, 'user');
    showChatLoading(true);

    try {
      const apiMessages = [{ role: 'user', content: text }];
      const result = await NexusAPI.chat(apiMessages);
      if (result.error) {
        addMessage('Error: ' + result.error, 'system');
      } else {
        const content = result.choices?.[0]?.message?.content || JSON.stringify(result);
        addMessage(content, 'assistant');
      }
    } catch (e) {
      addMessage('Request failed: ' + e.message, 'system');
    } finally {
      showChatLoading(false);
    }
  }

  el.chatSendBtn.addEventListener('click', sendMessage);
  el.chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  /* ── Skills ───────────────────────────────────────────── */

  async function loadSkills() {
    try {
      const result = await NexusAPI.listSkills();
      if (result.error) {
        el.skillsGrid.innerHTML = '<div class="skills-placeholder">Failed to load skills: ' + result.error + '</div>';
        el.skillsCount.textContent = '';
        return;
      }
      nostackSkills = result.skills || [];
      el.skillsCount.textContent = nostackSkills.length + ' skills';
      renderSkillsGrid();
    } catch (e) {
      el.skillsGrid.innerHTML = '<div class="skills-placeholder">Failed to load skills: ' + e.message + '</div>';
      el.skillsCount.textContent = '';
    }
  }

  function renderSkillsGrid() {
    if (nostackSkills.length === 0) {
      el.skillsGrid.innerHTML = '<div class="skills-placeholder">No skills available.</div>';
      return;
    }
    el.skillsGrid.innerHTML = '';
    nostackSkills.forEach(skill => {
      const card = document.createElement('div');
      card.className = 'skill-card';
      card.innerHTML =
        '<div class="skill-card-name">' + escapeHtml(skill.name || skill.command) + '</div>' +
        '<div class="skill-card-command">' + escapeHtml(skill.command || '') + '</div>' +
        '<div class="skill-card-desc">' + escapeHtml(skill.description || '') + '</div>';
      card.addEventListener('click', () => selectSkill(skill));
      el.skillsGrid.appendChild(card);
    });
  }

  function selectSkill(skill) {
    selectedSkillName = skill.command ? skill.command.replace(/^\//, '') : skill.name;
    el.skillDetails.classList.remove('hidden');
    el.skillDetailName.textContent = skill.name || skill.command;
    el.skillDetailCommand.textContent = skill.command || '';
    el.skillDetailDesc.textContent = skill.description || '';
    el.skillTaskInput.value = '';
    el.skillRunResult.classList.add('hidden');

    document.querySelectorAll('.skill-card').forEach(c => c.classList.remove('selected'));
    const target = document.querySelector('.skill-card-command');
    const cards = document.querySelectorAll('.skill-card');
    cards.forEach(c => {
      if (c.querySelector('.skill-card-command').textContent === (skill.command || '')) {
        c.classList.add('selected');
      }
    });
  }

  async function runSelectedSkill() {
    const task = el.skillTaskInput.value.trim();
    if (!task || !selectedSkillName) return;

    el.skillRunBtn.disabled = true;
    el.skillRunResult.classList.add('hidden');
    try {
      const result = await NexusAPI.runSkill(selectedSkillName, task);
      showRunResult(el.skillRunResult, result);
    } catch (e) {
      showRunResult(el.skillRunResult, { error: e.message });
    } finally {
      el.skillRunBtn.disabled = false;
    }
  }

  el.skillRunBtn.addEventListener('click', runSelectedSkill);

  async function runSprint() {
    const task = el.sprintTaskInput.value.trim();
    const skillsRaw = el.sprintSkillsInput.value.trim();
    if (!task || !skillsRaw) return;

    const skills = skillsRaw.split(',').map(s => s.trim()).filter(Boolean);
    if (skills.length === 0) return;

    el.sprintRunBtn.disabled = true;
    el.sprintResult.classList.add('hidden');
    try {
      const result = await NexusAPI.runSprint(task, skills);
      showRunResult(el.sprintResult, result);
    } catch (e) {
      showRunResult(el.sprintResult, { error: e.message });
    } finally {
      el.sprintRunBtn.disabled = false;
    }
  }

  el.sprintRunBtn.addEventListener('click', runSprint);

  function showRunResult(container, result) {
    container.classList.remove('hidden', 'success', 'error');
    if (result.error) {
      container.classList.add('error');
      container.textContent = 'Error: ' + result.error;
    } else {
      container.classList.add('success');
      container.textContent = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
    }
  }

  /* ── Images ───────────────────────────────────────────── */

  async function generateImage() {
    const prompt = el.imagePromptInput.value.trim();
    if (!prompt) return;

    el.imageGenBtn.disabled = true;
    el.imageGenLoading.classList.remove('hidden');

    try {
      const result = await NexusAPI.agentTask('Generate an image: ' + prompt, []);
      const imgData = result.result || result.image || (typeof result === 'string' ? result : JSON.stringify(result));
      const img = {
        id: Date.now().toString(),
        data: imgData,
        timestamp: Date.now(),
        prompt: prompt,
      };
      generatedImages.push(img);
      renderImagesGrid();
    } catch (e) {
      const img = {
        id: Date.now().toString(),
        data: null,
        timestamp: Date.now(),
        prompt: prompt,
        error: e.message,
      };
      generatedImages.push(img);
      renderImagesGrid();
    } finally {
      el.imageGenBtn.disabled = false;
      el.imageGenLoading.classList.add('hidden');
      el.imagePromptInput.value = '';
    }
  }

  el.imageGenBtn.addEventListener('click', generateImage);
  el.imagePromptInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      generateImage();
    }
  });

  function renderImagesGrid() {
    if (generatedImages.length === 0) {
      el.imagesGrid.innerHTML = '<div class="images-placeholder">No images generated yet.</div>';
      return;
    }
    el.imagesGrid.innerHTML = '';
    generatedImages.slice().reverse().forEach(img => {
      const card = document.createElement('div');
      card.className = 'image-card';
      if (img.error) {
        card.innerHTML =
          '<div style="aspect-ratio:1;display:flex;align-items:center;justify-content:center;color:var(--danger);font-size:12px;padding:12px;text-align:center;">Error: ' +
          escapeHtml(img.error) + '</div>' +
          '<div class="image-card-info"><div class="image-card-prompt">' + escapeHtml(img.prompt) + '</div></div>';
      } else {
        card.innerHTML =
          '<img src="' + escapeAttr(img.data) + '" alt="' + escapeAttr(img.prompt) + '" loading="lazy" />' +
          '<div class="image-card-info"><div class="image-card-prompt">' + escapeHtml(img.prompt) + '</div>' +
          '<div class="image-card-time">' + new Date(img.timestamp).toLocaleString() + '</div></div>';
      }
      el.imagesGrid.appendChild(card);
    });
  }

  /* ── Settings ─────────────────────────────────────────── */

  async function loadSettings() {
    try {
      const url = await NexusAPI.getBackendUrl();
      el.settingsBackendUrl.value = url || '';
    } catch (e) {
      el.settingsBackendUrl.value = '';
    }
    try {
      const platform = electronAPI.getPlatform();
      el.infoPlatform.textContent = platform;
    } catch (e) {
      el.infoPlatform.textContent = '—';
    }
    try {
      el.infoElectron.textContent = navigator.userAgent.match(/Electron\/([\d.]+)/)?.[1] || '—';
    } catch (e) {
      el.infoElectron.textContent = '—';
    }
    try {
      const packaged = await electronAPI.isAppPackaged();
      el.infoPackaged.textContent = packaged ? 'Yes' : 'No (dev)';
    } catch (e) {
      el.infoPackaged.textContent = '—';
    }
    try {
      const version = electronAPI.getAppVersion();
      el.infoVersion.textContent = version || '—';
    } catch (e) {
      el.infoVersion.textContent = '—';
    }
  }

  el.settingsSaveUrl.addEventListener('click', async () => {
    const url = el.settingsBackendUrl.value.trim();
    if (!url) return;
    try {
      new URL(url);
      NexusAPI.setBackendUrl(url);
      const saved = document.createElement('span');
      saved.textContent = ' Saved!';
      saved.style.cssText = 'color:var(--success);font-size:12px;margin-left:8px;';
      el.settingsSaveUrl.parentNode.appendChild(saved);
      setTimeout(() => saved.remove(), 2000);
      pollConnection();
    } catch (e) { /* ignore invalid URL */ }
  });

  /* ── Utilities ────────────────────────────────────────── */

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function escapeAttr(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /* ── Init ─────────────────────────────────────────────── */

  function init() {
    startConnectionPolling();
    switchTab('chat');
    el.chatInput.focus();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
