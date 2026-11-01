# -*- coding: utf-8 -*-
"""NR 2026-10-20 -- Reaffectation sur echec d'authentification du CLI (indisponibilite de surface).

Mesure du 20/10 : la tache job_bd6b5a3b assignee a ANTIGRAVITY a ete rendue status=done intent=ERR_INTERNAL
avec detail « commits produits : 0 ... | authentication failed or timed out », reaffectations=None.
La reaffectation automatique (_reaffecter, ordre ANTIGRAVITY MISTRAL CODEX WORKER_CODE) ne s'est pas
declenchee car un echec d'authentification du CLI etait traite comme un echec brut sans livraison au
lieu d'une indisponibilite de surface (comme un quota).

Contrat :
  * Un detail contenant 'authentication failed' / 'not logged in' / 'unauthorized' / '401' declenche
    un motif d'echec d'authentification dans _motif_reaffectation_apres ;
  * _reaffecter bascule la tache vers le prochain executeur vivant et marque la surface indisponible ;
  * La surface marquee indisponible n'est plus consideree comme vivante pour les affectations suivantes ;
  * Un echec de TRAVAIL (NR rouges / test failure) reste SANS reaffectation de surface, et ne marque
    pas la surface comme indisponible.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402


@pytest.fixture(autouse=True)
def reinit_surfaces():
    te.reinitialiser_surfaces_indisponibles()
    yield
    te.reinitialiser_surfaces_indisponibles()


@pytest.mark.parametrize("detail_auth", [
    "commits produits : 0 (c53187cc8..c53187cc8) ; fichiers non commites : 0 | authentication failed or timed out",
    "Error: not logged in to cli, please run agy auth",
    "ClientResponseError: 401 Unauthorized for https://generativelanguage.googleapis.com",
    "HTTP 401: unauthorized access to model resource",
])
def test_detail_echec_auth_donne_motif_reaffectation(detail_auth):
    """Un echec d'authentification de surface (auth failed, not logged in, unauthorized, 401) donne un motif."""
    effet = "[effet observe] commits produits : 0 (aaa..aaa) ; fichiers non commites : 0"
    motif = te._motif_reaffectation_apres(False, effet, detail_auth)
    assert motif is not None, f"detail={detail_auth!r} aurait du donner un motif d'echec auth"
    assert "AUTH" in motif.upper(), f"motif={motif!r} doit nommer l'authentification"


@pytest.mark.parametrize("detail_travail", [
    "FAILED tests/nr/test_chiffrement_obligatoire_par_defaut_nr.py::test_refus - AssertionError: assert False",
    "=== 1 failed, 12 passed in 1.23s === ; NR rouges persistant",
    "AssertionError: Expected rc=0 but got rc=1",
])
def test_echec_travail_nr_rouges_sans_reaffectation_de_surface(detail_travail):
    """Un echec de TRAVAIL (NR rouges / assertion) ne doit PAS declencher de reaffectation de surface."""
    effet = "[effet observe] commits produits : 0 (aaa..aaa) ; fichiers non commites : 0"
    motif = te._motif_reaffectation_apres(False, effet, detail_travail)
    assert motif is None, (
        f"detail={detail_travail!r} est un echec de travail (NR rouges) et ne doit pas declencher "
        f"de reaffectation de surface (obtenu: {motif!r})"
    )
    assert te.surface_est_indisponible("ANTIGRAVITY") is None


