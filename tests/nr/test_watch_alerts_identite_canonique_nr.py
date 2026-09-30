"""NR -- le consommateur des alertes de version lit TOUTES les alertes pertinentes (veille lot_C_06, 24/09).

Mesure : `analyze_all_watch_alerts()` rendait « 0 critique » en 0,0 s -- il ne lisait RIEN, sa selection
exigeait `author != ''` alors que le champ est vide sur 12/12 alertes breaking/security. onnxruntime
v1.25 (breaking) et qdrant v1.17.1 (security) etaient invisibles. Contrat :
  - identite canonique tiree de la SOURCE (depot, paquet, version) ; author facultatif ;
  - securite lue autant que breaking ;
  - correspondance EXACTE au module importe (le serveur qdrant n'est pas le client qdrant_client) ;
  - version comparee a l'installee ; incomparable DIT ; lecture seule ; base illisible = exception.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_diff_analyzer as da  # noqa: E402

GH = "https://github.com/%s/releases/tag/%s"


@pytest.fixture()
def monde(tmp_path, monkeypatch):
    db = tmp_path / "rag.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT, "
                "role_hint TEXT, author TEXT DEFAULT '', ingested_at TEXT)")
    lignes = [
        ("a1", "Removed `run_legacy` API", GH % ("microsoft/onnxruntime", "v1.25.0"), "release:breaking_change:chunk00"),
        ("a2", "suite", GH % ("microsoft/onnxruntime", "v1.25.0"), "release:breaking_change:chunk01"),
        ("a3", "security fix", GH % ("qdrant/qdrant", "v1.17.1"), "alert:security"),
        ("a4", "breaking", GH % ("encode/starlette", "0.42.0"), "release:breaking_change"),
        ("a5", "feature", GH % ("encode/starlette", "1.4.0"), "release:feature"),
    ]
    for i, t, s, r in lignes:
        con.execute("INSERT INTO rag_chunks (id, text, source, domain, role_hint, author) VALUES (?,?,?,?,?, '')",
                    (i, t, s, "watch_alerts", r))
    con.commit()
    con.close()
    code = tmp_path / "app"
    code.mkdir()
    (code / "m.py").write_text("import onnxruntime\nimport starlette\nimport qdrant_client\nrun_legacy()\n",
                               encoding="utf-8")
    monkeypatch.setattr(da, "DB_PATH", db)
    monkeypatch.setattr(da, "APP_DIR", code)
    monkeypatch.setattr(da, "TOOLS", tmp_path / "vide")
    monkeypatch.setattr(da, "ROOT", tmp_path)
    monkeypatch.setattr(da, "version_installee", {"onnxruntime": "1.24.0", "starlette": "1.3.1"}.get)
    return db


def test_identite_canonique_depuis_la_source():
    assert da.identite_alerte(GH % ("microsoft/onnxruntime", "v1.25.0")) == {
        "hote": "github", "depot": "microsoft/onnxruntime", "paquet": "onnxruntime", "version": "1.25.0"}
    i = da.identite_alerte(GH % ("langchain-ai/langchain", "langchain-core%3D%3D1.4.0"))
    assert (i["paquet"], i["version"]) == ("langchain-core", "1.4.0")
    assert da.identite_alerte("https://pypi.org/project/litellm/1.80.0/")["paquet"] == "litellm"
    assert da.identite_alerte("n'importe quoi")["paquet"] is None


def test_author_vide_ne_cache_plus_rien_et_la_securite_est_lue(monde):
    b = da.bilan_watch_alerts()
    par = {(a["paquet"], a["version"]): a for a in b["alertes"]}
    assert b["alertes_lues"] == 4, "breaking + securite, jamais les features"
    assert par[("onnxruntime", "1.25.0")]["statut"] == "A_EXAMINER"
    assert par[("onnxruntime", "1.25.0")]["usages"], "le symbole retire `run_legacy` est utilise"
    q = par[("qdrant", "1.17.1")]
    assert "securite" in q["genres"] and q["statut"] == "NON_UTILISE_EN_PYTHON", "serveur != client qdrant_client"
    assert "prothese" in q["note"]
    assert par[("starlette", "0.42.0")]["statut"] == "DEJA_AU_DELA"
    assert b["nb_fichiers_code_illisibles"] == 0
    assert [a["paquet"] for a in da.analyze_all_watch_alerts()] == ["onnxruntime"]


def test_un_fichier_de_code_illisible_est_compte(monde, tmp_path):
    (tmp_path / "app" / "casse.py").write_text("import onnxruntime\ndef (:\n", encoding="utf-8")
    b = da.bilan_watch_alerts()
    assert b["nb_fichiers_code_illisibles"] == 1 and b["fichiers_code_illisibles"][0].endswith("casse.py")


def test_base_illisible_leve_au_lieu_de_rendre_rien(monkeypatch, tmp_path):
    monkeypatch.setattr(da, "DB_PATH", tmp_path / "absente.db")
    with pytest.raises(sqlite3.Error):
        da.analyze_all_watch_alerts()


def test_le_consommateur_ne_s_ouvre_jamais_en_ecriture(monde):
    con = da._lecture_seule()
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("DELETE FROM rag_chunks")
    finally:
        con.close()
