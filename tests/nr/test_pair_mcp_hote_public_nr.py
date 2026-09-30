"""NR -- le Host PUBLIC annonce passe la protection DNS-rebinding de FastMCP, un Host etranger non.

Connecteur des pairs (2026-09-28). FastMCP (mcp 1.28.1) active d'office sur 127.0.0.1 une
protection qui n'accepte que les Host loopback. Derriere Tailscale Funnel, le Host est celui de
l'URL publique : sans l'etendre, /mcp rendrait 421 a tout pair AUTHENTIFIE -- et le NR du 401 ne
le voyait pas, l'authentification repondant avant le controle du Host. Chemin reel : l'application
HTTP de construire_serveur, requete `initialize` complete, sans OAuth pour atteindre le controle.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUBLIQUE = "https://noeud-test.tailnet-test.ts.net"
INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "nr", "version": "0"}}}
ENTETES = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setenv("NOKIDO_PAIR_PUBLIC_URL", PUBLIQUE + "/")
    spec = importlib.util.spec_from_file_location("nr_pair_hote", ROOT / "tools/forge_pair_mcp.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _statut(m, hote, origine=None):
    """Un serveur NEUF par requete : le gestionnaire de session ne demarre qu'une fois par instance."""
    from starlette.testclient import TestClient
    entetes = dict(ENTETES, Host=hote)
    if origine:
        entetes["Origin"] = origine
    with TestClient(m.construire_serveur(oauth=False).streamable_http_app()) as client:
        return client.post("/mcp", json=INIT, headers=entetes).status_code


def test_le_host_public_annonce_est_accepte(application):
    assert _statut(application, "noeud-test.tailnet-test.ts.net") == 200
    assert _statut(application, "noeud-test.tailnet-test.ts.net", PUBLIQUE) == 200


def test_le_loopback_reste_accepte(application):
    assert _statut(application, "127.0.0.1:8793") == 200


def test_un_host_ou_une_origine_etrangers_sont_refuses(application):
    assert _statut(application, "attaquant.example") == 421
    assert _statut(application, "noeud-test.tailnet-test.ts.net", "https://attaquant.example") == 403


def test_la_protection_n_est_jamais_coupee_ni_ouverte_a_tous(application):
    m = application
    reglage = m.construire_serveur(oauth=False).settings.transport_security
    assert reglage.enable_dns_rebinding_protection is True
    assert "*" not in reglage.allowed_hosts and "*" not in reglage.allowed_origins
    sans_url = m.securite_transport("http://127.0.0.1:8793")
    assert sans_url.allowed_hosts == ["127.0.0.1:*", "localhost:*", "[::1]:*"]
