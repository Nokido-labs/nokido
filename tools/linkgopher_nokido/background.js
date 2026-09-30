
// background.js v4.1
const HUB    = 'http://127.0.0.1:8766';
const LF_HDR = 'LF1.B.H.1.5.ING';

// ── Token storage helpers (Bearer auth) ──────────────────────────────────────
async function getToken() {
  try {
    const r = await chrome.storage.local.get('forge_token');
    return r?.forge_token || '';
  } catch(e) { return ''; }
}

// Single DRY hub fetch helper. Auto-attaches Authorization: Bearer if token set.
async function hubFetch(path, init) {
  const token = await getToken();
  const headers = Object.assign(
    { 'Content-Type': 'application/json' },
    (init && init.headers) || {}
  );
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const opts = Object.assign({}, init, { headers });
  if (!opts.signal) opts.signal = AbortSignal.timeout(opts._timeout || 8000);
  return fetch(`${HUB}${path}`, opts);
}

// ── Menus contextuels ────────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  // Menu sur texte sélectionné
  chrome.contextMenus.create({
    id: 'lf-send-text',
    title: '⚡ Envoyer le texte à Nokido',
    contexts: ['selection']
  });
  // Menu sur lien
  chrome.contextMenus.create({
    id: 'lf-send-link',
    title: '⚡ Envoyer ce lien à Nokido',
    contexts: ['link']
  });
  // Menu sur page entière
  chrome.contextMenus.create({
    id: 'lf-send-page',
    title: '⚡ Envoyer cette page à Nokido',
    contexts: ['page']
  });
  // Séparateur + ouvrir Link Gopher
  chrome.contextMenus.create({ id: 'lf-sep', type: 'separator', contexts: ['page','selection','link'] });
  chrome.contextMenus.create({
    id: 'lf-open',
    title: '🔗 Ouvrir Link Gopher',
    contexts: ['page','selection','link']
  });
  // Markdown copy (token-economical for LLMs)
  chrome.contextMenus.create({ id: 'lf-md-sep', type: 'separator', contexts: ['page','selection'] });
  chrome.contextMenus.create({
    id: 'lf-md-selection',
    title: '📋 Copier sélection en Markdown',
    contexts: ['selection']
  });
  chrome.contextMenus.create({
    id: 'lf-md-article',
    title: '📋 Copier article en Markdown (clean)',
    contexts: ['page']
  });
  chrome.contextMenus.create({
    id: 'lf-md-full',
    title: '📋 Copier page entière en Markdown',
    contexts: ['page']
  });
  // Qualify link via hub LLM
  chrome.contextMenus.create({ id: 'lf-q-sep', type: 'separator', contexts: ['link'] });
  chrome.contextMenus.create({
    id: 'lf-qualify-link',
    title: '🧪 Qualifier ce lien (Nokido)',
    contexts: ['link']
  });
  // Options
  chrome.contextMenus.create({ id: 'lf-opt-sep', type: 'separator', contexts: ['action','page'] });
  chrome.contextMenus.create({
    id: 'lf-options',
    title: '🔑 Configurer token Nokido',
    contexts: ['action','page']
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === 'lf-send-text') {
    await hubIngest({
      header: LF_HDR,
      body: {
        url:    tab.url,
        title:  tab.title,
        text:   info.selectionText,
        source: 'contextmenu_selection',
        type:   'text_selection'
      }
    });
    notify(tab.id, `✓ Texte envoyé à Nokido (${info.selectionText.length} chars)`);
  }
  if (info.menuItemId === 'lf-send-link') {
    await hubIngest({
      header: LF_HDR,
      body: { url: info.linkUrl, title: info.linkUrl, source: 'contextmenu_link' }
    });
    notify(tab.id, `✓ Lien envoyé : ${info.linkUrl.substring(0,60)}...`);
  }
  if (info.menuItemId === 'lf-send-page') {
    // Extraire texte + meta de la page
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => ({
        url:   location.href,
        title: document.title,
        text:  document.body.innerText.substring(0, 8000),
        meta:  document.querySelector('meta[name="description"]')?.content || ''
      })
    });
    const data = results?.[0]?.result;
    if (data) {
      await hubIngest({ header: LF_HDR, body: { ...data, source: 'contextmenu_page', type: 'page_content' } });
      notify(tab.id, `✓ Page envoyée à Nokido`);
    }
  }
  if (info.menuItemId === 'lf-open') {
    chrome.tabs.create({ url: chrome.runtime.getURL(
      `browser/linkgopher.html?tabId=${tab.id}&filtering=false&filteringDomains=false&onlyDomains=false`
    )});
  }
  if (info.menuItemId === 'lf-options') {
    if (chrome.runtime.openOptionsPage) chrome.runtime.openOptionsPage();
    else chrome.tabs.create({ url: chrome.runtime.getURL('options.html') });
  }
  if (info.menuItemId === 'lf-qualify-link') {
    try {
      const r = await hubQualify({ url: info.linkUrl, title: info.linkUrl });
      notify(tab.id, r.ok
        ? `🧪 Qualifié : ${info.linkUrl.substring(0,55)}...`
        : `✗ Qualify: ${r.error || 'fail'}`);
    } catch(e) { notify(tab.id, `✗ Qualify: ${e.message}`); }
  }
  // Markdown copy handlers
  if (info.menuItemId === 'lf-md-selection' || info.menuItemId === 'lf-md-article' || info.menuItemId === 'lf-md-full') {
    const mode = info.menuItemId.replace('lf-md-', ''); // selection|article|full
    try {
      const r = await chrome.scripting.executeScript({
        target: { tabId: tab.id },
        func: copyAsMarkdown,
        args: [mode]
      });
      const out = r?.[0]?.result;
      if (out?.ok) notify(tab.id, `✓ MD copié (${out.tokens_est} tokens, ${out.chars} chars)`);
      else notify(tab.id, `✗ MD: ${out?.error || 'fail'}`);
    } catch(e) { notify(tab.id, `✗ MD: ${e.message}`); }
  }
});

