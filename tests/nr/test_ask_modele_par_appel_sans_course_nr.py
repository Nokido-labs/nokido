"""NR -- une surcharge de modele dans `ask()` ne fuit pas vers un appel concurrent (2026-10-13).

`ask()` ecrivait `provider.model = model` sur l'instance PARTAGEE puis la restaurait en `finally`.
Mesure (debat swarm du 13/10, semaphore 6) : nemotron-3-super demande, gemma-4-26b servi ; et la
restauration croisee peut figer un mauvais modele par defaut. Chemin reel : `ask()` lui-meme, avec un
fournisseur factice inscrit comme les autres.
"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

AP = pytest.importorskip("nokido_agent.app.forge_agent_proxy")


class _Lent(AP.Provider):
    name = "nr_lent"
    model = "defaut"
    api_key_env = None

    def __init__(self):
        self.vus = []

    def is_available(self):
        return True

    async def ask(self, message, thread_messages, system_prompt, max_tokens, timeout):
        demande = self.model
        await asyncio.sleep(0.05)          # l'autre appel s'intercale ici
        self.vus.append((message, demande, self.model))
        return "servi par " + self.model


def test_deux_modeles_concurrents_ne_se_melangent_pas(monkeypatch):
    lent = _Lent()
    monkeypatch.setattr(AP, "get_provider", lambda nom: lent if nom == "nr_lent" else None)

    async def deux():
        return await asyncio.gather(
            AP.ask("nr_lent", "A", rag_context=False, model="modele-a", raw=True),
            AP.ask("nr_lent", "B", rag_context=False, model="modele-b", raw=True))
    ra, rb = asyncio.run(deux())
    assert "modele-a" in (ra.get("text") or "") and ra.get("model") == "modele-a", ra
    assert "modele-b" in (rb.get("text") or "") and rb.get("model") == "modele-b", rb
    assert lent.model == "defaut", "le modele par defaut de l'instance partagee a ete modifie"
