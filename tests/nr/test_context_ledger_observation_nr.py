# -*- coding: utf-8 -*-
"""NR -- phase 1 du contexte servi : le ledger OBSERVE les archives CCR et les sorties bornees.

Choix owner 2026-11-08 : la mesure A/A commence par les sorties d'outils (84 % des tokens) :
`forge_mcp_registry.ToolRegistry._archive_blob` (sandbox/ccr) et `forge_run_sortie.borner`
(sandbox/run_sorties). Contrat ajoute a app/forge_context_ledger.py :

  observer(uri, essence="", racine=None)          indexe en OBSERVATION, fail-silent
  observer_relecture(uri, agent, racine=None)     ajoute {ts, uri, agent} a
                                                  <racine>/sandbox/context_ledger_relectures.jsonl
  racine par defaut = racine_donnees() ; base = <racine>/sandbox/context_ledger.db
  interrupteur global LAFORGE_CONTEXT_LEDGER_OBS=0 lu A CHAQUE APPEL : rien n'est ecrit

Observation seule : rien n'est servi, la sortie rendue a l'agent ne change pas ; une panne du
ledger ne casse JAMAIS l'archivage. L'essence ne recopie que du texte caviarde (<= 150 car.).
Tout tourne en tmp_path (NOKIDO_DATA_DIR) ; aucun acces a la base RAG.
"""
import asyncio
import importlib
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTENU_CCR = "contenu archive par le garde de sortie\n" * 120


def _mod(nom):
    return importlib.import_module("nokido_agent.app." + nom)


@pytest.fixture()
def racine(tmp_path, monkeypatch):
    r = tmp_path / "donnees"
    (r / "sandbox").mkdir(parents=True)
    monkeypatch.setenv("NOKIDO_DATA_DIR", str(r))
    monkeypatch.delenv("LAFORGE_CONTEXT_LEDGER_OBS", raising=False)
    monkeypatch.delenv("LAFORGE_RUN_SORTIE_DIR", raising=False)
    return r


def _uris(r):
    db = r / "sandbox" / "context_ledger.db"
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    try:
        return sorted(x[0] for x in conn.execute("SELECT uri FROM context_ledger"))
    finally:
        conn.close()


def _texte_long():
    rs = _mod("forge_run_sortie")
    return "".join("ligne %05d de la sortie d'outil\n" % i for i in range(rs.SEUIL_CAR // 20 + 50))


def test_borner_indexe_sa_sortie_sans_rien_changer_au_rendu(racine):
    rs = _mod("forge_run_sortie")
    texte = _texte_long()
    out = rs.borner(texte, "OPENCODE_GLM")
    assert out != texte and "[source:" not in out, "observation seule : le rendu ne change pas"
    fichiers = list((racine / "sandbox" / "run_sorties").glob("run_*.txt"))
    assert len(fichiers) == 1
    assert _uris(racine) == ["run_sortie://" + fichiers[0].name]


def test_archive_blob_indexe_le_ccr(racine):
    reg = _mod("forge_mcp_registry")
    mid = reg.ToolRegistry._archive_blob(SimpleNamespace(root=racine), CONTENU_CCR, "CLAUDE", "run")
    assert mid
    assert _uris(racine) == ["ccr://" + mid]


def test_relecture_archived_journalisee(racine):
    reg = _mod("forge_mcp_registry")
    soi = SimpleNamespace(root=racine)
    mid = reg.ToolRegistry._archive_blob(soi, CONTENU_CCR, "CLAUDE", "run")
    out = asyncio.run(reg.ToolRegistry.handle_read(soi, {"action": "archived", "id": mid}, "CLAUDE", 0))
    assert out == CONTENU_CCR
    j = racine / "sandbox" / "context_ledger_relectures.jsonl"
    assert j.exists(), "la relecture d'une archive n'est pas journalisee : pas de mesure A/A possible"
    derniere = json.loads(j.read_text(encoding="utf-8").splitlines()[-1])
    assert derniere["uri"] == "ccr://" + mid and derniere["agent"] == "CLAUDE" and derniere.get("ts")


def test_interrupteur_coupe_l_observation(racine, monkeypatch):
    monkeypatch.setenv("LAFORGE_CONTEXT_LEDGER_OBS", "0")
    _mod("forge_run_sortie").borner(_texte_long(), "OPENCODE_GLM")
    reg = _mod("forge_mcp_registry")
    reg.ToolRegistry._archive_blob(SimpleNamespace(root=racine), CONTENU_CCR, "CLAUDE", "run")
    assert not (racine / "sandbox" / "context_ledger.db").exists()


def test_ledger_en_panne_ne_casse_pas_l_archivage(racine, monkeypatch):
    led = _mod("forge_context_ledger")

    def _panne(*_a, **_k):
        raise RuntimeError("panne du ledger")

    monkeypatch.setattr(led.ContextLedger, "indexer", _panne)
    out = _mod("forge_run_sortie").borner(_texte_long(), "OPENCODE_GLM")
    assert "sortie bornee" in out
    reg = _mod("forge_mcp_registry")
    soi = SimpleNamespace(root=racine)
    mid = reg.ToolRegistry._archive_blob(soi, CONTENU_CCR, "CLAUDE", "run")
    assert mid
    assert asyncio.run(reg.ToolRegistry.handle_read(soi, {"action": "archived", "id": mid}, "CLAUDE", 0)) == CONTENU_CCR
