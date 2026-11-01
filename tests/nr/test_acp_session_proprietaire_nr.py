"""NR : une session ACP appartient a l'appelant qui l'a ouverte (audit AGY docs/audit/AUDIT_ACP_HUB_20261029.md, cas (a)).

Constat verifie le 29/10 : handle_acp ne transmettait pas l'appelant au worker ; envoyer/fermer ne controlaient aucun
proprietaire ; lister rendait les sessions de TOUS les agents ; une session liberee etait reprise par un autre appelant
avec son historique. Ce NR tient les trois couches : routeur (refus AVANT tout contact avec le client CLI, lister
filtre, pool cloisonne), worker (l'appelant scelle passe au routeur), hub (l'appelant authentifie entre dans le job).
Sans appelant (ancien hub), le comportement d'avant est garde.
"""
import ast
import sys
import threading
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
from tools import forge_acp_router as R  # noqa: E402
from tools import forge_acp_worker as W  # noqa: E402


class _Cli:
    def is_session_busy(self, acp):
        return False

    def __getattr__(self, nom):
        raise AssertionError("client CLI touche (%s) : le refus doit tomber avant" % nom)


def _routeur(tmp_path):
    r = R.ACPRouter(log_dir=tmp_path, route=lambda a: str(tmp_path))
    now = time.time()
    profil = R._profil_resolu("claude", None)
    for sid, prop, libre in (("claude-1", "agt_a", False), ("claude-2", "agt_b", False), ("claude-3", "agt_a", True)):
        r._sessions[sid] = {"cli": _Cli(), "agent": "claude", "cwd": str(tmp_path), "acp": "acp-" + sid,
                            "profil": profil, "isolee": False, "libre": libre, "taches": 1, "dernier": now,
                            "proprietaire": prop, "reprise": threading.Lock(), "init": {}}
    return r, profil


def test_envoyer_la_session_d_un_autre_est_refuse(tmp_path):
    r, _ = _routeur(tmp_path)
    with pytest.raises(PermissionError):
        r.envoyer("claude-1", "bonjour", proprietaire="agt_b")


def test_fermer_la_session_d_un_autre_est_refuse(tmp_path):
    r, _ = _routeur(tmp_path)
    with pytest.raises(PermissionError):
        r.fermer("claude-1", proprietaire="agt_b")
    assert r._sessions["claude-1"]["libre"] is False


def test_lister_ne_rend_que_ses_sessions(tmp_path):
    r, _ = _routeur(tmp_path)
    assert [s["id"] for s in r.lister(proprietaire="agt_a")] == ["claude-1"]
    assert sorted(s["id"] for s in r.lister()) == ["claude-1", "claude-2"]  # sans appelant : comportement d'avant


def test_le_pool_ne_rend_une_session_libre_qu_a_son_proprietaire(tmp_path):
    r, profil = _routeur(tmp_path)
    assert r._prendre_du_pool("claude", profil, None, proprietaire="agt_b") is None
    pris = r._prendre_du_pool("claude", profil, None, proprietaire="agt_a")
    assert pris is not None and pris[0] == "claude-3"


class _RouteurEspion:
    def __init__(self):
        self.appels = []

    def envoyer(self, sid, texte, timeout=None, proprietaire=None):
        self.appels.append(("envoyer", proprietaire))
        return "ok"

    def fermer(self, sid, proprietaire=None):
        self.appels.append(("fermer", proprietaire))

    def lister(self, proprietaire=None):
        self.appels.append(("lister", proprietaire))
        return []


def test_le_worker_passe_l_appelant_scelle_au_routeur():
    w = W.AcpWorker.__new__(W.AcpWorker)
    w.router = _RouteurEspion()
    w.executer("envoyer", {"session": "claude-1", "texte": "x", "appelant": "agt_b"})
    w.executer("fermer", {"session": "claude-1", "appelant": "agt_b"})
    w.executer("lister", {"appelant": "agt_b"})
    assert w.router.appels == [("envoyer", "agt_b"), ("fermer", "agt_b"), ("lister", "agt_b")]


def test_le_hub_scelle_l_appelant_dans_le_job():
    src = (RACINE / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "handle_acp")
    affectations = [n for n in ast.walk(fn) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Subscript)
                    and getattr(n.targets[0].value, "id", "") == "params"
                    and getattr(n.targets[0].slice, "value", None) == "appelant"]
    assert affectations and getattr(affectations[0].value, "id", "") == "agent"
