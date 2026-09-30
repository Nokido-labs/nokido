# -*- coding: utf-8 -*-
"""NR -- la synchro des jetons MCP couvre AUSSI `~/.claude.json` (incident du 2026-09-28).

Mesure du jour : apres la rotation des `FORGE_TOKEN_*` par le semeur, Claude Code restait en
401 meme apres `forge_mcp_json_sync`. Le serveur hub etait declare TROIS fois : `.mcp.json`
(portee projet, le seul fichier que la synchro ouvrait) et deux fois dans `~/.claude.json`
(portee LOCALE du projet et portee UTILISATEUR). La portee locale passe AVANT `.mcp.json` :
le client envoyait l'ancien jeton, et la synchro disait « en phase ».

Et la declaration UTILISATEUR n'avait pas d'en-tete `X-Agent-Name` : la synchro la classait
« transport stdio », ce qui etait faux (c'est du HTTP) -- une entree jamais regardee.

Valeurs de test factices ; aucun secret.
"""
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

URL = "http://127.0.0.1:8766/mcp"


def _hub(agent="CLAUDE", jeton="vieux"):
    h = {"Authorization": f"Bearer {jeton}"}
    if agent:
        h["X-Agent-Name"] = agent
    return {"type": "http", "url": URL, "headers": h}


def _claude_json():
    return {
        "numStartups": 3,
        "mcpServers": {"laforge-sovereign-hub": _hub()},
        "projects": {
            "C:/Users/x/Script python IA": {"mcpServers": {"laforge-sovereign-hub": _hub()},
                                            "allowedTools": []},
            "C:/autre": {"allowedTools": []},
        },
    }


def _module(monkeypatch):
    mod = importlib.import_module("forge_mcp_json_sync")
    monkeypatch.setattr(mod, "_resolve_token", lambda agent: "neuf" if agent == "CLAUDE" else None)
    monkeypatch.setattr(mod, "vault_available", lambda: True)
    return mod


def test_portees_utilisateur_et_locale_sont_resynchronisees(monkeypatch):
    mod = _module(monkeypatch)
    cfg, changes = mod._patch_claude_json(_claude_json())
    assert cfg["mcpServers"]["laforge-sovereign-hub"]["headers"]["Authorization"] == "Bearer neuf"
    local = cfg["projects"]["C:/Users/x/Script python IA"]["mcpServers"]["laforge-sovereign-hub"]
    assert local["headers"]["Authorization"] == "Bearer neuf"
    patches = [nom for nom, action in changes if action == "PATCHED"]
    assert len(patches) == 2
    assert any("utilisateur" in n for n in patches) and any("local" in n for n in patches)
    # le reste du fichier n'est pas touche
    assert cfg["numStartups"] == 3 and cfg["projects"]["C:/autre"] == {"allowedTools": []}


def test_http_sans_agent_est_dit_et_pas_pris_pour_du_stdio(monkeypatch):
    mod = _module(monkeypatch)
    _cfg, changes = mod._patch_config({"mcpServers": {"laforge-sovereign-hub": _hub(agent=None)}})
    (nom, action), = changes
    assert action.startswith("SANS_AGENT"), action
    assert "stdio" not in action


def test_le_point_d_entree_couvre_claude_json(monkeypatch, tmp_path, capsys):
    mod = _module(monkeypatch)
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"laforge-sovereign-hub": _hub()}}), encoding="utf-8")
    cj = tmp_path / ".claude.json"
    cj.write_text(json.dumps(_claude_json()), encoding="utf-8")
    argv = ["forge_mcp_json_sync.py", "--path", str(mcp), "--claude-json", str(cj)]

    monkeypatch.setattr(sys, "argv", argv + ["--check"])
    assert mod.main() == 1, "le --check doit voir les portees perimees de ~/.claude.json"

    monkeypatch.setattr(sys, "argv", argv)
    assert mod.main() == 0
    relu = json.loads(cj.read_text(encoding="utf-8"))
    assert relu["mcpServers"]["laforge-sovereign-hub"]["headers"]["Authorization"] == "Bearer neuf"
    local = relu["projects"]["C:/Users/x/Script python IA"]["mcpServers"]["laforge-sovereign-hub"]
    assert local["headers"]["Authorization"] == "Bearer neuf"
    assert relu["numStartups"] == 3

    monkeypatch.setattr(sys, "argv", argv + ["--check"])
    assert mod.main() == 0
    capsys.readouterr()
