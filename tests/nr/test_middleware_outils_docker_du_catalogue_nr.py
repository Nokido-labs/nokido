# -*- coding: utf-8 -*-
"""NR (28/10) : la liste blanche STATIQUE du /mcp (hub_middleware._ALLOWED_TOOLS) admet les outils docker_*
du CATALOGUE EN CACHE, et eux seuls.

Mesure 28/10 13:07 : apres /mcp, Claude Code (ring 1) voit docker_mcp-find (tools/list lit le catalogue) mais
l'appel rend « tool 'docker_mcp-find' not allowed » (journal : forge.middleware TOOL_BLOCKED) -- le piege deja
paye pour forge_deep_explore (outil liste et autorise par le RBAC, refuse par la liste blanche). Admettre tout le
prefixe docker_* ouvrirait des noms jamais mesures : on admet ceux que le gateway a reellement exposes.
Catalogue illisible ou absent -> refus (fail-closed)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import hub_middleware as hm  # noqa: E402
from nokido_agent.app import forge_docker_supervisor as fds  # noqa: E402


def _catalogue(monkeypatch, etat, noms):
    monkeypatch.setattr(fds, "catalogue_en_cache", lambda path=None: {"etat": etat, "outils": [{"name": n} for n in noms]})


def test_outil_du_catalogue_admis(monkeypatch):
    _catalogue(monkeypatch, "FRAIS", ["mcp-find", "code-mode"])
    assert hm.validate_tool_name("docker_mcp-find") == (True, "docker_mcp-find")


def test_outil_hors_catalogue_refuse(monkeypatch):
    _catalogue(monkeypatch, "FRAIS", ["mcp-find"])
    ok, msg = hm.validate_tool_name("docker_inconnu")
    assert not ok and "not allowed" in msg


def test_catalogue_absent_refuse(monkeypatch):
    _catalogue(monkeypatch, "ABSENT", [])
    assert hm.validate_tool_name("docker_mcp-find")[0] is False


def test_catalogue_illisible_refuse(monkeypatch):
    def boom(path=None):
        raise OSError("illisible")
    monkeypatch.setattr(fds, "catalogue_en_cache", boom)
    assert hm.validate_tool_name("docker_mcp-find")[0] is False


def test_les_outils_statiques_inchanges():
    assert hm.validate_tool_name("introspect")[0] is True
    assert hm.validate_tool_name("pas_un_outil")[0] is False
