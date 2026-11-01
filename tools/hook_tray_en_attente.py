"""hook_tray_en_attente.py -- UserPromptSubmit : rappelle les commandes du tray encore en attente.

Owner 28/10 : « tu feras du clean dans les commandes tray si elles sont deja passees ! tu oublies souvent, ancre-le
en post ». Une regle de memoire ne suffisait pas (recidive 18/10, 25/10, 28/10 : 3 commandes passees restees
« deposees »). Le geste vit donc ici, dans le corps : a chaque message de l'owner -- typiquement une sortie collee --
la liste des commandes en attente est remise sous les yeux, avec la consigne `commande-faite`. Silencieux s'il n'y a
rien ; ne casse jamais le tour (journal illisible = dit ILLISIBLE, exit 0).
"""
from __future__ import annotations

__FORGE_COLOR__ = "systeme-nerveux/reflexe : rappel des commandes du tray en attente a chaque message de l'owner"

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _lire_en_attente() -> list:
    for p in (str(ROOT), str(ROOT / "app")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import forge_ordres_bureau as B
    return B.commandes_en_attente()


def rappel(commandes: list, maintenant: float | None = None) -> str:
    """Texte du rappel, vide s'il n'y a rien en attente."""
    if not commandes:
        return ""
    t = time.time() if maintenant is None else maintenant
    lignes = ["[tray] %d commande(s) en attente -- si l'owner vient d'en coller la sortie : "
              "demander_ordre ordre=commande-faite cible=<id> texte=<extrait>" % len(commandes)]
    for c in commandes:
        age = max(0, int((t - float(c.get("depose_a") or t)) // 60))
        lignes.append("  - %s (%d min) : %s" % (c.get("id"), age, str(c.get("raison") or "")[:90]))
    return "\n".join(lignes)


def main() -> int:
    try:
        texte = rappel(_lire_en_attente())
    except Exception as e:  # noqa: BLE001 -- un hook ne casse jamais le tour : il dit ce qu'il n'a pas pu lire
        texte = "[tray] commandes en attente ILLISIBLES (%s)" % type(e).__name__
    if texte:
        try:  # 28/10 : sous Windows la sortie du hook partait en cp1252 -> « » illisibles dans le contexte
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):  # muet-ok : flux deja remplace (tests, capsys)
            pass
        print(texte)
    return 0


if __name__ == "__main__":
    sys.exit(main())
