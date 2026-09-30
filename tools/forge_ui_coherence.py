#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_ui_coherence.py - une tuile ment-elle sur l'etat du systeme ?

Ne verifie PAS que l'UI est jolie : verifie qu'elle DIT VRAI. Trois questions,
posees au systeme vivant et non aux declarations :

  1. une surface declaree `dormant` l'est-elle vraiment, ou son service ecoute-t-il
     sur un AUTRE port que celui sonde ?
  2. une surface declaree `live` repond-elle reellement ?
  3. les ports cites dans l'UI (`app/web_hub/`) et ceux du manifest concordent-ils ?

MOTIF FONDATEUR (2026-08-18). Le manifest sondait `graph` sur 7420 — ferme — et
declarait donc `dormant` une capacite VIVANTE qui ecoutait sur 7474, ce que
`app/web_hub/app.py` savait depuis toujours. Une analyse externe recommandait au
meme moment de promouvoir ce manifest en source unique de verite : on aurait
institutionnalise l'erreur. **Un registre ne devient une autorite qu'apres avoir
ete confronte au reel.**

C'est le pendant UI de la doctrine maison : la FORME d'une declaration ne prouve
jamais l'EFFET. Ici, l'effet est un socket qui accepte une connexion.

  LAFORGE_PYTHON tools/forge_ui_coherence.py
  LAFORGE_PYTHON tools/forge_ui_coherence.py --json

Sortie 0 = coherent ; 1 = au moins une tuile ment (utilisable en garde CI).
"""
from __future__ import annotations

import json
import re

import socket
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.tools.forge_archeo_socle import cli, sortie
from nokido_agent.tools.forge_archeo_socle import port_ouvert as _ouvert

ROOT = Path(__file__).resolve().parent.parent
WEB_HUB = ROOT / "app" / "web_hub"

# Plage scrutee pour retrouver un service qui aurait demenage. Bornee a dessein :
# balayer 1-65535 prendrait des minutes et reveillerait des services tiers.
PORTS_CONNUS = (7400, 7401, 7410, 7420, 7430, 7440, 7474, 7500, 8000, 8765, 8766)


# _ouvert vient du socle (import ci-dessus) : meme sonde que celle de
# forge_capability_contracts, dupliquee a l'octet pres.


def _ports_cites_dans_ui() -> dict:
    """Ports mentionnes dans app/web_hub -> port : {contextes de ligne}.

    L'UI historique connait parfois la VRAIE valeur quand le manifest se trompe :
    c'est `app.py` qui savait, pour graph, qu'il fallait sonder 7474.

    ⚠️ On indexe la LIGNE, pas le nom du fichier. Premiere version de ce
    controle : elle cherchait le nom de la surface dans « app.py » et ne trouvait
    donc jamais rien — un detecteur qui repondait toujours « aucune tuile ne
    ment ». C'est le commentaire de la ligne (`# graph_explorer root`) qui porte
    l'indice du demenagement, jamais le nom du fichier.
    """
    trouve: dict = {}
    if not WEB_HUB.exists():
        return trouve
    for p in WEB_HUB.rglob("*"):
        if p.suffix not in (".py", ".html") or "__pycache__" in str(p):
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ligne in txt.splitlines():
            for m in re.finditer(r"127\.0\.0\.1:(\d{4,5})", ligne):
                trouve.setdefault(int(m.group(1)), set()).add(ligne.strip()[:160])
    return trouve


def analyser() -> dict:
    sys.path.insert(0, str(ROOT))
    from nokido_agent.tools import forge_ui_manifest as M  # noqa: E402

    cites = _ports_cites_dans_ui()
    ouverts = {p for p in set(PORTS_CONNUS) | set(cites) if _ouvert(p)}

    surfaces, mensonges = [], []
    for nom, spec in sorted(M.SURFACES.items()):
        probe = spec.get("probe") or ()
        if not (len(probe) > 1 and probe[0] == "port" and probe[1]):
            surfaces.append({"surface": nom, "verdict": "hors-port", "sonde": probe[0] if probe else "?"})
            continue
        port = int(probe[1])
        vivant = port in ouverts
        entree = {"surface": nom, "port_sonde": port, "ecoute": vivant}

        if not vivant:
            # Le coeur du controle : le service a-t-il DEMENAGE ? On ne peut pas
            # l'affirmer d'un port ouvert quelconque, mais un port cite par l'UI
            # pour cette meme surface est un candidat serieux.
            # Un port n'est un candidat que si l'UI le cite DANS UN CONTEXTE qui
            # nomme cette surface : sinon n'importe quel port ouvert de la machine
            # ferait un faux coupable.
            candidats = sorted(
                p for p in ouverts
                if p != port and any(nom.lower() in ctx.lower() for ctx in cites.get(p, ()))
            )
            entree["candidats_deménagement"] = candidats
            if candidats:
                entree["verdict"] = "MENT — declare mort, ecoute ailleurs"
                mensonges.append(entree)
            else:
                entree["verdict"] = "dormant (confirme, aucun port ouvert)"
        else:
            entree["verdict"] = "live (confirme)"
        surfaces.append(entree)

    return {"surfaces": surfaces, "mensonges": mensonges,
            "ports_ouverts": sorted(ouverts), "ports_cites_ui": sorted(cites)}


def _rendre(r) -> None:
    print("=== COHERENCE UI (declarations confrontees a l'ecoute reelle) ===")
    for s in r["surfaces"]:
        port = s.get("port_sonde", "-")
        print("  %-13s %-6s %s" % (s["surface"], port, s["verdict"]))
    print("\nports ouverts : %s" % ", ".join(str(p) for p in r["ports_ouverts"]))
    if r["mensonges"]:
        print("\n%s tuile(s) MENTENT sur l'etat du systeme :" % len(r["mensonges"]))
        for m in r["mensonges"]:
            print("  %s : sonde %s (ferme) alors que %s ecoute"
                  % (m["surface"], m["port_sonde"], m.get("candidats_deménagement")))
    else:
        print("\naucune tuile ne ment.")


def main() -> int:
    a = cli("Une tuile ment-elle sur l'etat du systeme ?")
    return sortie(analyser(), a.json, _rendre, lambda r: bool(r["mensonges"]))


if __name__ == "__main__":
    sys.exit(main())
