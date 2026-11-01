# -*- coding: utf-8 -*-
"""NR (28/10, accord owner) : la config canonique de secours de Claude Desktop ne reinjecte plus MCP_DOCKER.

Le gateway Docker MCP est joignable VIA Nokido (outils docker_* du hub, prouve 28/10 : docker_mcp-find en ring 1).
Le bloc MCP_DOCKER des clients a ete retire (accord owner) ; forge_rescue._canonical() le restaurait a chaque
validate_config(). Le pont Nokido (stdio, LAFORGE_AGENT=CLAUDE, ring 1) reste, et porte docker_*."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_rescue as rescue  # noqa: E402


def test_le_canonique_ne_declare_plus_mcp_docker():
    c = rescue._canonical()
    assert "MCP_DOCKER" not in c
    assert "Nokido" in c  # docker_* passe par le hub
