# -*- coding: utf-8 -*-
"""NR 2026-10-22 -- Indisponibilite de surface expirable (TTL), plus eternelle.

Bug (bb:architecture_rules/bug_reaffectation_absente_sur_echec_auth_20261020) : marquer_surface_indisponible()
range la surface dans un dict en memoire SANS expiration. Un seul echec d'authentification ecarte la surface
jusqu'au redemarrage de l'executeur.

Contrat :
  * marquer_surface_indisponible(agent, motif) note l'heure de la marque ;
  * surface_est_indisponible(agent, maintenant=...) rend le motif tant que
    maintenant - marque < LAFORGE_SURFACE_INDISPO_TTL_S (defaut 1800), puis None (la surface est retentee) ;
  * reinitialiser_surfaces_indisponibles() vide tout ;
  * signature retrocompatible : maintenant optionnel (defaut time.time()).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402


@pytest.fixture(autouse=True)
def reinit_surfaces(monkeypatch):
    monkeypatch.delenv("LAFORGE_SURFACE_INDISPO_TTL_S", raising=False)
    te.reinitialiser_surfaces_indisponibles()
    yield
    te.reinitialiser_surfaces_indisponibles()


def test_surface_marquee_reste_indisponible_avant_ttl():
    """Juste apres la marque (dans le TTL par defaut), la surface reste indisponible avec son motif."""
    avant = time.time()
    te.marquer_surface_indisponible("ANTIGRAVITY", "authentication failed")
    apres = time.time()
    motif = te.surface_est_indisponible("ANTIGRAVITY", maintenant=apres + 1)
    assert motif == "authentication failed"
    motif_mi_ttl = te.surface_est_indisponible("ANTIGRAVITY", maintenant=avant + 1799)
    assert motif_mi_ttl == "authentication failed"


def test_surface_retentee_apres_ttl_par_defaut():
    """Passe le TTL par defaut (1800 s), la surface n'est plus indisponible : elle est retentee."""
    avant = time.time()
    te.marquer_surface_indisponible("ANTIGRAVITY", "authentication failed")
    assert te.surface_est_indisponible("ANTIGRAVITY", maintenant=avant + 1801) is None


def test_ttl_configurable_par_variable_d_environnement(monkeypatch):
    """LAFORGE_SURFACE_INDISPO_TTL_S pilote l'expiration (lue a chaque appel)."""
    monkeypatch.setenv("LAFORGE_SURFACE_INDISPO_TTL_S", "60")
    avant = time.time()
    te.marquer_surface_indisponible("MISTRAL", "401 unauthorized")
    assert te.surface_est_indisponible("MISTRAL", maintenant=avant + 30) == "401 unauthorized"
    assert te.surface_est_indisponible("MISTRAL", maintenant=avant + 61) is None


def test_surface_inconnue_n_est_pas_indisponible():
    """Une surface jamais marquee n'est pas indisponible, quelle que soit l'heure."""
    assert te.surface_est_indisponible("CODEX", maintenant=time.time()) is None


def test_appel_sans_maintenant_reste_retrocompatible():
    """Sans `maintenant`, l'appel d'origine (un seul argument) continue de fonctionner."""
    te.marquer_surface_indisponible("CODEX", "quota")
    assert te.surface_est_indisponible("CODEX") == "quota"


def test_reinitialiser_vide_toutes_les_surfaces():
    """reinitialiser_surfaces_indisponibles() efface toutes les marques, expirees ou non."""
    te.marquer_surface_indisponible("ANTIGRAVITY", "auth")
    te.marquer_surface_indisponible("MISTRAL", "auth")
    te.reinitialiser_surfaces_indisponibles()
    assert te.surface_est_indisponible("ANTIGRAVITY", maintenant=time.time()) is None
    assert te.surface_est_indisponible("MISTRAL", maintenant=time.time()) is None