// ─── Markdown converter (injected into page context) ────────────────────────
// Token-economical HTML→MD for LLM consumption.
// Strips nav/footer/script/aside/forms; preserves headings, p, lists, links,
// code, tables, blockquote. Modes: selection|article|full.
function copyAsMarkdown(mode) {
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','SVG','IFRAME','NAV','FOOTER',
                        'ASIDE','FORM','BUTTON','HEADER','TEMPLATE','VIDEO','AUDIO','CANVAS']);
  function pickRoot() {
    if (mode === 'selection') {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
      const div = document.createElement('div');
      div.appendChild(sel.getRangeAt(0).cloneContents());
      return div;
    }
    if (mode === 'article') {
      // Heuristic: prefer <article>, then <main>, then biggest text container.
      const a = document.querySelector('article');
      if (a && a.innerText.length > 200) return a;
      const m = document.querySelector('main');
      if (m && m.innerText.length > 200) return m;
      // Largest by text length
      let best = document.body, bestLen = 0;
      for (const el of document.querySelectorAll('section, div')) {
        const t = el.innerText || '';
        if (t.length > bestLen && t.length < 50000) { best = el; bestLen = t.length; }
      }
      return best;
    }
    return document.body;
  }
  function clean(s) { return (s || '').replace(/\s+/g, ' ').replace(/^\s|\s$/g, ''); }
  function walk(n, out, ctx) {
    if (n.nodeType === 3) { out.push(n.textContent); return; }
    if (n.nodeType !== 1) return;
    const tag = n.tagName;
    if (SKIP.has(tag)) return;
    if (n.getAttribute && (n.getAttribute('aria-hidden') === 'true' || n.getAttribute('hidden') !== null)) return;
    if (/^H[1-6]$/.test(tag)) {
      out.push('\n\n' + '#'.repeat(+tag[1]) + ' ' + clean(n.textContent) + '\n\n');
      return;
    }
    if (tag === 'P') { out.push('\n\n'); for (const c of n.childNodes) walk(c, out, ctx); out.push('\n\n'); return; }
    if (tag === 'BR') { out.push('\n'); return; }
    if (tag === 'HR') { out.push('\n\n---\n\n'); return; }
    if (tag === 'A') {
      const href = n.getAttribute('href') || '';
      const txt = clean(n.textContent);
      if (href && txt && !href.startsWith('javascript:') && !href.startsWith('#')) {
        out.push(`[${txt}](${href})`);
      } else if (txt) { out.push(txt); }
      return;
    }
    if (tag === 'IMG') {
      const alt = clean(n.getAttribute('alt') || '');
      const src = n.getAttribute('src') || '';
      if (src && !src.startsWith('data:')) out.push(`![${alt}](${src})`);
      return;
    }
    if (tag === 'STRONG' || tag === 'B') { out.push('**'); for (const c of n.childNodes) walk(c, out, ctx); out.push('**'); return; }
    if (tag === 'EM' || tag === 'I')     { out.push('*');  for (const c of n.childNodes) walk(c, out, ctx); out.push('*');  return; }
    if (tag === 'CODE' && n.parentElement?.tagName !== 'PRE') {
      out.push('`' + n.textContent + '`'); return;
    }
    if (tag === 'PRE') {
      const lang = n.querySelector('code')?.className?.match(/language-(\S+)/)?.[1] || '';
      out.push('\n\n```' + lang + '\n' + n.textContent.replace(/\n+$/, '') + '\n```\n\n');
      return;
    }
    if (tag === 'BLOCKQUOTE') {
      const buf = [];
      for (const c of n.childNodes) walk(c, buf, ctx);
      const txt = buf.join('').trim().split('\n').map(l => '> ' + l).join('\n');
      out.push('\n\n' + txt + '\n\n');
      return;
    }
    if (tag === 'UL' || tag === 'OL') {
      out.push('\n');
      let i = 0;
      for (const li of n.children) {
        if (li.tagName !== 'LI') continue;
        i++;
        const prefix = tag === 'OL' ? `${i}. ` : '- ';
        const buf = [];
        for (const c of li.childNodes) walk(c, buf, ctx);
        const t = clean(buf.join('').replace(/\n+/g, ' '));
        out.push(prefix + t + '\n');
      }
      out.push('\n');
      return;
    }
    if (tag === 'TABLE') {
      const rows = n.querySelectorAll('tr');
      if (!rows.length) return;
      const head = [...rows[0].querySelectorAll('th,td')].map(c => clean(c.textContent).replace(/\|/g, '\\|'));
      out.push('\n\n| ' + head.join(' | ') + ' |\n|' + head.map(() => '---').join('|') + '|\n');
      for (let r = 1; r < rows.length; r++) {
        const cells = [...rows[r].querySelectorAll('td,th')].map(c => clean(c.textContent).replace(/\|/g, '\\|'));
        out.push('| ' + cells.join(' | ') + ' |\n');
      }
      out.push('\n');
      return;
    }
    for (const c of n.childNodes) walk(c, out, ctx);
  }
  try {
    const root = pickRoot();
    if (!root) return { ok: false, error: 'no-content' };
    const out = [];
    walk(root, out, {});
    let md = out.join('')
      .replace(/[ \t]+\n/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .replace(/[ \t]{2,}/g, ' ')
      .trim();
    // Front-matter for context
    const fm = `> Source: [${document.title || location.host}](${location.href})\n\n`;
    md = fm + md;
    // Copy
    return navigator.clipboard.writeText(md).then(() => ({
      ok: true,
      chars: md.length,
      tokens_est: Math.ceil(md.length / 4)
    })).catch(e => ({ ok: false, error: 'clipboard:' + e.message }));
  } catch(e) {
    return { ok: false, error: String(e) };
  }
}

