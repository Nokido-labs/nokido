'use strict';
/* Nokido Link Gopher — popup UI controller (vanilla, no framework).
   Hub calls go directly via fetch() with a local hubFetch() wrapper that
   mirrors background.js (Bearer token from chrome.storage.local.forge_token
   + LF_HDR header). The popup keeps using chrome.runtime.sendMessage only
   for browser-API actions already wired in background.js (extractLinks,
   getTabs, getHistory, qualifyUrls). */

const HUB     = 'http://127.0.0.1:8766';
const LF_HDR  = 'LF1.B.H.1.5.ING';
const PRESETS = ['ia','code','security','network','devops','system',
                 'bibliography','neuromorphic','research','web','exploit','collab'];

const params           = new URLSearchParams(location.search);
const sourceTabId      = parseInt(params.get('tabId'));
const filtering        = params.get('filtering') === 'true';
const filteringDomains = params.get('filteringDomains') === 'true';
const onlyDomains      = params.get('onlyDomains') === 'true';
const initialPattern   = filtering ? window.prompt('Pattern (regex) ?') : null;

// In-memory store : raw items per tab. Filtering/dedup is applied at render.
const STORE = {
  page:    [],   // {url,title}
  tabs:    [],   // {url,title,tabId,favIconUrl}
  history: [],   // {url,title,visitCount,lastVisit}
  rag:     [],   // {url,title,score,preview,source}
};

let activeTab   = 'page';
let tabsLoaded  = false;
let histTimer   = null;
let _pending    = [];
let _tags       = new Set();

// ─── DOM ──────────────────────────────────────────────────────────────
const $  = id => document.getElementById(id);
const qa = sel => [...document.querySelectorAll(sel)];

const fText  = $('f-text');
const fDom   = $('f-domain');
const fHttps = $('f-https');
const fDedup = $('f-dedup');

// ─── Helpers ──────────────────────────────────────────────────────────
const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                         .replace(/"/g,'&quot;').replace(/>/g,'&gt;');

function getDomain(url){
  try { return new URL(url).hostname; } catch { return ''; }
}

async function getToken(){
  try { const r = await chrome.storage.local.get('forge_token');
        return r?.forge_token || ''; }
  catch { return ''; }
}

/** Local hubFetch wrapper — mirrors background.js Change C.
 *  Adds Authorization: Bearer <token> if set, default JSON content-type,
 *  default 8s timeout. Caller may override via init.headers / init.signal. */
async function hubFetch(path, init){
  init = init || {};
  const token   = await getToken();
  const headers = Object.assign(
    { 'Content-Type': 'application/json' },
    init.headers || {}
  );
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const opts = Object.assign({}, init, { headers });
  if (!opts.signal) opts.signal = AbortSignal.timeout(opts._timeout || 8000);
  return fetch(`${HUB}${path}`, opts);
}

// ─── Tabs nav ─────────────────────────────────────────────────────────
qa('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    qa('.tab-btn').forEach(b => b.classList.remove('active'));
    qa('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    $('tab-' + btn.dataset.tab).classList.add('active');
    activeTab = btn.dataset.tab;
    if (activeTab === 'tabs' && !tabsLoaded) loadTabs();
    if (activeTab === 'history' && !STORE.history.length) loadHistory('');
    refreshDomainOptions();
    rerenderActive();
    syncSelCount();
  });
});

// ─── Filter row : shared across all tabs ──────────────────────────────
[fText, fHttps, fDedup, fDom].forEach(el => {
  el.addEventListener('input',  () => { rerenderActive(); syncSelCount(); });
  el.addEventListener('change', () => { rerenderActive(); syncSelCount(); });
});

function refreshDomainOptions(){
  const items = STORE[activeTab] || [];
  const domains = [...new Set(items.map(i => getDomain(i.url)).filter(Boolean))].sort();
  const cur = fDom.value;
  fDom.innerHTML = '<option value="">tous domaines</option>' +
    domains.map(d => `<option value="${esc(d)}">${esc(d)}</option>`).join('');
  if (domains.includes(cur)) fDom.value = cur;
}

