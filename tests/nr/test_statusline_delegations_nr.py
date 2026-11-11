"""La ligne d'etat montre les delegations en cours (owner 24/10 : « visualiser direct en bas de terminal »).

Segment `DÉL n AGENT<marque><age>` lu dans tasks.db en lecture seule : en cours ▶, en attente ⏸.
Base illisible = `DÉL ?` (jamais 0 : une source muette ne prouve rien). Aucune delegation = segment absent.
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import nokido_statusline as S  # noqa: E402


def _base(tmp_path, lignes):
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, agent TEXT, status TEXT, from_agent TEXT, updated_at TEXT)")
    c.executemany("INSERT INTO tasks VALUES (?,?,?,?,?)", lignes)
    c.commit()
    c.close()
    return db


def test_delegations_en_cours_et_en_attente(tmp_path):
    maintenant = datetime(2026, 10, 24, 18, 0, 0)
    db = _base(tmp_path, [
        ("j1", "CLAUDE_HEADLESS", "running", "agt_claude", (maintenant - timedelta(minutes=3)).isoformat()),
        ("j2", "OPENCODE_GLM", "pending", "agt_claude", (maintenant - timedelta(minutes=12)).isoformat()),
        ("j3", "MISTRAL", "done", "agt_claude", maintenant.isoformat()),
        ("j4", "CODEX", "running", "agt_autre", maintenant.isoformat()),
    ])
    seg = S._delegations(db, maintenant=maintenant)
    assert seg.startswith("DÉL 2"), seg
    assert "HEADLESS▶3m" in seg and "GLM⏸12m" in seg, seg
    assert "MISTRAL" not in seg and "CODEX" not in seg, seg


def test_aucune_delegation_pas_de_segment(tmp_path):
    db = _base(tmp_path, [("j3", "MISTRAL", "done", "agt_claude", "2026-10-24T18:00:00")])
    assert S._delegations(db) == ""


def _base_causes(tmp_path, lignes):
    db = tmp_path / "causes.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, from_agent TEXT, cause_echec TEXT, updated_at TEXT)")
    c.executemany("INSERT INTO tasks VALUES (?,'CLAUDE',?,?)", lignes)
    c.commit()
    c.close()
    return db


def test_acquittement_masque_les_causes_traitees_pas_les_suivantes(tmp_path, monkeypatch):
    """Owner 6/11 « Masquer si traite » : un echec acquitte s'efface sans attendre 2 h, une panne NOUVELLE s'affiche."""
    now = datetime(2026, 11, 6, 19, 30)
    db = _base_causes(tmp_path, [("a", "NON_LIVRE", (now - timedelta(minutes=60)).isoformat()),
                                 ("b", "FAUX_VERT", (now - timedelta(minutes=5)).isoformat())])
    marque = tmp_path / "acquit.txt"
    monkeypatch.setattr(S, "_ACQUIT", marque, raising=False)
    assert "NON_LIVRE" in S._causes_recentes(db, [], now)

    marque.write_text((now - timedelta(minutes=30)).isoformat(), encoding="utf-8")
    segment = S._causes_recentes(db, [], now)
    assert "NON_LIVRE" not in segment and "FAUX_VERT" in segment


def test_marque_illisible_laisse_les_causes_visibles(tmp_path, monkeypatch):
    """UNKNOWN != NO : une marque illisible ne masque jamais un echec."""
    now = datetime(2026, 11, 6, 19, 30)
    db = _base_causes(tmp_path, [("a", "NON_LIVRE", (now - timedelta(minutes=5)).isoformat())])
    marque = tmp_path / "acquit.txt"
    marque.write_text("pas une date", encoding="utf-8")
    monkeypatch.setattr(S, "_ACQUIT", marque, raising=False)
    assert "NON_LIVRE" in S._causes_recentes(db, [], now)


def test_drapeau_acquitter_ecrit_la_marque_sans_lire_stdin(tmp_path, monkeypatch, capsys):
    marque = tmp_path / "acquit.txt"
    monkeypatch.setattr(S, "_ACQUIT", marque, raising=False)
    monkeypatch.setattr(sys, "argv", ["nokido_statusline.py", "--acquitter"])

    class SansStdin:
        def read(self):
            raise AssertionError("--acquitter ne lit pas stdin")

    monkeypatch.setattr(sys, "stdin", SansStdin())
    assert S.main() == 0
    datetime.fromisoformat(marque.read_text(encoding="utf-8").strip())


def test_base_illisible_dit_inconnu(tmp_path):
    assert S._delegations(tmp_path / "absente.db") == "DÉL ?"
