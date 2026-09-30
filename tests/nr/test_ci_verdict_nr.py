"""NR -- un commit NON MESURE n'est pas un commit sain.

POURQUOI. Trois fois le 2026-08-20, la question « le dernier push est-il vert ? »
est restee sans reponse : tantot aucun run n'etait rattache au commit, tantot le
dernier run de la branche portait un AUTRE commit. Le piege n'est pas de lire
FAIL pour PASS -- c'est de lire « aucun run » comme « rien a signaler ». C'est
le faux-vert temporel : il ne ment sur rien, il laisse simplement conclure.

Ces tests verrouillent la table de verite du verdict. Ils n'appellent PAS
GitHub : ils exercent la logique de classement sur des reponses fabriquees, ce
qui les rend deterministes et utilisables sur un runner nu.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

for _zone in ("tools", "app"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _cic():
    chemin = ROOT / "tools" / "forge_ci_check.py"
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location("forge_ci_check", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forge_ci_check"] = mod
    sys.modules["nokido_agent.tools.forge_ci_check"] = mod
    spec.loader.exec_module(mod)
    return mod


def _faux_api(runs):
    """Remplace l'appel reseau par une reponse fabriquee."""
    return lambda _path, _cred: {"workflow_runs": runs}


def _run(sha, statut="completed", conclusion="success", branche="alpha", cree="2026-08-20T20:00:00Z"):
    return {"head_sha": sha, "status": statut, "conclusion": conclusion,
            "head_branch": branche, "created_at": cree, "id": 1}


def test_un_run_reussi_sur_le_commit_vaut_PASS(monkeypatch):
    m = _cic()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_api", _faux_api([_run("abcdef1234")]))
    assert m.verdict_commit("r", "abcdef1234")["verdict"] == m.CI_PASS


def test_un_run_en_echec_vaut_FAIL(monkeypatch):
    m = _cic()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_api", _faux_api([_run("abcdef1234", conclusion="failure")]))
    assert m.verdict_commit("r", "abcdef1234")["verdict"] == m.CI_FAIL


def test_un_run_ANNULE_n_est_ni_vert_ni_rouge(monkeypatch):
    """Mesure sur le vivant, 2026-08-20 : un run supplante par un push plus
    recent rend `cancelled`. Les tests n'ont pas rougi -- ils n'ont pas fini.
    Le classer FAIL accuserait un commit a tort ; PASS serait pire."""
    m = _cic()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_api",
                        _faux_api([_run("abcdef1234", conclusion="cancelled")]))
    v = m.verdict_commit("r", "abcdef1234")
    assert v["verdict"] == m.CI_NOT_FOUND
    assert v["verdict"] not in (m.CI_PASS, m.CI_FAIL)
    assert "NON MESURE" in v["motif"]


def test_un_run_skipped_est_aussi_un_non_mesure(monkeypatch):
    m = _cic()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_api",
                        _faux_api([_run("abcdef1234", conclusion="skipped")]))
    assert m.verdict_commit("r", "abcdef1234")["verdict"] == m.CI_NOT_FOUND


def test_un_run_en_cours_n_est_pas_un_succes(monkeypatch):
    """RUNNING n'autorise pas a conclure : le verdict n'existe pas encore."""
    m = _cic()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_api",
                        _faux_api([_run("abcdef1234", statut="in_progress", conclusion=None)]))
    v = m.verdict_commit("r", "abcdef1234")
    assert v["verdict"] == m.CI_RUNNING
    assert v["verdict"] != m.CI_PASS


def test_aucun_run_du_tout_vaut_NOT_FOUND(monkeypatch):
    """LE cas qui fabrique les faux-verts temporels."""
    m = _cic()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_api", _faux_api([]))
    v = m.verdict_commit("r", "abcdef1234")
    assert v["verdict"] == m.CI_NOT_FOUND
    assert v["verdict"] != m.CI_PASS


def test_un_run_d_un_AUTRE_commit_vaut_STALE(monkeypatch):
    """Des runs existent, mais aucun ne porte ce commit : le verdict qu'on lit
    concerne du code qui n'est pas celui qu'on evalue."""
    m = _cic()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")
    monkeypatch.setattr(m, "_api", _faux_api([_run("999999aaaa")]))
    v = m.verdict_commit("r", "abcdef1234")
    assert v["verdict"] == m.CI_STALE
    assert "999999aa" in v["motif"], v["motif"]


def test_un_jeton_absent_ne_vaut_pas_vert(monkeypatch):
    """Ne pas POUVOIR mesurer n'est pas mesurer : c'est NOT_FOUND, pas PASS."""
    m = _cic()
    monkeypatch.setattr(m, "_creds", lambda: None)
    v = m.verdict_commit("r", "abcdef1234")
    assert v["verdict"] == m.CI_NOT_FOUND
    assert v["ok"] is False


def test_une_panne_reseau_ne_vaut_pas_vert(monkeypatch):
    m = _cic()
    monkeypatch.setattr(m, "_creds", lambda: "jeton")

    def _casse(_p, _c):
        raise OSError("reseau coupe")

    monkeypatch.setattr(m, "_api", _casse)
    v = m.verdict_commit("r", "abcdef1234")
    assert v["verdict"] == m.CI_NOT_FOUND
    assert "OSError" in v["motif"]


def test_un_seul_verdict_est_vert():
    """La table de verite doit rester asymetrique : quatre etats sur cinq
    interdisent de conclure. Si un jour l'un d'eux rejoint le vert, ce test
    tombe -- et c'est exactement ce qu'on veut."""
    m = _cic()
    assert m.CI_PASS not in m.CI_VERDICTS_NON_VERTS
    for v in (m.CI_FAIL, m.CI_RUNNING, m.CI_NOT_FOUND, m.CI_STALE):
        assert v in m.CI_VERDICTS_NON_VERTS