function applyFilters(items){
  const txt   = fText.value.trim().toLowerCase();
  const dom   = fDom.value;
  const https = fHttps.checked;
  const dedup = fDedup.checked;

  let out = items;
  if (https) out = out.filter(i => /^https?:/i.test(i.url));
  if (dom)   out = out.filter(i => getDomain(i.url) === dom);
  if (txt)   out = out.filter(i =>
    (i.url||'').toLowerCase().includes(txt) ||
    (i.title||'').toLowerCase().includes(txt)
  );
  if (dedup){
    const seen = new Set();
    out = out.filter(i => {
      const k = (i.url||'').toLowerCase();
      if (seen.has(k)) return false;
      seen.add(k); return true;
    });
  }
  if (initialPattern && activeTab === 'page'){
    try {
      const re = new RegExp(initialPattern);
      out = out.filter(i => re.test(i.url));
    } catch {}
  }
  return out;
}

// ─── Render ───────────────────────────────────────────────────────────
const LIST_OF = { page:'page-list', tabs:'tabs-list', history:'hist-list', rag:'rag-list' };
const CNT_OF  = { page:'page-count', tabs:'tabs-count', history:'hist-count', rag:'rag-count' };

function renderList(tabKey){
  const listEl = $(LIST_OF[tabKey]);
  if (!listEl) return;
  const raw = STORE[tabKey] || [];
  const items = applyFilters(raw);
  listEl.innerHTML = '';
  for (const it of items){
    const row = document.createElement('div');
    row.className = 'item';
    let metaHtml = '';
    if (tabKey === 'history' && it.lastVisit){
      const d = new Date(it.lastVisit).toLocaleDateString('fr-FR');
      metaHtml = `<span class="meta">${d}${it.visitCount>1?` ·${it.visitCount}x`:''}</span>`;
    } else if (tabKey === 'rag' && it.score != null){
      metaHtml = `<span class="badge">${(+it.score).toFixed(2)}</span>`;
    } else if (tabKey === 'tabs'){
      metaHtml = `<span class="badge dim">tab</span>`;
    }
    row.innerHTML = `
      <input type="checkbox" data-url="${esc(it.url)}" data-title="${esc(it.title||it.url)}">
      <div class="body">
        <div class="ititle">${esc(it.title || it.url)}</div>
        <div class="iurl">${esc(it.url)}</div>
        ${tabKey==='rag' && it.preview ? `<div class="iurl" style="color:#666">${esc(it.preview).substring(0,160)}</div>` : ''}
      </div>
      ${metaHtml}
    `;
    row.addEventListener('click', e => {
      if (e.target.tagName !== 'INPUT'){
        const cb = row.querySelector('input');
        cb.checked = !cb.checked;
        syncSelCount();
      }
    });
    listEl.appendChild(row);
  }
  $(CNT_OF[tabKey]).textContent = `${items.length}/${raw.length}`;
}

function rerenderActive(){
  renderList(activeTab);
}

// ─── Selection helpers (work on currently active tab) ────────────────
function activeListEl(){ return $(LIST_OF[activeTab]); }

function getChecked(){
  const el = activeListEl(); if (!el) return [];
  return [...el.querySelectorAll('input:checked')]
    .map(cb => ({ url: cb.dataset.url, title: cb.dataset.title }));
}

function syncSelCount(){
  const el = activeListEl();
  const ck = el ? el.querySelectorAll('input:checked').length : 0;
  $('sel-count').textContent = `${ck} sélectionné${ck>1?'s':''}`;
  const dis = ck === 0;
  $('act-send').disabled    = dis;
  $('act-qualify').disabled = dis;
  $('act-md').disabled      = dis;
}

document.addEventListener('change', e => {
  if (e.target.matches('.item input[type=checkbox]')) syncSelCount();
});

