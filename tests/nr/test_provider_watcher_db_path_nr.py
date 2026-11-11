"""NR -- forge_provider_watcher ecrit dans la base que designe forge_db_path, pas dans RAG/embeddings.db code en dur
(audit Z.ai verifie par AGY, 8/11, geste 3 ; docs/rapports/audit_zai_verifie_20261108.md). Hermetique : aucune vraie base.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import forge_db_path  # noqa: E402
import forge_provider_watcher as W  # noqa: E402


def test_le_chemin_vient_de_forge_db_path(monkeypatch, tmp_path):
    cible = tmp_path / "rag.db"
    monkeypatch.setattr(forge_db_path, "db_path", lambda: str(cible))
    assert W._chemin_db() == cible


def test_write_scores_ouvre_la_base_redirigee(monkeypatch, tmp_path):
    cible = tmp_path / "rag.db"
    monkeypatch.setattr(forge_db_path, "db_path", lambda: str(cible))
    ouverts = []
    vrai = sqlite3.connect

    def espion(chemin, *a, **k):
        ouverts.append(str(chemin))
        return vrai(":memory:")
    monkeypatch.setattr(W.sqlite3, "connect", espion)
    W._write_scores({})
    assert ouverts == [str(cible)], ouverts
    assert str(W.DB) not in ouverts


def test_redirection_explicite_de_db_prime(monkeypatch, tmp_path):
    """Un test ou un appelant qui redirige DB ne doit JAMAIS ecrire dans la base vivante."""
    explicite = tmp_path / "explicite.db"
    monkeypatch.setattr(W, "DB", explicite)
    monkeypatch.setattr(forge_db_path, "db_path", lambda: str(tmp_path / "vivante.db"))
    assert W._chemin_db() == explicite


def test_interrupteur_illisible_replie_sur_db_et_le_dit(monkeypatch, caplog):
    def casse():
        raise RuntimeError("illisible")
    monkeypatch.setattr(forge_db_path, "db_path", casse)
    with caplog.at_level("WARNING"):
        assert W._chemin_db() == W.DB
    assert "illisible" in caplog.text
