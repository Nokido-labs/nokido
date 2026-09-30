"""NR — l'identifiant d'un appel d'outil ACP doit être CANONIQUE.

Mesure du 2026-09-12 (E2E `sandbox/e2e_acp_permission.py`, rc=0, 0,1 s) :

    session/update  tool_call          toolCallId = s1
    session/request_permission         toolCallId = s2      <-- autre identite
    session/update  tool_call_update   toolCallId = s1

Deux identifiants pour UN SEUL appel d'outil. Côté client ACP (Zed), la demande
d'autorisation ne se rattache alors à aucun appel affiché, et l'appel autorisé
(`s2`) ne reçoit jamais de mise à jour : la chaîne

    annonce  ->  permission  ->  effet

perd sa causalité. Sur une frontière de contrôle, c'est ce qui permet
d'autoriser A et d'exécuter B.

CAUSE : `TurnContext.tool_call()` prend `_next_rid()` (-> s1), puis
`ACPServer.request_permission()` en reprend un AUTRE (-> s2) et le réutilise
comme `toolCallId`. Le compteur d'identifiants JSON-RPC sert donc à la fois
d'identité de requête et d'identité d'outil : deux espaces de noms confondus
dans un seul compteur — même famille que « deux index ne se comparent jamais par
leurs identifiants internes ».

Ce test emprunte le CHEMIN REEL (stdio, `__main__` du serveur), pas la fonction
isolée : c'est le niveau qui a manqué aux 5 NR d'appui ACP existants, lesquels
vérifient seulement `importlib.import_module(...) is not None` — un import ne
prouve aucun runtime.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.60)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
SERVEUR = RACINE / "tools" / "forge_acp_server.py"


def _dialogue(prompt: str, secondes: float = 25.0):
    """Joue le rôle du CLIENT ACP et rend tous les messages reçus.

    Répond `allow_once` à toute demande de permission, sinon le tour ne se
    termine pas et le test mesurerait un blocage au lieu d'une identité.
    """
    if not SERVEUR.is_file():
        pytest.skip(f"serveur ACP absent: {SERVEUR}")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(RACINE), str(RACINE / "app"), str(RACINE / "tools"), env.get("PYTHONPATH", "")])
    env["PYTHONIOENCODING"] = "utf-8"
    env["ACP_BRAIN"] = "echo"
    p = subprocess.Popen([sys.executable, str(SERVEUR), "--echo"],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8",
                         errors="replace", bufsize=1, cwd=str(RACINE), env=env)
    recus: queue.Queue = queue.Queue()
    tous: list = []

    def _lire():
        for ligne in p.stdout:
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                obj = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            tous.append(obj)
            recus.put(obj)

    threading.Thread(target=_lire, daemon=True).start()

    def envoyer(o):
        p.stdin.write(json.dumps(o, ensure_ascii=False) + "\n")
        p.stdin.flush()

    def attendre(pred, s):
        fin = time.time() + s
        while time.time() < fin:
            try:
                o = recus.get(timeout=0.3)
            except queue.Empty:
                continue
            if pred(o):
                return o
        return None

    try:
        envoyer({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": 1, "clientCapabilities": {}}})
        attendre(lambda o: o.get("id") == 1, 10)
        envoyer({"jsonrpc": "2.0", "id": 2, "method": "session/new",
                 "params": {"cwd": str(RACINE), "mcpServers": []}})
        r = attendre(lambda o: o.get("id") == 2, 10)
        sid = ((r or {}).get("result") or {}).get("sessionId")
        if not sid:
            pytest.skip("pas de sessionId — le serveur n'a pas ouvert de session")
        envoyer({"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
                 "params": {"sessionId": sid, "prompt": [{"type": "text", "text": prompt}]}})
        dem = attendre(lambda o: o.get("method") == "session/request_permission"
                       and o.get("id") is not None, secondes)
        if dem is not None:
            envoyer({"jsonrpc": "2.0", "id": dem["id"],
                     "result": {"outcome": {"outcome": "selected", "optionId": "allow_once"}}})
        attendre(lambda o: o.get("id") == 3, 20)
    finally:
        try:
            p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    return tous


def _ids(messages):
    annonces, permissions, maj = [], [], []
    for m in messages:
        if m.get("method") == "session/update":
            u = (m.get("params") or {}).get("update") or {}
            if u.get("sessionUpdate") == "tool_call":
                annonces.append(u.get("toolCallId"))
            elif u.get("sessionUpdate") == "tool_call_update":
                maj.append(u.get("toolCallId"))
        elif m.get("method") == "session/request_permission":
            tc = (m.get("params") or {}).get("toolCall") or {}
            permissions.append(tc.get("toolCallId"))
    return annonces, permissions, maj


def test_le_cycle_outil_se_declenche():
    """Contrôle positif : sans lui, une égalité sur deux listes vides passerait."""
    msgs = _dialogue("!lister le repertoire")
    annonces, permissions, maj = _ids(msgs)
    assert annonces, "aucun tool_call annoncé — le cycle mesuré n'a pas eu lieu"
    assert permissions, "aucune demande de permission — rien à corréler"
    assert maj, "aucun tool_call_update — l'effet n'a pas été rapporté"


def test_le_toolcallid_autorise_est_celui_annonce():
    """ROUGE ATTENDU avant correctif.

    L'identifiant présenté à l'autorisation doit être exactement celui annoncé.
    Autoriser un identifiant et en mettre à jour un autre rompt la chaîne de
    causalité sur laquelle repose tout contrôle d'effet.
    """
    msgs = _dialogue("!lister le repertoire")
    annonces, permissions, maj = _ids(msgs)
    assert permissions[0] == annonces[0], (
        "PERTE DE CAUSALITE : outil annoncé %r, autorisé %r — "
        "l'identifiant de transaction a été remplacé en cours de route."
        % (annonces[0], permissions[0]))
    assert set(maj) <= set(annonces), (
        "les mises à jour portent sur %r, hors des appels annoncés %r" % (maj, annonces))
