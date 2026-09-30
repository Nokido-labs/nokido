"""hub_shell_html.py — Coquille « Hub Nokido PC » (portail unifie :7400).

Port server-rendered (Alpine + nokido.css) de la maquette React
design_handoff_nokido/ui_kits/hub/. Phase 1 + C2-deep : utilise les PRIMITIVES
du design-system (laforge-components.css) — `.lf-module` (tuiles), `.lf-gauge`
(souverainete), `.lf-prov` (provenance), `.lf-power` (curseur) — au lieu de CSS
hand-rolled. Seul le CHROME (sidebar/topbar/nav layout) est local (pas dans le DS).

Accueil = grille de modules via render_modules. Cap/Federation/Maison/Persona =
scaffolds (Phase 5). Assets 100% locaux (souverain) : nokido.css + lucide + alpine.
"""
from __future__ import annotations

from app.web_hub.dashboard_html import render_modules

_BOLT = (
    '<svg width="26" height="26" viewBox="0 0 64 64" fill="none" style="flex-shrink:0">'
    '<defs><linearGradient id="lfBolt" x1="26" y1="12" x2="40" y2="40" gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#FFE070"/><stop offset="1" stop-color="#FFC22D"/></linearGradient></defs>'
    '<g stroke="#15121F" stroke-width="2.4" stroke-linejoin="round">'
    '<path d="M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z" fill="#9A90BC"/>'
    '<path d="M28 45 h8 l-1.5 5 h-5 Z" fill="#6F6498"/>'
    '<path d="M17 50 H47 l3 6 H14 Z" fill="#9A90BC"/></g>'
    '<g><rect x="4" y="29" width="23" height="5" rx="2.5" fill="#C77D4A" stroke="#15121F" stroke-width="2.4" stroke-linejoin="round"/>'
    '<rect x="25" y="21" width="11" height="21" rx="3" fill="#B7BCD2" stroke="#15121F" stroke-width="2.4" stroke-linejoin="round"/>'
    '<rect x="27.5" y="24" width="5.5" height="6" rx="1.5" fill="#D9DCE8"/></g>'
    '<path d="M31 41 L40 26 H34 L42 11 L30 28 H36 Z" fill="url(#lfBolt)" stroke="#15121F" stroke-width="2" stroke-linejoin="round"/></svg>'
)

