"""NR identites phase 2 : une seule variable d'identite LAFORGE_AGENT (provision, connect, bridge)."""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_ENV = re.compile(r'"env":\s*\{[^}]*\}')


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _env_blocs(rel):
    # Repere par l'agent, plus par le jeton : depuis le 3/11 le bloc env ne porte plus aucun jeton
    # (le pont lit le coffre) -- cf. test_generateurs_clients_sans_jeton_nr.
    return [b for b in _ENV.findall(_src(rel)) if "CLAUDE_DESKTOP" in b]


def test_provision_pose_laforge_agent():
    blocs = _env_blocs("tools/forge_provision_clients.py")
    assert blocs and all('"LAFORGE_AGENT": "CLAUDE_DESKTOP"' in b for b in blocs)


def test_connect_pose_laforge_agent():
    blocs = _env_blocs("tools/forge_connect_clients.py")
    assert blocs and all('"LAFORGE_AGENT": "CLAUDE_DESKTOP"' in b for b in blocs)


def test_bridge_repli_laforge_agent_name():
    tree = ast.parse(_src("tools/mcp_stdio_bridge.py"))
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_AGENT" for t in n.targets):
            code = ast.unparse(n.value)
            assert "LAFORGE_AGENT_NAME" in code
            assert code.index("'LAFORGE_AGENT'") < code.index("LAFORGE_AGENT_NAME")
            return
    raise AssertionError("_AGENT introuvable")
