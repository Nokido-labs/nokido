// Nokido — couche vitale, VANILLA (offline-natif, zero Alpine/CDN).
// (a) loader : fetch /api/vital/<signal> par panneau -> remplit .lf-rows (5s).
// (b) tokens : SSE /api/vitals/sse -> CSS variables (Design System vivant).
(function () {
  function meter(v, k) {
    var n = (typeof v === 'number') ? v : parseFloat(v);
    if (isNaN(n)) return '';
    var frac = (n >= 0 && n <= 1) ? n : (n >= 0 && n <= 100 ? n / 100 : null);
    if (frac === null) return '';
    var cls = 'ok', kl = String(k || '').toLowerCase();
    if (/stress|frustrat|fatigue|urgency|fault|overload/.test(kl)) cls = frac >= 0.75 ? 'err' : 'warn';
    var pct = Math.max(0, Math.min(100, Math.round(frac * 100)));
    return '<span class="lf-meter"><span class="lf-meter-fill ' + cls + '" data-pct="' + pct + '"></span></span>';
  }
  function render(sec, data) {
    var rows = sec.querySelector('.lf-rows');
    var err = sec.querySelector('.lf-panel-err');
    if (!rows) return;
    if (data && data.error) { if (err) err.textContent = data.error; rows.innerHTML = ''; return; }
    if (err) err.textContent = '';
    var html = '';
    for (var k in data) {
      if (!Object.prototype.hasOwnProperty.call(data, k)) continue;
      var v = data[k];
      var vs = (v !== null && typeof v === 'object') ? JSON.stringify(v) : String(v);
      html += '<div class="lf-row"><span class="lf-k">' + k + '</span>' + meter(v, k) + '<span class="lf-v">' + vs + '</span></div>';
    }
    rows.innerHTML = html || '<div class="lf-row"><span class="lf-v">(vide)</span></div>';
    var fills = rows.querySelectorAll('.lf-meter-fill');
    for (var m = 0; m < fills.length; m++) { fills[m].style.width = fills[m].getAttribute('data-pct') + '%'; }
  }
  function load() {
    var secs = document.querySelectorAll('section[data-signal]');
    for (var i = 0; i < secs.length; i++) {
      (function (sec) {
        var name = sec.getAttribute('data-signal');
        fetch('/api/vital/' + name, { credentials: 'same-origin' })
          .then(function (r) { return r.json(); })
          .then(function (j) { render(sec, j); })
          .catch(function (e) { render(sec, { error: String(e) }); });
      })(secs[i]);
    }
  }
  // ── Controles REELS : ils agissent sur le flux vivant, pas sur un decor ──────
  // Mesure 2026-08-26 : la page portait 0 element interactif — un mur d'observation
  // que personne ne pouvait ni figer, ni filtrer, ni rafraichir a la demande.
  var timer = null, enPause = false, es = null;

  function planifier() {
    if (timer) { clearInterval(timer); timer = null; }
    if (!enPause) timer = setInterval(load, 5000);
  }
  function etat(txt) {
    var e = document.getElementById('lf-etat');
    if (e) e.textContent = txt;
  }
  function filtrer(q) {
    q = (q || '').trim().toLowerCase();
    var secs = document.querySelectorAll('section[data-signal]'), n = 0;
    for (var i = 0; i < secs.length; i++) {
      var s = secs[i];
      var cle = (s.getAttribute('data-signal') + ' ' + (s.textContent || '')).toLowerCase();
      var vu = !q || cle.indexOf(q) >= 0;
      s.style.display = vu ? '' : 'none';
      if (vu) n++;
    }
    // On affiche le denominateur : « 3 sur 14 » ne se confond pas avec « 3 signaux ».
    etat(q ? (n + ' signal(s) sur ' + secs.length + ' — filtre "' + q + '"')
           : (secs.length + ' signaux — ' + (enPause ? 'FIGE' : 'live 5 s')));
  }

  function brancherControles() {
    var b = document.getElementById('lf-refresh');
    if (b) b.addEventListener('click', function () { load(); etat('rafraichi a la demande'); });
    var p = document.getElementById('lf-pause');
    if (p) p.addEventListener('click', function () {
      enPause = !enPause;
      p.textContent = enPause ? '▶ Reprendre' : '⏸ Figer';
      p.setAttribute('aria-pressed', enPause ? 'true' : 'false');
      if (enPause && es) { es.close(); es = null; } else if (!enPause) { ouvrirSSE(); }
      planifier();
      var ff = document.getElementById('lf-filtre');
      filtrer(ff ? ff.value : '');
    });
    var f = document.getElementById('lf-filtre');
    if (f) f.addEventListener('input', function () { filtrer(f.value); });
    filtrer('');
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', brancherControles);
  } else {
    brancherControles();
  }

  load();
  planifier();

  // Tokens vitaux via SSE -> fond ambiant
  function ouvrirSSE() {
  try {
    es = new EventSource('/api/vitals/sse');
    es.onmessage = function (e) {
      var d; try { d = JSON.parse(e.data); } catch (err) { return; }
      if (!d || d.type !== 'vitals') return;
      var r = document.documentElement.style;
      r.setProperty('--forge-surprise', d.surprise != null ? d.surprise : 0);
      r.setProperty('--forge-arousal', d.arousal != null ? d.arousal : 0.3);
      r.setProperty('--forge-frustration', d.frustration != null ? d.frustration : 0);
      r.setProperty('--forge-tempo', d.tempo != null ? d.tempo : 1);
      r.setProperty('--forge-salience', d.salience != null ? d.salience : 0);
    };
    es.onerror = function () { /* SSE indispo -> tokens statiques */ };
  } catch (e) { /* EventSource absent */ }
  }
  ouvrirSSE();
})();
