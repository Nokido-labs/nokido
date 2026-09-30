
'use strict';

const LAFORGE_HUB   = 'http://127.0.0.1:8766';
const LAFORGE_TOKEN = '';
const STREAM_DELAY  = 10;

const containerLinks   = document.getElementById('links');
const containerDomains = document.getElementById('domains');
const message          = document.getElementById('message');
const reBaseURL = /(^\w+:\/\/[^\/]+)|(^[A-Za-z0-9.-]+)\/|(^[A-Za-z0-9.-]+$)/;

const params           = new URLSearchParams(location.search);
const tabId            = parseInt(params.get('tabId'));
const filtering        = params.get('filtering') === 'true';
const filteringDomains = params.get('filteringDomains') === 'true';
const onlyDomains      = params.get('onlyDomains') === 'true';
const pattern          = filtering ? window.prompt(chrome.i18n.getMessage('askPattern')) : null;

// Demande au background (service_worker) d'extraire via scripting.executeScript
(async () => {
  message.textContent = 'Extraction en cours...';
  try {
    const resp = await chrome.runtime.sendMessage({ action: 'extractLinks', tabId });
    if (!resp || resp.error) throw new Error(resp?.error || 'Pas de réponse du background');
    if (!resp.links) { message.textContent = 'Aucun lien trouvé.'; return; }
    handler(resp.links, pattern, onlyDomains);
  } catch(e) {
    message.textContent = 'Erreur: ' + e.message;
    console.error(e);
  }
})();

function handler(links, pattern, onlyDomains) {
  const resLinks = links.filter(l => l.lastIndexOf('://', 10) > 0);
  const items    = [...new Set(resLinks)].sort();
  const re       = pattern ? new RegExp(pattern, 'g') : null;
  const added    = items.filter(l => addNodes(l, containerLinks, re, onlyDomains));
  if (!added.length) { message.textContent = 'Aucun lien trouvé.'; return; }
  message.style.display = 'none';
  const domains = [...new Set(added.map(getBaseURL))].filter(Boolean).sort();
  domains.forEach(d => addNodes(d, containerDomains, filteringDomains ? re : null, onlyDomains));
  injectNokidoButton(added);
}

function injectNokidoButton(urls) {
  const panel = document.createElement('div');
  panel.style.cssText = 'background:#0d1117;border:1px solid #00d4ff;border-radius:6px;padding:12px 16px;margin:0 0 16px 0;font-family:monospace;position:sticky;top:0;z-index:999';
  panel.innerHTML = `
    <div style="color:#00d4ff;font-weight:bold;margin-bottom:8px">
      ⚡ Nokido Hub <span style="color:#888;font-weight:normal;font-size:11px;margin-left:8px">${urls.length} URLs · LF1.B.H.1.5.ING</span>
    </div>
    <button id="lg-send" style="background:#00d4ff;color:#000;border:none;padding:7px 14px;border-radius:4px;cursor:pointer;font-weight:bold;margin-right:8px">🚀 Envoyer à Nokido</button>
    <button id="lg-copy" style="background:#222;color:#ccc;border:1px solid #444;padding:7px 14px;border-radius:4px;cursor:pointer">📋 Copier JSON</button>
    <div id="lg-progress" style="margin-top:8px;font-size:11px;color:#888;display:none"></div>
  `;
  document.body.insertBefore(panel, document.body.firstChild);
  document.getElementById('lg-send').addEventListener('click', () => streamToNokido(urls));
  document.getElementById('lg-copy').addEventListener('click', () => {
    navigator.clipboard.writeText(JSON.stringify(urls, null, 2))
      .then(() => setProgress(`✓ ${urls.length} URLs copiées`, '#00ff88'));
  });
}

async function streamToNokido(urls) {
  const btn = document.getElementById('lg-send');
  btn.disabled = true; btn.textContent = '⏳';
  let sent = 0;
  const t0 = Date.now();

  // Test hub
  try { await fetch(`${LAFORGE_HUB}/health`, {signal: AbortSignal.timeout(2000)}); }
  catch(e) { return fallbackBulk(urls, btn); }

  // Streaming atomique URL par URL avec LF header
  for (let i = 0; i < urls.length; i++) {
    try {
      const h = {'Content-Type':'application/json'};
      if (LAFORGE_TOKEN) h['Authorization'] = `Bearer ${LAFORGE_TOKEN}`;
      await fetch(`${LAFORGE_HUB}/ingest/url`, {
        method:'POST', headers:h,
        body: JSON.stringify({
          header: 'LF1.B.H.1.5.ING',
          body: {url: urls[i], source:'linkgopher', priority:3}
        }),
        signal: AbortSignal.timeout(3000)
      });
      sent++;
    } catch(e) {}
    if (i % 5 === 0 || i === urls.length-1)
      setProgress(`${Math.round((i+1)/urls.length*100)}% — ${sent} envoyées`, '#888');
    if (STREAM_DELAY > 0) await sleep(STREAM_DELAY);
  }
  btn.textContent = '✓'; btn.style.background = '#00ff88';
  setProgress(`✓ ${sent}/${urls.length} en ${((Date.now()-t0)/1000).toFixed(1)}s`, '#00ff88');
}

async function fallbackBulk(urls, btn) {
  try {
    const h = {'Content-Type':'application/json'};
    if (LAFORGE_TOKEN) h['Authorization'] = `Bearer ${LAFORGE_TOKEN}`;
    await fetch(`${LAFORGE_HUB}/ingest/bulk`, {
      method:'POST', headers:h,
      body: JSON.stringify({header:'LF1.B.H.1.5.ING', body: urls.map(u=>({url:u,source:'linkgopher'}))}),
      signal: AbortSignal.timeout(10000)
    });
    setProgress('✓ bulk OK', '#00ff88');
  } catch(e) {
    navigator.clipboard.writeText(JSON.stringify(urls))
      .then(() => setProgress('Hub injoignable — JSON copié', '#ffaa00'));
  }
}

function setProgress(t, c='#888') {
  const el = document.getElementById('lg-progress');
  if (!el) return;
  el.style.display='block'; el.style.color=c; el.textContent=t;
}
function sleep(ms) { return new Promise(r=>setTimeout(r,ms)); }
function addNodes(url, container, re, onlyDomains) {
  if (re && !url.match(re)) return false;
  if (onlyDomains === true && container === containerLinks) return true;
  const a = document.createElement('a'); a.href=url; a.innerText=url;
  container.appendChild(a); container.appendChild(document.createElement('br'));
  return true;
}
function getBaseURL(link) {
  const r = link.match(reBaseURL);
  if (!r) return null;
  return r[1] ? `${r[1]}/` : `http://${r[2]||r[3]}/`;
}
