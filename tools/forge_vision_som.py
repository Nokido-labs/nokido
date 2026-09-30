# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE [BLUE]
DATE:2026-06-02 | VER:v_vision_som_scaffold

forge_vision_som.py — Fallback VISION (Set-of-Mark sur PIXELS) quand l'arbre
a11y/DOM est vide : canvas, WebGL, jeux, Figma, maps, dashboards custom-rendered.
Là `get_interactive_elements()` retourne ~rien → `ui_observe.vision_fallback=True`
→ on route ici.

POURQUOI (anti-dup) : l'oracle DOM (forge_ui_oracle / forge_playwright_browser) ne
voit QUE les éléments sémantiques HTML. Aucun module Nokido ne fait du SoM par
détection visuelle pure. Complémentaire, pas redondant.

ÉTAT : SCAFFOLD. Le détecteur d'éléments visuels nécessite un modèle :
  - OmniParser (Microsoft) — détection icônes/boutons + OCR, modèle ~ qq Go.
  - OU Florence-2 (transformers, déjà dispo) en mode region-detection/OCR.
torch + transformers SONT présents (base miniforge) ; le modèle reste à télécharger
(sur demande explicite — pas de pull multi-Go automatique, cf. règles cloud/heavy).

CONTRAT (stable, pour que l'appelant code dès maintenant) :
    detect(png_path) -> [{"i":int,"x":int,"y":int,"w":int,"h":int,"label":str,"kind":str}]
Même schéma d'index que le SoM DOM → l'agent clique par index de façon homogène.
"""
from __future__ import annotations

import os

_BACKEND = os.environ.get("LAFORGE_VISION_SOM_BACKEND", "")  # "omniparser" | "florence" | ""


def available() -> bool:
    """True si un backend vision est configuré ET son modèle présent."""
    return bool(_BACKEND)


def detect(png_path: str) -> list[dict]:
    """Détecte les éléments interactifs visuels sur une capture (pixels).
    SCAFFOLD : lève tant qu'aucun backend n'est configuré + le modèle installé.

    Pour activer (sur demande) :
      - OmniParser : pip install + poids, set LAFORGE_VISION_SOM_BACKEND=omniparser
      - Florence-2 : modèle HF microsoft/Florence-2-base, BACKEND=florence
    Puis implémenter le bloc correspondant ci-dessous (sortie = contrat docstring)."""
    if _BACKEND == "florence":
        raise NotImplementedError(
            "Florence-2 backend non câblé. Confirmer le download du modèle "
            "(microsoft/Florence-2-base, ~0.5Go) pour l'implémenter."
        )
    if _BACKEND == "omniparser":
        raise NotImplementedError(
            "OmniParser backend non câblé. Confirmer le download des poids "
            "(~qq Go) pour l'implémenter."
        )
    raise RuntimeError(
        "Aucun backend vision configuré (LAFORGE_VISION_SOM_BACKEND vide). "
        "Le fallback canvas/WebGL nécessite un modèle vision — demander l'install."
    )


if __name__ == "__main__":
    print("forge_vision_som: scaffold. backend=", _BACKEND or "(aucun)", "available=", available())
