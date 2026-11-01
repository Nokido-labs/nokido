"""NR point 3 de l'homeostasie (owner 29/10) : UN SEUL point de decision pour les demandes de piliers.

Physiologie : muscles antagonistes et inhibition reciproque (OpenStax A&P 2e, m46487) -- un seul centre decide de la
contraction, sinon agoniste et antagoniste tirent ensemble. Technique : breathe-control, single-writer guard.
Mesure 29/10 : forge_embed_router.declare_wanted passait DEJA par forge_pillar_arbiter.reclamer, mais
forge_docker_agent.ensure_daemon ecrivait docker.wanted DIRECTEMENT -- d'ou l'interblocage du jour (Docker reclame
pour des veilles que la satiete refusait). Desormais ensure_daemon demande l'arbitre avant d'ecrire ; arbitre
indisponible = pas de blocage (meme regle que declare_wanted).
"""
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _da():
    nom = "forge_docker_agent_nr_arbitre"
    if nom in sys.modules:
        return sys.modules[nom]
    sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]
    spec = importlib.util.spec_from_file_location(nom, ROOT / "app" / "forge_docker_agent.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


def _arbitre(monkeypatch, verdict=None, leve=False):
    mod = types.ModuleType("nokido_agent.app.forge_pillar_arbiter")
    vus = []

    def reclamer(flag, motif=""):
        vus.append((flag, motif))
        if leve:
            raise RuntimeError("arbitre en panne")
        return verdict
    mod.reclamer = reclamer
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_pillar_arbiter", mod)
    return vus


def test_refus_de_l_arbitre_aucun_drapeau(tmp_path, monkeypatch):
    m = _da()
    monkeypatch.setattr(m, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(m, "daemon_up", lambda: False)
    vus = _arbitre(monkeypatch, {"accorde": False, "motif": "RAM", "substitut": "cloud"})
    r = m.ensure_daemon(motif="veille")
    assert r["ok"] is False and r["action"] == "refuse_par_arbitre"
    assert not (tmp_path / "docker.wanted").exists()
    assert vus == [("docker.wanted", "veille")]


def test_accord_de_l_arbitre_drapeau_pose(tmp_path, monkeypatch):
    m = _da()
    monkeypatch.setattr(m, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(m, "daemon_up", lambda: False)
    _arbitre(monkeypatch, {"accorde": True})
    assert m.ensure_daemon()["action"] == "docker_wanted_posted"
    assert (tmp_path / "docker.wanted").read_text(encoding="utf-8").strip()


def test_usage_declare_refuse_par_l_arbitre_ne_prolonge_pas_le_bail(tmp_path, monkeypatch):
    """29/10 soir : declarer_usage ecrivait docker.wanted SANS l'arbitre -- un Docker refuse par la politique mais leve
    par un autre restait prolonge a chaque usage. Deuxieme ecrivain du meme levier, aligne sur ensure_daemon."""
    m = _da()
    monkeypatch.setattr(m, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(m, "daemon_up", lambda: True)
    vus = _arbitre(monkeypatch, {"accorde": False, "motif": "satiete"})
    assert m.declarer_usage("veille") is False
    assert not (tmp_path / "docker.wanted").exists() and vus and vus[-1][0] == "docker.wanted"


def test_usage_declare_accorde_prolonge_le_bail(tmp_path, monkeypatch):
    m = _da()
    monkeypatch.setattr(m, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(m, "daemon_up", lambda: True)
    _arbitre(monkeypatch, {"accorde": True})
    assert m.declarer_usage("veille") is True and (tmp_path / "docker.wanted").exists()


def test_arbitre_indisponible_ne_bloque_pas(tmp_path, monkeypatch):
    m = _da()
    monkeypatch.setattr(m, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(m, "daemon_up", lambda: False)
    _arbitre(monkeypatch, leve=True)
    assert m.ensure_daemon()["action"] == "docker_wanted_posted"
