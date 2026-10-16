"""NR - l'ingestion Gitingest ne repart jamais d'un manifeste vide, et persiste sa preuve a chaque depot (15/10).

Audit ChatGPT web du 15/10, VERIFIE sur le code : manifeste `.processed` illisible -> ensemble vide ->
tous les depots re-ingeres et comptes comme neufs ; ecriture ratee -> « travail refait au prochain tour,
indefiniment ». Corrige : illisible = INDETERMINE (rien n'est traite), ecriture ATOMIQUE apres CHAQUE
depot, echec d'ecriture = arret du tour. Pipeline, ancrage RAG et garde RAM sont simules.
"""
from __future__ import annotations

import sys
import types

import pytest

from nokido_agent.app import forge_autonomous_loops as L


@pytest.fixture
def banc(monkeypatch, tmp_path):
    d = tmp_path / "gitingest"
    d.mkdir()
    for n in ("a.txt", "b.txt"):
        (d / n).write_text("dump", encoding="utf-8")
    monkeypatch.setattr(L, "_GITINGEST_DIR", d)
    monkeypatch.setattr(L, "_GITINGEST_PROCESSED", d / ".processed")
    monkeypatch.setattr(L, "_ram_gate", lambda *a, **k: True)
    monkeypatch.setattr(L, "_anchor", lambda **k: None)
    traites = []
    faux = types.ModuleType("nokido_agent.app.forge_ingestion_pipeline")
    faux.run_ingestion_pipeline = lambda p, top_k=10: traites.append(p) or '{"core_modules": []}'
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_ingestion_pipeline", faux)
    return d, traites


def test_manifeste_illisible_rend_indetermine_sans_rien_reingerer(banc, monkeypatch):
    d, traites = banc
    (d / ".processed").write_bytes(b"\xff\xfe\x00\xd8")  # UTF-8 invalide
    r = L.pat_repo_ingestion()
    assert r["issue"] == "INDETERMINE" and traites == []


def test_la_preuve_est_ecrite_apres_chaque_depot_et_relue(banc):
    d, traites = banc
    r = L.pat_repo_ingestion()
    assert r["processed"] == 2 and len(traites) == 2
    assert set((d / ".processed").read_text(encoding="utf-8").splitlines()) == {"a.txt", "b.txt"}
    assert not (d / ".processed.tmp").exists()
    traites.clear()
    assert L.pat_repo_ingestion()["pending"] == 0 and traites == []   # rien n'est refait


def test_un_echec_d_ecriture_arrete_le_tour(banc, monkeypatch):
    d, traites = banc

    def _replace_refuse(src, dst):
        raise PermissionError("ACL")

    monkeypatch.setattr(L.os, "replace", _replace_refuse)
    r = L.pat_repo_ingestion()
    assert r["issue"] == "MANIFESTE_NON_ECRIT" and len(traites) == 1   # arrete apres le 1er depot
