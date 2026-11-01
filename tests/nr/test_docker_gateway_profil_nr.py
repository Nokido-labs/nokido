# -*- coding: utf-8 -*-
"""NR (28/10) : le gateway Docker MCP du hub utilise le MEME profil que les clients (`--profile laforge`).

Mesure : ~/.claude.json declare MCP_DOCKER = `docker mcp gateway run --profile laforge` ; le hub lancait
`docker mcp gateway run` SANS profil (« Default profile not found, using empty configuration ») -- donc un
autre inventaire que celui des clients, et le catalogue en cache aurait decrit un gateway que personne
n'utilise. Le profil reste surchargeable (LAFORGE_DOCKER_MCP_PROFILE ; vide = pas de profil)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_docker_supervisor as fds  # noqa: E402


def test_profil_laforge_par_defaut(monkeypatch):
    monkeypatch.delenv("LAFORGE_DOCKER_MCP_PROFILE", raising=False)
    assert fds._gateway_cmd() == ["docker", "mcp", "gateway", "run", "--profile", "laforge"]


def test_profil_surchargeable_et_desactivable(monkeypatch):
    monkeypatch.setenv("LAFORGE_DOCKER_MCP_PROFILE", "autre")
    assert fds._gateway_cmd()[-2:] == ["--profile", "autre"]
    monkeypatch.setenv("LAFORGE_DOCKER_MCP_PROFILE", "")
    assert fds._gateway_cmd() == ["docker", "mcp", "gateway", "run"]


def test_le_spawn_utilise_la_commande_avec_profil():
    src = (ROOT / "app" / "forge_docker_supervisor.py").read_text(encoding="utf-8")
    assert "_gateway_cmd()," in src, "spawn_gateway_stdio lance encore GATEWAY_CMD sans profil"
