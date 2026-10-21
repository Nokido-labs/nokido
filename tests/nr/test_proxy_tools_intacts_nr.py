"""NR -- le wrapper garde de `Provider.ask` (persona, firewall, symbiose) ne retire ni n'altere JAMAIS `tools`.

Decision owner 19/10 (principe « valider l'integrite des definitions d'outils apres toute mutation du payload ») :
une reecriture de requete qui perd ou corrompt `tools` desactive en silence les appels de fonction du modele. Mesure
du jour : `_guarded` (app/forge_agent_proxy.py) ne reecrit que `message` et `system_prompt` et passe `*a, **kw` tels
quels -- ce NR fige ce contrat sur le chemin reel (sous-classe de Provider, wrapper pose par __init_subclass__),
y compris quand la symbiose COMPRESSE le message.
"""
from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_agent_proxy as P  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "lire", "parameters": {"type": "object", "properties": {}}}},
         {"type": "function", "function": {"name": "ecrire", "parameters": {"type": "object", "properties": {}}}}]


def test_tools_traversent_le_wrapper_garde_intacts(monkeypatch):
    vus = {}

    class _Temoin(P.Provider):
        name = "temoin_cloud"

        async def ask(self, message, thread_messages, system_prompt, max_tokens, timeout, tools=None,
                      tool_choice=None):
            vus.update(message=message, tools=tools, tool_choice=tool_choice)
            return {"ok": True, "text": "r"}

    monkeypatch.setattr(P, "_firewall_pre", lambda prov, msg, sp: (None, msg, {}))
    monkeypatch.setattr(P, "_firewall_post", lambda resp, m: resp)

    async def _compresse(provider, message):
        return "COMPRESSE " + message[:10]
    monkeypatch.setattr(P.Provider, "_symbiose_pre", staticmethod(_compresse))

    envoyes = copy.deepcopy(TOOLS)
    asyncio.run(_Temoin().ask("x" * 5000, [], "sys", 100, 10, tools=envoyes, tool_choice="auto"))
    assert vus["message"].startswith("COMPRESSE"), "la symbiose doit avoir agi pour que le test ait un sens"
    assert vus["tools"] is envoyes and vus["tools"] == TOOLS and vus["tool_choice"] == "auto"
