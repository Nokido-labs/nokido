/* Nokido UI common JS — helpers minimalistes pour toutes les UIs Nokido.
   Importer après nokido.css :  <script src="/static/nokido.js"></script>
   Pas de framework, vanilla DOM/fetch. Version 1.0 — 2026-04-30 */

(function () {
  'use strict';

  const HUB_DEFAULT = 'http://127.0.0.1:8766';

  const Nokido = {
    hubUrl: HUB_DEFAULT,
    token: null,

    /** Configure global hub URL + token (lus du localStorage si pas fournis). */
    init({ hubUrl, token } = {}) {
      this.hubUrl = hubUrl || localStorage.getItem('nokido.hubUrl') || HUB_DEFAULT;
      this.token  = token  || localStorage.getItem('nokido.token')  || null;
    },

    /** Appel JSON-RPC tools/call vers le hub MCP. */
    async fetchHub(toolName, args = {}, { id = 1 } = {}) {
      const headers = { 'Content-Type': 'application/json' };
      if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
      const res = await fetch(this.hubUrl + '/mcp', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          jsonrpc: '2.0', id,
          method: 'tools/call',
          params: { name: toolName, arguments: args },
        }),
      });
      if (!res.ok) {
        throw new Error(`Hub HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
      }
      const data = await res.json();
      if (data.error) throw new Error(`Hub RPC error: ${JSON.stringify(data.error)}`);
      return data.result;
    },

    /** GET /health — renvoie { up: bool, ...health } sans throw. */
    async health() {
      try {
        const r = await fetch(this.hubUrl + '/health', { cache: 'no-store' });
        if (!r.ok) return { up: false, status: r.status };
        const d = await r.json();
        return { up: true, ...d };
      } catch (e) {
        return { up: false, error: String(e.message || e) };
      }
    },

    /** Toast non bloquant. levels: info|success|warn|error. */
    toast(message, level = 'info', { duration = 3500 } = {}) {
      let stack = document.querySelector('.laforge-toast-stack');
      if (!stack) {
        stack = document.createElement('div');
        stack.className = 'laforge-toast-stack';
        document.body.appendChild(stack);
      }
      const el = document.createElement('div');
      el.className = 'laforge-toast laforge-toast-' + level;
      el.textContent = message;
      stack.appendChild(el);
      setTimeout(() => {
        el.style.opacity = '0';
        el.style.transform = 'translateX(20px)';
        el.style.transition = 'all 200ms';
        setTimeout(() => el.remove(), 220);
      }, duration);
    },

    /** Theme toggle (dark default, light optionnel via [data-theme]). */
    theme: {
      get current() { return document.documentElement.dataset.theme || 'dark'; },
      set(theme) {
        document.documentElement.dataset.theme = theme;
        localStorage.setItem('nokido.theme', theme);
      },
      toggle() { this.set(this.current === 'dark' ? 'light' : 'dark'); },
      restore() {
        const saved = localStorage.getItem('nokido.theme');
        if (saved) this.set(saved);
      },
    },

    /** Helper DOM : escape HTML pour insertions safe. */
    escapeHtml(s) {
      return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },

    /** Helper DOM : timestamp HH:MM:SS courant. */
    ts() { return new Date().toTimeString().slice(0, 8); },

    /** Helper UI : poll périodique d'un endpoint (clearable). */
    poll(fn, intervalMs = 2000) {
      let stopped = false;
      const tick = async () => {
        if (stopped) return;
        try { await fn(); } catch (e) { console.warn('[nokido.poll]', e); }
        setTimeout(tick, intervalMs);
      };
      tick();
      return () => { stopped = true; };
    },
  };

  Nokido.init();
  Nokido.theme.restore();
  window.Nokido = Nokido;
})();
