"""NR — tools/forge_backup_hotswap.py : la sauvegarde couvre le tableau noir et le registre des fiches.

Geste 3 du rapport cognition (choix owner 8/11, docs/rapports/debat_cognition_centralisee_20261108.md
§3 Gate G3) : `swarm_blackboard` et `memory_ledger` doivent figurer dans SOURCES, chiffrees comme
le RAG. `cmd_status` donne un etat explicite par source : une source illisible (PermissionError)
ou sans generation attestee n'est JAMAIS saine, et une source critique dont la derniere generation
verifiee a plus de 7 jours rend rc != 0.

Pur : fichiers factices sous tmp_path, diskpart mocke, aucune vraie base, aucun disque F:/V:.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))


@pytest.fixture()
def bk(monkeypatch):
    # Import sans effet de bord disque : le module ouvre un FileHandler a l'import.
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())
    sys.modules.pop("forge_backup_hotswap", None)
    import forge_backup_hotswap as m  # noqa: PLC0415

    monkeypatch.setattr(m, "_diskpart", lambda *a, **k: "[diskpart simule]")
    return m


def _sources_isolees(bk, monkeypatch, chemin):
    monkeypatch.setattr(bk, "SOURCES", {
        "swarm_blackboard": {
            "kind": "sqlite",
            "path": chemin,
            "dest_subdir": "rag",
            "encrypt": True,
        },
    })


def _generation(racine, quand, nom="swarm_blackboard"):
    gen = racine / f"gen_{quand:%Y%m%d_%H%M%S}"
    gen.mkdir(parents=True)
    (gen / "manifest.json").write_text(json.dumps({
        "generation": gen.name,
        "success": True,
        "items": {nom: {"ok": True}},
    }), encoding="utf-8")


def test_sources_cognition_presentes(bk):
    assert "swarm_blackboard" in bk.SOURCES
    assert "memory_ledger" in bk.SOURCES
    for nom in ("swarm_blackboard", "memory_ledger"):
        assert bk.SOURCES[nom]["encrypt"] is True


def test_permission_error_nest_jamais_saine(bk, monkeypatch, tmp_path, capsys):
    src = tmp_path / "swarm.db"
    src.write_bytes(b"x")
    _sources_isolees(bk, monkeypatch, src)
    monkeypatch.setattr(bk, "BACKUP_ROOT", tmp_path / "backups")
    vrai_open = Path.open

    def _refuse(self, *a, **k):
        if self == src:
            raise PermissionError(13, "Permission denied")
        return vrai_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", _refuse)
    rc = bk.cmd_status()
    sortie = capsys.readouterr().out
    assert "ILLISIBLE" in sortie
    assert "VERIFIEE" not in sortie
    assert "NON_VERIFIEE" not in sortie
    assert rc != 0


def test_generation_de_plus_de_7_jours_rend_rc_non_nul(bk, monkeypatch, tmp_path, capsys):
    src = tmp_path / "swarm.db"
    src.write_bytes(b"x")
    _sources_isolees(bk, monkeypatch, src)
    backups = tmp_path / "backups"
    _generation(backups, datetime.now() - timedelta(days=8))
    monkeypatch.setattr(bk, "BACKUP_ROOT", backups)
    rc = bk.cmd_status()
    sortie = capsys.readouterr().out
    assert "PERIMEE" in sortie
    assert rc != 0


def test_generation_recente_est_verifiee(bk, monkeypatch, tmp_path, capsys):
    src = tmp_path / "swarm.db"
    src.write_bytes(b"x")
    _sources_isolees(bk, monkeypatch, src)
    backups = tmp_path / "backups"
    _generation(backups, datetime.now() - timedelta(days=1))
    monkeypatch.setattr(bk, "BACKUP_ROOT", backups)
    rc = bk.cmd_status()
    sortie = capsys.readouterr().out
    assert "VERIFIEE" in sortie
    assert rc == 0
