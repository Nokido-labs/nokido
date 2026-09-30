'use strict';

// ─── Nokido Config ───────────────────────────────────────────────────────────
const LAFORGE_HUB   = 'http://127.0.0.1:8766';
const LAFORGE_TOKEN = ''; // Optionnel si hub en local
const STREAM_DELAY  = 10; // ms entre chaque URL (streaming atomique)
// ─────────────────────────────────────────────────────────────────────────────

const containerLinks   = document.getElementById('links');
const containerDomains = document.getElementById('domains');
const message          = document.getElementById('message');
const reBaseURL = /(^\w+:\/\/[^\/]+)|(^[A-Za-z0-9.-]+)\/|(^[A-Za-z0-9.-]+$)/;
const tabId       = parseInt(location.search.replace(/.*tabId=(\d+).*/, '$1'));
const filtering   = location.search.replace(/.*filtering=(true|false).*/, '$1');
const pattern     = filtering === 'true'
  ? window.prompt(chrome.i18n.getMessage('askPattern'))
  : null;
const filteringDomains = location
  .search.replace(/.*filteringDomains=(true|false).*/, '$1') === 'true';
const onlyDomains = location.search.replace(/.*onlyDomains=(true|false).*/, '$1');

chrome.tabs.sendMessage(tabId, {action: 'extract'}, links => {
  handler(links, pattern, onlyDomains);
});

// Localization.
[
  {id: 'links',   messageId: 'links'},
  {id: 'domains', messageId: 'domains'},
  {id: 'message', messageId: 'pleaseWait'}
].forEach(item => {
  const el = document.getElementById(item.id);
  if (el) el.dataset.content = chrome.i18n.getMessage(item.messageId);
});

/**
 * handler — appelé avec la liste des URLs extraites.
 * Modifié : injecte le bouton Nokido + collecte les URLs pour streaming.
 */
function handler(links, pattern, onlyDomains) {
  if (chrome.runtime.lastError) {
    return window.alert(chrome.runtime.lastError);
  }

  const resLinks = links.filter(link => link.lastIndexOf('://', 10) > 0);
  const items    = [...(new Set(resLinks))].sort();
  const re       = pattern ? new RegExp(pattern, 'g') : null;
  const added    = items.filter(link => addNodes(link, containerLinks, re, onlyDomains));

  if (!added.length) {
    message.dataset.content = chrome.i18n.getMessage('noMatches');
    return;
  }

  const domains   = [...(new Set(added.map(link => getBaseURL(link))))].sort();
  const reDomains = filteringDomains ? re : null;
  domains.forEach(domain => addNodes(domain, containerDomains, reDomains, onlyDomains));

  // ── Injecter le bouton Nokido ──────────────────────────────────────────
  injectNokidoButton(added);
}

/**
 * injectNokidoButton — ajoute le panneau Nokido au-dessus des résultats.
 * @param {string[]} urls - Liste d'URLs filtrées et triées.
 */
function injectNokidoButton(urls) {
  const panel = document.createElement('div');
  panel.id = 'laforge-panel';
  panel.style.cssText = [
    'background:#0d1117', 'border:1px solid #00d4ff', 'border-radius:6px',
    'padding:12px 16px', 'margin:0 0 16px 0', 'font-family:monospace',
    'position:sticky', 'top:0', 'z-index:999'
  ].join(';');

  panel.innerHTML = `
    <div style="color:#00d4ff;font-weight:bold;margin-bottom:8px">
      ⚡ Nokido Hub
      <span id="lg-count" style="color:#888;font-weight:normal;font-size:11px;margin-left:8px">
        ${urls.length} URLs prêtes
      </span>
    </div>
    <button id="lg-send" style="
      background:#00d4ff;color:#000;border:none;padding:7px 14px;
      border-radius:4px;cursor:pointer;font-weight:bold;margin-right:8px;font-size:12px
    ">🚀 Envoyer à Nokido (streaming)</button>
    <button id="lg-copy" style="
      background:#222;color:#ccc;border:1px solid #444;padding:7px 14px;
      border-radius:4px;cursor:pointer;font-size:12px
    ">📋 Copier JSON</button>
    <div id="lg-progress" style="
      margin-top:8px;font-size:11px;color:#888;display:none
    "></div>
  `;

  // Insérer avant tout le reste
  document.body.insertBefore(panel, document.body.firstChild);

  document.getElementById('lg-send').addEventListener('click', () => {
    streamToNokido(urls);
  });

  document.getElementById('lg-copy').addEventListener('click', () => {
    const json = JSON.stringify(urls.map(u => ({url: u, title: u})), null, 2);
    navigator.clipboard.writeText(json).then(() => {
      setProgress(`✓ ${urls.length} URLs copiées — colle dans: python tools/forge_bulk_import.py --clipboard`, '#00ff88');
    });
  });
}

