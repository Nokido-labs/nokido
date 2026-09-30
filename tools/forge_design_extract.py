#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_design_extract.py — Passe 1 du portage du design system Nokido.

Extrait les tokens CSS + assets depuis `Nokido Design System.zip` (handoff
design) vers `app/web_hub/static/laforge-ds/`, et écrit une entrée `styles.css`
COMPLÈTE (les 10 fichiers tokens — le styles.css du package en omet 3 :
domains/motion/provenance). Idempotent (ré-extrait à chaque run).

Le web hub vanilla (app/web_hub) lie ensuite `/static/laforge-ds/styles.css`
dans le <head> (CSP-safe, même origine). Cf roadmap design system portage.
"""

__FORGE_COLOR__ = "interface/ui_ : extraction des tokens CSS et assets du design system"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP = os.path.join(ROOT, "Nokido Design System.zip")
DEST = os.path.join(ROOT, "app", "web_hub", "static", "laforge-ds")
PREFIX = "design_handoff_nokido/"
WANT = ("tokens/", "assets/")

# Entrée complète : les 10 fichiers tokens (le styles.css du package en omet
# domains/motion/provenance). Ordre : fonts -> colors -> themes -> ... -> base.
STYLES_ENTRY = """/* ===========================================================================
   Nokido Design System — entrée CSS complète (portage web hub, passe 1).
   Source : Nokido Design System.zip (design handoff). Lier CE fichier seul.
   =========================================================================== */
@import "tokens/fonts.css";
@import "tokens/colors.css";
@import "tokens/themes.css";
@import "tokens/typography.css";
@import "tokens/spacing.css";
@import "tokens/effects.css";
@import "tokens/motion.css";
@import "tokens/domains.css";
@import "tokens/provenance.css";
@import "tokens/base.css";
"""


def main() -> int:
    if not os.path.exists(ZIP):
        print(f"ZIP introuvable: {ZIP}")
        return 1
    z = zipfile.ZipFile(ZIP)
    n = 0
    for name in z.namelist():
        if name.endswith("/"):
            continue
        rel = name[len(PREFIX):] if name.startswith(PREFIX) else name
        if not any(rel.startswith(w) for w in WANT):
            continue
        out = os.path.join(DEST, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(z.read(name))
        n += 1
    os.makedirs(DEST, exist_ok=True)
    with open(os.path.join(DEST, "styles.css"), "w", encoding="utf-8") as f:
        f.write(STYLES_ENTRY)

    # FLAT : un seul fichier tokens servable en 1 segment. La route /static/{fname}
    # du HUB :8766 refuse les chemins imbriqués (anti-traversal) -> laforge-ds/
    # 403. Le plat se lie en /static/laforge-tokens.css sur :7400 ET :8766.
    # L'@import Google Fonts de fonts.css reste en tête (1ère instruction non-
    # commentaire) -> valide.
    order = ["fonts", "colors", "themes", "typography", "spacing",
             "effects", "motion", "domains", "provenance", "base"]
    flat = ["/* Nokido tokens — PLAT (généré par forge_design_extract.py, ne pas éditer).\n"
            "   Source : laforge-ds/tokens/. Servable en 1 segment (compat hub :8766). */\n"]
    for t in order:
        fp = os.path.join(DEST, "tokens", t + ".css")
        if os.path.exists(fp):
            with open(fp, encoding="utf-8") as f:
                flat.append(f"\n/* ==== {t}.css ==== */\n" + f.read())
    static_dir = os.path.dirname(DEST)
    with open(os.path.join(static_dir, "laforge-tokens.css"), "w", encoding="utf-8") as f:
        f.write("\n".join(flat))

    print(f"extracted {n} token/asset files + styles.css + laforge-tokens.css (flat) -> {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
