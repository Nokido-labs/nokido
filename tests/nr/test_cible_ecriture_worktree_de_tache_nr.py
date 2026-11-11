"""7/11 : governed_edit d'un executeur va au worktree de SA tache, pas a son arbre fixe que le juge ne lit pas."""
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_worktree as W  # noqa: E402

T1 = "job_aaaaaaaa_1_x"
T2 = "job_bbbbbbbb_2_x"


def _arbre(d: Path) -> Path:
    d.mkdir(parents=True)
    (d / ".git").write_text("gitdir: x\n", encoding="utf-8")
    return d


@pytest.fixture()
def racine(tmp_path):
    r = tmp_path / "nokido_worktrees"
    _arbre(r / "claude_headless")
    return r


def _base(tmp_path, *lignes) -> Path:
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT)")
    c.executemany("INSERT INTO tasks VALUES (?,?,?)", lignes)
    c.commit()
    c.close()
    return db


def _tache(r, agent, t) -> Path:
    return _arbre(r / "taches" / ("%s_%s" % (agent, W.court_tache(t))))


def test_une_tache_en_cours_ecrit_dans_son_worktree(racine, tmp_path):
    wt = _tache(racine, "claude_headless", T1)
    db = _base(tmp_path, (T1, "CLAUDE_HEADLESS", "running"))
    r = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=db)
    assert r["cible"] == "WORKTREE" and r["racine"] == wt


def test_sans_tache_arbre_fixe_comme_avant(racine, tmp_path):
    db = _base(tmp_path, (T1, "CLAUDE_HEADLESS", "done"))
    r = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=db)
    assert r["cible"] == "WORKTREE" and r["racine"] == racine / "claude_headless"


def test_deux_taches_refus_et_jamais_l_arbre_fixe(racine, tmp_path):
    _tache(racine, "claude_headless", T1)
    _tache(racine, "claude_headless", T2)
    db = _base(tmp_path, (T1, "CLAUDE_HEADLESS", "running"), (T2, "CLAUDE_HEADLESS", "running"))
    r = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=db)
    assert r["cible"] == "REFUS" and r["racine"] is None and "ambigu" in r["raison"]


def test_tache_d_un_autre_agent_ignoree(racine, tmp_path):
    _tache(racine, "claude_headless", T1)
    db = _base(tmp_path, (T1, "OPENCODE_GLM", "running"))
    r = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=db)
    assert r["racine"] == racine / "claude_headless"


def test_alias_headless_vers_la_tache_de_son_executeur(tmp_path):
    r = tmp_path / "nokido_worktrees"
    _arbre(r / "mistral")
    wt = _tache(r, "mistral", T1)
    db = _base(tmp_path, (T1, "MISTRAL", "running"))
    assert W.cible_ecriture("VIBE_HEADLESS", "", r, tasks_db=db)["racine"] == wt


def test_base_illisible_garde_l_arbre_fixe(racine, tmp_path):
    r = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=tmp_path / "absente.db")
    assert r["racine"] == racine / "claude_headless"


def test_deux_taches_et_entete_tache_le_bon_dossier(racine, tmp_path):
    w1 = _tache(racine, "claude_headless", T1)
    w2 = _tache(racine, "claude_headless", T2)
    db = _base(tmp_path, (T1, "CLAUDE_HEADLESS", "running"), (T2, "CLAUDE_HEADLESS", "running"))
    r1 = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=db, tache=W.court_tache(T1))
    r2 = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=db, tache=W.court_tache(T2))
    assert r1["racine"] == w1 and r2["racine"] == w2


def test_entete_d_une_tache_d_un_autre_agent_refus(racine, tmp_path):
    _tache(racine, "claude_headless", T1)
    _tache(racine, "opencode_glm", T2)
    db = _base(tmp_path, (T1, "CLAUDE_HEADLESS", "running"), (T2, "OPENCODE_GLM", "running"))
    r = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=db, tache=W.court_tache(T2))
    assert r["cible"] == "REFUS" and r["racine"] is None


def test_message_ambigu_cite_l_entete_et_plus_l_outil_natif(racine, tmp_path):
    _tache(racine, "claude_headless", T1)
    _tache(racine, "claude_headless", T2)
    db = _base(tmp_path, (T1, "CLAUDE_HEADLESS", "running"), (T2, "CLAUDE_HEADLESS", "running"))
    r = W.cible_ecriture("CLAUDE_HEADLESS", "", racine, tasks_db=db)
    assert "LaForge-Tache" in r["raison"] and "natif" not in r["raison"]


def test_emit_headers_tache_sortie_reelle(monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / "tools"))
    import forge_mcp_json_sync as S
    monkeypatch.setattr(S, "vault_get", lambda k: "jeton-factice")
    monkeypatch.setattr(S, "vault_available", lambda: True)
    monkeypatch.setattr(S, "_journaliser_appel", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["x", "--emit-headers", "CLAUDE_HEADLESS", "--tache", "aaaaaaaa1234"])
    assert S.main() == 0
    import json
    h = json.loads(capsys.readouterr().out)
    assert h["LaForge-Tache"] == "aaaaaaaa1234"
    assert "LaForge-Tache" not in (S.entetes_agent("CLAUDE_HEADLESS", "P") or {})


def test_owner_reste_sur_l_arbre_partage(racine, tmp_path):
    assert W.cible_ecriture("CLAUDE", "", racine, tasks_db=tmp_path / "absente.db")["cible"] == "PARTAGE"
