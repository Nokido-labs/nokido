"""forge_vol_worker.py -- enregistreur de vol des workers de la suite pure.

Owner 5/11 : la CI tombe depuis des semaines sur le meme test. Le worker meurt « Not properly terminated », sans evenement
Windows ni trace dans le rapport : pytest-timeout (methode thread) et tout autre appelant de os._exit ne laissent rien, et
xdist abandonne ensuite le run. faulthandler ne voit que les plantages natifs, et un plantage natif journalise ne prouve
meme pas la mort (5/11 : un worker a continue des milliers de tests apres un crash arrow.dll).

Actif seulement quand NOKIDO_FAULTHANDLER_DIR est pose (ci_local) : tests/conftest.py arme, ci_local rapporte.
Un journal par processus : debut et fin de chaque test, et la pile de tous les fils a os._exit. Aucun effet sur un verdict.
"""
from __future__ import annotations

__FORGE_COLOR__ = "proprioception/vol-worker-ci"

import os
import re
import sys
import threading
import time
import traceback
from pathlib import Path

_MAX_FILS = 25
_MAX_CADRES = 14
_MAX_LIGNES_RAPPORT = 70


class _Journal:
    def __init__(self, fichier):
        self._f = fichier

    def debut(self, nodeid):
        self._ecrire("START %s" % nodeid)

    def fin(self, nodeid):
        self._ecrire("FIN %s" % nodeid)

    def _ecrire(self, texte):
        try:
            self._f.write("%s %s\n" % (time.strftime("%H:%M:%S"), texte))
        except (OSError, ValueError):
            pass  # muet-ok : un journal perdu ne change jamais le verdict d'un test

    def piles(self, code):
        self._ecrire("OS_EXIT code=%s fil=%s" % (code, threading.current_thread().name))
        noms = {t.ident: t.name for t in threading.enumerate()}
        cadres = sys._current_frames()
        # Le fil appelant d'abord, puis le principal : ce sont eux qui disent qui a tue et ce qui bloquait.
        moi, principal = threading.get_ident(), threading.main_thread().ident
        ordre = sorted(cadres, key=lambda i: (i != moi, i != principal))[:_MAX_FILS]
        for ident in ordre:
            try:
                self._f.write("--- fil %s\n" % noms.get(ident, ident))
                self._f.write("".join(traceback.format_stack(cadres[ident])[-_MAX_CADRES:]))
            except (OSError, ValueError):
                return
        if len(cadres) > _MAX_FILS:
            self._ecrire("[%d fil(s) non montres]" % (len(cadres) - _MAX_FILS))


def armer(dossier, qui) -> _Journal | None:
    """Ouvre le journal du processus et intercepte os._exit, qui reste appele a l'identique. None si le dossier refuse."""
    try:
        Path(dossier).mkdir(parents=True, exist_ok=True)
        f = open(Path(dossier) / ("vol_%s_%d.log" % (qui, os.getpid())), "a", encoding="utf-8", buffering=1)
    except OSError:
        return None
    journal = _Journal(f)
    if not getattr(os._exit, "_vol_worker", False):
        vrai = os._exit

        def _exit(code):
            try:
                journal.piles(code)
            except Exception:  # noqa: BLE001 - quoi qu'il arrive, le processus sort avec son code
                pass  # muet-ok : on sort de toute facon, plus personne ne lirait une trace
            vrai(code)

        _exit._vol_worker = True
        os._exit = _exit
    return journal


def rapporter(dossier) -> list:
    """Dit quels workers se sont arretes en plein test, et comment. Rend [{worker, test, heure, os_exit}]. Ne decide d'aucun verdict."""
    try:
        fichiers = sorted(Path(dossier).glob("vol_*.log"))
    except OSError as e:
        print("  [vol] dossier ILLISIBLE (%s) : aucun journal, rien a conclure" % type(e).__name__)
        return []
    if not fichiers:
        print("  [vol] aucun journal dans %s : enregistreur inactif, rien a conclure" % dossier)
        return []
    morts, interrompus, workers = [], 0, 0
    for f in fichiers:
        m = re.match(r"vol_(.+)_\d+\.log$", f.name)
        qui = m.group(1) if m else f.name
        try:
            lignes = [l for l in f.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        except OSError as e:
            print("  [vol] %s ILLISIBLE (%s)" % (f.name, type(e).__name__))
            continue
        est_worker = qui.startswith("gw")
        workers += est_worker
        k = next((i for i, l in enumerate(lignes) if " OS_EXIT " in l), None)
        coupe = bool(lignes) and " START " in lignes[-1]
        if k is None and not coupe:
            continue
        if not est_worker:  # un sous-processus de test peut etre tue expres : on le compte sans l'accuser
            interrompus += 1
            continue
        dernier = lignes[k - 1] if k else lignes[-1]
        test = dernier.split(" START ")[-1] if " START " in dernier else "(hors test)"
        morts.append({"worker": qui, "test": test, "heure": (lignes[k] if k is not None else lignes[-1])[:8], "os_exit": k is not None, "_lignes": lignes[k:] if k is not None else []})
    for d in sorted(morts, key=lambda x: x["heure"]):
        if d["os_exit"]:
            print("\033[31m  [vol] %s : os._exit a %s pendant %s\033[0m" % (d["worker"], d["heure"], d["test"]))
            for l in d["_lignes"][:_MAX_LIGNES_RAPPORT]:
                print("     " + l[:200])
        else:
            print("\033[31m  [vol] %s : arrete a %s pendant %s, sans os._exit (mort, ou session abandonnee)\033[0m" % (d["worker"], d["heure"], d["test"]))
    if not morts:
        print("  [vol] %d worker(s) suivi(s), aucun arret en plein test" % workers)
    if interrompus:
        print("  [vol] %d sous-processus de test interrompu(s), sans conclusion" % interrompus)
    for d in morts:
        d.pop("_lignes", None)
    return morts
