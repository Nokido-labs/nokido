"""NR -- la veille declenchee par la soif utilise un modele VIVANT, choisi par le routeur.

MESURE 2026-09-25 (GET api.groq.com/openai/v1/models, 11 modeles) : `llama3-8b-8192`, code EN DUR
dans forge_research_agent._groq, n'est plus servi. veille_on_gap forcait provider="groq" : chaque
veille lancee sur un manque aurait echoue au premier appel. Le routeur, lui, avait remplace les
modeles Groq morts le 2026-08-18 (slot groq_fast) -- le JUMEAU de research_agent n'avait pas suivi.
Regle : le modele vient du routeur (source unique), et la veille passe par ses chaines
strategy/synthesis (sante, bascule, pare-feu) plutot que par un fournisseur force.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_epistemic_veille as ev  # noqa: E402
from nokido_agent.app import forge_research_agent as fra  # noqa: E402


def test_la_veille_passe_par_le_routeur_par_defaut():
    assert inspect.signature(ev.veille_on_gap).parameters["provider"].default == "auto"


def test_aucun_modele_groq_code_en_dur():
    src = (RACINE / "app" / "forge_research_agent.py").read_text(encoding="utf-8")
    assert "llama3-8b-8192" not in src


def test_le_modele_groq_vient_du_slot_du_routeur():
    from nokido_agent.app.forge_llm_router import get_router
    attendu = get_router().slot("groq_fast").config["models"][0].split("groq/", 1)[-1]
    assert fra._modele_groq() == attendu


def test_l_appel_groq_emporte_le_modele_du_routeur(monkeypatch):
    envoye = {}

    class _Rep:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        envoye.update(json.loads(req.data))
        return _Rep()
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr(fra, "_gs", lambda k: "cle-de-test")
    from nokido_agent.app import forge_key_rotation as fkr
    monkeypatch.setattr(fkr, "resolve", lambda name: (False, None))
    assert fra._groq("bonjour") == "ok"
    assert envoye["model"] == fra._modele_groq()
