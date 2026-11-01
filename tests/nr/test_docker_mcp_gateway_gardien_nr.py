# -*- coding: utf-8 -*-
"""NR (28/10, accord owner) : le gateway Docker MCP tourne sous la SESSION OWNER, garde par un gardien.

Mesure 28/10 : lance par le hub ou un job (comptes LaForgeSbx*/service), `docker mcp gateway run` meurt au
demarrage -- `unable to open database file (14)` -- sa base ~/.docker/mcp/mcp-toolkit.db vit dans le profil
owner ; sous la session owner il demarre (258 ms). Le gardien (service runAs=interactive) :
- lance le gateway en transport HTTP `streaming` sur 127.0.0.1, protege par MCP_GATEWAY_AUTH_TOKEN (coffre ;
  jamais `--allow-unauthenticated`) -- le gateway expose mcp-add et code-mode, un port ouvert sans jeton
  donnerait ces pouvoirs a tout processus local ;
- attend Docker SANS le reveiller (Docker eteint = etat voulu, pas une panne ; seul le hub pose docker.wanted) ;
- relance le gateway s'il meurt pendant que Docker est leve, l'arrete si Docker s'endort ;
- ne journalise jamais la valeur du jeton.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_docker_mcp_gateway as g  # noqa: E402


class _Proc:
    def __init__(self, vivant=True):
        self.vivant, self.termine = vivant, False

    def poll(self):
        return None if self.vivant else 1

    def terminate(self):
        self.termine, self.vivant = True, False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.vivant = False


def test_argv_streaming_local_authentifie(monkeypatch):
    monkeypatch.delenv("LAFORGE_DOCKER_MCP_PROFILE", raising=False)
    monkeypatch.delenv("LAFORGE_DOCKER_MCP_PORT", raising=False)
    a = g.argv_gateway()
    assert a[:4] == ["docker", "mcp", "gateway", "run"]
    assert a[a.index("--profile") + 1] == "laforge"
    assert a[a.index("--transport") + 1] == "streaming"
    assert a[a.index("--host") + 1] == "127.0.0.1"
    assert a[a.index("--port") + 1] == str(g.PORT_DEFAUT)
    assert "--allow-unauthenticated" not in a


def test_jeton_du_coffre_cree_au_besoin_jamais_affiche(monkeypatch, capsys):
    coffre = {}
    import nokido_agent.app.forge_secrets as fs
    monkeypatch.setattr(fs, "get_secret", lambda k, required=False: coffre.get(k))
    monkeypatch.setattr(fs, "set_secret", lambda k, v: coffre.__setitem__(k, v) or True)
    env = g.env_gateway()
    v = env[g.NOM_JETON]
    assert v and coffre[g.NOM_JETON] == v
    assert g.env_gateway()[g.NOM_JETON] == v  # relu, pas recree
    sortie = capsys.readouterr()
    assert v not in sortie.out and v not in sortie.err


def test_docker_eteint_attend_sans_lancer_et_arrete_le_gateway():
    lances = []
    etat = {"proc": _Proc(vivant=True)}
    vieux = etat["proc"]
    assert g.tour(etat, docker_up=lambda: False, lancer=lambda a, e: lances.append(a)) == "EN_ATTENTE_DOCKER"
    assert vieux.termine and etat["proc"] is None and lances == []


def test_docker_leve_lance_puis_relance_un_gateway_mort(monkeypatch):
    monkeypatch.setattr(g, "env_gateway", lambda: {"X": "1"})
    etat = {}
    assert g.tour(etat, docker_up=lambda: True, lancer=lambda a, e: _Proc()) == "LANCE"
    assert g.tour(etat, docker_up=lambda: True, lancer=lambda a, e: _Proc()) == "VIVANT"
    etat["proc"].vivant = False
    assert g.tour(etat, docker_up=lambda: True, lancer=lambda a, e: _Proc()) == "LANCE"
    assert etat["morts"] == 1


def test_le_gardien_ne_pose_jamais_docker_wanted():
    src = (ROOT / "tools" / "forge_docker_mcp_gateway.py").read_text(encoding="utf-8")
    assert "ensure_docker" not in src and "docker.wanted" not in src.replace("SANS poser docker.wanted", "")
