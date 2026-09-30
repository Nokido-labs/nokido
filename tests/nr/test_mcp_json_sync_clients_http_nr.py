# -*- coding: utf-8 -*-
"""NR -- apres une rotation, la synchro rafraichit AUSSI Gemini, Antigravity, VS Code natif, Copilot.

Mesure du 2026-09-28 (recensement des copies hors coffre apres la rotation des FORGE_TOKEN_*) :
Gemini CLI (`~/.gemini/settings.json`), Antigravity (`~/.gemini/config/mcp_config.json`) et
VS Code natif (`Code/User/mcp.json`) portaient des jetons MORTS -- 401. Aucun outil ne les
rafraichissait : `forge_vscode_mcp_sync` garde volontairement le jeton existant (« ne casse
jamais un addon qui marche ») et renvoie la rotation a `forge_mcp_json_sync`, qui ne couvrait
que Claude Code. Deux formes en plus : VS Code range ses serveurs sous `servers` (pas
`mcpServers`), et deux configs portent l'ancien en-tete `LaForge-Agent-Name` (encore reconnu
par le hub). Et sous SYSTEM, `Path.home()` n'est pas le dossier de l'owner.

Contrat : `_patch_config` lit `mcpServers` OU `servers`, et l'agent dans `X-Agent-Name` OU
`LaForge-Agent-Name` ; les serveurs etrangers ne sont pas touches ; chemin reel main() avec
--client : --check voit le perime, la synchro ecrit, --check repasse a 0. Valeurs factices.
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


def _module(monkeypatch):
    mod = importlib.import_module("forge_mcp_json_sync")
    monkeypatch.setattr(mod, "_resolve_token", lambda agent: f"neuf-{agent}")
    monkeypatch.setattr(mod, "vault_available", lambda: True)
    return mod


def _vscode():
    return {"servers": {
        "laforge": {"type": "http", "url": URL,
                    "headers": {"Authorization": "Bearer mort", "LaForge-Agent-Name": "VSCODE"}},
        "MCP_DOCKER": {"command": "docker", "args": ["mcp", "gateway", "run"]},
    }}


def _antigravity():
    return {"mcpServers": {"laforge-sovereign-hub": {
        "serverUrl": URL, "headers": {"Authorization": "Bearer mort", "LaForge-Agent-Name": "ANTIGRAVITY"}}}}


def test_servers_de_vscode_et_ancien_en_tete_sont_couverts(monkeypatch):
    mod = _module(monkeypatch)
    cfg, changes = mod._patch_config(_vscode())
    assert cfg["servers"]["laforge"]["headers"]["Authorization"] == "Bearer neuf-VSCODE"
    assert cfg["servers"]["MCP_DOCKER"] == {"command": "docker", "args": ["mcp", "gateway", "run"]}
    assert ("laforge", "PATCHED") in changes
    cfg, changes = mod._patch_config(_antigravity())
    assert cfg["mcpServers"]["laforge-sovereign-hub"]["headers"]["Authorization"] == "Bearer neuf-ANTIGRAVITY"


def test_les_chemins_par_defaut_sont_ceux_de_l_owner(monkeypatch):
    mod = _module(monkeypatch)
    owner = ROOT.parent.parent
    assert mod.CLAUDE_JSON == owner / ".claude.json"
    assert all(str(p).startswith(str(owner)) for p in mod.CLIENTS_HTTP)
    noms = {p.name for p in mod.CLIENTS_HTTP}
    assert {"settings.json", "mcp_config.json", "mcp.json"} <= noms


def test_le_point_d_entree_resynchronise_les_clients(monkeypatch, tmp_path, capsys):
    mod = _module(monkeypatch)
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    vs, ag = tmp_path / "mcp.json", tmp_path / "mcp_config.json"
    vs.write_text(json.dumps(_vscode()), encoding="utf-8")
    ag.write_text(json.dumps(_antigravity()), encoding="utf-8")
    argv = ["forge_mcp_json_sync.py", "--path", str(mcp), "--claude-json", str(tmp_path / "absent.json"),
            "--client", str(vs), "--client", str(ag)]
    monkeypatch.setattr(sys, "argv", argv + ["--check"])
    assert mod.main() == 1
    monkeypatch.setattr(sys, "argv", argv)
    assert mod.main() == 0
    assert json.loads(vs.read_text(encoding="utf-8"))["servers"]["laforge"]["headers"]["Authorization"] == "Bearer neuf-VSCODE"
    assert "MCP_DOCKER" in json.loads(vs.read_text(encoding="utf-8"))["servers"]
    assert json.loads(ag.read_text(encoding="utf-8"))["mcpServers"]["laforge-sovereign-hub"]["headers"]["Authorization"] == "Bearer neuf-ANTIGRAVITY"
    monkeypatch.setattr(sys, "argv", argv + ["--check"])
    assert mod.main() == 0
    capsys.readouterr()
