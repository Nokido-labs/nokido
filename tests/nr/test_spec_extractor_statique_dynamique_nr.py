# -*- coding: utf-8 -*-
"""NR (8/11, choix owner) : gate separe statique/dynamique + chasse aux chiffres nus + parenthese wiki.

Verrouille :
1. Derive DYNAMIQUE seule (bareme_rings/forge_tools, sqlite_master, roadmap_arbre.json) -> etat DYNAMIQUE_BOUGE
   (avec age_j), jamais FRAIS, et rc 0 sur --verifier.
2. Derive STATIQUE (constantes AST, contrat MCP schemas_mcp_structure.json, machines d'etat fichier:ligne) ->
   etat PERIME et rc 1 sur --verifier.
3. Controle CHIFFRE_DYNAMIQUE_NU dans verifier sur docs/specs/*.md (hors redige/) et docs/wiki/*.md :
   compteur d'entite dynamique sans date ISO ni pointeur SSoT sur la meme ligne -> signale avec fichier:ligne.
4. Compteur accompagne d'une date ISO ou d'un pointeur SSoT sur la meme ligne -> non signale ; reutilisation
   de forge_capability_audit.c_benchmarks sans recopier la regex.
5. forge_wiki_modules._premiere_phrase ne coupe jamais au milieu d'une parenthese ouverte (cas forge_db_conn.py).
"""
# pylint: disable=missing-function-docstring,protected-access
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_spec_extractor as sx  # noqa: E402
import forge_wiki_modules as wm  # noqa: E402


def test_derive_dynamique_seule_rend_rc_0_et_dynamique_bouge(tmp_path, monkeypatch):
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    outils = [{"nom": "ask", "requis": ["message"], "parametres": ["message", "provider"]}]
    bases_v1 = {
        tmp_path / "b.db": (
            ["rag (db_path)"],
            {"etat": "LU", "chemin": str(tmp_path / "b.db"), "journal_mode": "wal",
             "objets": [{"type": "table", "nom": "t1", "sql": "CREATE TABLE t1 (x INT)"}]},
        )
    }
    bases_v2 = {
        tmp_path / "b.db": (
            ["rag (db_path)"],
            {"etat": "LU", "chemin": str(tmp_path / "b.db"), "journal_mode": "wal",
             "objets": [
                 {"type": "table", "nom": "t1", "sql": "CREATE TABLE t1 (x INT)"},
                 {"type": "table", "nom": "t2", "sql": "CREATE TABLE t2 (y INT)"},
             ]},
        )
    }
    schema_disque = sx.rendre_schema(bases_v1, outils, {"ask": {"min_ring": 3, "actif": True}}, "abc", "2026-11-05")
    schema_neuf = sx.rendre_schema(bases_v2, outils, {"ask": {"min_ring": 2, "actif": True}}, "def", "2026-11-08")
    (specs / "01_SCHEMA.md").write_text(schema_disque, encoding="utf-8")

    plan_disque = sx.rendre_plan(
        {"total": 10, "comptes": {"CLOS": 5, "PARTIEL": 5}, "restants": [], "clos": []},
        "abc", "2026-11-05",
    )
    plan_neuf = sx.rendre_plan(
        {"total": 10, "comptes": {"CLOS": 6, "PARTIEL": 4}, "restants": [], "clos": []},
        "def", "2026-11-08",
    )
    (specs / "06_PLAN.md").write_text(plan_disque, encoding="utf-8")

    rendus = {"01_SCHEMA.md": schema_neuf, "06_PLAN.md": plan_neuf}
    v = sx.verifier(rendus, specs)
    for nom in ("01_SCHEMA.md", "06_PLAN.md"):
        assert v[nom]["etat"] == "DYNAMIQUE_BOUGE", f"{nom}: attendu DYNAMIQUE_BOUGE, obtenu {v[nom]}"
        assert v[nom]["etat"] != "FRAIS"
        assert "age_j" in v[nom]

    monkeypatch.setattr(sx, "ROOT", tmp_path)
    monkeypatch.setattr(sx, "rendre_tout", lambda: rendus)
    assert sx.main(["--verifier"]) == 0