_SHELL = """<!doctype html>
<html lang="fr" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hub Nokido PC</title>
<link rel="stylesheet" href="/static/nokido.css">
<script src="/static/lucide.min.js"></script>
<script src="/static/alpine.min.js" defer></script>
<style>
  /* CHROME du shell uniquement (pas dans le DS). Composants = classes .lf-* de laforge-components.css. */
  html, body { height: 100%; }
  body { margin: 0; background: var(--bg-0); color: var(--text-primary); font-family: var(--font-sans); overflow: hidden; }
  [x-cloak] { display: none !important; }
  #hub { height: 100vh; display: flex; }
  .hub-aside { width: var(--sidebar-w, 220px); background: var(--bg-1); border-right: 1px solid var(--border-subtle);
               display: flex; flex-direction: column; flex-shrink: 0; }
  .hub-brand { display: flex; align-items: center; gap: 8px; padding: 14px 16px; border-bottom: 1px solid var(--border-subtle); }
  .hub-brand b { font-size: 15px; letter-spacing: 0.4px; }
  .hub-brand .dot { margin-left: auto; width: 7px; height: 7px; border-radius: 50%; background: var(--green); }
  .hub-nav { padding: 10px 8px; display: flex; flex-direction: column; gap: 2px; }
  .hub-nav button { display: flex; align-items: center; gap: 10px; padding: 9px 11px; border-radius: var(--radius-sm);
               border: none; cursor: pointer; text-align: left; font-size: 13px; font-weight: 500; font-family: var(--font-sans);
               background: transparent; color: var(--text-secondary); transition: background var(--motion-fast); }
  .hub-nav button:hover { background: var(--bg-2); }
  .hub-nav button.on { background: var(--bg-3); color: var(--text-primary); font-weight: 600; box-shadow: inset 3px 0 0 var(--purple); }
  .hub-foot { margin-top: auto; padding: 14px; border-top: 1px solid var(--border-subtle); }
  .hub-id { margin-top: 12px; display: flex; align-items: center; gap: 8px; }
  .hub-id .av { width: 26px; height: 26px; border-radius: 50%; background: var(--purple-dim); display: flex;
               align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
  .hub-id .nm { font-size: 12px; font-weight: 600; }
  .hub-id .rg { font-family: var(--font-mono); font-size: 9.5px; color: var(--text-dim); }
  .hub-main-col { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .hub-top { height: var(--topbar-h, 52px); border-bottom: 1px solid var(--border-subtle); background: var(--bg-1);
             display: flex; align-items: center; padding: 0 22px; gap: 14px; flex-shrink: 0; }
  .hub-top .t { font-size: 15px; font-weight: 700; line-height: 1.1; }
  .hub-top .s { font-size: 11px; color: var(--text-dim); font-family: var(--font-mono); }
  .hub-top .right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
  .hub-main { flex: 1; overflow-y: auto; padding: 24px 28px; }
  .hub-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
  .hub-scaffold { border: 1px dashed var(--border); border-radius: var(--radius-md); padding: 28px;
               color: var(--text-secondary); background: var(--bg-1); }
  .hub-scaffold h2 { margin: 0 0 6px; color: var(--text-primary); }
</style>
</head>
<body>
<div id="hub" x-data="hub()" x-cloak>

  <aside class="hub-aside">
    <div class="hub-brand">__BOLT__ <b>Nokido</b> <span class="dot laforge-pulse"></span></div>
    <nav class="hub-nav">
      <button data-testid="nav-accueil" :class="view==='accueil'      ? 'on':''" @click="go('accueil')"><i data-lucide="layout-grid"></i>Accueil</button>
      <button data-testid="nav-cap" :class="view==='cap'          ? 'on':''" @click="go('cap')"><i data-lucide="target"></i>Intention longue</button>
      <button data-testid="nav-federation" :class="view==='federation'   ? 'on':''" @click="go('federation')"><i data-lucide="share-2"></i>Fédération</button>
      <button data-testid="nav-maison" :class="view==='maison'       ? 'on':''" @click="go('maison')"><i data-lucide="house"></i>Maison</button>
      <button data-testid="nav-persona" :class="view==='persona'      ? 'on':''" @click="go('persona')"><i data-lucide="brain"></i>Mémoire persona</button>
      <button data-testid="nav-souverainete" :class="view==='souverainete' ? 'on':''" @click="go('souverainete')"><i data-lucide="shield-check"></i>Souveraineté</button>
    </nav>
    <div class="hub-foot">
      <div class="lf-gauge">
        <div class="lf-gauge__head"><span class="lf-gauge__label">Souveraineté</span><span class="lf-gauge__pct" x-text="power+'%'"></span></div>
        <div class="lf-gauge__track"><div class="lf-gauge__fill" :style="'width:'+power+'%'"></div></div>
        <div class="lf-gauge__legend"><span>distant</span><span>local</span></div>
      </div>
      <div class="hub-id">
        <span class="av">__USERINITIAL__</span>
        <div style="line-height:1.2"><div class="nm">__USER__</div><div class="rg">Ring __RING__ · nœud souverain</div></div>
      </div>
    </div>
  </aside>

  <div class="hub-main-col">
    <header class="hub-top">
      <div><div class="t" x-text="titles[view][0]"></div><div class="s" x-text="titles[view][1]"></div></div>
      <div class="right">
        <span class="lf-prov" :class="prov==='hybrid' ? 'lf-prov--hybrid' : (prov==='remote' ? 'lf-prov--remote' : '')" x-text="power+'% local'"></span>
        <button data-testid="nav-theme" class="lf-btn lf-btn--ghost lf-btn--sm" @click="cycleTheme()" :title="'Thème : '+theme"><i :data-lucide="themeIcon"></i></button>
        <span style="font-family:var(--font-mono);font-size:11px;color:var(--text-dim);border:1px solid var(--border);border-radius:var(--radius-sm);padding:2px 8px">v__VERSION__</span>
      </div>
    </header>

    <main class="hub-main">
      <section x-show="view==='accueil'" class="hub-grid">__MODULES__</section>

      <section x-show="view==='cap'" class="hub-scaffold">
        <h2>Intention longue (Cap)</h2>
        <p>Horizon → jalons → étapes, anneaux d'intégrité (composant DS <code>.lf-step</code>). À brancher sur le SSoT / roadmap (forge_ssot). <em>Phase 5.</em></p>
      </section>
      <section x-show="view==='federation'" class="hub-scaffold">
        <h2>Fédération</h2>
        <p>Exposer son hub d'IA, garde-fous souverains, pairs de confiance. <em>Phase 5.</em></p>
      </section>
      <section x-show="view==='maison'" class="hub-scaffold">
        <h2>Maison — domotique local-first</h2>
        <p>Scènes + appareils, garantie « ne dépend jamais du cloud ». <em>Phase 5.</em></p>
      </section>
      <section x-show="view==='persona'" class="hub-scaffold">
        <h2>Mémoire du persona</h2>
        <p>Souvenirs (provenance + anneau) + « Oublier » révocable. À brancher sur la mémoire/persona. <em>Phase 5.</em></p>
      </section>

      <section x-show="view==='souverainete'" class="hub-scaffold">
        <h2>Souveraineté</h2>
        <p>Plus de local = plus de confidentialité ; plus de distant = plus de puissance brute (signalé, réversible).</p>
        <div class="lf-power" style="margin-top:14px">
          <div class="lf-power__head"><strong>Puissance allouée</strong><span class="lf-gauge__pct" x-text="power+'% local · '+prov"></span></div>
          <input type="range" min="0" max="100" step="1" x-model.number="power" class="lf-power-range">
          <div class="lf-power__metrics"><span>← confidentialité (local)</span><span style="margin-left:auto">puissance / coût / latence (distant) →</span></div>
        </div>
      </section>
    </main>
  </div>
</div>

<script>
function hub(){
  return {
    view: 'accueil',
    power: Number(localStorage.getItem('lf_power')) || 68,
    theme: localStorage.getItem('lf_theme') || 'dark',
    titles: {
      accueil: ['Accueil', 'ton hub personnel · local par défaut'],
      cap: ['Intention longue', 'le cap → jalons → étapes'],
      federation: ['Fédération', "exposer son hub d'IA · garde-fous souverains"],
      maison: ['Maison', 'domotique · local-first absolu'],
      persona: ['Mémoire du persona', 'visible · éditable · révocable'],
      souverainete: ['Souveraineté', 'curseur puissance · provenance']
    },
    get prov(){ return this.power >= 60 ? 'local' : this.power >= 30 ? 'hybrid' : 'remote'; },
    get themeIcon(){ return {dark:'moon', light:'sun', auto:'monitor'}[this.theme] || 'moon'; },
    init(){
      document.documentElement.dataset.theme = this.theme;
      this.$watch('power', v => localStorage.setItem('lf_power', v));
      this.$nextTick(() => window.lucide && lucide.createIcons());
    },
    go(v){ this.view = v; this.$nextTick(() => window.lucide && lucide.createIcons()); },
    cycleTheme(){
      const o = ['dark','light','auto'];
      this.theme = o[(o.indexOf(this.theme)+1) % 3];
      document.documentElement.dataset.theme = this.theme;
      localStorage.setItem('lf_theme', this.theme);
      this.$nextTick(() => window.lucide && lucide.createIcons());
    }
  };
}
window.addEventListener('load', () => { if (window.lucide) lucide.createIcons(); });
</script>
</body></html>
"""


def render_hub_shell(services: dict, version: str, *, user: str = "user", ring: int = 0) -> str:
    """Rend la coquille Hub Nokido PC. Accueil = tuiles .lf-module (DS)."""
    initial = (user[:1] or "N").upper()
    return (
        _SHELL.replace("__BOLT__", _BOLT)
        .replace("__MODULES__", render_modules(services))
        .replace("__VERSION__", str(version))
        .replace("__USERINITIAL__", initial)
        .replace("__USER__", user)
        .replace("__RING__", str(ring))
    )
