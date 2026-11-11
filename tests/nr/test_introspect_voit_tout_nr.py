# -*- coding: utf-8 -*-
"""NR : introspect voit aussi ce qui n'est pas un `def`, et dit ce qu'il n'a pas lu.

Mesure du 5/11 : `BUDGET_VOLUME` (constante d'un hook) rendait `symboles_trouves: []`, et
`OmniRoute`, `RTK` (veille ingeree au RAG) rien du tout, sans que `non_consulte` le nomme.
Le silence se lisait comme une absence. Base factice au schema reel : jamais la base vivante.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import forge_introspect as fi  # noqa: E402


@pytest.fixture
def base_rag(tmp_path):
    chemin = tmp_path / "embeddings_factice.db"
    con = sqlite3.connect(chemin)
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)")
    lignes = [
        ("1", "RTK reecrit les commandes par PreToolUse", "github:rtk-ai/rtk/README.md", "veille"),
        ("2", "compression OmniRoute RTK Caveman", "gitingest/omniroute", "veille"),
        ("3", "lecon payee sur RTK : Bash seulement", "memory:project_debat_tokens.md", "memoire"),
        ("4", "RTK cite dans le code", "app/forge_run_sortie.py#chunk0", "code"),
        ("5", "RTK evoque en seance", "conv_agy/3dff3197/7", "conv"),
    ]
    con.executemany("INSERT INTO rag_fts VALUES (?,?,?,?)", lignes)
    con.commit()
    con.close()
    return chemin


@pytest.fixture
def depot(tmp_path):
    racine = tmp_path / "depot"
    (racine / "tools").mkdir(parents=True)
    (racine / "app").mkdir()
    (racine / "tools" / "hook_garde.py").write_text("x = 1\nREFUS = 'BUDGET_VOLUME: plafond'\n", encoding="utf-8")
    (racine / "app" / "forge_a.py").write_text("# renvoi vers BUDGET_VOLUME\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(racine)], check=True)
    return racine


def test_un_litteral_sans_def_est_trouve_et_le_hook_est_nomme_garde(depot):
    nc: list = []
    rendu = fi._litteraux("pourquoi BUDGET_VOLUME refuse ?", [], nc, racine=depot)
    assert len(rendu) == 1 and rendu[0]["terme"] == "BUDGET_VOLUME"
    assert rendu[0]["occurrences"] == 2
    assert rendu[0]["gardes"] == ["tools/hook_garde.py:2"]
    assert rendu[0]["ailleurs"] == ["app/forge_a.py:1"]
    assert nc == []


def test_l_instrument_ne_se_lit_pas_lui_meme(depot):
    (depot / "app" / "forge_introspect.py").write_text("# exemple : BUDGET_VOLUME\n", encoding="utf-8")
    rendu = fi._litteraux("BUDGET_VOLUME", [], [], racine=depot)
    assert rendu[0]["occurrences"] == 2 and "app/forge_introspect.py:1" not in rendu[0]["ailleurs"]


def test_un_mot_courant_ne_sert_pas_de_bruit(base_rag):
    con = sqlite3.connect(base_rag)
    con.execute("INSERT INTO rag_fts VALUES ('6','la marche du projet','github:autre/projet/fr.json','veille')")
    con.commit()
    con.close()
    assert fi._veille("marche", [], base=base_rag) == []


def test_un_mot_qui_nomme_une_source_est_servi_meme_en_minuscules(base_rag):
    rendu = fi._veille("as-tu envisage le rtk", [], base=base_rag)
    entree = next(e for e in rendu if e["terme"] == "rtk")
    assert entree["veille"] == ["github:rtk-ai/rtk/README.md"]


def test_les_mots_ensemble_cherchent_le_theme(base_rag):
    con = sqlite3.connect(base_rag)
    con.execute("INSERT INTO rag_fts VALUES ('7','compression des orchestrateurs','github:tiers/guide.md','veille')")
    con.commit()
    con.close()
    rendu = fi._veille("compression orchestrateurs", [], base=base_rag)
    assert rendu[0]["terme"] == "orchestrateurs + compression"
    assert rendu[0]["veille"] == ["github:tiers/guide.md"]


def test_un_mot_courant_n_est_pas_un_litteral(depot):
    assert fi._litteraux("pourquoi refuse encore", [], [], racine=depot) == []


def test_un_symbole_deja_trouve_n_est_pas_recherche_deux_fois(depot):
    assert fi._litteraux("BUDGET_VOLUME", [{"symbole": "BUDGET_VOLUME"}], [], racine=depot) == []


def test_git_en_panne_est_nomme_pas_tu(tmp_path):
    nc: list = []
    assert fi._litteraux("BUDGET_VOLUME", [], nc, racine=tmp_path / "absent") == []
    assert any("litteraux" in e["organe"] for e in nc)


def test_un_terme_de_trois_lettres_atteint_la_veille(base_rag):
    rendu = fi._veille("as-tu envisage RTK", [], base=base_rag)
    assert rendu[0]["terme"] == "RTK"
    assert "github:rtk-ai/rtk/README.md" in rendu[0]["veille"]
    assert "memory:project_debat_tokens.md" in rendu[0]["lecons"]
    assert "conv_agy/3dff3197/7" in rendu[0]["conversations"]
    assert rendu[0]["autres"] == 1


def test_la_veille_rend_des_pointeurs_jamais_le_texte(base_rag):
    assert "reecrit" not in repr(fi._veille("RTK", [], base=base_rag))


def test_la_requete_passe_par_l_index_fts_seul(base_rag):
    con = sqlite3.connect(base_rag)
    plan = " ".join(str(l[3]) for l in con.execute("EXPLAIN QUERY PLAN " + fi._SQL_POINTEURS, ('"rtk"',)))
    con.close()
    assert "VIRTUAL TABLE" in plan
    # rag_fts porte son propre texte et ses sources : aucune lecture de rag_chunks, et c'est
    # l'index qu'alimente l'ingestion de veille (94b56f548e7c).
    assert "FROM rag_fts " in fi._SQL_POINTEURS and "rag_chunks" not in fi._SQL_POINTEURS


def test_un_terme_avec_syntaxe_fts_reste_du_texte(base_rag):
    nc: list = []
    fi._veille("forge-core: NOT(RTK)", nc, base=base_rag)
    assert not [e for e in nc if "illisible" in e.get("raison", "")]


def test_le_plafond_epuise_nomme_les_termes_non_interroges(base_rag):
    nc: list = []
    assert fi._veille("RTK OmniRoute", nc, base=base_rag, plafond_s=0) == []
    assert any("RTK" in e["raison"] and "OmniRoute" in e["raison"] for e in nc)


def test_une_base_absente_est_nommee_pas_tue(tmp_path):
    nc: list = []
    assert fi._veille("RTK", nc, base=tmp_path / "absente.db") == []
    assert any("veille" in e["organe"] for e in nc)


def _isoler(monkeypatch):
    monkeypatch.setattr(fi, "_code", lambda *a, **k: [])
    monkeypatch.setattr(fi, "_modules", lambda *a, **k: [])
    monkeypatch.setattr(fi, "_enquetes", lambda *a, **k: [])
    monkeypatch.setattr(fi, "_succes", lambda *a, **k: [])
    monkeypatch.setattr(fi, "_voisinage", lambda *a, **k: {})


def test_introspect_sert_les_deux_sections_par_son_point_d_entree(monkeypatch, base_rag, depot):
    _isoler(monkeypatch)
    res = fi.introspect("BUDGET_VOLUME et RTK", jit=object(), base_rag=base_rag, racine_litteraux=depot)
    assert res["litteraux_trouves"][0]["terme"] == "BUDGET_VOLUME"
    assert any(e["terme"] == "RTK" for e in res["veille_et_lecons"])
    assert "verdict" not in res


def test_le_budget_retire_les_nouvelles_sections_et_le_dit(monkeypatch, base_rag, depot):
    _isoler(monkeypatch)
    res = fi.introspect("BUDGET_VOLUME et RTK", budget_tokens=1, jit=object(), base_rag=base_rag, racine_litteraux=depot)
    assert res["budget"]["retire"].get("veille_et_lecons") and res["budget"]["retire"].get("litteraux_trouves")


def test_non_consulte_nomme_l_usage_des_cli_tant_que_le_lot_2_n_y_est_pas(monkeypatch, base_rag, depot):
    _isoler(monkeypatch)
    res = fi.introspect("RTK", jit=object(), base_rag=base_rag, racine_litteraux=depot)
    assert any("token_usage" in e["organe"] for e in res["non_consulte"])
