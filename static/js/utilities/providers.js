// Provider utilities split from index.html
async function refreshProviders() {
  const d = await fetch("/providers").then((r) => r.json()).catch(() => null);
  if (d) {
    window._providerCache = d.providers || [];
    updateProviderUI(d.providers || []);
  }
  await loadFreeDiagnostics();
}

function updateProviderUI(providers) {
  const ready = providers.filter((p) => p.available).length;
  const cooling = providers.filter((p) => p.rate_limited).length;
  document.getElementById("provider-label").textContent =
    `${ready} ready${cooling ? ` · ${cooling} cooling` : ""}`;
  renderProviderGrid(providers);
}

function renderProviderGrid(providers) {
  const g = document.getElementById("p-grid");
  if (!providers.length) {
    g.innerHTML = '<span style="color:var(--muted);font-size:.76rem">No providers.</span>';
    return;
  }
  let i = 1;
  g.innerHTML = providers.map((p) => {
    let dotC;
    let cardC;
    let badge;
    if (!p.has_key && !p.keyless) {
      dotC = "d-nokey";
      cardC = "c-nokey";
      badge = '<span class="p-badge b-nokey">No key</span>';
    } else if (p.rate_limited) {
      dotC = "d-cooling";
      cardC = "c-cooling";
      badge = `<span class="p-badge b-cooling">${p.cooldown_remaining}s</span>`;
    } else if (p.keyless) {
      dotC = "d-keyless";
      cardC = "";
      badge = '<span class="p-badge b-free">Free</span>';
    } else {
      dotC = "d-ready";
      cardC = "";
      badge = '<span class="p-badge b-free">Ready</span>';
    }
    const num = p.available ? `<span style="color:var(--muted);font-size:.58rem;margin-right:2px">#${i++}</span>` : "";
    return `<div class="p-card ${cardC}"><div class="p-dot ${dotC}"></div>
      <div class="p-info"><div class="p-name">${num}${p.label}</div>
      <div class="p-model">${p.model}</div></div>${badge}</div>`;
  }).join("");
}

async function loadFreeDiagnostics() {
  const grid = document.getElementById("p-grid");
  if (!grid) return;

  let panel = document.getElementById("free-diagnostics-panel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "free-diagnostics-panel";
    panel.style.cssText = "margin-top:8px;border:1px solid var(--border);border-radius:10px;padding:8px;background:var(--surface2);font-size:.74rem;";
    grid.insertAdjacentElement("afterend", panel);
  }

  const data = await fetch("/providers/free-diagnostics").then((r) => r.json()).catch(() => null);
  if (!data || !Array.isArray(data.providers)) {
    panel.innerHTML = '<div style="color:var(--muted)">Free diagnostics unavailable.</div>';
    return;
  }

  const summary = data.summary || {};
  const usable = data.providers.filter((p) => p.currently_usable).slice(0, 6);
  const blocked = data.providers.filter((p) => !p.currently_usable).slice(0, 6);
  const modeLabel = data.free_only_mode ? "ON" : "OFF";

  panel.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
      <strong>Free Model Diagnostics</strong>
      <span style="color:${data.free_only_mode ? 'var(--teal)' : 'var(--amber)'}">FREE_ONLY_MODE ${modeLabel}</span>
    </div>
    <div style="display:flex;gap:10px;color:var(--muted);margin-bottom:6px;">
      <span>Configured: ${summary.configured || 0}</span>
      <span>Free-usable: ${summary.free_usable || 0}</span>
      <span>Usable now: ${summary.currently_usable || 0}</span>
    </div>
    <div style="margin-bottom:6px;color:var(--muted);">
      Strict clone bypasses: <strong style="color:var(--text)">${summary.strict_clone_bypass_count || 0}</strong>
      <span style="margin-left:4px;">(${esc((data.strict_clone_bypass && data.strict_clone_bypass.window) || 'database_persistent_total')})</span>
      <span style="margin-left:6px;">retained: ${Number((data.strict_clone_bypass && data.strict_clone_bypass.retained_window_count) || 0)}</span>
    </div>
    <div style="margin-bottom:4px;"><strong>Usable now</strong></div>
    <div>${usable.length ? usable.map((p) => `• ${esc(p.label)} (${esc(p.model || "n/a")})`).join("<br>") : '<span style="color:var(--muted)">None</span>'}</div>
    <div style="margin:7px 0 4px;"><strong>Blocked</strong></div>
    <div>${blocked.length ? blocked.map((p) => `• ${esc(p.label)} — ${(p.reasons || []).join(", ") || "unknown"}`).join("<br>") : '<span style="color:var(--muted)">None</span>'}</div>
  `;
}

function toggleDrawer() {
  drawerOpen = !drawerOpen;
  document.getElementById("drawer").classList.toggle("open", drawerOpen);
  if (drawerOpen) refreshProviders();
}

async function openHealthModal() {
  document.getElementById("health-modal").classList.add("open");
  await loadHealthModal();
}

function closeHealthModal() {
  document.getElementById("health-modal").classList.remove("open");
}

async function loadHealthModal() {
  const body = document.getElementById("health-modal-body");
  const d = await fetch("/providers/health").then((r) => r.json()).catch(() => null);
  if (!d) {
    body.innerHTML = '<div style="color:var(--muted)">Failed to load.</div>';
    return;
  }
  const entries = Object.values(d.health || {});
  body.innerHTML = entries.map((p) => {
    const dotClass = p.cooling ? "h-cool" : (p.has_key ? "h-ok" : "h-nokey");
    const status = p.cooling ? `Cooling ${p.cd_left}s` : (p.has_key ? "Available" : "No key");
    return `<div class="health-row">
      <div class="health-dot ${dotClass}"></div>
      <div class="health-name">${esc(p.label)}</div>
      <div class="health-status">${status}</div>
    </div>`;
  }).join("");
}
