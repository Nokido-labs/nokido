"""NR 30/10 : CLAUDE_HEADLESS sur la connexion Max « en attendant » le quota API (decision owner).

Mesure : `claude -p` (agent claude_api) -> « Credit balance is too low » en 0,3 s (job_bc5c454e) : le credit promo de la
cle API est epuise, la surface etait morte jusqu'au 01/11. Le repli Max existant (`repli_connexion_max`) ne joue que
cle ABSENTE ; ici la cle est presente mais sans credit. Interrupteur versionne `forcer_connexion_max` : la cle est
retiree de l'environnement du SEUL enfant claude_api. Defaut faux ; fichier illisible = faux (UNKNOWN n'est pas OUI).
"""
import json
import types

import pytest

from nokido_agent.app import forge_cli_harness as H


@pytest.fixture(autouse=True)
def _capture_env(monkeypatch):
    """L'env vit dans le backend de CliHarness : on capture celui que harness_for TRANSMET (sans lancer de process)."""
    monkeypatch.setattr(H, "CliHarness", lambda cmd, cwd=None, env=None, backend="auto", stdin_devnull=False:
                        types.SimpleNamespace(env=dict(env or {})))


def _harness(monkeypatch, tmp_path, cfg):
    f = tmp_path / "claude_headless.json"
    f.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(H, "_CONFIG_CLAUDE_HEADLESS", f)
    monkeypatch.setattr(H, "jeton_mcp", lambda agent: {"ANTHROPIC_API_KEY": "factice"})
    return H.harness_for("claude_api", args=["-p"], binaire="claude.exe")


def _env(h):
    return h.env


def test_max_force_retire_la_cle_du_seul_enfant(monkeypatch, tmp_path):
    h = _harness(monkeypatch, tmp_path, {"repli_connexion_max": False, "forcer_connexion_max": True})
    assert "ANTHROPIC_API_KEY" not in _env(h)


def test_par_defaut_la_cle_reste(monkeypatch, tmp_path):
    h = _harness(monkeypatch, tmp_path, {"repli_connexion_max": False})
    assert _env(h).get("ANTHROPIC_API_KEY") == "factice"


def test_autre_agent_jamais_touche(monkeypatch, tmp_path):
    f = tmp_path / "claude_headless.json"
    f.write_text(json.dumps({"forcer_connexion_max": True}), encoding="utf-8")
    monkeypatch.setattr(H, "_CONFIG_CLAUDE_HEADLESS", f)
    monkeypatch.setattr(H, "jeton_mcp", lambda agent: {"ANTHROPIC_API_KEY": "factice"})
    h = H.harness_for("vibe", args=[], binaire="vibe.exe")
    assert _env(h).get("ANTHROPIC_API_KEY") == "factice"