def test_reaffectation_sur_echec_auth_marque_surface_indisponible_et_reaffecte(monkeypatch, tmp_path):
    """Sur echec auth, la tache est reaffectee au prochain vivant et la surface est marquee indisponible."""
    db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(te, "TASKS_DB", db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, description TEXT, reaffectations TEXT)")
    conn.execute("INSERT INTO tasks (id, agent, status, description) VALUES ('job_bd6b5a3b', 'ANTIGRAVITY', 'running', 'desc')")
    conn.commit()
    conn.close()

    # Tous les executeurs ont un pouls frais
    monkeypatch.setattr(te, "_executeur_bat", lambda agent, **kw: True)

    task = {"id": "job_bd6b5a3b", "agent": "ANTIGRAVITY", "description": "desc"}
    motif = "ECHEC AUTHENTIFICATION : authentication failed or timed out"

    vers = te._reaffecter(task, motif, ordre=te._ORDRE_REPLI)

    # 1. Reaffectee au prochain vivant dans _ORDRE_REPLI (ANTIGRAVITY -> MISTRAL)
    assert vers == "MISTRAL", f"La tache aurait du etre reaffectee a MISTRAL, obtenu: {vers}"

    # 2. La surface ANTIGRAVITY est marquee indisponible
    motif_indisp = te.surface_est_indisponible("ANTIGRAVITY")
    assert motif_indisp is not None, "ANTIGRAVITY doit etre marquee indisponible"
    assert "AUTH" in motif_indisp.upper()
    assert te._executeur_suspendu("ANTIGRAVITY") is not None

    # 3. Base de donnees mise a jour proprement
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT agent, status, reaffectations FROM tasks WHERE id='job_bd6b5a3b'").fetchone()
    conn.close()
    assert row[0] == "MISTRAL"
    assert row[1] == "pending"
    reaffs = json.loads(row[2])
    assert len(reaffs) == 1
    assert reaffs[0]["de"] == "ANTIGRAVITY"
    assert reaffs[0]["vers"] == "MISTRAL"

    # 4. Une affectation suivante n'evalue plus ANTIGRAVITY comme vivante
    vivants = [a for a in te._ORDRE_REPLI if te._executeur_bat(a) and not te._executeur_suspendu(a)]
    assert "ANTIGRAVITY" not in vivants, "ANTIGRAVITY ne doit plus apparaitre parmi les vivants car indisponible"


def test_un_rapport_qui_PARLE_d_authentification_n_est_pas_une_panne():
    """22/10 (job_f0172e63) : le rapport de CLAUDE_HEADLESS sur les identites citait `401` et `unauthorized` en
    plein texte ; tout le rapport etait scanne -> « ECHEC AUTHENTIFICATION », tache reaffectee, rapport efface,
    surface marquee indisponible. Seul le DEBUT de la sortie dit une panne (meme critere que _panne_cli)."""
    rapport = ("## Rapport phase 2b -- identites par surface\n"
               + "Le canal journalise vient du registre (`_CHANNEL_SEED`), pas du transport reel. " * 8
               + "\n4. Un bearer d'agent X avec LaForge-Agent-Name=Y : le hub rend 401 Unauthorized "
                 "(nokido_hub.py:1210) ; authentication failed n'est jamais journalise.")
    effet = "[effet observe] commits produits : 0 (aaa..aaa) ; fichiers non commites : 0"
    m = te._motif_reaffectation_apres(False, effet, rapport)
    assert m is None or "AUTH" not in m.upper(), m


def test_echec_travail_ne_marque_pas_surface_indisponible():
    """Un echec de travail ne touche pas a la disponibilite de la surface."""
    detail = "FAILED tests/nr/test_sample_nr.py - AssertionError: 42 != 0"
    m = te._motif_reaffectation_apres(False, "[effet observe] commits produits : 0", detail)
    assert m is None
    assert te.surface_est_indisponible("ANTIGRAVITY") is None
    assert te._executeur_suspendu("ANTIGRAVITY") is None


def test_delegate_to_agy_branche_reaffectation():
    """Le chemin _delegate_to_agy doit appeler _motif_reaffectation_apres et _reaffecter."""
    src = (ROOT / "tools" / "forge_task_executor.py").read_text(encoding="utf-8", errors="replace")
    idx = src.find("def _delegate_to_agy")
    assert idx != -1, "fonction _delegate_to_agy introuvable"
    fin_idx = src.find("def _delegate_to_codex", idx)
    assert fin_idx != -1, "fin de _delegate_to_agy introuvable"
    corps = src[idx:fin_idx]
    assert "_motif_reaffectation_apres(" in corps, "_delegate_to_agy doit appeler _motif_reaffectation_apres"
    assert "_reaffecter(" in corps, "_delegate_to_agy doit appeler _reaffecter"
