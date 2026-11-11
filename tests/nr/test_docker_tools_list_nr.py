# -*- coding: utf-8 -*-
"""NR (28/10, accord owner) : les outils du gateway Docker MCP apparaissent dans tools/list depuis le
catalogue en CACHE -- lister ne reveille jamais Docker -- et seulement pour le ring autorise a les appeler
(ring 0 par defaut, meme regle que la garde de dispatch). Un catalogue ABSENT n'ajoute rien (ABSENT n'est
pas « aucun outil ») ; un catalogue PERIME reste visible mais le dit."""
import pytest

from nokido_agent.app import forge_docker_supervisor as fds
from app.forge_mcp_registry import ToolRegistry


def _catalogue(monkeypatch, etat, outils):
    monkeypatch.setattr(fds, "catalogue_en_cache", lambda path=None: {"etat": etat, "outils": outils})

    def boom(*a, **k):
        raise AssertionError("tools/list a tente de reveiller Docker")
    monkeypatch.setattr(fds.DockerSupervisor, "ensure_daemon", boom)
    monkeypatch.setattr(fds.DockerSupervisor, "spawn_gateway_stdio", boom)


def _noms(reg, ring):
    return {t["name"] for t in reg.get_tool_list(ring=ring, agent="TEST_OWNER")}


def test_catalogue_frais_visible_au_ring_1(monkeypatch):
    """Ring 1 par defaut (owner 28/10) : les clients ring 1 (Claude Code...) atteignent le gateway VIA le hub."""
    _catalogue(monkeypatch, "FRAIS", [{"name": "fetch", "description": "d", "inputSchema": {"type": "object"}}])
    reg = ToolRegistry()
    assert "docker_fetch" in _noms(reg, 0) and "docker_fetch" in _noms(reg, 1)


def test_invisible_au_dela_du_ring_autorise(monkeypatch):
    _catalogue(monkeypatch, "FRAIS", [{"name": "fetch"}])
    reg = ToolRegistry()
    assert "docker_fetch" not in _noms(reg, 2)


def test_catalogue_absent_n_ajoute_rien(monkeypatch):
    _catalogue(monkeypatch, "ABSENT", [])
    reg = ToolRegistry()
    assert not [n for n in _noms(reg, 0) if n.startswith("docker_") and n != "docker_action"]


def test_catalogue_perime_ne_liste_aucun_outil(monkeypatch):
    """07/11 (accord owner) : PERIME = 0 outil docker_* liste (plus de prefixe « [catalogue perime] »)."""
    _catalogue(monkeypatch, "PERIME", [{"name": "fetch", "description": "d"}])
    reg = ToolRegistry()
    assert "docker_fetch" not in _noms(reg, 0)


def test_docker_action_natif_jamais_double(monkeypatch):
    _catalogue(monkeypatch, "FRAIS", [{"name": "action"}])
    reg = ToolRegistry()
    noms = [t["name"] for t in reg.get_tool_list(ring=0, agent="TEST_OWNER")]
    assert noms.count("docker_action") <= 1