$('sel-all').addEventListener('click', () => {
  const el = activeListEl(); if (!el) return;
  el.querySelectorAll('input').forEach(cb => cb.checked = true);
  syncSelCount();
});
$('sel-none').addEventListener('click', () => {
  const el = activeListEl(); if (!el) return;
  el.querySelectorAll('input').forEach(cb => cb.checked = false);
  syncSelCount();
});

// ─── Action toolbar ───────────────────────────────────────────────────
$('act-send').addEventListener('click', () => {
  const items = getChecked(); if (!items.length) return;
  openTagPanel(items); // manual tag flow → /ingest/bulk (with /ingest/url fallback)
});

$('act-qualify').addEventListener('click', () => {
  const items = getChecked(); if (!items.length) return;
  qualifyAndSend(items);
});

$('act-md').addEventListener('click', async () => {
  const items = getChecked(); if (!items.length) return;
  const md = items.map(i => `- [${i.title||i.url}](${i.url})`).join('\n');
  try {
    await navigator.clipboard.writeText(md);
    flashFooter(`📋 ${items.length} liens copiés en Markdown`, 'ok');
  } catch(e){
    flashFooter('Erreur clipboard: '+e.message, 'err');
  }
});

// ─── Tab : Liens page ─────────────────────────────────────────────────
(async () => {
  const st = $('page-status');
  try {
    const r = await chrome.runtime.sendMessage({ action:'extractLinks', tabId: sourceTabId });
    if (!r || r.error) throw new Error(r?.error || 'no response');
    const links = (r.links || []);
    STORE.page = links.map(u => ({ url: u, title: u }));
    if (!STORE.page.length){ st.textContent = 'Aucun lien'; st.className='lf-status warn'; return; }
    st.textContent = `${STORE.page.length} liens`;
    st.className = 'lf-status ok';
    refreshDomainOptions(); rerenderActive(); syncSelCount();
  } catch(e){
    st.textContent = 'Erreur: '+e.message; st.className='lf-status err';
  }
})();

// ─── Tab : Onglets ────────────────────────────────────────────────────
async function loadTabs(){
  tabsLoaded = true;
  const st = $('tabs-status');
  try {
    const r = await chrome.runtime.sendMessage({ action:'getTabs' });
    STORE.tabs = (r.tabs || []).map(t => ({ url:t.url, title:t.title||t.url, tabId:t.id, favIconUrl:t.favIconUrl }));
    st.textContent = `${STORE.tabs.length} onglets`;
    st.className = 'lf-status ok';
    refreshDomainOptions(); rerenderActive(); syncSelCount();
  } catch(e){
    st.textContent = 'Erreur: '+e.message; st.className='lf-status err';
  }
}

// ─── Tab : Historique ─────────────────────────────────────────────────
$('hist-search').addEventListener('input', e => {
  clearTimeout(histTimer);
  histTimer = setTimeout(() => loadHistory(e.target.value), 300);
});

async function loadHistory(query){
  const st = $('hist-status');
  st.textContent = 'Recherche…'; st.className = 'lf-status';
  try {
    const r = await chrome.runtime.sendMessage({ action:'getHistory', query, maxResults:300 });
    STORE.history = (r.history || []);
    if (!STORE.history.length){
      st.textContent = query
        ? `Aucun résultat pour "${query}"`
        : 'Historique vide ou non accessible';
      st.className = 'lf-status warn';
    } else {
      st.textContent = `${STORE.history.length} entrées (90j)`;
      st.className = 'lf-status ok';
    }
    refreshDomainOptions(); rerenderActive(); syncSelCount();
  } catch(e){
    st.textContent = 'Erreur: '+e.message; st.className='lf-status err';
  }
}

// ─── Tab : Recherche RAG ──────────────────────────────────────────────
$('rag-go').addEventListener('click', () => searchRag());
$('rag-q').addEventListener('keydown', e => { if (e.key === 'Enter') searchRag(); });

