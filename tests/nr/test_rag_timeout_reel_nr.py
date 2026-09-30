# -*- coding: utf-8 -*-
"""Test NR — le timeout sémantique de RAGManager.search est RÉELLEMENT strict.

Mesure du 2026-08-21 (défaut signalé par une analyse externe, confirmé) :
l'ancien code faisait

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(self._semantic_search, ...)
        result = fut.result(timeout=_SEMANTIC_TIMEOUT)

À l'échéance, fut.result() lève TimeoutError -> on sort du `with` ->
ThreadPoolExecutor.__exit__ appelle shutdown(wait=True), qui ATTEND la tâche.
Mesuré : tâche 5 s, timeout annoncé 0,5 s -> temps réel 5,0 s (×10). Le
commentaire disait pourtant « jamais bloquant ». nokido_core est appelé par
forge_hub_handlers, donc ce faux timeout était dans le chemin chaud du hub.

Ce test échouerait sur l'ancien code (temps réel ~= durée de la tâche) et passe
sur le pool partagé qui rend la main à l'échéance.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import nokido_core as nc  # noqa: E402


class _State:
    active_ring = 1  # mode DEV : la branche sémantique est empruntée
    rag_topk = 5
    rag_min_trust = 0.0


class _StateMgr:
    def get(self):
        return _State()


def _rag_avec_semantique_lente(duree_s: float):
    rm = nc.RAGManager.__new__(nc.RAGManager)
    rm._state = _StateMgr()
    rm._semantic_search = lambda *a, **k: (time.sleep(duree_s) or [{"semantic": 1}])
    rm._keyword_search = lambda *a, **k: [{"keyword": 1}]
    return rm


def test_le_timeout_semantique_ne_reattend_pas_le_thread_lent():
    """Le coeur du défaut : à l'échéance on retombe sur le keyword search
    SANS attendre la tâche sémantique bloquée."""
    duree = nc._SEMANTIC_TIMEOUT + 4.0  # nettement plus long que le timeout
    rm = _rag_avec_semantique_lente(duree)

    t0 = time.perf_counter()
    res = rm.search("une requete")
    elapse = time.perf_counter() - t0

    # Marge large : ce n'est pas la précision du timeout qu'on teste, c'est qu'on
    # ne réattend PAS les 4 s superflues. Ancien code : elapse ~= duree.
    assert elapse < duree - 1.0, (
        f"search a attendu {elapse:.2f}s (tache {duree:.1f}s) : le timeout réattend le thread"
    )
    # Et le fallback keyword a bien pris le relais.
    assert res == [{"keyword": 1}]


def test_une_semantique_rapide_est_bien_rendue():
    """Le garde-fou de l'autre côté : si la sémantique répond DANS les temps, on
    rend son résultat, pas le fallback."""
    rm = _rag_avec_semantique_lente(0.0)
    assert rm.search("une requete") == [{"semantic": 1}]


def test_l_executor_semantique_est_partage_pas_recree():
    """Un pool par requête, c'est la cause racine. On vérifie qu'il est unique."""
    a = nc._semantic_executor()
    b = nc._semantic_executor()
    assert a is b
    assert getattr(a, "_max_workers", None) and a._max_workers > 1
