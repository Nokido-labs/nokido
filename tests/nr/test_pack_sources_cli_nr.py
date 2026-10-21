"""NR -- le drapeau `--sources` de forge_knowledge_pack_export traverse le CHEMIN REEL (main), 2026-10-20.

`exporter_sources` (1f3397388) n'avait aucun point d'entree : mesurer la taille reelle des packs par source et leur
taux de doublons demandait un script hors depot. `--sources` exporte tous les composants `rag_pack_source` du
manifeste ; `--dry-run` COMPTE sans rien ecrire (l'owner a refuse l'usure disque : la mesure ne doit pas couter
deux gigaoctets d'ecriture) ; sans `--output` ni `--dry-run`, refus.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
MANIFESTE = """schema = "nokido-distribution/pack"
version_schema = 1
id = "knowledge"
statut = "PRET"

[[composant]]
id = "knowledge-docset-flask"
source = "construit"
construit = "rag_pack_source"
sha256 = "au_build"
taille = "au_build"
famille = "docset:Flask"
licence = "BSD-3-Clause"
conditions = "attribution"
preuve = "https://flask.palletsprojects.com/en/latest/license/"
obligatoire = true
"""
TEXTE = "Flask est un micro-cadre web ecrit en Python ; documentation de reference, section "


def _module():
    spec = importlib.util.spec_from_file_location("pack_sources_cli_nr", RACINE / "tools" / "forge_knowledge_pack_export.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _vec(i):
    v = np.zeros(1024, dtype=np.float32)
    v[i] = 1.0
    return v.tobytes()


@pytest.fixture
def lieux(tmp_path):
    base = tmp_path / "rag.db"
    con = sqlite3.connect(base)
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, domain TEXT, text TEXT, "
                "embedding BLOB, active INTEGER)")
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?,?,?)", [
        ("f1", "docset:Flask#a", "reference", TEXTE + "un", _vec(1), 1),
        ("f2", "docset:Flask#a", "reference", TEXTE + "un", _vec(2), 1),
        ("f3", "docset:Flask#b", "reference", TEXTE + "deux", _vec(3), 1),
    ])
    con.commit()
    con.close()
    manifeste = tmp_path / "knowledge.toml"
    manifeste.write_text(MANIFESTE, encoding="utf-8")
    return base, manifeste, tmp_path / "out"


def test_sources_dry_run_compte_sans_rien_ecrire(lieux, capsys):
    base, manifeste, out = lieux
    rc = _module().main(["--sources", "--dry-run", "--base", str(base), "--manifeste", str(manifeste)])
    assert rc == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["docset:Flask"]["retenus"] == 2 and stats["docset:Flask"]["doublons"] == 1
    assert stats["docset:Flask"]["octets_vecteurs"] == 2 * 1024 * 2
    assert not out.exists()


def test_sources_ecrit_un_tar_par_source(lieux, capsys):
    base, manifeste, out = lieux
    assert _module().main(["--sources", "--base", str(base), "--manifeste", str(manifeste),
                           "--output", str(out), "--version", "9.9.9"]) == 0
    assert [p.name for p in out.iterdir()] == ["nokido_pack_docset-flask_v9.9.9.tar"]


def test_sources_sans_sortie_ni_dry_run_refuse(lieux, capsys):
    base, manifeste, _ = lieux
    with pytest.raises(SystemExit):
        _module().main(["--sources", "--base", str(base), "--manifeste", str(manifeste)])
    assert "--sources exige --output ou --dry-run" in capsys.readouterr().err
