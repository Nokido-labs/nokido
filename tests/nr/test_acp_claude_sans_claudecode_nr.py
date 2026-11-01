"""NR 28/10 (recette reelle) : l'agent ACP claude ne recoit jamais CLAUDECODE (garde anti-imbrication de Claude Code).

Mesure : sous NokidoAcpWorker, le CLI sort rc=1 sans stderr 4 s apres session/new. Diff d'environnement
worker/console : le profil est complet ; CLAUDECODE est present (pose par Claude Code, herite jusqu'au worker).
Un claude qui voit CLAUDECODE se croit imbrique dans une autre session et refuse de demarrer.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_acp_client as C  # noqa: E402


def _env_au_lancement(monkeypatch, agent, env=None):
    vu = {}

    class _P:
        def __init__(self, *a, **k):
            vu.update(k.get("env") or {})
            self.stdin = self.stdout = self.stderr = iter(())
            self.pid = 0

        def poll(self):
            return 0

    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(subprocess, "Popen", _P)
    cli = C.ACPClient(cmd=["agent.exe"], agent=agent, env=env)
    cli.start()
    return vu


def test_claude_ne_recoit_pas_claudecode(monkeypatch):
    vu = _env_au_lancement(monkeypatch, "claude")
    assert vu, "un environnement explicite doit etre passe pour pouvoir retirer CLAUDECODE"
    assert "CLAUDECODE" not in vu and "PATH" in {k.upper() for k in vu}


def test_claude_avec_env_fourni_ne_recoit_pas_claudecode(monkeypatch):
    assert "CLAUDECODE" not in _env_au_lancement(monkeypatch, "claude", env={"X": "1"})
