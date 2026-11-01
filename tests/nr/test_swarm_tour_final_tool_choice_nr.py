"""NR -- le tour final du swarm pointeur reste sur la voie UNIQUE (outils declares, tool_choice="none").

Recette reelle 28/10 23 h 23 : le tour final partait with_tools=False, donc par la voie aplatie du routeur (autre
transport, historique d'outils ecrase en texte) ; Ollama Cloud y rendait un contenu vide, et le motif affiche
(finish_reason=tool_calls) etait un RESTE de l'etat de la sonde du tour precedent. Faux hf, aucun reseau."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_cli_swarm as S  # noqa: E402
from app import forge_handoff as fh  # noqa: E402


def lire_fichier(chemin: str) -> str:
    """Lit un fichier."""
    return "contenu"


class _FauxHf:
    def __init__(self):
        self.appels = []

    def _llm_round(self, agent, messages, with_tools):
        self.appels.append({"with_tools": with_tools, "tool_choice": getattr(agent, "tool_choice", "auto"),
                            "outils": len(agent.tools)})
        if len(self.appels) == 1:
            return {"message": {"content": ""}, "tool_calls": [
                {"id": "c1", "function": {"name": "lire_fichier", "arguments": '{"chemin": "x"}'}}],
                "_router_meta": {"ok": True, "tools": True}}
        return {"message": {"content": "reponse fondee"}, "_router_meta": {"ok": True, "tools": True}}


def test_tour_final_garde_les_outils_avec_tool_choice_none():
    hf = _FauxHf()
    agent = fh.Agent(name="m", instructions="i", tools=[lire_fichier], text_handoff=False)
    S._boucle_membre(hf, agent, "lis x", max_tours=2)
    assert len(hf.appels) == 2
    premier, final = hf.appels
    assert premier == {"with_tools": True, "tool_choice": "auto", "outils": 1}
    assert final == {"with_tools": True, "tool_choice": "none", "outils": 1}  # voie unique, appel interdit
    assert getattr(agent, "tool_choice", "auto") == "auto"  # l'agent d'origine n'est pas modifie


def test_sonde_transmet_tool_choice(monkeypatch):
    import forge_tool_call_probe as P
    vus = {}

    def fausse_requete(*a, **k):
        vus["charge"] = next((x for x in list(a) + list(k.values()) if isinstance(x, (bytes, bytearray))), b"")
        raise OSError("coupe ici")

    monkeypatch.setattr(P, "requete", fausse_requete)
    try:
        P.appeler_avec_outils("http://x", "", "m", [{"role": "user", "content": "q"}], [], tool_choice="none")
    except OSError:
        pass
    assert b'"tool_choice": "none"' in vus["charge"]