async function searchRag(){
  const q  = $('rag-q').value.trim();
  const st = $('rag-status');
  if (!q){ st.textContent='Tapez une query'; st.className='lf-status warn'; return; }
  st.textContent = 'Search…'; st.className = 'lf-status';
  try {
    const r = await hubFetch(`/search?q=${encodeURIComponent(q)}&limit=20`,
                             { method:'GET', _timeout: 10000 });
    if (!r.ok) throw new Error('HTTP '+r.status);
    const data = await r.json();
    // Normalize : API may return {results:[...]}, [...] or {hits:[...]}
    let hits = Array.isArray(data) ? data
             : data.results || data.hits || data.matches || [];
    STORE.rag = hits.map(h => ({
      url:     h.url || h.source || h.id || '',
      title:   h.title || h.name || h.source || h.url || '(sans titre)',
      score:   h.score ?? h.rank ?? h.bm25 ?? null,
      preview: h.preview || h.snippet || h.text || '',
      source:  h.source || ''
    }));
    st.textContent = `${STORE.rag.length} hits`;
    st.className = 'lf-status ok';
    refreshDomainOptions(); rerenderActive(); syncSelCount();
  } catch(e){
    st.textContent = 'Erreur: '+e.message; st.className='lf-status err';
  }
}

// ─── Tag panel (manual tag flow) ──────────────────────────────────────
const chipsDiv = $('tag-chips');
PRESETS.forEach(t => {
  const c = document.createElement('span');
  c.className = 'tag-chip'; c.textContent = t; c.dataset.tag = t;
  c.addEventListener('click', () => {
    c.classList.toggle('on');
    if (c.classList.contains('on')) _tags.add(t); else _tags.delete(t);
    renderTags();
  });
  chipsDiv.appendChild(c);
});
$('tag-custom').addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.target.value.trim()){
    _tags.add(e.target.value.trim()); e.target.value=''; renderTags();
  }
});
$('tag-cancel').addEventListener('click', closeTagPanel);
$('tag-ok').addEventListener('click', sendWithTags);

function renderTags(){
  $('tag-active').textContent = _tags.size ? '🏷️ ' + [..._tags].join(' · ') : '';
}
function openTagPanel(items){
  if (!items.length) return;
  _pending = items; _tags.clear();
  qa('.tag-chip').forEach(c => c.classList.remove('on'));
  $('tag-custom').value=''; $('tag-note').value=''; $('tag-domain').value='';
  $('tag-active').textContent=''; $('tag-result').textContent='';
  $('tag-panel').hidden = false;
}
function closeTagPanel(){
  $('tag-panel').hidden = true;
}
async function sendWithTags(){
  const domain = $('tag-domain').value || 'general';
  const note   = $('tag-note').value;
  const tags   = [..._tags];
  const res    = $('tag-result');
  res.textContent = `Envoi ${_pending.length} URLs…`; res.style.color = '#888';

  // Try bulk first (token-economical)
  let sent = 0, bulkOk = false;
  try {
    const r = await hubFetch('/ingest/bulk', {
      method:'POST',
      body: JSON.stringify({
        header: LF_HDR,
        body: _pending.map(it => ({
          url: it.url, title: it.title,
          source:'linkgopher', tags, domain, notes: note,
          keywords: tags.join(', '), priority: 3
        }))
      }),
      _timeout: 12000
    });
    if (r.ok){ bulkOk = true; sent = _pending.length; }
  } catch(e) {}

  if (!bulkOk){
    for (const it of _pending){
      try {
        const r = await hubFetch('/ingest/url', {
          method:'POST',
          body: JSON.stringify({ header: LF_HDR, body: {
            url: it.url, title: it.title,
            source:'linkgopher', tags, domain, notes: note,
            keywords: tags.join(', '), priority: 3
          }}),
          _timeout: 4000
        });
        if (r.ok) sent++;
      } catch(e) {}
    }
  }

  // Notify hub (best-effort)
  try {
    await hubFetch('/mcp', {
      method:'POST',
      body: JSON.stringify({ jsonrpc:'2.0', id:1, method:'tools/call',
        params:{ name:'hub', arguments:{ action:'notify',
          message:`[BROWSER][INGEST] ${sent} URLs · tags:[${tags}] · domain:${domain}` }}})
    });
  } catch(e) {}

  res.textContent = `✓ ${sent}/${_pending.length} envoyées — tags:[${tags.join(', ')||'aucun'}] domain:${domain}`;
  res.style.color = '#00ff88';
  setTimeout(closeTagPanel, 2500);
}

