"""NR -- une reponse VIDE n'empoisonne pas le fil de conversation.

MESURE 2026-09-26 (swarm P1 bis, sandbox/debat_auto_amelioration/swarm2_brut.json) : 4 modeles
OpenRouter gratuits rendent une reponse VIDE au tour 1 (modeles a raisonnement, budget epuise), puis
TOUS rendent `400 Provider returned error` aux tours 2 et 3 ; nemotron-3-ultra : OK, VIDE, puis 400.
Cause : `ask()` ajoutait au fil un tour assistant de contenu vide -- un fournisseur refuse ensuite
tout le fil. Un echange sans reponse ne s'ecrit pas dans le fil (ni la question, sinon deux tours
utilisateur se suivraient).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_agent_proxy as ap  # noqa: E402
from nokido_agent.app import forge_network_logger as nl  # noqa: E402


class _Fournisseur:
    model = "modele-test"
    display_name = "test"
    api_key_env = "CLE_TEST"

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.fils_recus = []

    def is_available(self):
        return True

    async def ask_tracked(self, thread_messages=None, **_k):
        self.fils_recus.append(list(thread_messages or []))
        return self.reponses.pop(0)


@pytest.fixture
def four(monkeypatch):
    monkeypatch.setattr(nl, "log_cloud_out", lambda *a, **k: None)
    monkeypatch.setattr(nl, "log_cloud_in", lambda *a, **k: None)
    monkeypatch.setattr(ap, "_emit", lambda *a, **k: None)
    f = _Fournisseur(["", "deuxieme"])
    monkeypatch.setattr(ap, "get_provider", lambda name: f)
    return f


def test_une_reponse_vide_n_entre_pas_dans_le_fil(four):
    fil = "fil_test_vide"
    ap._THREADS.pop(fil, None)
    asyncio.run(ap.ask("x", "question 1", thread_id=fil, rag_context=False, raw=True))
    assert ap._THREADS.get(fil, []) == []
    asyncio.run(ap.ask("x", "question 2", thread_id=fil, rag_context=False, raw=True))
    assert all(m.get("content") for m in four.fils_recus[1])      # aucun tour vide envoye
    assert [m["role"] for m in ap._THREADS[fil]] == ["user", "assistant"]
