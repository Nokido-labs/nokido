# -*- coding: utf-8 -*-
"""
tools/forge_ui_vitals_cover.py — MOULINETTE des SIGNAUX VITAUX (couvre le code cognitif).

Sibling de forge_ui_repo_cover (qui couvre les TOOLS hub en forms d'INPUT). Ici on
couvre les SIGNAUX (forge_vitals_tools.VITAL_SIGNALS) en panneaux d'OUTPUT (monitoring)
auto-generes, deterministes, 0 token. Comble le gap "la moulinette doit couvrir TOUT le
code" : les organes cognitifs (affect/agentivite/temps-subjectif/flux/percept) deviennent
des panneaux du dashboard sans une ligne de HTML ecrite a la main (doc interface P0/P1).

Chaque panneau (HTMX/Alpine, classes lf-* du Design System) poll /hub/tool/<signal>
toutes les 5s et rend le dict. Le signal vital atterrit via les tokens du Design System.

  LAFORGE_PYTHON tools/forge_ui_vitals_cover.py    # genere vitals_panels.py + selftest
"""
from __future__ import annotations
import ast, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (os.path.join(ROOT, "app"), os.path.join(ROOT, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

HEADER = ("# GENERE par forge_ui_vitals_cover — 1 panneau de monitoring par signal vital.\n"
          "# DETERMINISTE, 0 token cloud. Regen: LAFORGE_PYTHON tools/forge_ui_vitals_cover.py\n"
          "# Chaque panneau poll /api/vital/<signal> (5s) -> classes lf-* (Nokido Design System).\n"
          "from __future__ import annotations\n\n\n")


def _panel_html(name: str, title: str) -> str:
    # VANILLA (offline-natif, pas d'Alpine/CDN) : section + placeholders, le loader
    # nokido_vitals.js fetch /api/vital/<name> et remplit .lf-rows toutes les 5s.
    return (
        f'<section class="lf-panel" data-signal="{name}">\n'
        f'  <h3 class="lf-panel-title">{title}</h3>\n'
        f'  <div class="lf-panel-err"></div>\n'
        f'  <div class="lf-rows">…</div>\n'
        f'</section>'
    )


def generate() -> dict:
    from nokido_agent.app import forge_vitals_tools as V
    fns, names = [], []
    for name, fn in V.VITAL_SIGNALS.items():
        title = ((fn.__doc__ or name).strip().splitlines()[0]).strip()[:80]
        slug = re.sub(r"\W+", "_", name).strip("_").lower()
        html = _panel_html(name, title)
        fns.append(f"def render_{slug}_panel() -> str:\n    return {html!r}\n")
        names.append((name, slug))
    registry = "PANELS = {\n" + "".join(f"    {n!r}: render_{s}_panel,\n" for n, s in names) + "}\n"
    dash = ("\n\ndef render_dashboard() -> str:\n"
            "    return '<div class=\"lf-vitals-grid\">' + ''.join(f() for f in PANELS.values()) + '</div>'\n")
    module = HEADER + "\n\n".join(fns) + "\n\n" + registry + dash
    ast.parse(module)            # compile ?
    ns: dict = {}
    exec(module, ns)             # s'execute ?
    assert "PANELS" in ns and len(ns["PANELS"]) == len(names)
    assert "render_dashboard" in ns and ns["render_dashboard"]().startswith("<div")
    return {"module": module, "count": len(names), "panels": [n for n, _ in names]}


def design_handoff() -> dict:
    """Contrat de structure pour Claude Design : composant VitalPanel + 9 signaux
    (champs decouverts live) + tokens dynamiques + SSE + assets. La moulinette envoie
    CE contrat a claude design pour qu'il design la couche vitale avec la bonne forme."""
    from nokido_agent.app import forge_vitals_tools as V
    signals = []
    for name, fn in V.VITAL_SIGNALS.items():
        try:
            sample = fn()
            fields = list(sample.keys()) if isinstance(sample, dict) else []
        except Exception:
            fields = []
        signals.append({"signal": name, "poll_url": f"/api/vital/{name}",
                        "title": ((fn.__doc__ or name).strip().splitlines()[0]).strip()[:80],
                        "fields": fields})
    return {
        "component": "VitalPanel",
        "framework": "HTMX+Alpine+Tailwind (Nokido Design System, classes lf-*)",
        "layout": "lf-vitals-grid (responsive auto-fill minmax(260px))",
        "dynamic_tokens": ["--forge-surprise", "--forge-arousal", "--forge-frustration",
                           "--forge-tempo", "--forge-salience"],
        "sse": "/api/vitals/sse",
        "assets": {"css": "/static/nokido_vitals.css", "js": "/static/nokido_vitals.js"},
        "signals": signals,
    }


def main(argv=None) -> int:
    res = generate()
    # ecrit dans web_hub si possible (owner), sinon C:/tmp (sandbox)
    # repli-hors-depot-ok: ECRITURE, depot d'abord ; le compte sandbox ne peut pas
    # y ecrire, et l'echec est journalise avec sa cause (cf. commentaire ci-dessous).
    targets = [os.path.join(ROOT, "app", "web_hub", "vitals_panels.py"), r"C:\tmp\vitals_panels.py"]
    written = None
    # UN REPLI HORS DEPOT SE DECLARE, AVEC SA CAUSE. Le chemin final etait deja
    # imprime, mais la raison de l'echec du depot etait avalee : on savait qu'on avait
    # replie, jamais POURQUOI. Or un module genere qui atterrit dans `C:\tmp` echappe
    # a git, a la CI et au git-gate — audit du 2026-09-04, ou une copie de 77 jours
    # pilotait encore un lanceur. Le repli reste permis (le compte sandbox ne peut pas
    # ecrire dans le depot), mais il doit etre LISIBLE.
    echecs = []
    for t in targets:
        try:
            os.makedirs(os.path.dirname(t), exist_ok=True)
            with open(t, "w", encoding="utf-8") as f:
                f.write(res["module"])
            written = t
            break
        except Exception as exc:
            echecs.append("%s (%s: %s)" % (t, type(exc).__name__, str(exc)[:70]))
            continue
    print(f"VITALS COVER: {res['count']} panneaux generes -> {res['panels']}")
    print(f"ecrit: {written}")
    if echecs:
        print("  cibles ECARTEES avant celle-ci : %s" % " | ".join(echecs))
    if written and not str(written).startswith(str(ROOT)):
        print("  ATTENTION : ecrit HORS DEPOT — ce fichier n'est ni versionne, ni "
              "couvert par la CI, ni scanne par le gate de secrets. Le rapatrier "
              "dans le depot des qu'un compte le permet.")
    # contrat de structure pour Claude Design (la moulinette envoie ca)
    import json as _json
    dh = design_handoff()
    for dt in (os.path.join(ROOT, "design_handoff_nokido", "vitals_design_handoff.json"),
               os.path.join(ROOT, "app", "web_hub", "vitals_design_handoff.json"),
               r"C:\tmp\vitals_design_handoff.json"):
        try:
            os.makedirs(os.path.dirname(dt), exist_ok=True)
            with open(dt, "w", encoding="utf-8") as f:
                _json.dump(dh, f, ensure_ascii=False, indent=2)
            print(f"design_handoff (Claude Design) -> {dt} ({len(dh['signals'])} signaux)")
            break
        except Exception:
            continue
    # selftest : les signaux renvoient-ils des donnees reelles ?
    try:
        from nokido_agent.app import forge_vitals_tools as V
        vit = V.all_vitals()
        live = sum(1 for v in vit.values() if isinstance(v, dict) and "unavailable" not in v)
        print(f"signaux LIVE: {live}/{len(vit)} | ex subjective_tempo={vit.get('subjective_tempo')}")
    except Exception as e:  # noqa: BLE001
        print("selftest signaux:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
