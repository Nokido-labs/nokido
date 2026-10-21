# -*- coding: utf-8 -*-
"""NR — OpenCode par ACP : resolution, env par instance et garde de session occupee.

Verrouille les contrats de la branche OpenCode ACP (2026-10-17) :
1. Resolution binaire : nokido_opencode_web.trouver_opencode(dossier_appdata())
   avant le PATH ; introuvable -> commande ["opencode", "acp"] inchangee (echec LISIBLE,
   jamais de repli sur un autre binaire comme agy ou gemini) ;
2. Surcharge explicite via OPENCODE_ACP_CMD (JSON liste) ;
3. ACPClient(env=dict) : fusionne a os.environ pour CE sous-processus sans fuiter
   dans l'environnement du parent ; sans env, comportement identique (env=None) ;
4. Garde protocole OpenCode ACP : un seul prompt a la fois par session. Un second prompt
   sur une session occupee est refuse cote client avec message explicite, puis la
   session est liberee des que le prompt actif se termine.

Aucun sous-processus opencode reel n'est lance : doublement via FakePopen et doubles
de shutil.which / dossier_appdata.
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_acp_client as CLI  # noqa: E402


class FakePipe:
    """Simulateur de pipe stdout / stderr sans I/O bloquant."""

    def __init__(self):
        self._q = queue.Queue()

    def put(self, line: str | None):
        self._q.put(line)

    def close(self):
        self._q.put(None)

    def __iter__(self):
        while True:
            item = self._q.get()
            if item is None:
                break
            yield item


class FakeStdin:
    """Simulateur de stdin de sous-processus."""

    def __init__(self):
        self.written: list[str] = []

    def write(self, s: str):
        self.written.append(s)

    def flush(self):
        pass

    def close(self):
        pass


class FakePopen:
    """Double de subprocess.Popen pour capturer args, kwargs et eviter tout spawn reel."""

    instances: list[FakePopen] = []

    def __init__(self, cmd, *args, **kwargs):
        self.cmd = cmd
        self.args = args
        self.kwargs = kwargs
        self.stdin = FakeStdin()
        self.stdout = FakePipe()
        self.stderr = FakePipe()
        self.pid = 4242
        self._returncode: int | None = None
        FakePopen.instances.append(self)

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0
        self.stdout.close()
        self.stderr.close()

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        return self._returncode or 0


@pytest.fixture(autouse=True)
def _reinitialiser_etat(monkeypatch):
    """Garantit un environnement propre a chaque test."""
    FakePopen.instances.clear()
    for v in ("OPENCODE_ACP_CMD", "GEMINI_ACP_CMD", "CLAUDE_ACP_CMD", "CODEX_ACP_CMD", "LAFORGE_AGY_BIN"):
        monkeypatch.delenv(v, raising=False)


# ==============================================================================
# 1. RESOLUTION DU BINAIRE OPENCODE ET OVERRIDE OPENCODE_ACP_CMD
# ==============================================================================

def test_resolution_opencode_via_appdata_npm_avant_path(monkeypatch, tmp_path):
    """trouver_opencode resout via %APPDATA%/npm avant le PATH."""
    dossier_npm = tmp_path / "npm"
    dossier_npm.mkdir(parents=True, exist_ok=True)
    binaire_npm = dossier_npm / "opencode.cmd"
    binaire_npm.write_text("@echo off", encoding="utf-8")

    # Simuler dossier_appdata retournant tmp_path
    monkeypatch.setattr(CLI, "dossier_appdata", lambda: tmp_path)

    # Simuler shutil.which verifiant le dossier npm passe en path
    def fake_which(cmd, path=None):
        if cmd == "opencode" and path and str(dossier_npm) in path:
            return str(binaire_npm)
        return None

    monkeypatch.setattr(CLI.shutil, "which", fake_which)
    import nokido_opencode_web
    monkeypatch.setattr(nokido_opencode_web.shutil, "which", fake_which)

    cmd = CLI._resolve_cmd("opencode")
    assert cmd == [str(binaire_npm), "acp"]


def test_resolution_opencode_via_path_si_absent_appdata(monkeypatch):
    """Si absent de AppData npm, opencode est resolu via le PATH."""
    monkeypatch.setattr(CLI, "dossier_appdata", lambda: None)
    binaire_path = r"C:\global\npm\opencode.cmd"

    def fake_which(cmd, path=None):
        if cmd == "opencode":
            return binaire_path
        return None

    monkeypatch.setattr(CLI.shutil, "which", fake_which)
    import nokido_opencode_web
    monkeypatch.setattr(nokido_opencode_web.shutil, "which", fake_which)

    cmd = CLI._resolve_cmd("opencode")
    assert cmd == [binaire_path, "acp"]


def test_resolution_opencode_introuvable_commande_inchangee(monkeypatch):
    """Quand introuvable : commande ['opencode', 'acp'] inchangee, echec LISIBLE,
    aucun repli vers agy.exe ou gemini."""
    monkeypatch.setattr(CLI, "dossier_appdata", lambda: None)
    monkeypatch.setattr(CLI.shutil, "which", lambda *a, **k: None)
    import nokido_opencode_web
    monkeypatch.setattr(nokido_opencode_web.shutil, "which", lambda *a, **k: None)

    cmd = CLI._resolve_cmd("opencode")
    assert cmd == ["opencode", "acp"]
    # Invariant de souverainete : pas de repli sur un autre binaire
    assert "agy" not in cmd[0]
    assert "gemini" not in cmd[0]


def test_surcharge_opencode_acp_cmd(monkeypatch):
    """OPENCODE_ACP_CMD (JSON liste) surcharge la commande resolue."""
    cible = [r"D:\tools\custom_opencode.exe", "acp", "--custom-flag"]
    monkeypatch.setenv("OPENCODE_ACP_CMD", json.dumps(cible))

    cmd = CLI._resolve_cmd("opencode")
    assert cmd == cible


def test_surcharge_opencode_acp_cmd_invalide_ignoree(monkeypatch):
    """Une valeur OPENCODE_ACP_CMD non JSON valide est ignoree silencieusement."""
    monkeypatch.setenv("OPENCODE_ACP_CMD", "invalid json list {")
    monkeypatch.setattr(CLI, "dossier_appdata", lambda: None)
    monkeypatch.setattr(CLI.shutil, "which", lambda *a, **k: None)

    cmd = CLI._resolve_cmd("opencode")
    assert cmd == ["opencode", "acp"]


# ==============================================================================
# 2. PROPAGATION DE L'ENVIRONNEMENT PAR INSTANCE SANS FUITE
# ==============================================================================

def test_env_propage_au_popen_sans_fuiter_dans_os_environ(monkeypatch):
    """L'env passe a ACPClient est propage a Popen sans modifier os.environ."""
    monkeypatch.setattr(CLI.subprocess, "Popen", FakePopen)

    cle_test = "NOKIDO_ACP_OPENCODE_TEST_ENV"
    assert cle_test not in os.environ

    client = CLI.ACPClient(cmd=["opencode", "acp"], agent="opencode", env={cle_test: "valeur_secrete_42"})
    client.start()
    try:
        assert len(FakePopen.instances) == 1
        pop = FakePopen.instances[0]
        env_enfant = pop.kwargs.get("env")
        assert env_enfant is not None
        assert env_enfant.get(cle_test) == "valeur_secrete_42"
        # L'env enfant herite aussi des variables de base comme PATH si presentes
        if "PATH" in os.environ:
            assert env_enfant.get("PATH") == os.environ["PATH"]

        # Invariant absolu : aucune pollution d'os.environ du parent
        assert cle_test not in os.environ
    finally:
        client.close()


