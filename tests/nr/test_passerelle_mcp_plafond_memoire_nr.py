"""NR 2/11 : la passerelle `docker mcp gateway run` plafonne la memoire de CHAQUE conteneur serveur MCP.

Doc Docker (reference gateway_run, ingeree le 2/11) : `--memory` vaut 2Gb PAR DEFAUT et `--cpus` 1 par serveur.
Sans plafond, quelques serveurs du profil suffisaient a remplir la VM WSL (memory=5GB dans .wslconfig).
Le port reste le DERNIER argument : le gardien le relit par argv_gateway()[-1] (pouls, journal).
"""
import importlib
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))


def _mo(valeur: str) -> float:
    v = valeur.strip().lower().rstrip("b")
    return float(v[:-1]) * 1024 if v.endswith("g") else float(v[:-1]) if v.endswith("m") else float(v) / 2 ** 20


def test_plafond_memoire_par_defaut_sous_la_valeur_docker(monkeypatch):
    monkeypatch.delenv("LAFORGE_DOCKER_MCP_MEMOIRE", raising=False)
    g = importlib.import_module("forge_docker_mcp_gateway")
    a = g.argv_gateway()
    assert "--memory" in a, a
    assert _mo(a[a.index("--memory") + 1]) <= 1024, "plafond au-dessus de 1 Go : le defaut Docker (2 Go) revient"
    assert "--cpus" in a, a
    assert a[-1].isdigit() and a[-2] == "--port", "le port doit rester le dernier argument"


def test_plafond_reglable_par_env(monkeypatch):
    monkeypatch.setenv("LAFORGE_DOCKER_MCP_MEMOIRE", "256Mb")
    g = importlib.import_module("forge_docker_mcp_gateway")
    a = g.argv_gateway()
    assert a[a.index("--memory") + 1] == "256Mb"
    assert a[-2] == "--port"
