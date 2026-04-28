// Shared static API helpers for panel modules.
(function () {
  async function apiJson(url, opts) {
    const res = await fetch(url, opts || {});
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      data = {};
    }
    return { ok: res.ok, status: res.status, data };
  }

  function setPanelOpen(id, open) {
    const el = document.getElementById(id);
    if (!el) return;
    el.style.display = open ? "flex" : "none";
  }

  window.NexusApi = {
    apiJson,
    setPanelOpen,
  };
})();