def test_sans_env_comportement_inchange(monkeypatch):
    """Sans env (defaut None), Popen ne recoit aucun dictionnaire env modifie."""
    monkeypatch.setattr(CLI.subprocess, "Popen", FakePopen)

    copie_avant = dict(os.environ)
    client = CLI.ACPClient(cmd=["opencode", "acp"], agent="opencode")
    assert client.env is None

    client.start()
    try:
        assert len(FakePopen.instances) == 1
        pop = FakePopen.instances[0]
        assert pop.kwargs.get("env") is None
        assert dict(os.environ) == copie_avant
    finally:
        client.close()


# ==============================================================================
# 3. GARDE DE PROTOCOLE : UN SEUL PROMPT A LA FOIS PAR SESSION
# ==============================================================================

def test_second_prompt_sur_session_occupee_refuse(monkeypatch):
    """Un prompt sur une session deja occupee est immediatement refuse avec un message clair."""
    monkeypatch.setattr(CLI.subprocess, "Popen", FakePopen)

    client = CLI.ACPClient(cmd=["opencode", "acp"], agent="opencode")
    client.start()

    prompt_en_cours = threading.Event()
    autoriser_fin = threading.Event()

    def fake_request(method, params, timeout=None):
        if method == "session/prompt":
            prompt_en_cours.set()
            autoriser_fin.wait(timeout=5.0)
            return {"stopReason": "end_turn"}
        return {}

    monkeypatch.setattr(client, "request", fake_request)

    session_id = "session_opencode_alpha"
    thread_prompt1 = threading.Thread(
        target=lambda: client.prompt(session_id, "premier prompt"),
        daemon=True,
    )
    thread_prompt1.start()

    # Attendre que le 1er prompt soit activement en cours
    assert prompt_en_cours.wait(timeout=2.0)
    assert client.is_session_busy(session_id)

    # Tentative d'un 2e prompt sur la session occupee -> refus cote client
    with pytest.raises((RuntimeError, CLI.SessionBusyError)) as exc_info:
        client.prompt(session_id, "second prompt concurrent")

    err_msg = str(exc_info.value).lower()
    assert "occupee" in err_msg
    assert "un seul prompt" in err_msg
    assert session_id in str(exc_info.value)

    # Une AUTRE session n'est pas bloquee par l'occupation de session_opencode_alpha
    assert not client.is_session_busy("session_opencode_beta")

    # Terminer le premier prompt
    autoriser_fin.set()
    thread_prompt1.join(timeout=2.0)
    assert not thread_prompt1.is_alive()

    # Apres liberation, un prompt sequentiel sur la session est desormais autorise
    assert not client.is_session_busy(session_id)
    rep = client.prompt(session_id, "nouveau prompt sequentiel")
    assert rep["stopReason"] == "end_turn"

    client.close()
    assert not client.is_session_busy(session_id)
