"""NR 18/10 -- la capsule d'autopsie est REINJECTEE au tour suivant (chantier 2 du takehome, pas 3).

Le juge rend une capsule (9998e6000) ; sans reinjection, le producteur (MutationCycle.run_cycle) repartait a
l'aveugle. Contrat : run_cycle accepte `capsule_precedente` et la place dans le prompt, et son resultat
REMONTE la capsule du juge pour que l'appelant la repasse.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_self_mutation as SM  # noqa: E402


class _Garde:
    rapport: list = []

    def valider(self, original, mute):
        return True, "ok"

    def diff(self, original, mute):
        return ""


def _cycle(prompts):
    def llm(prompt):
        prompts.append(prompt)
        return "```python\nx = 1\n```"
    return SM.MutationCycle(appel_llm=llm, guard=_Garde())


def test_la_capsule_precedente_entre_dans_le_prompt(tmp_path):
    cible = tmp_path / "m.py"
    cible.write_text("x = 0\n", encoding="utf-8")
    prompts = []
    _cycle(prompts).run_cycle(str(cible), "accelerer", dry_run=True,
                              capsule_precedente="capsule c1 : DEGRADE\nperdu b : E   assert 1 == 2")
    assert "capsule c1 : DEGRADE" in prompts[0] and "assert 1 == 2" in prompts[0]


def test_sans_capsule_le_prompt_est_inchange(tmp_path):
    cible = tmp_path / "m.py"
    cible.write_text("x = 0\n", encoding="utf-8")
    prompts = []
    _cycle(prompts).run_cycle(str(cible), "accelerer", dry_run=True)
    assert "autopsie" not in prompts[0].lower()


def test_le_resultat_remonte_la_capsule_du_juge(tmp_path, monkeypatch):
    cible = tmp_path / "m.py"
    cible.write_text("x = 0\n", encoding="utf-8")
    juge = types.ModuleType("nokido_agent.app.forge_mutation_judge")
    juge.juger_module_avec_gain = lambda rel, mute, tests: {"verdict": "SURVIT_SANS_GAIN", "capsule": "capsule m.py : X"}
    juge.perimetre_mesure = lambda rel: []
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_mutation_judge", juge)
    r = _cycle([]).run_cycle(str(cible), "accelerer", dry_run=False)
    assert r["capsule"] == "capsule m.py : X"
