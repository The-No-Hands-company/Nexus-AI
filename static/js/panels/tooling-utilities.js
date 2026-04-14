// Tooling utility module (static split from index.html)
let _retryTask = null;
let _retryTimer = null;
let _retryCountdown = 0;

const artifactItems = [];
let activeArtifactIdx = 0;
let _ttsUtterance = null;

function showRateLimitToast(errorMsg, originalTask) {
  _retryTask = originalTask;
  const toast = document.getElementById("rate-toast");
  const cdMatch = errorMsg.match(/(\d+)s/);
  _retryCountdown = cdMatch ? parseInt(cdMatch[1], 10) : 60;

  renderToast();
  toast.classList.add("visible");

  clearInterval(_retryTimer);
  _retryTimer = setInterval(() => {
    _retryCountdown -= 1;
    if (_retryCountdown <= 0) {
      clearInterval(_retryTimer);
      hideRateLimitToast();
      if (_retryTask) {
        ta.value = _retryTask;
        send();
      }
    } else {
      renderToast();
    }
  }, 1000);
}

function renderToast() {
  const toast = document.getElementById("rate-toast");
  const available = _retryCountdown;
  toast.innerHTML = `
    <span class="toast-icon">⏳</span>
    <div class="toast-text">
      <strong>All providers are cooling down.</strong>
      Retrying automatically in <strong>${available}s</strong> -
      or <a href="#" onclick="event.preventDefault();hideRateLimitToast();openHealthModal()" style="color:var(--amber)">check provider status</a>.
    </div>
    <button class="toast-retry" onclick="retryNow()">Retry now</button>
    <button class="toast-dismiss" onclick="hideRateLimitToast()">×</button>
  `;
}

function hideRateLimitToast() {
  clearInterval(_retryTimer);
  const toast = document.getElementById("rate-toast");
  toast.classList.remove("visible");
  _retryTask = null;
}

function retryNow() {
  clearInterval(_retryTimer);
  hideRateLimitToast();
  if (_retryTask) {
    ta.value = _retryTask;
    send();
  }
}

function openArtifactPanel(title, content, mimeType = "text/html") {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const id = "ap-" + Date.now();
  artifactItems.push({ id, title, url, content });
  activeArtifactIdx = artifactItems.length - 1;
  renderArtifactPanel();
  document.getElementById("artifact-panel").classList.add("open");
}

function renderArtifactPanel() {
  const tabs = document.getElementById("artifact-tabs");
  const body = document.getElementById("artifact-panel-body");
  tabs.innerHTML = artifactItems.map((a, i) =>
    `<button class="artifact-tab ${i === activeArtifactIdx ? "active" : ""}" onclick="switchArtifact(${i})">${esc(a.title)}</button>`
  ).join("");
  body.innerHTML = artifactItems.map((a, i) =>
    `<div class="artifact-iframe-wrap ${i === activeArtifactIdx ? "active" : ""}" id="${a.id}"><iframe src="${a.url}" sandbox="allow-scripts allow-same-origin"></iframe></div>`
  ).join("");
}

function switchArtifact(idx) {
  activeArtifactIdx = idx;
  renderArtifactPanel();
}

function toggleArtifactPanel() {
  document.getElementById("artifact-panel").classList.toggle("open");
}

function openArtifactExternal() {
  const a = artifactItems[activeArtifactIdx];
  if (a) window.open(a.url, "_blank");
}

(() => {
  const dragger = document.getElementById("dragger");
  const panel = document.getElementById("artifact-panel");
  let dragging = false;
  let startX = 0;
  let startW = 0;
  dragger.addEventListener("mousedown", (e) => {
    dragging = true;
    startX = e.clientX;
    startW = panel.offsetWidth;
    dragger.classList.add("dragging");
    e.preventDefault();
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const delta = startX - e.clientX;
    const newW = Math.max(220, Math.min(startW + delta, window.innerWidth * 0.65));
    panel.style.width = newW + "px";
  });
  document.addEventListener("mouseup", () => {
    dragging = false;
    dragger.classList.remove("dragging");
  });
})();

function addMessageActions(wrap, role, content, rowEl) {
  const actions = document.createElement("div");
  actions.className = "msg-actions";

  if (role === "user") {
    const editBtn = document.createElement("button");
    editBtn.className = "msg-action-btn";
    editBtn.textContent = "✏️ Edit";
    editBtn.onclick = () => {
      ta.value = content;
      ta.dispatchEvent(new Event("input"));
      ta.focus();
      const msgs = document.getElementById("messages");
      const nodes = [...msgs.children];
      const idx = nodes.indexOf(rowEl);
      nodes.slice(idx).forEach((n) => {
        if (n.id !== "typing") n.remove();
      });
    };
    actions.appendChild(editBtn);
  }

  if (role === "agent") {
    const retryBtn = document.createElement("button");
    retryBtn.className = "msg-action-btn";
    retryBtn.textContent = "↺ Retry";
    retryBtn.onclick = () => {
      const msgs = document.getElementById("messages");
      const userRows = [...msgs.querySelectorAll(".msg-row.user")];
      if (!userRows.length) return;
      const last = userRows[userRows.length - 1].querySelector(".bubble");
      if (last) {
        rowEl.remove();
        ta.value = last.innerText.trim();
        send();
      }
    };

    const ttsBtn = document.createElement("button");
    ttsBtn.className = "msg-action-btn";
    ttsBtn.textContent = "🔊";
    ttsBtn.title = "Read aloud";
    ttsBtn.onclick = () => toggleTTS(ttsBtn, content);
    actions.appendChild(retryBtn);
    actions.appendChild(ttsBtn);
  }

  wrap.appendChild(actions);
}

function toggleTTS(btn, text) {
  if (!window.speechSynthesis) return;
  if (window.speechSynthesis.speaking) {
    window.speechSynthesis.cancel();
    document.querySelectorAll(".tts-active").forEach((b) => b.classList.remove("tts-active"));
    if (_ttsUtterance && _ttsUtterance._btn === btn) return;
  }
  const clean = text.replace(/[#*`_~>]/g, "").trim();
  const utt = new SpeechSynthesisUtterance(clean);
  utt._btn = btn;
  utt.rate = 1.05;
  utt.onend = () => btn.classList.remove("tts-active");
  utt.onerror = () => btn.classList.remove("tts-active");
  _ttsUtterance = utt;
  btn.classList.add("tts-active");
  window.speechSynthesis.speak(utt);
}
