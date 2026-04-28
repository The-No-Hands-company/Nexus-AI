function openCodeRunnerPanel() {
  NexusApi.setPanelOpen("code-runner-panel", true);
}

function closeCodeRunnerPanel() {
  NexusApi.setPanelOpen("code-runner-panel", false);
}

function _codeRunnerSrcdoc(language, code) {
  const escapedCode = JSON.stringify(String(code || ""));
  if (language === "python") {
    return `<!doctype html><html><body style="font-family:ui-monospace,monospace;background:#0f172a;color:#e2e8f0;margin:0;padding:12px"><pre id="out">Loading Pyodide...</pre><script src="https://cdn.jsdelivr.net/pyodide/v0.27.5/full/pyodide.js"></script><script>(async()=>{const out=document.getElementById('out');function log(v){out.textContent += '\\n'+String(v);}try{const pyodide=await loadPyodide();out.textContent='';pyodide.setStdout({batched:(s)=>log(s)});pyodide.setStderr({batched:(s)=>log('[err] '+s)});await pyodide.runPythonAsync(${escapedCode});}catch(e){log(String(e));}})();</script></body></html>`;
  }
  return `<!doctype html><html><body style="font-family:ui-monospace,monospace;background:#0b1220;color:#e2e8f0;margin:0;padding:12px"><pre id="out"></pre><script>const out=document.getElementById('out');const log=(...a)=>{out.textContent += a.map(String).join(' ')+'\\n';};window.console.log=log;window.console.error=(...a)=>log('[err]',...a);try{const result=(function(){${String(code || "")}})();if(result!==undefined)log(result);}catch(e){log('[err]',String(e));}</script></body></html>`;
}

function runSandboxCode() {
  const lang = document.getElementById("cr-lang")?.value || "javascript";
  const code = document.getElementById("cr-code")?.value || "";
  const iframe = document.getElementById("cr-frame");
  const status = document.getElementById("cr-status");
  if (!iframe || !status) return;
  status.textContent = `Running ${lang}...`;
  iframe.srcdoc = _codeRunnerSrcdoc(lang, code);
  setTimeout(() => {
    status.textContent = `${lang} run complete`;
  }, 300);
}