def test_derive_statique_rend_rc_1_et_perime(tmp_path, monkeypatch):
    specs = tmp_path / "docs" / "specs"
    specs.mkdir(parents=True)
    outils_v1 = [{"nom": "ask", "requis": ["message"], "parametres": ["message"]}]
    outils_v2 = [
        {"nom": "ask", "requis": ["message"], "parametres": ["message"]},
        {"nom": "run", "requis": ["action"], "parametres": ["action"]},
    ]
    (specs / "01_SCHEMA.md").write_text(
        sx.rendre_schema({}, outils_v1, {}, "abc", "2026-11-05"), encoding="utf-8"
    )
    rendus = {"01_SCHEMA.md": sx.rendre_schema({}, outils_v2, {}, "def", "2026-11-08")}
    v = sx.verifier(rendus, specs)
    assert v["01_SCHEMA.md"]["etat"] == "PERIME"

    monkeypatch.setattr(sx, "ROOT", tmp_path)
    monkeypatch.setattr(sx, "rendre_tout", lambda: rendus)
    assert sx.main(["--verifier"]) == 1


def test_chiffre_dynamique_nu_est_signale_avec_fichier_ligne(tmp_path):
    specs = tmp_path / "docs" / "specs"
    redige = specs / "redige"
    wiki = tmp_path / "docs" / "wiki"
    redige.mkdir(parents=True)
    wiki.mkdir(parents=True)

    spec_txt = "# 04 — PRD\n\n## 1. ETAT STATIQUE\nLe hub expose 25 outils MCP et 130 tables.\n"
    (specs / "04_PRD.md").write_text(spec_txt, encoding="utf-8")
    (redige / "04_PRD.md").write_text("Le hub expose 99 outils MCP dans redige.\n", encoding="utf-8")
    (wiki / "Home.md").write_text("# Wiki\n- 29 providers disponibles\n- ~531k chunks en memoire\n", encoding="utf-8")

    v = sx.verifier({"04_PRD.md": spec_txt}, specs)
    assert "CHIFFRE_DYNAMIQUE_NU" in v
    lignes = v["CHIFFRE_DYNAMIQUE_NU"]["lignes"]
    assert any("04_PRD.md:4" in s for s in lignes), lignes
    assert any("Home.md:2" in s for s in lignes), lignes
    assert any("Home.md:3" in s for s in lignes), lignes
    assert not any("redige" in s for s in lignes), lignes


def test_chiffre_date_ou_pointe_n_est_pas_signale(tmp_path):
    specs = tmp_path / "docs" / "specs"
    wiki = tmp_path / "docs" / "wiki"
    specs.mkdir(parents=True)
    wiki.mkdir(parents=True)

    spec_txt = (
        "# 04 — PRD\n\n## 1. ETAT STATIQUE\n"
        "- 58 outils MCP declares dans `tests/schemas_mcp_structure.json`.\n"
        "- 130 tables dans `%NOKIDO_DATA%\\embeddings.db` (`sqlite_master`).\n"
    )
    (specs / "04_PRD.md").write_text(spec_txt, encoding="utf-8")
    (wiki / "05-LLM-Providers.md").write_text(
        "# Providers\n"
        "24 free-tier slots on 2026-09-29.\n"
        "39 routed slots dans `app/forge_provider_specs.py::PROVIDER_SPECS`.\n"
        "56 MCP tools dans `app/forge_mcp_registry.py:1936`.\n",
        encoding="utf-8",
    )

    v = sx.verifier({"04_PRD.md": spec_txt}, specs)
    assert "CHIFFRE_DYNAMIQUE_NU" not in v

    src_sx = (ROOT / "tools" / "forge_spec_extractor.py").read_text(encoding="utf-8")
    assert "c_benchmarks" in src_sx, "verifier doit reutiliser c_benchmarks de forge_capability_audit"
    assert r"20\d\d-\d\d-\d\d" not in src_sx, "ne pas recopier la regex de date ISO de c_benchmarks"


def test_premiere_phrase_ne_coupe_pas_une_parenthese():
    doc_db_conn = (
        "forge_db_conn.py — Point de connexion DB CENTRAL (fondation at-rest SQLCipher)\n"
        "============================================================================\n\n"
        "Pourquoi ce module\n------------------\n"
        "Le code Nokido ouvre ~631 connexions sqlite3 directes réparties sur ~340\n"
        "fichiers (audit 2026-06-01), avec le chemin DB redéfini en dur 193+ fois et\n"
        "AUCUN helper unifié. Impossible de migrer."
    )
    res = wm._premiere_phrase(doc_db_conn, "forge_db_conn.py")
    assert res.count("(") == res.count(")"), f"parenthese ouverte non fermee dans : {res!r}"
    assert not res.endswith("(au"), f"troncature au milieu d'une parenthese : {res!r}"

    doc_sep_interne = "forge_x.py — Routeur central (cf. doc. interne - v2). Suite du texte."
    res2 = wm._premiere_phrase(doc_sep_interne, "forge_x.py")
    assert res2 == "Routeur central (cf. doc. interne - v2)"
    assert res2.count("(") == res2.count(")")
