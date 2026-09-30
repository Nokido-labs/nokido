#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tests/nr/test_reachability_ledger_nr.py — l'atteignabilite est-elle bien jugee ?

Mesure fondatrice du 2026-08-16 : `forge_lmstudio.py`, `forge_litellm_router.py` et
les 16 modules swarm sont TOUS presents, aucun n'a jamais ete supprime, et pourtant
39 providers declares ne donnent que 17 atteignables. Un fichier present ne prouve
aucune capacite -- d'ou ce registre.

Les etats qui comptent, et ce qui les separe :
  ORPHELIN  vs UNPROVEN  : atteignable par RIEN, vs atteignable sans preuve
  LOST      vs HISTORICALLY_PROVEN : jamais demontre, vs demontre autrefois

Hermetiques : aucun git, aucun reseau, aucun working tree.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


# ── hierarchie de preuve, du plus fort au plus faible ───────────────────────

def test_un_appel_reussi_est_la_preuve_la_plus_forte():
    import forge_reachability_ledger as L

    etat, preuve = L.classer_vivant("run", {"run"}, Counter(), set(), Counter())
    assert etat == "PROVEN" and "socle" in preuve


def test_un_test_qui_le_cite_vaut_preuve():
    import forge_reachability_ledger as L

    etat, _ = L.classer_vivant("axe_sorties", set(), Counter({"axe_sorties": 4}),
                               set(), Counter())
    assert etat == "PROVEN"


def test_expose_sans_preuve_est_signale_comme_tel():
    """Etre offert n'est pas etre demontre -- c'est exactement le piege des providers."""
    import forge_reachability_ledger as L

    etat, _ = L.classer_vivant("lmstudio_native", set(), Counter(),
                               {"lmstudio_native"}, Counter())
    assert etat == "OFFERT_NON_PROUVE"


def test_reference_sans_preuve_reste_atteignable():
    import forge_reachability_ledger as L

    etat, preuve = L.classer_vivant("_slot_local_ready", set(), Counter(), set(),
                                    Counter({"_slot_local_ready": 5}))
    assert etat == "UNPROVEN" and "5 references" in preuve


def test_orphelin_quand_rien_ne_latteint():
    """Une seule occurrence = sa propre definition. Le code existe, aucun chemin
    ne le traverse : c'est le fossile type."""
    import forge_reachability_ledger as L

    etat, _ = L.classer_vivant("fonction_oubliee", set(), Counter(), set(),
                               Counter({"fonction_oubliee": 1}))
    assert etat == "ORPHELIN"


def test_absence_de_test_nest_pas_absence_de_capacite():
    """Consigne owner : ne jamais conclure d'un test manquant a une capacite morte."""
    import forge_reachability_ledger as L

    etat, _ = L.classer_vivant("x", set(), Counter(), set(), Counter({"x": 9}))
    assert etat != "LOST" and etat != "ORPHELIN"


# ── disparus ────────────────────────────────────────────────────────────────

def test_disparu_encore_cite_par_un_test_fut_demontre():
    import forge_reachability_ledger as L

    etat, _ = L.classer_disparu("axe_workflows", Counter({"axe_workflows": 2}))
    assert etat == "HISTORICALLY_PROVEN"


def test_disparu_sans_trace_est_perdu():
    import forge_reachability_ledger as L

    etat, _ = L.classer_disparu("vieux_helper", Counter())
    assert etat == "LOST"


# ── sources : les tests sont une SOURCE, pas du bruit ───────────────────────

def test_les_fichiers_de_test_sont_reconnus():
    import forge_reachability_ledger as L

    for c in ("tests/nr/test_x_nr.py", "app/tests/test_y.py", "a/b/x_test.py"):
        assert L._est_test(c), c
    for c in ("app/forge_llm_router.py", "tools/forge_regression_sweep.py"):
        assert not L._est_test(c), c


def test_le_vendor_est_ecarte_mais_pas_les_tests():
    """Phase 6 traite `test_*` comme du bruit ; ici ils PROUVENT. Ne pas confondre."""
    import forge_reachability_ledger as L

    assert L._vendor("x/.venv/lib/m.py")
    assert L._vendor("RAG/eval_repos/p.py")
    assert not L._vendor("tests/nr/test_capability_ratchet_nr.py")


# ── observabilite ───────────────────────────────────────────────────────────

def test_aucun_depot_lisible_rend_indetermine(tmp_path):
    import forge_reachability_ledger as L

    res = L.analyser({"faux": str(tmp_path)})
    assert res.get("observable") is False


def test_surface_non_observable_nempeche_pas_de_juger_le_reste():
    """Une sonde muette ne doit pas transformer tout le registre en INDETERMINE :
    elle retire un cran de la hierarchie, pas la hierarchie entiere."""
    import forge_reachability_ledger as L

    etat, _ = L.classer_vivant("z", set(), Counter(), None, Counter({"z": 4}))
    assert etat == "UNPROVEN"
