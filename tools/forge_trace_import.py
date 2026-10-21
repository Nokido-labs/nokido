#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_trace_import.py -- nommer le TEST qui charge un module (traceur d'import, desarme par defaut).

Item p2_turbo_worker_mort_sans_trace_2026-10-14. Mesure du 19/10 : 80 plantages de python.exe dans arrow.dll
(c0000005), tous des workers pytest de la CI (60/80 sous tools/ci_local.py) ; pyarrow n'est PAS charge a la collecte
(18 680 tests, PYARROW_CHARGE=False) mais pendant l'execution d'un test. Decision owner 19/10 : poser le traceur a
la prochaine CI plutot que rejouer la suite pour lui seul.

`armer(modules)` installe en tete de sys.meta_path un finder qui ne BLOQUE JAMAIS l'import (find_spec rend None) et
journalise, au premier chargement d'un module surveille ou d'un sous-module, {module, test, worker, pid, pile} dans
sandbox/trace_import.jsonl. Le conftest des NR l'arme seulement si NOKIDO_TRACE_IMPORT est pose et tient COURANT a jour.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/outil : traceur d'import (nomme le test qui charge un module), desarme par defaut"

import importlib.abc
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _donnees() -> Path:
    """Racine des DONNEES (forge_db_path), jamais derivee de __file__ (cliquet racine_donnees, 20/10)."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        try:
            from forge_db_path import racine_donnees
        except ImportError:  # app/ hors sys.path : checkout, donnees = depot
            return ROOT
    return Path(racine_donnees())
COURANT = {"test": None}   # tenu a jour par le conftest (pytest_runtest_setup)


class _Traceur(importlib.abc.MetaPathFinder):
    def __init__(self, modules, sortie):
        self.modules = tuple(m for m in modules if m)
        self.sortie = Path(sortie)
        self.vus: set = set()
        # 19/10 : pas de purge (fichier en ajout seul) -- chaque ligne porte la session ; les workers xdist d'un meme
        # run heritent NOKIDO_TRACE_SESSION si l'appelant la pose, sinon la session vaut ce processus.
        self.session = os.environ.get("NOKIDO_TRACE_SESSION") or "%d-%d" % (int(time.time()), os.getpid())

    def find_spec(self, name, path=None, target=None):
        racine = next((m for m in self.modules if name == m or name.startswith(m + ".")), None)
        if racine and racine not in self.vus:
            self.vus.add(racine)
            try:
                pile = [ligne.strip() for ligne in traceback.format_stack()[:-1]
                        if "importlib" not in ligne and "forge_trace_import" not in ligne][-8:]
                self.sortie.parent.mkdir(parents=True, exist_ok=True)
                with open(self.sortie, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"module": racine, "nom": name, "session": self.session,
                                        "test": COURANT.get("test"),
                                        "worker": os.environ.get("PYTEST_XDIST_WORKER"), "pid": os.getpid(),
                                        "pile": pile}, ensure_ascii=False) + "\n")
            except Exception as e:  # noqa: BLE001 - un traceur ne casse jamais un import ; il le dit sur stderr
                sys.stderr.write("[trace_import] non journalise (%s)\n" % type(e).__name__)
        return None


def armer(modules, sortie=None):
    """Installe le traceur et le rend (pour desarmer). `sortie` par defaut : sandbox/trace_import.jsonl."""
    finder = _Traceur(modules, sortie or (_donnees() / "sandbox" / "trace_import.jsonl"))
    sys.meta_path.insert(0, finder)
    # TEMOIN POSITIF (19/10, CI de reference e6642dcf1) : sans lui, une trace absente ne disait pas si le module n'a
    # jamais ete importe ou si le traceur n'a jamais ete arme. A cote de la trace, qui garde son contrat.
    temoin = finder.sortie.with_name(finder.sortie.stem + ".armement.jsonl")
    try:
        temoin.parent.mkdir(parents=True, exist_ok=True)
        with open(temoin, "a", encoding="utf-8") as f:
            f.write(json.dumps({"modules": list(finder.modules), "session": finder.session, "pid": os.getpid(),
                                "worker": os.environ.get("PYTEST_XDIST_WORKER"),
                                "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001 - un temoin ne casse jamais l'armement ; il le dit sur stderr
        sys.stderr.write("[trace_import] temoin d'armement non ecrit (%s)\n" % type(e).__name__)
    return finder


def lire_derniere_session(sortie=None, session=None) -> list:
    """Lignes de `session` (par defaut : celle de la DERNIERE ligne du fichier). Ligne illisible : ignoree."""
    p = Path(sortie or (_donnees() / "sandbox" / "trace_import.jsonl"))
    lignes, illisibles = [], 0
    for brut in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        try:
            lignes.append(json.loads(brut))
        except ValueError:
            illisibles += 1   # ligne coupee (worker tue en ecrivant) : ecartee ET comptee
    if illisibles:
        sys.stderr.write("[trace_import] %d ligne(s) illisible(s) ecartee(s) de %s\n" % (illisibles, p.name))
    if session is None and lignes:
        session = lignes[-1].get("session")
    return [x for x in lignes if x.get("session") == session]


def desarmer(finder) -> None:
    if finder in sys.meta_path:
        sys.meta_path.remove(finder)
