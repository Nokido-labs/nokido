"""Organe d'integrite de livraison : le DECLARE confronte au REEL.

Les scanners lisent git + tasks.db, donc les tests isolent la logique de verdict
plutot que l'etat courant du depot (qui change a chaque commit).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele); git + gh reels
#   (code appele) (l.244)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

import forge_delivery_integrity as di  # noqa: E402


def test_as_utc_normalise_naif_et_aware():
    """Le coeur du detecteur : sans normalisation, 2h d'ecart = faux positifs."""
    naif = di._as_utc("2026-07-23T11:36:25.388251")
    aware = di._as_utc("2026-07-23T12:58:55+02:00")
    assert naif.tzinfo is not None and aware.tzinfo is not None
    # 12:58:55+02:00 == 10:58:55 UTC, donc ANTERIEUR au naif 11:36:25 UTC.
    assert aware < naif


def test_as_utc_tolere_les_entrees_illisibles():
    assert di._as_utc(None) is None
    assert di._as_utc("pas une date") is None


def test_attestation_commit_anterieur_detectee(monkeypatch, tmp_path):
    """Cas reel du 2026-07-23 : done en citant un commit anterieur de 37 min."""
    import sqlite3

    db = tmp_path / "tasks.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, "
                "result TEXT, created_at TEXT)")
    con.execute("INSERT INTO tasks VALUES (?,?,?,?,?)",
                ("job_x", "ANTIGRAVITY", "done",
                 '{"status_code":"SUCCESS","pointer_ref":"commit:0a880f22"}',
                 "2026-07-23T11:36:25"))
    con.commit()
    con.close()

    monkeypatch.setattr(di, "TASKS_DB", db)
    # commit date 10:58:55 UTC < task 11:36:25 UTC
    monkeypatch.setattr(di, "_git", lambda repo, *a: "2026-07-23T12:58:55+02:00")

    found = di._scan_false_attestations()
    assert len(found) == 1
    assert found[0]["kind"] == "attestation_commit_anterieur"
    assert found[0]["severity"] == "high"
    assert "37 min" in found[0]["detail"]


def test_attestation_posterieure_est_valide(monkeypatch, tmp_path):
    import sqlite3

    db = tmp_path / "tasks.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, "
                "result TEXT, created_at TEXT)")
    con.execute("INSERT INTO tasks VALUES (?,?,?,?,?)",
                ("job_ok", "AGY", "done", '{"pointer_ref":"commit:6fcc68bc"}',
                 "2026-07-23T11:36:13"))
    con.commit()
    con.close()
    monkeypatch.setattr(di, "TASKS_DB", db)
    monkeypatch.setattr(di, "_git", lambda repo, *a: "2026-07-23T20:07:56+02:00")
    assert di._scan_false_attestations() == []


def test_git_muet_ne_produit_aucune_accusation(monkeypatch, tmp_path):
    """Doute -> s'abstenir. git indisponible ne doit jamais accuser une task."""
    import sqlite3

    db = tmp_path / "tasks.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, "
                "result TEXT, created_at TEXT)")
    con.execute("INSERT INTO tasks VALUES (?,?,?,?,?)",
                ("job_y", "AGY", "done", '{"pointer_ref":"commit:deadbeef"}',
                 "2026-07-23T11:36:25"))
    con.commit()
    con.close()
    monkeypatch.setattr(di, "TASKS_DB", db)
    monkeypatch.setattr(di, "_git", lambda repo, *a: None)
    assert di._scan_false_attestations() == []


def test_file_non_drainee(monkeypatch, tmp_path):
    import sqlite3

    vieux = (datetime.now(tz=timezone.utc) - timedelta(days=31)).replace(tzinfo=None).isoformat()
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, "
                "result TEXT, created_at TEXT)")
    con.execute("INSERT INTO tasks VALUES ('a','ANTIGRAVITY','claimed',NULL,?)", (vieux,))
    con.commit()
    con.close()
    monkeypatch.setattr(di, "TASKS_DB", db)
    found = di._scan_stale_queue()
    assert len(found) == 1
    assert found[0]["kind"] == "file_non_drainee"
    assert found[0]["severity"] == "high"


def test_file_recente_ne_sonne_pas(monkeypatch, tmp_path):
    import sqlite3

    recent = (datetime.now(tz=timezone.utc) - timedelta(days=1)).replace(tzinfo=None).isoformat()
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, status TEXT, "
                "result TEXT, created_at TEXT)")
    con.execute("INSERT INTO tasks VALUES ('a','AGY','pending',NULL,?)", (recent,))
    con.commit()
    con.close()
    monkeypatch.setattr(di, "TASKS_DB", db)
    assert di._scan_stale_queue() == []


@pytest.mark.parametrize("n,attendu", [(0, 0), (2, 0), (3, 1), (25, 1)])
def test_seuil_commits_non_pousses(monkeypatch, n, attendu):
    def fake_git(repo, *a):
        if a[:1] == ("rev-parse",) and "--abbrev-ref" in a and "@{u}" in a:
            return "origin/alpha"
        if a[:1] == ("rev-parse",):
            return "alpha"
        if a[:1] == ("rev-list",):
            return str(n)
        return None

    monkeypatch.setattr(di, "_git", fake_git)
    assert len(di._scan_unpushed()) == attendu


