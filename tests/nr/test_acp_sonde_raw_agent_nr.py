"""NR 28/10 : la sonde `--raw` du client ACP lance l'agent DEMANDE (et le cwd demande), pas gemini par defaut.

Mesure : `forge_acp_client.py --raw --agent claude` a lance `gemini --acp` -- main() lisait --agent mais appelait
`_raw()` sans lui ; la sonde censee diagnostiquer claude a teste un autre CLI.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_acp_client as C  # noqa: E402


def test_raw_recoit_l_agent_et_le_cwd(monkeypatch):
    vu = {}
    monkeypatch.setattr(C, "_raw", lambda agent="gemini", cwd=None, duree=20, prompt=None, options=None:
                        vu.update(agent=agent, cwd=cwd) or 0)
    monkeypatch.setattr(sys, "argv", ["forge_acp_client.py", "--raw", "--agent", "claude", "--cwd", "C:/x"])
    assert C.main() == 0
    assert vu == {"agent": "claude", "cwd": "C:/x"}


def test_raw_recoit_la_duree(monkeypatch):
    """28/10 : 20 s ne suffisaient pas a recevoir la reponse de session/new (30-60 s sous le worker)."""
    vu = {}
    monkeypatch.setattr(C, "_raw", lambda agent="gemini", cwd=None, duree=20, prompt=None, options=None:
                        vu.update(duree=duree) or 0)
    monkeypatch.setattr(sys, "argv", ["forge_acp_client.py", "--raw", "--agent", "claude", "--duree", "120"])
    assert C.main() == 0
    assert vu == {"duree": 120.0}


def test_raw_recoit_les_options_claude(monkeypatch):
    """28/10 economie de tokens : un tour BONJOUR = 54 547 tokens (profil complet). La sonde doit transmettre
    `_meta.claudeCode.options` (settingSources, skills, strictMcpConfig... lus dans sdk.d.ts) a session/new."""
    vu = {}
    monkeypatch.setattr(C, "_raw", lambda agent="gemini", cwd=None, duree=20, prompt=None, options=None:
                        vu.update(options=options) or 0)
    monkeypatch.setattr(sys, "argv", ["forge_acp_client.py", "--raw", "--agent", "claude",
                                      "--options-json", '{"settingSources": [], "skills": []}'])
    assert C.main() == 0
    assert vu == {"options": {"settingSources": [], "skills": []}}


def test_raw_recoit_le_prompt(monkeypatch):
    """28/10 : l'agent claude meurt ~11 s apres session/new, toujours AVANT le 1er prompt ; la seule session
    reussie envoyait son prompt aussitot. La sonde doit pouvoir envoyer un prompt des la reponse a session/new."""
    vu = {}
    monkeypatch.setattr(C, "_raw", lambda agent="gemini", cwd=None, duree=20, prompt=None, options=None:
                        vu.update(prompt=prompt) or 0)
    monkeypatch.setattr(sys, "argv", ["forge_acp_client.py", "--raw", "--agent", "claude", "--prompt", "dis bonjour"])
    assert C.main() == 0
    assert vu == {"prompt": "dis bonjour"}
