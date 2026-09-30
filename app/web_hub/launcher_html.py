"""
app/web_hub/launcher_html.py - Page de pilotage des modules.

CSP-compatible : script inline mais sans eval/Function, fetch same-origin.
Pour une CSP 100%% stricte (script-src 'self'), deplacer le JS dans un
fichier static/ servi par FastAPI (evolution future).
"""

from __future__ import annotations

import html as _h

_HTML = """<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nokido Hub - Modules</title>
<link rel="stylesheet" href="/static/nokido.css">
<style>
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg-0); color:var(--text-primary);
         font-family: var(--font-sans); }
  header { border-bottom:1px solid #1f2937; padding:1rem 1.5rem;
           display:flex; align-items:center; gap:1rem; }
  header a { color:#94a3b8; text-decoration:none; font-size:0.85rem; }
  header h1 { margin:0; font-size:1.2rem; font-weight:600; }
  header .spacer { flex:1; }
  header .info { font-family:ui-monospace,monospace; font-size:0.75rem; color:#475569; }
  main { padding:2rem 1.5rem; max-width:1100px; margin:0 auto; }
  .warn { background:#78350f; border:1px solid #b45309; color:#fde68a;
          padding:0.8rem 1rem; border-radius:8px; margin-bottom:1.2rem;
          font-size:0.9rem; }
  .grid { display:grid; grid-template-columns:1fr; gap:1rem; }
  @media (min-width:760px){ .grid{ grid-template-columns:1fr 1fr; } }
  .card { background:#11151c; border:1px solid #1f2937; border-radius:10px;
          padding:1.2rem; }
  .card h3 { margin:0 0 0.3rem; font-size:1.05rem; }
  .card .desc { color:#94a3b8; font-size:0.85rem; margin:0 0 0.8rem; }
  .status { display:inline-block; padding:2px 8px; border-radius:10px;
            font-size:0.75rem; font-family:ui-monospace,monospace;
            text-transform:uppercase; letter-spacing:0.05em; }
  .status.running { background:#064e3b; color:#6ee7b7; }
  .status.stopped { background:#1f2937; color:#94a3b8; }
  .status.stale   { background:#7c2d12; color:#fca5a5; }
  .meta { font-family:ui-monospace,monospace; font-size:0.8rem; color:#64748b;
          margin-top:0.6rem; }
  .actions { margin-top:1rem; display:flex; gap:0.6rem; }
  button { padding:0.55rem 0.9rem; border:0; border-radius:6px;
           font-size:0.85rem; font-weight:500; cursor:pointer; }
  button.start { background:#059669; color:white; }
  button.start:hover { background:#047857; }
  button.stop  { background:#dc2626; color:white; }
  button.stop:hover  { background:#b91c1c; }
  button.logs  { background:#1f2937; color:#cbd5e1; }
  button.logs:hover  { background:#374151; }
  button.live { background:#7c3aed; color:white; }
  button.live:hover { background:#6d28d9; }
  button.live.on { background:#dc2626; }
  button.live.on:hover { background:#b91c1c; }
  button.live.on::before {
    content:"●"; display:inline-block; margin-right:0.3rem;
    animation: pulse 1.4s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100% {opacity:1;} 50% {opacity:0.35;} }
  a.open { padding:0.55rem 0.9rem; border-radius:6px;
           font-size:0.85rem; font-weight:500; text-decoration:none;
           background:#2563eb; color:white; display:inline-block; }
  a.open:hover { background:#1d4ed8; }
  .badge-cli { margin-left:0.5rem; padding:1px 6px; border-radius:4px;
               background:#1f2937; color:#94a3b8; font-size:0.7rem;
               font-family:ui-monospace,monospace; }
  button:disabled { opacity:0.4; cursor:not-allowed; }
  pre.log { background:#0a0e14; border:1px solid #1f2937;
            border-radius:6px; padding:0.75rem; margin-top:0.8rem;
            font-size:0.75rem; color:#94a3b8; max-height:260px;
            overflow:auto; white-space:pre-wrap; }
  .err { color:#fca5a5; font-size:0.85rem; margin-top:0.4rem; }
</style>
</head><body>
<header>
  <a href="/">&larr; Hub</a>
  <h1>Modules</h1>
  <div class="spacer"></div>
  <span class="info" id="refreshInfo">--</span>
</header>
<main>
  <div id="flagWarn" class="warn" hidden>
    <b>Start/Stop desactives.</b> Le flag <code>enable_remote_start</code> est a
    <code>false</code>. Active-le via <code>PATCH /api/config</code> ou l'ecran config.
  </div>
  <div class="grid" id="grid"></div>

  <h2 style="margin:2.2rem 0 0.3rem;font-size:1.05rem">Services a la demande</h2>
  <p class="desc" style="margin:0 0 1rem;color:#94a3b8;font-size:0.85rem;max-width:80ch">
    Ces services sont <b>eteints au demarrage</b>, volontairement : ils coutent de la
    memoire et ne servent qu'a la demande. Les tuiles du portail y renvoient ici au lieu
    de les lancer toutes seules. Le cout est annonce <b>avant</b> le clic.
  </p>
  <div class="grid" id="ondemand"></div>
</main>

<script>
(() => {
  const grid = document.getElementById('grid');
  const flagWarn = document.getElementById('flagWarn');
  const info = document.getElementById('refreshInfo');
  let enabled = false;

  async function loadConfig() {
    try {
      const r = await fetch('/api/config', { cache:'no-store' });
      if (!r.ok) return;
      const d = await r.json();
      enabled = !!(d.settings && d.settings.enable_remote_start);
      flagWarn.hidden = enabled;
    } catch (e) {}
  }

  function mkCard(m) {
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.mod = m.module;
    const running = m.status === 'running';
    const apiManaged = m.api_managed !== false;  // undefined => true (retrocompat)
    // Bouton "Ouvrir" : si module running ET open_path defini
    const openBtn = (running && m.open_path)
      ? '<a class="open" href="' + esc(m.open_path) +
        '" target="_blank" rel="noopener">Ouvrir &rarr;</a>' : '';
    // Badge "cli only" si !api_managed
    const cliBadge = apiManaged ? ''
      : '<span class="badge-cli" title="Start/Stop via CLI uniquement">CLI only</span>';
    // Disabled : si !apiManaged, Start/Stop sont toujours disabled
    const startDis = (running || !enabled || !apiManaged) ? 'disabled' : '';
    const stopDis  = (!running || !enabled || !apiManaged) ? 'disabled' : '';
    card.innerHTML = [
      '<h3>', esc(m.title || m.module), cliBadge, '</h3>',
      '<p class="desc">', esc(m.description || ''), '</p>',
      '<span class="status ', esc(m.status), '">', esc(m.status), '</span> ',
      m.pid ? ('<span class="meta">pid=' + esc(String(m.pid)) +
               (m.port ? ' port=' + esc(String(m.port)) : '') +
               (m.uptime_s ? ' uptime=' + esc(String(m.uptime_s)) + 's' : '') +
               '</span>') : '',
      '<div class="actions">',
        '<button class="start" data-act="start" ', startDis, '>Start</button>',
        '<button class="stop"  data-act="stop"  ', stopDis, '>Stop</button>',
        '<button class="logs"  data-act="log">Logs</button>',
        '<button class="live"  data-act="live">Live</button>',
        openBtn,
      '</div>',
      '<pre class="log" hidden></pre>',
      '<div class="err" hidden></div>',
    ].join('');
    card.querySelectorAll('button').forEach(b => {
      b.addEventListener('click', () => act(card, m.module, b.dataset.act));
    });
    // La grille est RECONSTRUITE toutes les 3 s (refresh) : un journal ouvert doit survivre
    // a la reconstruction, sinon il se referme aussitot (mesure owner 2026-09-25).
    const vue = vues[m.module];
    if (vue) {
      const pre = card.querySelector('pre.log');
      pre.textContent = vue.texte;
      pre.hidden = false;
      requestAnimationFrame(() => { pre.scrollTop = pre.scrollHeight; });
    }
    if (streams[m.module]) {
      const lb = card.querySelector('button.live');
      if (lb) lb.classList.add('on');
    }
    return card;
  }

  // Journaux ouverts, par module : {mod: {texte}} (null = ferme). Survit a la reconstruction.
  const vues = {};
  // Le <pre> COURANT du module (la carte est remplacee a chaque rafraichissement).
  function preDe(mod) {
    const c = grid.querySelector('.card[data-mod="' + CSS.escape(mod) + '"]');
    return c ? c.querySelector('pre.log') : null;
  }

  function esc(s) { return String(s).replace(/[&<>\"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c])); }

  // Sessions EventSource actives : {mod: EventSource}
  const streams = {};

  async function act(card, mod, action) {
    const logEl = card.querySelector('pre.log');
    const errEl = card.querySelector('.err');
    const liveBtn = card.querySelector('button.live');
    errEl.hidden = true; errEl.textContent = '';
    try {
      if (action === 'log') {
        // Second clic : referme (le journal ne se referme plus tout seul).
        if (vues[mod] && !streams[mod]) {
          vues[mod] = null;
          logEl.hidden = true;
          return;
        }
        const r = await fetch('/api/launcher/' + encodeURIComponent(mod) + '/log?n=80');
        const d = await r.json();
        vues[mod] = { texte: d.content || '(log vide)' };
        logEl.textContent = vues[mod].texte;
        logEl.hidden = false;
        logEl.scrollTop = logEl.scrollHeight;
        return;
      }
      if (action === 'live') {
        // Toggle : si deja actif -> close ; sinon ouvre EventSource
        if (streams[mod]) {
          streams[mod].close(); delete streams[mod];
          if (liveBtn) liveBtn.classList.remove('on');
          vues[mod] = null;
          logEl.hidden = true;
          return;
        }
        // Ouverture stream
        vues[mod] = { texte: '' };
        logEl.textContent = '';
        logEl.hidden = false;
        const es = new EventSource('/api/launcher/' + encodeURIComponent(mod) + '/stream');
        streams[mod] = es;
        if (liveBtn) liveBtn.classList.add('on');
        // Plafond client : garder ~500 lignes dans le <pre> (anti-DoS memoire)
        let lineCount = 0;
        const MAX_LINES = 500;
        es.onmessage = (e) => {
          // Ecrit dans l'ETAT puis dans le <pre> COURANT : l'element capture a l'ouverture
          // est detruit au premier rafraichissement (3 s).
          const vue = vues[mod] || (vues[mod] = { texte: '' });
          vue.texte += e.data + "\\n";
          lineCount += 1;
          if (lineCount > MAX_LINES) {
            vue.texte = vue.texte.split("\\n").slice(-MAX_LINES).join("\\n");
            lineCount = MAX_LINES;
          }
          const pre = preDe(mod);
          if (pre) {
            pre.textContent = vue.texte;
            pre.hidden = false;
            pre.scrollTop = pre.scrollHeight;
          }
        };
        es.addEventListener('error', (e) => {
          errEl.textContent = 'Stream ferme';
          errEl.hidden = false;
          es.close(); delete streams[mod];
          if (liveBtn) liveBtn.classList.remove('on');
        });
        return;
      }
      const r = await fetch('/api/launcher/' + encodeURIComponent(mod) + '/' + action,
                           { method:'POST' });
      if (!r.ok) {
        const t = await r.text();
        errEl.textContent = 'HTTP ' + r.status + ' : ' + t.slice(0, 200);
        errEl.hidden = false;
      }
    } catch (e) {
      errEl.textContent = 'Erreur reseau';
      errEl.hidden = false;
    }
    await refresh();
  }

  async function refresh() {
    const t0 = performance.now();
    try {
      await loadConfig();
      const r = await fetch('/api/launcher/modules', { cache:'no-store' });
      const d = await r.json();
      grid.innerHTML = '';
      (d.modules || []).forEach(m => grid.appendChild(mkCard(m)));
      const ms = Math.round(performance.now() - t0);
      const dt = new Date();
      const h = String(dt.getHours()).padStart(2,'0');
      const mi = String(dt.getMinutes()).padStart(2,'0');
      const s = String(dt.getSeconds()).padStart(2,'0');
      info.textContent = h+':'+mi+':'+s+' ('+ms+'ms)';
    } catch (e) {
      info.textContent = 'refresh failed';
    }
  }

  // ---- Services a la demande (eteints au boot, lances par un geste VOULU) ----
  const gridOd = document.getElementById('ondemand');

  function mkOndemand(s) {
    const card = document.createElement('div');
    card.className = 'card';
    const actif = !!s.actif;
    card.innerHTML = [
      '<h3>', esc(s.titre), '</h3>',
      '<p class="desc">', esc(s.note || ''), '</p>',
      '<span class="status ', actif ? 'running' : 'stopped', '">',
      actif ? 'running' : 'stopped', '</span> ',
      '<span class="meta">port=', esc(String(s.port)), '</span>',
      // L'avertissement est AFFICHE, pas seulement dans une confirmation : on ne
      // decouvre pas le cout d'un geste au moment ou on le declenche.
      '<div class="warn" style="margin:0.9rem 0 0;font-size:0.8rem">&#9888; ',
      esc(s.avertissement || ''), '</div>',
      '<div class="actions">',
        '<button class="start" data-od="start"', actif ? ' disabled' : '', '>Demarrer</button>',
        '<button class="stop"  data-od="stop"',  actif ? '' : ' disabled', '>Arreter</button>',
        actif ? ('<a class="open" href="http://127.0.0.1:' + esc(String(s.port)) +
                 '" target="_blank" rel="noopener">Ouvrir &rarr;</a>') : '',
      '</div>',
      '<div class="err" hidden></div>',
    ].join('');
    card.querySelectorAll('button[data-od]').forEach(b => {
      b.addEventListener('click', () => agirOndemand(card, s, b.dataset.od));
    });
    return card;
  }

  async function agirOndemand(card, s, action) {
    const errEl = card.querySelector('.err');
    errEl.hidden = true;
    if (action === 'start' &&
        !window.confirm(s.titre + "\\n\\n" + (s.avertissement || '') +
                        "\\n\\nDemarrer maintenant ?")) return;
    card.querySelectorAll('button[data-od]').forEach(b => { b.disabled = true; });
    try {
      const r = await fetch('/api/services/' + encodeURIComponent(s.cle) + '/' + action,
                            { method: 'POST', credentials: 'same-origin' });
      const d = await r.json();
      if (!d.ok) {
        errEl.textContent = d.error || ('HTTP ' + r.status);
        errEl.hidden = false;
      } else {
        // REQUESTED != ACHIEVED : le modele met des secondes a charger. On le DIT,
        // au lieu d'afficher un succes que rien ne soutient encore.
        errEl.textContent = "Demande transmise — le service sera disponible quand son "
                          + "port repondra (rafraichissement automatique).";
        errEl.hidden = false;
      }
    } catch (e) {
      errEl.textContent = 'Erreur reseau';
      errEl.hidden = false;
    }
    await refreshOndemand();
  }

  async function refreshOndemand() {
    if (!gridOd) return;
    try {
      const r = await fetch('/api/services/ondemand', { cache: 'no-store',
                                                        credentials: 'same-origin' });
      if (!r.ok) return;
      const d = await r.json();
      gridOd.innerHTML = '';
      (d.services || []).forEach(s => gridOd.appendChild(mkOndemand(s)));
    } catch (e) {}
  }

  refresh();
  refreshOndemand();
  setInterval(refresh, 3000);
  // Plus lent que les modules : une sonde de port par service, et l'etat ne change
  // qu'au rythme d'un chargement de modele.
  setInterval(refreshOndemand, 8000);
})();
</script>
</body></html>
"""


def render_launcher(version: str) -> str:
    return _HTML.replace("{VERSION}", _h.escape(version))


__all__ = ["render_launcher"]
