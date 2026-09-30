"""NR — vascularisation du joint vers GOAP : annotation_preference (fiche_capability_graph_joint).

Le planificateur PREFERE les methodes EPROUVEES par l'usage en trajectoire, sans jamais s'y restreindre.
Invariants :
- une methode planifiable a SUCCES effectifs en trajectoire est NOMMEE (avec son compte de succes) ;
- une methode TENTEE sans succes (taux 0) n'est PAS prouvee (une abstention n'est pas un acte) ;
- une methode prouvee mais HORS des methodes planifiables n'est jamais nommee ;
- sans preuve, le suffixe est vide (prompt inchange = comportement actuel preserve) ;
- c'est une PREFERENCE : le suffixe le dit explicitement, aucune methode n'est retiree.

Hermetique : import nu depuis tools, aucun DB, aucun reseau, stats injectees.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_capability_crosswalk import annotation_preference  # noqa: E402
from nokido_agent.app.forge_goap import decompose_goal, invalidate_plan_cache  # noqa: E402

_ALLOWED = {"run_python": {"ring": 1}, "web_search": {"ring": 2}, "notify": {"ring": 2}, "embed": {"ring": 2}}
_STATS = {
    "run_python": {"count": 24, "success_rate": 1.0},   # prouve fort
    "web_search": {"count": 32, "success_rate": 0.75},  # prouve (32*0.75 = 24 succes)
    "notify": {"count": 1, "success_rate": 0.0},        # tente, jamais reussi -> pas prouve
    "rag_search": {"count": 9, "success_rate": 1.0},    # prouve MAIS hors methods_available
}
_DISPO = ["run_python", "web_search", "notify", "embed"]


def test_methode_prouvee_nommee_avec_ses_succes():
    s = annotation_preference(_DISPO, _ALLOWED, _STATS)
    assert "run_python(24)" in s
    assert "web_search(24)" in s


def test_methode_tentee_sans_succes_non_prouvee():
    assert "notify" not in annotation_preference(_DISPO, _ALLOWED, _STATS)


def test_methode_hors_planifiables_jamais_nommee():
    assert "rag_search" not in annotation_preference(_DISPO, _ALLOWED, _STATS)


def test_sans_preuve_prompt_inchange():
    assert annotation_preference(_DISPO, _ALLOWED, {}) == ""
    assert annotation_preference(_DISPO, _ALLOWED, {"notify": {"count": 3, "success_rate": 0.0}}) == ""


def test_est_une_preference_pas_une_restriction():
    s = annotation_preference(_DISPO, _ALLOWED, _STATS)
    assert isinstance(s, str)
    assert "ne restreint pas" in s


# --- Chemin REEL : l'enrichissement traverse decompose_goal, pas seulement la fonction pure ---
# Regression 2026-09-27 : le bloc d'enrichissement reassignait `_t` (alias de `import time as _t`)
# a une str -> la boucle de retry cassait sur `_t.time()` ('str' object has no attribute 'time').
# Le test unitaire de annotation_preference passait pendant que le chemin reel mourait : un NR
# emprunte le POINT D'ENTREE reel (RULES_SHARED, table des reflexes : check() vs --check).

_PLAN_FAKE = json.dumps({"goal": "t", "subgoals": [
    {"description": "chercher", "actions": [{"method": "rag_search", "params": {"q": "x"}}]}]})


async def _fake_llm(prompt, system):
    return _PLAN_FAKE


def _decompose_avec_flag(flag):
    import asyncio
    import os
    prev = os.environ.get("LAFORGE_GOAP_PREUVE")
    os.environ["LAFORGE_GOAP_PREUVE"] = flag
    try:
        invalidate_plan_cache()
        return asyncio.run(decompose_goal("objectif ouvert de test flag %s" % flag,
                                          ring_max=2, llm_call_fn=_fake_llm))
    finally:
        if prev is None:
            os.environ.pop("LAFORGE_GOAP_PREUVE", None)
        else:
            os.environ["LAFORGE_GOAP_PREUVE"] = prev
        invalidate_plan_cache()


def test_flag_on_ne_casse_pas_le_chemin_reel():
    # LE garde de non-regression : enrichissement ACTIF, le plan se construit sans lever.
    plan = _decompose_avec_flag("1")
    assert plan is not None
    assert len(plan.subgoals) >= 1


def test_flag_off_chemin_reel_ok():
    # Controle : sans enrichissement, comportement inchange.
    plan = _decompose_avec_flag("0")
    assert plan is not None
    assert len(plan.subgoals) >= 1
