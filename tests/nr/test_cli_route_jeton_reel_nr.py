"""tests/nr/test_cli_route_jeton_reel_nr.py — NR jeton réel pour forge_cli_route.

Contrat :
- Plus de jeton 'laforge-local' en dur dans INGRESS ni transmis aux enfants.
- Obtention d'un jeton court (CapabilityToken) ou fallback coffre (FORGE_TOKEN_<AGENT> / MASTER_TOKEN).
- Injection du jeton dans l'environnement du sous-processus enfant seulement (jamais dans os.environ ni journalisé).
- Si jeton indisponible : arrêt avec message clair, code retour != 0, pas de repli sur 'laforge-local'.
- Aucun accès réseau ni CLI lancé réellement (subprocess.run mocké).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.tools import forge_cli_route as cr


def test_plus_aucun_laforge_local_dans_ingress():
    """Vérifie que 'laforge-local' a été totalement retiré des définitions INGRESS."""
    for cli, (var, val, extra) in cr.INGRESS.items():
        if extra:
            for k, v in extra.items():
                assert "laforge-local" not in str(v).lower(), f"Jeton factice 'laforge-local' trouvé dans INGRESS[{cli}][{k}]"


def test_cmd_launch_claude_injecte_jeton_reel_enfant_seulement(tmp_path, monkeypatch):
    """Vérifie qu'un vrai jeton est injecté dans env enfant (ANTHROPIC_AUTH_TOKEN) et non dans os.environ."""
    f = tmp_path / "cli_route.json"
    f.write_text(json.dumps({"enabled": True, "clis": {"claude": True}}), encoding="utf-8")
    monkeypatch.setattr(cr, "STATE", f)
    monkeypatch.setattr(cr, "_hub_up", lambda: True)

    fake_token = "cap.header_part.signature_part"
    monkeypatch.setattr(cr, "_obtenir_jeton_auth", lambda cli: fake_token)

    captured_env = {}

    def fake_run(cmd, env=None, cwd=None):
        nonlocal captured_env
        captured_env = dict(env or {})
        class Ret:
            returncode = 0
        return Ret()

    monkeypatch.setattr("subprocess.run", fake_run)

    # Nettoyage préalable os.environ
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    rc = cr.cmd_launch("claude", ["--help"])
    assert rc == 0
    assert captured_env.get("ANTHROPIC_AUTH_TOKEN") == fake_token
    assert captured_env.get("ANTHROPIC_BASE_URL") == "http://127.0.0.1:7776"
    assert "ANTHROPIC_AUTH_TOKEN" not in os.environ


def test_cmd_launch_jeton_indisponible_arret_sans_repli(tmp_path, monkeypatch, capsys):
    """Si jeton indisponible : arrêt avec message clair, rc != 0, et aucun repli 'laforge-local'."""
    f = tmp_path / "cli_route.json"
    f.write_text(json.dumps({"enabled": True, "clis": {"claude": True}}), encoding="utf-8")
    monkeypatch.setattr(cr, "STATE", f)
    monkeypatch.setattr(cr, "_hub_up", lambda: True)

    # Simulation d'un échec d'obtention de jeton
    monkeypatch.setattr(cr, "_obtenir_jeton_auth", lambda cli: None)

    run_called = False
    def fake_run(*args, **kwargs):
        nonlocal run_called
        run_called = True

    monkeypatch.setattr("subprocess.run", fake_run)

    rc = cr.cmd_launch("claude", ["--help"])
    assert rc != 0
    assert not run_called, "subprocess.run ne doit pas être appelé sans jeton valide"

    out = capsys.readouterr().out
    assert "jeton" in out.lower() or "auth" in out.lower()
    assert "laforge-local" not in out.lower()