// ── Clic icone toolbar → ouvre Link Gopher ───────────────────────────────────
chrome.action.onClicked.addListener((tab) => {
  chrome.tabs.create({ url: chrome.runtime.getURL(
    `browser/linkgopher.html?tabId=${tab.id}&filtering=false&filteringDomains=false&onlyDomains=false`
  )});
});

// ── Messages depuis linkgopher.html ──────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.action === 'extractLinks') {
    chrome.scripting.executeScript({
      target: { tabId: msg.tabId },
      func: () => {
        const links = [];
        for (let i = 0; i < document.links.length; i++)
          links.push(decodeURI(document.links[i].href));
        return links.length ? links : null;
      }
    }).then(r => sendResponse({ links: r?.[0]?.result ?? null }))
      .catch(e => sendResponse({ error: e.message }));
    return true;
  }

  if (msg.action === 'extractText') {
    chrome.scripting.executeScript({
      target: { tabId: msg.tabId },
      func: () => ({
        text:     document.body.innerText.substring(0, 12000),
        title:    document.title,
        url:      location.href,
        selected: window.getSelection()?.toString() || ''
      })
    }).then(r => sendResponse({ data: r?.[0]?.result ?? null }))
      .catch(e => sendResponse({ error: e.message }));
    return true;
  }

  if (msg.action === 'getTabs') {
    chrome.tabs.query({}, tabs => {
      sendResponse({ tabs: tabs
        .filter(t => t.url?.startsWith('http'))
        .map(t => ({ id:t.id, url:t.url, title:t.title||t.url, favIconUrl:t.favIconUrl||'' }))
      });
    });
    return true;
  }

  if (msg.action === 'hubBulk') {
    hubBulk(msg.items || []).then(r => sendResponse(r));
    return true;
  }

  if (msg.action === 'hubQualify') {
    hubQualify({ url: msg.url, title: msg.title, text: msg.text }).then(r => sendResponse(r));
    return true;
  }

  if (msg.action === 'hubSearch') {
    hubSearch(msg.q, msg.limit).then(r => sendResponse(r));
    return true;
  }

  if (msg.action === 'getHistory') {
    // Firefox : text='' peut retourner rien → utiliser startTime + text
    const query = msg.query || '';
    const params = {
      text: query,
      maxResults: msg.maxResults || 300,
      startTime: Date.now() - (1000 * 60 * 60 * 24 * 90) // 90 jours
    };
    chrome.history.search(params, items => {
      const results = (items || [])
        .filter(i => i.url?.startsWith('http'))
        .sort((a,b) => b.lastVisitTime - a.lastVisitTime)
        .map(i => ({
          url: i.url,
          title: i.title || i.url,
          visitCount: i.visitCount,
          lastVisit: i.lastVisitTime
        }));
      sendResponse({ history: results, total: results.length });
    });
    return true;
  }
});


  // Qualification : ouvre chaque URL, extrait texte, ferme l'onglet
  if (msg.action === 'qualifyUrls') {
    (async () => {
      const results = [];
      for (const item of msg.items) {
        let tabId = null;
        try {
          // Ouvrir dans un onglet en arrière-plan
          const tab = await chrome.tabs.create({ url: item.url, active: false });
          tabId = tab.id;

          // Attendre que la page soit chargée (max 8s)
          await new Promise((resolve) => {
            const listener = (id, info) => {
              if (id === tabId && info.status === 'complete') {
                chrome.tabs.onUpdated.removeListener(listener);
                resolve();
              }
            };
            chrome.tabs.onUpdated.addListener(listener);
            setTimeout(resolve, 8000); // timeout
          });

          // Extraire texte + meta
          const extracted = await chrome.scripting.executeScript({
            target: { tabId },
            func: () => {
              const meta = (sel) => document.querySelector(sel)?.content || '';
              return {
                title:    document.title,
                text:     document.body.innerText.substring(0, 6000),
                lang:     document.documentElement.lang || '',
                desc:     meta('meta[name="description"]') || meta('meta[property="og:description"]'),
                keywords: meta('meta[name="keywords"]'),
                h1:       document.querySelector('h1')?.innerText || '',
                h2s:      [...document.querySelectorAll('h2')].slice(0,5).map(h=>h.innerText).join(' | ')
              };
            }
          });

          results.push({
            url:   item.url,
            title: item.title,
            ...( extracted?.[0]?.result || {} ),
            ok: true
          });

        } catch(e) {
          results.push({ url: item.url, title: item.title, error: e.message, ok: false });
        } finally {
          // Fermer l'onglet temporaire
          if (tabId) {
            try { await chrome.tabs.remove(tabId); } catch(e) {}
          }
        }

        // Petit délai entre chaque URL pour ne pas surcharger
        await new Promise(r => setTimeout(r, 500));
      }
      sendResponse({ results });
    })();
    return true; // async
  }