/**
 * streamToNokido — envoie les URLs en streaming atomique.
 * Principe : chaque URL = 1 micro-event, pas d'attente du batch complet.
 * @param {string[]} urls
 */
async function streamToNokido(urls) {
  const btn = document.getElementById('lg-send');
  btn.disabled = true;
  btn.textContent = '⏳ Envoi en cours...';

  let sent = 0, failed = 0, skipped = 0;
  const startTime = Date.now();

  setProgress(`0 / ${urls.length} URLs envoyées...`, '#888');

  // Vérifier d'abord si le hub répond
  try {
    const ping = await fetch(`${LAFORGE_HUB}/health`, {signal: AbortSignal.timeout(2000)});
    if (!ping.ok) throw new Error('hub not ok');
  } catch(e) {
    // Fallback : bulk classique si hub injoignable
    return fallbackBulk(urls, btn);
  }

  // Streaming atomique : URL par URL avec délai minimal
  for (let i = 0; i < urls.length; i++) {
    const url = urls[i];
    try {
      const headers = {'Content-Type': 'application/json'};
      if (LAFORGE_TOKEN) headers['Authorization'] = `Bearer ${LAFORGE_TOKEN}`;

      // POST unitaire — Nokido peut crawler immédiatement sans attendre le batch
      await fetch(`${LAFORGE_HUB}/ingest/url`, {
        method: 'POST',
        headers,
        body: JSON.stringify({url, title: url, source: 'linkgopher', priority: 3}),
        signal: AbortSignal.timeout(3000)
      });
      sent++;
    } catch(e) {
      // Si /ingest/url échoue, accumuler pour bulk final
      failed++;
    }

    // Mise à jour progression toutes les 5 URLs
    if (i % 5 === 0 || i === urls.length - 1) {
      const pct = Math.round((i + 1) / urls.length * 100);
      setProgress(`${pct}% — ${sent} envoyées, ${failed} en attente bulk...`, '#888');
    }

    // Délai inter-URL pour ne pas saturer le hub
    if (STREAM_DELAY > 0) await sleep(STREAM_DELAY);
  }

  // Si des URLs ont échoué en unitaire → bulk final
  if (failed > 0) {
    const failedUrls = urls.slice(sent);
    await fallbackBulk(failedUrls, null, silent=true);
  }

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  btn.textContent = '✓ Envoyé';
  btn.style.background = '#00ff88';
  setProgress(
    `✓ ${sent} URLs streamées en ${elapsed}s. ${failed > 0 ? `${failed} via bulk.` : ''} Gemini notifié.`,
    '#00ff88'
  );
}

/**
 * fallbackBulk — envoi groupé si streaming atomique indisponible.
 * @param {string[]} urls
 * @param {HTMLElement|null} btn
 * @param {boolean} silent
 */
async function fallbackBulk(urls, btn, silent = false) {
  const payload = urls.map(u => ({url: u, title: u, status: 'unverified', source: 'linkgopher'}));
  const headers = {'Content-Type': 'application/json'};
  if (LAFORGE_TOKEN) headers['Authorization'] = `Bearer ${LAFORGE_TOKEN}`;

  try {
    const r = await fetch(`${LAFORGE_HUB}/ingest/bulk`, {
      method: 'POST', headers,
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(10000)
    });
    if (r.ok) {
      const d = await r.json();
      if (!silent) {
        if (btn) { btn.textContent = '✓ Envoyé (bulk)'; btn.style.background = '#00ff88'; }
        setProgress(`✓ ${d.inserted || urls.length} URLs insérées (bulk). Gemini notifié.`, '#00ff88');
      }
    } else throw new Error('bulk failed');
  } catch(e) {
    // Dernier recours : clipboard
    const json = JSON.stringify(payload, null, 2);
    navigator.clipboard.writeText(json).then(() => {
      if (btn) { btn.textContent = '📋 JSON copié'; }
      setProgress('Hub injoignable — JSON copié. Lance: python tools/forge_bulk_import.py --clipboard', '#ffaa00');
    });
  }
}

function setProgress(text, color = '#888') {
  const el = document.getElementById('lg-progress');
  if (!el) return;
  el.style.display = 'block';
  el.style.color   = color;
  el.textContent   = text;
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

/**
 * addNodes — inchangé par rapport à l'original.
 */
function addNodes(url, container, re, onlyDomains) {
  if (re && !url.match(re)) return false;
  if (onlyDomains === 'true' && container === containerLinks) return true;

  const br = document.createElement('br');
  const a  = document.createElement('a');
  a.href      = url;
  a.innerText = url;
  container.appendChild(a);
  container.appendChild(br);
  return true;
}

/**
 * getBaseURL — inchangé par rapport à l'original.
 */
function getBaseURL(link) {
  const result = link.match(reBaseURL);
  if (!result) return null;
  if (result[1]) return `${result[1]}/`;
  return `http://${result[2] || result[3]}/`;
}