def test_branche_sans_upstream_sonne(monkeypatch):
    def fake_git(repo, *a):
        if "@{u}" in a:
            return None
        if a[:1] == ("rev-parse",):
            return "alpha"
        return None

    monkeypatch.setattr(di, "_git", fake_git)
    found = di._scan_unpushed()
    assert len(found) == 1 and found[0]["kind"] == "branche_sans_upstream"


def test_travail_non_commite_ancien_sonne(monkeypatch, tmp_path):
    vieux = tmp_path / "orphelin.py"
    vieux.write_text("# jamais commite\n", encoding="utf-8")
    old = (datetime.now(tz=timezone.utc) - timedelta(days=30)).timestamp()
    os.utime(vieux, (old, old))

    monkeypatch.setattr(di, "ROOT", tmp_path)
    monkeypatch.setattr(di, "_git", lambda repo, *a: "orphelin.py" if "--cached" not in a else "")
    found = di._scan_uncommitted()
    assert len(found) == 1
    assert found[0]["kind"] == "travail_non_commite"
    assert "30 j" in found[0]["detail"]


def test_travail_non_commite_recent_ne_sonne_pas(monkeypatch, tmp_path):
    """Un fichier tout juste edite est du travail EN COURS, pas un oubli."""
    frais = tmp_path / "en_cours.py"
    frais.write_text("# edite a l instant\n", encoding="utf-8")
    monkeypatch.setattr(di, "ROOT", tmp_path)
    monkeypatch.setattr(di, "_git", lambda repo, *a: "en_cours.py" if "--cached" not in a else "")
    assert di._scan_uncommitted() == []


def test_arbre_propre_ne_sonne_pas(monkeypatch):
    monkeypatch.setattr(di, "_git", lambda repo, *a: "")
    assert di._scan_uncommitted() == []


def _runs(*couples):
    """(nom, conclusion) -> payload gh, du plus recent au plus ancien."""
    import json as _j
    return _j.dumps([{"name": n, "status": "completed", "conclusion": c,
                      "headSha": "abcdef1234", "createdAt": "2026-07-24T10:00:00Z",
                      "url": "http://x"} for n, c in couples])


def test_ci_muette_le_DIT(monkeypatch):
    """gh absent / non authentifie / hors reseau : on n'accuse personne, mais on ne
    laisse pas le silence passer pour un feu vert."""
    monkeypatch.setattr(di, "_git", lambda repo, *a: "alpha")
    monkeypatch.setattr(di, "_gh", lambda *a: None)
    f = di._scan_ci_failures()
    assert len(f) == 1
    assert f[0]["kind"] == "ci_non_observable"
    assert f[0]["severity"] == "low"  # signal, pas accusation


def test_ci_verte_ne_sonne_pas(monkeypatch):
    monkeypatch.setattr(di, "_git", lambda repo, *a: "alpha")
    monkeypatch.setattr(di, "_gh", lambda *a: _runs(("CI", "success"), ("CI", "failure")))
    assert di._scan_ci_failures() == []


def test_ci_rouge_est_signalee(monkeypatch):
    """Le cas du 24-07 : deux semaines de rouge que personne ne regardait."""
    monkeypatch.setattr(di, "_git", lambda repo, *a: "alpha")
    monkeypatch.setattr(di, "_gh", lambda *a: _runs(*[("CI", "failure")] * 14))
    f = di._scan_ci_failures()
    assert len(f) == 1
    assert f[0]["kind"] == "ci_en_echec" and f[0]["severity"] == "high"
    assert "14 consecutif" in f[0]["detail"]


def test_serie_coupee_au_premier_succes(monkeypatch):
    monkeypatch.setattr(di, "_git", lambda repo, *a: "alpha")
    monkeypatch.setattr(di, "_gh", lambda *a: _runs(
        ("CI", "failure"), ("CI", "failure"), ("CI", "success"), ("CI", "failure")))
    assert "2 consecutif" in di._scan_ci_failures()[0]["detail"]


def test_chaque_workflow_est_juge_separement(monkeypatch):
    monkeypatch.setattr(di, "_git", lambda repo, *a: "alpha")
    monkeypatch.setattr(di, "_gh", lambda *a: _runs(
        ("CI", "failure"), ("Dependency Graph", "success")))
    assert [x["target"] for x in di._scan_ci_failures()] == ["CI"]


def test_runs_en_cours_ignores(monkeypatch):
    """Un run encore en vol n'est pas un echec."""
    import json as _j
    monkeypatch.setattr(di, "_git", lambda repo, *a: "alpha")
    monkeypatch.setattr(di, "_gh", lambda *a: _j.dumps(
        [{"name": "CI", "status": "in_progress", "conclusion": None}]))
    assert di._scan_ci_failures() == []


def test_scan_retourne_le_contrat():
    r = di.scan()
    assert set(("findings", "count", "new_or_updated")) <= set(r)
    assert r["count"] == len(r["findings"])
    for f in r["findings"]:
        assert set(("kind", "target", "severity", "detail")) <= set(f)
        assert f["severity"] in ("high", "med", "low")
