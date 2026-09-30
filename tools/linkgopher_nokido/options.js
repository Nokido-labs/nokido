'use strict';

const tokEl = document.getElementById('tok');
const stEl  = document.getElementById('status');

function setStatus(msg, kind) {
  stEl.textContent = msg;
  stEl.className = 'status' + (kind ? ' ' + kind : '');
}

// Load existing token (do not log it)
chrome.storage.local.get('forge_token').then(r => {
  tokEl.value = r?.forge_token || '';
  if (tokEl.value) setStatus('Token chargé.', 'ok');
}).catch(() => {});

document.getElementById('show-tok').addEventListener('click', e => {
  if (tokEl.type === 'password') { tokEl.type = 'text'; e.target.textContent = '🙈 masquer'; }
  else { tokEl.type = 'password'; e.target.textContent = '👁 afficher'; }
});

document.getElementById('save').addEventListener('click', async () => {
  const v = tokEl.value.trim();
  await chrome.storage.local.set({ forge_token: v });
  setStatus(v ? '✓ Token enregistré.' : '✓ Token effacé.', 'ok');
});

document.getElementById('clear').addEventListener('click', async () => {
  tokEl.value = '';
  await chrome.storage.local.remove('forge_token');
  setStatus('Token effacé.', 'ok');
});

document.getElementById('test').addEventListener('click', async () => {
  setStatus('Test en cours...', '');
  const tok = tokEl.value.trim();
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (tok) headers['Authorization'] = 'Bearer ' + tok;
    const r = await fetch('http://127.0.0.1:8766/search?q=test&limit=1', {
      method: 'GET', headers,
      signal: AbortSignal.timeout(5000)
    });
    if (r.ok) setStatus(`✓ Hub répond (${r.status}).`, 'ok');
    else if (r.status === 401 || r.status === 403) setStatus(`✗ Auth refusée (${r.status}). Token invalide ?`, 'warn');
    else setStatus(`⚠ Hub a répondu ${r.status}.`, 'warn');
  } catch(e) {
    setStatus('✗ Hub injoignable: ' + e.message, 'warn');
  }
});
