// Safety audit and scanner panel module (static split from index.html)
let _auditEvents = [];

async function openSafetyAudit() {
  document.getElementById("audit-modal").classList.add("open");
  await loadAuditLog();
}

function closeAuditModal() {
  document.getElementById("audit-modal").classList.remove("open");
}

async function loadAuditLog() {
  const filter = document.getElementById("audit-filter")?.value || "";
  const severity = document.getElementById("audit-severity")?.value || "";
  let url = "/safety/audit?limit=500";
  if (filter === "session" && sid) {
    url += `&session_id=${encodeURIComponent(sid)}`;
  } else if (filter && filter !== "session") {
    url += `&event_type=${encodeURIComponent(filter)}`;
  }
  if (severity) {
    url += `&severity=${encodeURIComponent(severity)}`;
  }
  const data = await fetch(url).then((r) => r.json()).catch(() => ({ events: [], total: 0, filtered: false }));
  if (data?.type === "validation_error") {
    document.getElementById("audit-list").innerHTML = `<span style="color:var(--red);font-size:.76rem">${esc(data.error || "Invalid audit filter")}</span>`;
    return;
  }
  _auditEvents = data.events || [];
  const sessionEvents = (filter === "session" && data.filtered)
    ? (data.total || 0)
    : _auditEvents.filter((e) => e.session || e.session_id).length;
  document.getElementById("audit-session-count").textContent = `${sessionEvents} session events`;
  document.getElementById("audit-count").textContent = `${_auditEvents.length} of ${data.total || 0} events`;
  renderAuditList();
}

function renderAuditList() {
  const filter = document.getElementById("audit-filter").value;
  const list = document.getElementById("audit-list");
  const events = (filter === "session" && !sid)
    ? _auditEvents.filter((e) => e.session || e.session_id)
    : _auditEvents;
  if (!events.length) {
    list.innerHTML = '<span style="color:var(--muted);font-size:.76rem">No events yet.</span>';
    return;
  }
  list.innerHTML = [...events].reverse().map((e) => {
    const d = new Date(e.ts * 1000);
    const time = d.toLocaleTimeString() + " " + d.toLocaleDateString();
    let detail = "";
    if (e.type === "block") {
      const reason = e.verdict?.issues?.[0]?.reason || e.verdict?.reason || e.verdict?.action || "blocked";
      detail = `<b>${e.tool || "input"}</b> — ${reason} <span style="color:var(--muted)">[${e.profile || "?"}]</span>`;
      if (e.scope) detail += ` <span style="color:var(--muted)">(${esc(e.scope)})</span>`;
      if (e.label) detail += `<div style="color:var(--muted);margin-top:2px;font-size:.64rem">${esc(e.label.slice(0, 120))}</div>`;
    } else if (e.type === "profile_change") {
      if (e.scope === "session") {
        detail = `Session <code>${esc(e.session_id || "?")}</code> → <b>${e.profile || "?"}</b>${e.overridden ? "" : " (cleared to global)"}`;
      } else {
        detail = `Global profile changed: <b>${e.from || "?"}</b> → <b>${e.to || "?"}</b>`;
      }
    } else if (e.type === "pii_scrub") {
      detail = `${e.count || "?"} item(s) scrubbed` + (e.scope ? ` <span style="color:var(--muted)">(${esc(e.scope)})</span>` : "");
      if (e.label) detail += `<div style="color:var(--muted);margin-top:2px;font-size:.64rem">${esc(e.label.slice(0, 120))}</div>`;
    } else {
      detail = JSON.stringify(e).slice(0, 120);
    }
    const sev = (e.severity || "none").toLowerCase();
    return `<div class="audit-event ${e.type}">
      <span class="ae-type">${e.type}</span>
      <span class="ae-sev ${sev}">${sev}</span>
      ${detail}
      <div class="ae-time">${time}</div>
    </div>`;
  }).join("");
}

function openSafetyScanner() {
  document.getElementById("safety-scanner-modal").classList.add("open");
}

function closeSafetyScanner() {
  document.getElementById("safety-scanner-modal").classList.remove("open");
}

function useScannerRewrite(text) {
  const ta = document.getElementById("scanner-input");
  if (!ta) return;
  ta.value = text;
  ta.focus();
}

async function runSafetyScanner() {
  const text = (document.getElementById("scanner-input")?.value || "").trim();
  const explain = !!document.getElementById("scanner-explain")?.checked;
  const out = document.getElementById("scanner-result");
  if (!text) {
    out.innerHTML = '<span style="color:var(--red)">Enter text to scan.</span>';
    return;
  }

  out.innerHTML = '<span style="color:var(--muted)">Scanning...</span>';
  const payload = await fetch("/safety/prompt-injection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, explain }),
  }).then((r) => r.json()).catch(() => null);

  if (!payload) {
    out.innerHTML = '<span style="color:var(--red)">Scanner request failed.</span>';
    return;
  }
  if (payload.type === "validation_error") {
    out.innerHTML = `<span style="color:var(--red)">${esc(payload.error || "Validation error")}</span>`;
    return;
  }

  const statusColor = payload.detected ? "var(--red)" : "var(--teal)";
  let html = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
      <span style="font-weight:700;color:${statusColor}">${payload.detected ? "Injection detected" : "No injection detected"}</span>
      <span style="font-size:.68rem;color:var(--muted)">threat: ${esc(payload.threat || "none")}</span>
    </div>
  `;

  if (payload.issues?.length) {
    html += `<div style="margin-bottom:8px"><b>Matched issues:</b><ul style="margin:4px 0 0 16px">`
      + payload.issues.map((i) => `<li>${esc(i.reason || i.code || "rule")}</li>`).join("")
      + "</ul></div>";
  }

  if (payload.explain) {
    const safer = payload.explain.safer_rewrite || "";
    html += `
      <div style="margin-bottom:6px"><b>Rule explain:</b></div>
      <div style="font-size:.72rem;color:var(--muted);margin-bottom:8px">${esc((payload.explain.matched_patterns || []).join(", ") || "No pattern details")}</div>
      <div><b>Safer rewrite:</b></div>
      <div style="margin:4px 0 8px 0;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg)">${esc(safer)}</div>
      <button class="btn-ghost" onclick="useScannerRewrite(${JSON.stringify(safer)})">Use safer rewrite</button>
    `;
  }

  out.innerHTML = html;
}