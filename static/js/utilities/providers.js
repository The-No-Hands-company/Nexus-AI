// Provider utilities split from index.html
async function refreshProviders() {
  const d = await fetch("/providers").then((r) => r.json()).catch(() => null);
  if (d) {
    window._providerCache = d.providers || [];
    updateProviderUI(d.providers || []);
  }
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