// ─── Qualify (LLM) flow ───────────────────────────────────────────────
async function qualifyAndSend(items){
  const bar = ensureToast();
  bar.style.display = 'block';
  bar.textContent = `Ouverture et extraction de ${items.length} URLs…`;

  let extracted = [];
  try {
    const r = await chrome.runtime.sendMessage({ action:'qualifyUrls', items });
    extracted = r.results || [];
  } catch(e){
    bar.textContent = 'Erreur extraction: '+e.message;
    bar.style.borderBottomColor = 'var(--err)';
    return;
  }

  let qualified = 0;
  for (const doc of extracted){
    if (!doc.ok){ continue; }
    try {
      await hubFetch('/ingest/qualify', {
        method:'POST',
        body: JSON.stringify({ header: LF_HDR, body: {
          url: doc.url, title: doc.title || doc.h1, text: doc.text,
          meta_desc: doc.desc, keywords: doc.keywords,
          headings: [doc.h1, doc.h2s].filter(Boolean).join(' | '),
          lang: doc.lang, source: 'linkgopher_qualify'
        }}),
        _timeout: 30000
      });
      qualified++;
      bar.textContent = `✓ ${qualified}/${items.length} qualifiés…`;
    } catch(e){
      try {
        await hubFetch('/ingest/url', {
          method:'POST',
          body: JSON.stringify({ header: LF_HDR, body:{
            url: doc.url, title: doc.title, text: doc.text, source:'linkgopher'
          }}),
          _timeout: 5000
        });
      } catch(_){}
    }
  }

  bar.textContent = `✓ ${qualified}/${items.length} qualifiés et ingérés`;
  bar.style.borderBottomColor = 'var(--ok)';
  setTimeout(() => { bar.style.display='none'; }, 4000);
}

function ensureToast(){
  let bar = $('toast-bar');
  if (!bar){
    bar = document.createElement('div');
    bar.id = 'toast-bar';
    bar.className = 'toast-bar';
    document.body.appendChild(bar);
  }
  bar.style.borderBottomColor = 'var(--ac)';
  return bar;
}

// ─── Footer : hub health, token, options ──────────────────────────────
async function pollHealth(){
  const dot  = $('hub-dot');
  const text = $('hub-text');
  try {
    const r = await hubFetch('/health', { method:'GET', _timeout: 3000 });
    if (r.ok){
      dot.className = 'dot ok';
      text.textContent = 'Hub OK :8766';
      text.className = 'lf-status ok';
    } else throw new Error('HTTP '+r.status);
  } catch(e){
    dot.className = 'dot err';
    text.textContent = 'Hub down';
    text.className = 'lf-status err';
  }
}

async function refreshTokenStatus(){
  const tk = await getToken();
  const el = $('tok-text');
  if (tk){ el.textContent = '🔑 OK'; el.className = 'lf-status ok'; }
  else   { el.textContent = '⚠ pas de token'; el.className = 'lf-status warn'; }
}

$('open-options').addEventListener('click', () => {
  try { chrome.runtime.openOptionsPage(); }
  catch(e){
    chrome.tabs.create({ url: chrome.runtime.getURL('options.html') });
  }
});

function flashFooter(msg, kind){
  const el = $('foot-info');
  const old = el.textContent, oldCl = el.className;
  el.textContent = msg;
  el.className = 'lf-status ' + (kind||'');
  setTimeout(() => { el.textContent = old; el.className = oldCl; }, 2500);
}

// Boot footer + start health polling (every 30s)
refreshTokenStatus();
pollHealth();
setInterval(pollHealth, 30000);
try {
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && changes.forge_token) refreshTokenStatus();
  });
} catch {}