// ── Hub helpers (all routed via hubFetch → auto Bearer) ─────────────────────
async function hubIngest(payload) {
  try {
    await hubFetch('/ingest/url', {
      method: 'POST',
      body: JSON.stringify(payload),
      _timeout: 5000
    });
  } catch(e) { console.warn('Nokido hub offline:', e.message); }
}

async function hubBulk(items) {
  try {
    const res = await hubFetch('/ingest/bulk', {
      method: 'POST',
      body: JSON.stringify({ header: LF_HDR, body: { items } }),
      _timeout: 15000
    });
    return { ok: res.ok, status: res.status };
  } catch(e) {
    return { ok: false, error: e.message };
  }
}

async function hubQualify({ url, title, text }) {
  try {
    const res = await hubFetch('/qualify', {
      method: 'POST',
      body: JSON.stringify({ header: LF_HDR, body: { url, title, text } }),
      _timeout: 30000
    });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    let data = null;
    try { data = await res.json(); } catch(_) {}
    return { ok: true, data };
  } catch(e) {
    return { ok: false, error: e.message };
  }
}

async function hubSearch(q, limit) {
  try {
    const u = `/search?q=${encodeURIComponent(q)}&limit=${encodeURIComponent(limit||10)}`;
    const res = await hubFetch(u, { method: 'GET', _timeout: 8000 });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    const data = await res.json().catch(() => ({}));
    return { ok: true, data };
  } catch(e) {
    return { ok: false, error: e.message };
  }
}

function notify(tabId, msg) {
  chrome.scripting.executeScript({
    target: { tabId },
    func: (m) => {
      const el = document.createElement('div');
      el.style.cssText = 'position:fixed;top:16px;right:16px;z-index:999999;background:#0d1117;color:#00d4ff;border:1px solid #00d4ff;padding:10px 16px;border-radius:6px;font-family:monospace;font-size:13px;box-shadow:0 4px 20px rgba(0,212,255,.3)';
      el.textContent = m;
      document.body.appendChild(el);
      setTimeout(() => el.remove(), 3000);
    },
    args: [msg]
  }).catch(() => {});
}
