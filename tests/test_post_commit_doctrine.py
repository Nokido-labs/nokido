"""Indexation des documents de DOCTRINE par le hook post-commit.

Mesure 2026-07-24 : RULES_SHARED.md etait dans le RAG depuis le 21 mai, mais sous
`mcp_result:POST_COMMIT:git_..._p0:<ts>` (introuvable par nom) et TRONQUE a 5 chunks
(~10k chars) alors qu'il en fait 17,8k — le tableau des capacites, en fin de fichier,
n'avait jamais ete indexe.
"""
from __future__ import annotations

import os
import sqlite3
import sys

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.79)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_post_commit as pc  # noqa: E402


def test_les_trois_documents_de_doctrine_sont_reconnus():
    assert {"RULES_SHARED.md", "CLAUDE.md", "COGNITION.md"} <= pc._DOCTRINE


def test_doctrine_indexee_ENTIERE_et_source_lisible(tmp_path, monkeypatch):
    """Ni troncature, ni source opaque."""
    db = tmp_path / "t.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT)")
    con.commit()
    con.close()

    import forge_db_path
    monkeypatch.setattr(forge_db_path, "db_path", lambda *a, **k: str(db))

    # Document long : au-dela des ~10k que l'ancien chemin tronquait.
    texte = "\n\n".join(f"## Section {i}\n" + ("contenu de doctrine. " * 40) for i in range(30))
    assert len(texte) > 12000

    assert pc._index_doctrine(tmp_path / "COGNITION.md", "COGNITION.md", texte, dry_run=False)

    con = sqlite3.connect(str(db))
    rows = con.execute("SELECT source, text FROM rag_chunks").fetchall()
    con.close()
    assert rows, "rien indexe"
    assert all(s.startswith("COGNITION.md#chunk") for s, _ in rows), [s for s, _ in rows[:3]]
    # La FIN du document doit etre presente : c'est ce que la troncature perdait.
    assert any("Section 29" in t for _, t in rows), "fin du document perdue (troncature)"


def test_repli_direct_quand_le_hub_refuse(tmp_path, monkeypatch):
    """Mesure 24-07 : le hook poste vers le hub sans jeton cote poste -> 401, et
    « RAG: 0/2 fichiers indexes » a chaque commit. Le code source n'entrait plus
    dans la cognition, en SILENCE. Un index qui ne recoit plus rien est pire qu'un
    index absent : il donne l'illusion d'une memoire a jour."""
    db = tmp_path / "t.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, domain TEXT)")
    con.commit()
    con.close()

    import forge_db_path
    monkeypatch.setattr(forge_db_path, "db_path", lambda *a, **k: str(db))

    # Le hub refuse systematiquement (401).
    def _401(*a, **k):
        raise OSError("HTTP Error 401: Unauthorized")

    monkeypatch.setattr(pc.urllib.request, "urlopen", _401)
    monkeypatch.setattr(pc, "ROOT", tmp_path)

    src = tmp_path / "app"
    src.mkdir()
    f = src / "un_module.py"
    f.write_text("# " + ("code " * 60), encoding="utf-8")

    assert pc.vectorise_file(f, dry_run=False) is True, "le repli doit sauver l'indexation"

    con = sqlite3.connect(str(db))
    rows = con.execute("SELECT source FROM rag_chunks").fetchall()
    con.close()
    assert rows and all(s.startswith("app/un_module.py#chunk") for (s,) in rows), rows


def test_dry_run_n_ecrit_rien(tmp_path, monkeypatch):
    appels = []
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: appels.append(a) or (_ for _ in ()).throw(AssertionError))
    assert pc._index_doctrine(tmp_path / "CLAUDE.md", "CLAUDE.md", "x" * 200, dry_run=True)
    assert appels == []


def test_echec_dindexation_ne_leve_jamais(tmp_path, monkeypatch):
    """Un post-commit qui plante bloquerait le flux de travail."""
    import forge_db_path
    monkeypatch.setattr(forge_db_path, "db_path", lambda *a, **k: str(tmp_path / "nope" / "x.db"))
    assert pc._index_doctrine(tmp_path / "CLAUDE.md", "CLAUDE.md", "x" * 200, dry_run=False) is False
