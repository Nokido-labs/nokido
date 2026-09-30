#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Attend que la RAM redescende, puis lance la CI. Sans mobiliser l'humain.

__FORGE_COLOR__ = 'regulation/attente-active'

POURQUOI CE SCRIPT EXISTE
=========================
Le 2026-09-22, la lane `ci` a refuse trois admissions de suite : RAM a 87 %,
3,0 Go libres contre 4,0 de reserve. Le refus est la REGULATION, pas une panne.

Ma reaction a ete de presenter trois options a l'owner et d'attendre sa reponse.
Sa reponse a ete : « tu devrais savoir auto reguler ». Elle est juste. La regle
du depot dit DECLARER LE BESOIN, JAMAIS ATTENDRE -- et attendre en bloquant
l'humain est la pire forme d'attente, parce qu'elle deplace le cout sur lui.

Ce script est l'attente ACTIVE : il ne force aucun garde, il ne contourne
aucune reserve, il redemande simplement l'admission quand la machine peut
l'accepter. Un travail lourd admis a 87 % de RAM provoquerait l'embolie que la
lane previent ; le meme travail admis a 82 % passe.

CE QU'IL NE FAIT PAS, ET C'EST DELIBERE
=======================================
Il n'evince rien. `_heavy_evictable_services` est DESARME PAR DEFAUT depuis le
2026-07-24, apres un degat MESURE : l'echelle d'eviction avait endormi
NokidoQdrantServer, NokidoLlamaEmbed et NokidoLlamaReranker -- les trois piliers
du RAG. Son inventaire vide n'est donc pas une panne :

    DISABLED_BY_POLICY  !=  RESOURCE_UNAVAILABLE

Reveiller ce mecanisme est une decision de politique, pas un geste d'agent
presse de lancer sa CI.

Il ne tue rien non plus. Les gros consommateurs mesures ce jour-la etaient le
navigateur de l'owner et les enfants du superviseur, nes du redemarrage. Rien
qui m'appartienne, donc rien que j'aie le droit d'arreter.

SORTIE
======
Une ligne par tentative, pour qu'un `Monitor` puisse suivre. Le `.rc` du job
CI reste le SIGNAL ; le verdict se lit sur `ci_proof.json` et le JUnit, jamais
sur lui.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
HUB = "http://127.0.0.1:8766"
INTERVALLE_S = 60
PLAFOND_S = 5400  # 90 min : au-dela, on le DIT plutot que de tourner en silence


def _ram() -> tuple:
    """Rend (pourcentage, Go disponibles) ou (None, None) si illisible.

    Trois etats et jamais deux : une lecture impossible n'est pas une machine
    saturee, et ne doit pas se lire comme telle.
    """
    try:
        import psutil
    except ImportError:
        return None, None
    try:
        v = psutil.virtual_memory()
        return v.percent, v.available / 2 ** 30
    except OSError:
        return None, None


def _tenter_ci(sha: str) -> dict:
    """Redemande l'admission a la lane. Le garde reste SEUL juge."""
    corps = json.dumps({
        "action": "run_job",
        "script": "tools/ci_local.py",
        "script_args": "--reference %s" % sha,
        "lane": "ci",
    }).encode("utf-8")
    req = urllib.request.Request(
        HUB + "/admin/run_job", data=corps,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as rep:
            return json.loads(rep.read().decode("utf-8", errors="replace") or "{}")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "http": exc.code, "reason": exc.read()[:200].decode(
            "utf-8", errors="replace")}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "reason": "hub injoignable: %r" % exc}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: forge_ci_quand_ram_dispo.py <sha> [--seuil-go 4.2]")
        return 2
    sha = argv[0]
    seuil = 4.2
    if "--seuil-go" in argv:
        seuil = float(argv[argv.index("--seuil-go") + 1])

    debut = time.time()
    tentative = 0
    while time.time() - debut < PLAFOND_S:
        tentative += 1
        pct, libre = _ram()
        if libre is None:
            print("[ci-attente] RAM ILLISIBLE (psutil absent ou refus) — "
                  "on tente quand meme, le garde de la lane tranchera", flush=True)
        else:
            print("[ci-attente] tentative %d — RAM %.1f %%, %.2f Go libres "
                  "(seuil %.1f)" % (tentative, pct, libre, seuil), flush=True)
            if libre < seuil:
                time.sleep(INTERVALLE_S)
                continue
        res = _tenter_ci(sha)
        if res.get("ok"):
            print("[ci-attente] ADMISE — job_id=%s pid=%s sur le sha %s"
                  % (res.get("job_id"), res.get("pid"), sha), flush=True)
            return 0
        motif = str(res.get("reason") or res.get("error") or res)[:200]
        # UN REFUS N'EST PAS L'AUTRE. La premiere version de ce script traitait
        # TOUT refus comme transitoire et rebouclait. Mesure du 2026-09-22 : la
        # lane rendait `unauthorized` -- ce POST part sans jeton -- et le script
        # a boucle vingt-trois fois en affichant la RAM, jusqu'a 7,24 Go libres,
        # sur un refus que le temps ne pouvait pas lever.
        #
        #     UNAUTHORIZED N'EST PAS RAM_SATUREE. Attendre qu'un refus
        #     d'authentification passe est une attente qui ne finit jamais.
        #
        # C'est `UNKNOWN != NO` retourne contre son propre capteur : le script
        # ne SAVAIT pas pourquoi il etait refuse, et a suppose la seule cause
        # qu'il surveillait.
        if any(m in motif.lower() for m in ("unauthorized", "forbidden", "403", "401")):
            print("[ci-attente] ARRET — refus DEFINITIF de la lane : %s. "
                  "Ce n'est pas un manque de RAM et le temps ne le levera pas ; "
                  "l'admission doit passer par un canal authentifie." % motif, flush=True)
            return 2
        print("[ci-attente] refus TRANSITOIRE de la lane : %s" % motif, flush=True)
        time.sleep(INTERVALLE_S)

    # Le silence n'est pas un succes : on DIT qu'on a renonce, et pourquoi.
    pct, libre = _ram()
    print("[ci-attente] ABANDON apres %d min et %d tentative(s) — RAM %s %%, %s Go libres. "
          "La CI n'a PAS ete lancee." % (PLAFOND_S // 60, tentative,
                                         "?" if pct is None else "%.1f" % pct,
                                         "?" if libre is None else "%.2f" % libre), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
