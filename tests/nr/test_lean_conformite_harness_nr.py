"""NR — Conformité du code Python aux modèles et théorèmes Lean 4.

Pilote Lean 4 (owner 15/10 : « pilote borné ») : Lean comme ARBITRE d'invariants,
pas comme moteur d'exécution.
Ce test relie directement les deux théorèmes Lean 4 au vrai code Python :
  1. Théorème 1 (« pas de faux succès ») :
     Table de vérité et liste blanche de `app/forge_harness_contract.py`
     (verdict_etape). Aucune étape n'est ACHIEVED si un champ est non prouvé
     (refus, échec, non vérifié, illisible, effet ou preuve manquants).
  2. Théorème 2 (« reprise = mêmes entrées ») :
     Journal durable de `tools/forge_durable_workflow.py` (WorkflowContext.activity).
     Un replay ne rend la sortie que si hash(entrées) == hash(enregistré).
     Sinon levée de WorkflowDivergence : ni replay de l'ancienne valeur, ni ré-exécution.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for zone in ("app", "tools"):
    p = str(ROOT / zone)
    if p not in sys.path:
        sys.path.insert(0, p)

import forge_harness_contract as fhc
from forge_durable_workflow import (
    WorkflowContext,
    WorkflowDivergence,
    WorkflowStore,
    _hash,
)

pytestmark = pytest.mark.timeout(30)


# ==============================================================================
# SECTION 1 : CONFORMITÉ AU THÉORÈME 1 (forge_harness_contract.py)
# Modèle Lean : Formel/HarnessContract.lean
# ==============================================================================

TABLE_CAS_HARNESS = [
    # 1. Nominale blanche : tout prouvé -> ACHIEVED
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="ALLOW",
            observation={"ok": True, "res": 1},
            effet_attendu="file_created",
            effet_observe="EFFECT_OBSERVED",
            preuve="accept",
        ),
        fhc.ACHIEVED,
        "Nominale blanche : tout prouve",
        id="nominale_achieved",
    ),
    # 2. Aucune action émise -> UNKNOWN
    pytest.param(
        dict(action=fhc.UNKNOWN),
        fhc.UNKNOWN,
        "action = UNKNOWN -> non execute",
        id="action_unknown",
    ),
    # 3. Refus DENY mais effet observé -> CONTRADICTION
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="DENY",
            effet_observe="EFFECT_OBSERVED_MUTATION",
        ),
        fhc.CONTRADICTION,
        "DENY + effet observe = contradiction d organes",
        id="deny_contradiction",
    ),
    # 4. Refus DENY et monde inchangé -> REFUSED
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="DENY",
            effet_observe="EFFECT_BLOCKED",
        ),
        fhc.REFUSED,
        "DENY + bloque certifie",
        id="deny_refused_blocked",
    ),
    # 5. Refus DENY et effet indéterminé -> REFUSED
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="DENY",
            effet_observe=fhc.UNKNOWN,
        ),
        fhc.REFUSED,
        "DENY + effet non certifie",
        id="deny_refused_unknown_effect",
    ),
    # 6. Action émise mais rien observé -> REQUESTED
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="ALLOW",
            observation=fhc.UNKNOWN,
        ),
        fhc.REQUESTED,
        "action emise, rien observe",
        id="requested_rien_observe",
    ),
    # 7. Échec observé -> FAILED
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="ALLOW",
            observation={"ok": False, "err": "timeout"},
        ),
        fhc.FAILED,
        "echec explicite observe",
        id="failed_echec_observe",
    ),
    # 8. Observation présente mais ok is None -> INCERTAIN
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="ALLOW",
            observation={"ok": None, "retour": "ambigu"},
        ),
        fhc.INCERTAIN,
        "observation non tranchee",
        id="incertain_non_tranche",
    ),
    # 9. Observation illisible (pas un dict) -> INCERTAIN
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="ALLOW",
            observation="chaine_brute_sans_json",
        ),
        fhc.INCERTAIN,
        "observation illisible",
        id="incertain_illisible",
    ),
    # 10. Manque autorisation (pas ALLOW) -> ACCEPTED (non prouvé)
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation=fhc.UNKNOWN,
            observation={"ok": True},
            effet_attendu="decl",
            effet_observe="EFFECT_OBSERVED",
            preuve="accept",
        ),
        fhc.ACCEPTED,
        "autorisation non ALLOW",
        id="manque_autorisation",
    ),
    # 11. Manque effet observé (pas EFFECT_OBSERVED) -> ACCEPTED (non prouvé)
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="ALLOW",
            observation={"ok": True},
            effet_attendu="decl",
            effet_observe=fhc.UNKNOWN,
            preuve="accept",
        ),
        fhc.ACCEPTED,
        "effet observe absent",
        id="manque_effet_observe",
    ),
    # 12. Manque preuve (preuve != accept) -> ACCEPTED (non prouvé)
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="ALLOW",
            observation={"ok": True},
            effet_attendu="decl",
            effet_observe="EFFECT_OBSERVED",
            preuve="challenge",
        ),
        fhc.ACCEPTED,
        "preuve challenge",
        id="manque_preuve_challenge",
    ),
    # 13. Manque effet attendu (non déclaré) -> ACCEPTED (non prouvé)
    pytest.param(
        dict(
            action={"op": "call"},
            autorisation="ALLOW",
            observation={"ok": True},
            effet_attendu=fhc.UNKNOWN,
            effet_observe="EFFECT_OBSERVED",
            preuve="accept",
        ),
        fhc.ACCEPTED,
        "effet attendu non declare",
        id="manque_effet_attendu",
    ),
]


@pytest.mark.parametrize("kwargs,statut_attendu,desc", TABLE_CAS_HARNESS)
def test_conformite_theoreme1_table_cas(kwargs, statut_attendu, desc):
    """Vérifie que le code Python reproduit exactement chaque cas du modèle Lean."""
    etape = fhc.EtapeContrat(**kwargs)
    v = fhc.verdict_etape(etape)
    assert v["statut"] == statut_attendu, f"Divergence sur {desc} : {v}"


def test_conformite_theoreme1_pas_de_faux_succes_invariant():
    """Vérifie l'invariant du Théorème 1 : ACHIEVED implique que TOUS les champs sont prouvés.

    Si un seul des 6 piliers fait défaut, l'étape ne peut JAMAIS valoir ACHIEVED.
    """
    nominale = dict(
        action={"intent": "run"},
        autorisation="ALLOW",
        observation={"ok": True},
        effet_attendu="modified",
        effet_observe="EFFECT_OBSERVED",
        preuve="accept",
    )
    # 1. Base prouvée -> ACHIEVED
    assert fhc.verdict_etape(fhc.EtapeContrat(**nominale))["statut"] == fhc.ACHIEVED

    # 2. Corollaires d'exclusion : altération de chaque pilier individuel
    altérations = [
        ("action", fhc.UNKNOWN),
        ("autorisation", "DENY"),
        ("autorisation", fhc.UNKNOWN),
        ("observation", {"ok": False}),
        ("observation", {"ok": None}),
        ("observation", fhc.UNKNOWN),
        ("effet_attendu", fhc.UNKNOWN),
        ("effet_observe", "EFFECT_BLOCKED"),
        ("effet_observe", fhc.UNKNOWN),
        ("preuve", "challenge"),
        ("preuve", "retry"),
        ("preuve", "abstain"),
        ("preuve", fhc.UNKNOWN),
    ]
    for champ, valeur_degradee in altérations:
        copie = dict(nominale)
        copie[champ] = valeur_degradee
        v = fhc.verdict_etape(fhc.EtapeContrat(**copie))
        assert v["statut"] != fhc.ACHIEVED, (
            f"Faux succès détecté quand {champ}={valeur_degradee!r} : {v}"
        )


# ==============================================================================
# SECTION 2 : CONFORMITÉ AU THÉORÈME 2 (forge_durable_workflow.py)
# Modèle Lean : Formel/DurableWorkflow.lean
# ==============================================================================

def test_conformite_theoreme2_reprise_memes_entrees(tmp_path):
    """Vérifie le Théorème 2, branche nominale :

    Un replay ne rend la sortie que si les entrées sont identiques.
    L'effet de bord réel n'est PAS ré-exécuté.
    """
    db_path = tmp_path / "test_traces.db"
    store = WorkflowStore(db_path)
    run_id = "run_test_nominal"

    appels_fn = 0

    def activite_side_effect(x: int, y: str):
        nonlocal appels_fn
        appels_fn += 1
        return {"result": x * 2, "label": y.upper()}

    # 1re exécution
    ctx1 = WorkflowContext(store, run_id)
    out1 = ctx1.activity("step_1", activite_side_effect, 21, y="hello")
    assert out1 == {"result": 42, "label": "HELLO"}
    assert appels_fn == 1
    assert ctx1.executed == 1
    assert ctx1.replayed == 0

    # Replay avec EXACTEMENT les mêmes entrées
    ctx2 = WorkflowContext(store, run_id)
    out2 = ctx2.activity("step_1", activite_side_effect, 21, y="hello")
    assert out2 == out1
    assert appels_fn == 1, "L'effet de bord ne doit PAS être ré-exécuté lors d'un replay"
    assert ctx2.executed == 0
    assert ctx2.replayed == 1


def test_conformite_theoreme2_divergence_si_autres_entrees(tmp_path):
    """Vérifie le Théorème 2, branche divergence :

    Si une activité déjà complétée est rappelée avec d'AUTRES entrées :
    -> Levée de WorkflowDivergence
    -> Ni replay de l'ancienne valeur
    -> Ni ré-exécution de la fonction
    """
    db_path = tmp_path / "test_traces.db"
    store = WorkflowStore(db_path)
    run_id = "run_test_divergence"

    appels_fn = 0

    def activite_side_effect(val: int):
        nonlocal appels_fn
        appels_fn += 1
        return f"output_{val}"

    # 1re exécution avec val=10
    ctx1 = WorkflowContext(store, run_id)
    out1 = ctx1.activity("task_alpha", activite_side_effect, 10)
    assert out1 == "output_10"
    assert appels_fn == 1

    hash_initial = _hash([[10], []])

    # Re-run avec val=99 (entrées différentes pour la même clé)
    ctx2 = WorkflowContext(store, run_id)
    with pytest.raises(WorkflowDivergence) as exc_info:
        ctx2.activity("task_alpha", activite_side_effect, 99)

    exc = exc_info.value
    assert exc.run_id == run_id
    assert exc.step_key == "task_alpha"
    assert exc.attendu == hash_initial
    assert exc.recu == _hash([[99], []])
    assert exc.attendu != exc.recu

    # Invariant : aucun appel supplémentaire à la fonction
    assert appels_fn == 1, "Ni replay ni ré-exécution : fn ne doit pas avoir été appelée"
    assert ctx2.replayed == 0
    assert ctx2.executed == 0
