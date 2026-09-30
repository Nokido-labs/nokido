"""NR — `authenticate` ne doit pas produire un accusé d'authentification vide.

Mesure du 2026-09-12 (lecture du dispatcher, `forge_acp_server._handle_request`) :

    initialize   -> agentCapabilities = {loadSession, promptCapabilities}
                    ... et AUCUNE `authMethods`
    authenticate -> self._reply(rid, {})        <-- succès, sans rien vérifier
    session/load -> -32601 "loadSession not supported"

L'asymétrie est le défaut. `session/load` refuse proprement parce que la capacité
n'est pas déclarée ; `authenticate` accepte alors qu'aucune méthode
d'authentification n'est déclarée non plus. Un client ACP reçoit donc un `result`
qu'il peut légitimement lire comme « authentifié », alors qu'aucune identité n'a
été établie.

C'est le motif « cérémonie de sécurité sans enforcement » de l'audit adversarial,
et la distinction `DECLARED` ≠ `VERIFIED` : une API appelée n'est pas une
identité authentifiée.

CE QUI N'EST PAS EN CAUSE : le transport WebSocket a, lui, une vraie admission
fail-closed (jeton du coffre, `hmac.compare_digest`, 401 + `WWW-Authenticate`).
L'authentification y est faite AU HANDSHAKE, hors bande. En stdio, le client
lance le processus lui-même : il n'y a rien à authentifier. Dans les deux cas,
répondre `{}` est faux — soit c'est déjà fait ailleurs, soit ça n'a pas de sens
ici. Le seul verdict honnête est un refus explicite.

ÉTAT ATTENDU : `test_authenticate_ne_simule_pas_un_succes` est ROUGE tant que le
correctif n'est pas posé.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.54)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
SERVEUR = RACINE / "tools" / "forge_acp_server.py"


def _echange(messages, secondes=25):
    """Envoie des messages en stdio et rend les réponses, par le CHEMIN REEL."""
    if not SERVEUR.is_file():
        pytest.skip(f"serveur ACP absent: {SERVEUR}")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(RACINE), str(RACINE / "app"), str(RACINE / "tools"), env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    env["ACP_BRAIN"] = "echo"
    entree = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages)
    p = subprocess.run([sys.executable, str(SERVEUR), "--echo"], input=entree,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=secondes, cwd=str(RACINE), env=env)
    out = []
    for ligne in (p.stdout or "").splitlines():
        ligne = ligne.strip()
        if ligne[:1] == "{":
            try:
                out.append(json.loads(ligne))
            except json.JSONDecodeError:
                continue
    return out


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": 1, "clientCapabilities": {}}}
AUTH = {"jsonrpc": "2.0", "id": 2, "method": "authenticate",
        "params": {"methodId": "inexistant"}}


def test_aucune_methode_d_authentification_n_est_declaree():
    """Contrôle positif ET prémisse du test suivant : si un jour le serveur
    déclare des `authMethods`, le refus attendu plus bas n'a plus lieu d'être."""
    rep = _echange([INIT])
    init = [m for m in rep if m.get("id") == 1]
    assert init, "initialize n'a pas répondu — rien à conclure"
    caps = (init[0].get("result") or {}).get("agentCapabilities") or {}
    methodes = (init[0].get("result") or {}).get("authMethods")
    assert not methodes, (
        "le serveur déclare maintenant des authMethods (%r) : ce NR doit être "
        "revu, le refus n'est plus le bon comportement" % (methodes,))
    assert "promptCapabilities" in caps, "capacités inattendues — dispatcher modifié ?"


def test_authenticate_ne_simule_pas_un_succes():
    """ROUGE ATTENDU avant correctif.

    Sans méthode déclarée, `authenticate` doit REFUSER explicitement, comme
    `session/load` le fait déjà. Rendre un `result` laisse croire à une identité
    établie.
    """
    rep = _echange([INIT, AUTH])
    auth = [m for m in rep if m.get("id") == 2]
    assert auth, "authenticate n'a pas répondu du tout"
    assert "error" in auth[0], (
        "CEREMONIE SANS ENFORCEMENT : authenticate rend %r — un client peut le "
        "lire comme « authentifié » alors qu'aucune identité n'a été établie."
        % (auth[0].get("result"),))


def test_session_load_refuse_toujours():
    """Garde-fou de symétrie : le refus de `session/load` ne doit pas régresser
    pendant qu'on corrige `authenticate`."""
    rep = _echange([INIT, {"jsonrpc": "2.0", "id": 3, "method": "session/load",
                           "params": {"sessionId": "x"}}])
    load = [m for m in rep if m.get("id") == 3]
    assert load and "error" in load[0], "session/load ne refuse plus"
