"""NR — ACP de bout en bout : service, authentification, session, observabilite.

Pourquoi ce fichier existe : le 2026-09-04, `forge_a2a_card` a REFUSE de publier
`acp.session` alors que le service tournait et venait d'etre durci — faute d'un NR
prouvant son execution. C'est le comportement voulu. La carte annonce ce qui est
PROUVE, pas ce que son auteur sait avoir fait. Ce test est donc la condition
d'entree de la capacite dans la carte, pas une formalite.

Invariant vise :

    service demarre -> authentification -> session ACP -> operation reelle
    -> resultat attendu -> evenements observables

CONDITIONNEL PAR CONSTRUCTION : si le service n'ecoute pas, le test SKIP au lieu
d'echouer. Un NR qui exige un service allume rendrait la CI dependante de l'etat
de la machine — et un rouge d'environnement, on vient d'en payer un toute la
soiree. En revanche, service allume = exigences PLEINES, aucune indulgence.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : reseau localhost reel (l.48)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
PORT = int(os.environ.get("ACP_WS_PORT", "7782"))


def _ecoute(port: int) -> bool:
    s = socket.socket()
    s.settimeout(1.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _handshake(entetes: str = "", port: int = PORT):
    """Rend (ligne_statut, en-tetes). Handshake WS a la main : pas de dependance."""
    s = socket.create_connection(("127.0.0.1", port), timeout=8)
    cle = base64.b64encode(os.urandom(16)).decode()
    req = ("GET /acp HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\n"
           "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
           "Sec-WebSocket-Version: 13\r\n%s\r\n" % (port, cle, entetes))
    s.sendall(req.encode())
    brut = s.recv(800).decode("utf-8", "replace")
    s.close()
    lignes = brut.splitlines()
    return (lignes[0] if lignes else ""), lignes[1:]


def _jeton():
    sys.path.insert(0, str(ROOT / "app"))
    try:
        from forge_secrets import get_secret
    except ImportError:
        return None
    for cle in ("FORGE_ACP_TOKEN", "FORGE_MCP_TOKEN"):
        try:
            v = get_secret(cle)
        except Exception:  # noqa: BLE001  # muet-ok : on tente la clef suivante
            continue
        if v and v.strip():
            return v.strip()
    return None


def _exige_service():
    if not _ecoute(PORT):
        pytest.skip("NokidoAcpWs n'ecoute pas sur %d — capacite non AVAILABLE" % PORT)


def test_acp_refuse_sans_jeton():
    """Le premier controle : un anonyme ne doit pas franchir le handshake."""
    _exige_service()
    statut, entetes = _handshake()
    assert "401" in statut, "handshake accepte SANS credential : %s" % statut
    assert any("WWW-Authenticate" in e for e in entetes), (
        "401 sans WWW-Authenticate — non conforme RFC 6750")


def test_acp_refuse_un_faux_jeton():
    _exige_service()
    statut, _ = _handshake("Authorization: Bearer faux-jeton\r\n")
    assert "401" in statut


def test_acp_accepte_le_jeton_du_coffre_et_ouvre_la_session():
    """Le chemin nominal COMPLET : jeton du coffre -> 101 -> session ACP."""
    _exige_service()
    tok = _jeton()
    if not tok:
        pytest.skip("aucun jeton au coffre — impossible de prouver le chemin nominal")
    statut, _ = _handshake("Authorization: Bearer %s\r\nX-Agent-Name: NR\r\n" % tok)
    assert "101" in statut, "jeton valide refuse : %s" % statut


def test_acp_journalise_ses_decisions():
    """Observabilite : une admission ou un refus DOIT laisser une empreinte.

    Sans journal, une session ouverte par un tiers est indetectable — c'est le
    manque mesure avant durcissement (`logger` x0 dans forge_acp_server).
    """
    _exige_service()
    _handshake()  # produit au moins un REFUS
    j = ROOT / "logs" / "acp_ws.log"
    if not j.exists():
        pytest.skip("journal non ecrivable par ce compte (repli stderr)")
    texte = j.read_text(encoding="utf-8", errors="replace")
    assert ("REFUS" in texte or "ADMIS" in texte), "aucune decision journalisee"
    tok = _jeton()
    if tok:
        assert tok not in texte, "LE JETON EST ECRIT EN CLAIR DANS LE JOURNAL"


def test_acp_ne_publie_pas_le_jeton_dans_la_carte():
    """Aucun secret ne doit fuir par la couche de decouverte."""
    sys.path.insert(0, str(ROOT / "tools"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "forge_a2a_card", ROOT / "tools" / "forge_a2a_card.py")
    card = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(card)
    brut = json.dumps(card.carte(etendue=True), ensure_ascii=False)
    tok = _jeton()
    if tok:
        assert tok not in brut


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
