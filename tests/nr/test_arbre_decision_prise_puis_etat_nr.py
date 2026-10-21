"""NR -- l'arbre des roadmaps lit l'etat APRES un segment « decision prise ».

Mesure 19/10 23:0x (recompte 145 items) : 11 items rendus SANS_MARQUEUR parce que leur tete est
`[DECISION 19/10 ~15 h, decision owner (choix multiple) : ...]` -- une decision owner PRISE, consignee devant le
segment `[PARTIEL ...]` qui porte l'etat. L'arbre affichait 11 chantiers vivants comme non qualifies.
Une decision prise n'est pas un etat ; `[DECISION OWNER ...]` (decision ATTENDUE) reste DECISION_OWNER.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_roadmap_keeper as K  # noqa: E402


def test_decision_prise_puis_partiel_rend_partiel():
    t = ("[DECISION 19/10 ~15 h, decision owner (choix multiple) : JOUER l'essai aujourd'hui] "
         "[PARTIEL 2026-10-19 02:59 : verifie par AGY ; reste = geste owner]")
    assert K._etat_arbre(t) == "PARTIEL"


def test_decision_prise_puis_clos_rend_clos():
    assert K._etat_arbre("[DECISION 19/10 : GO] [CLOS 2026-10-19 : constate]") == "CLOS"


def test_decision_attendue_reste_decision_owner():
    assert K._etat_arbre("[DECISION OWNER 2026-10-18 (choix multiple) : OUI identite CI]") == "DECISION_OWNER"


def test_decision_prise_sans_etat_derriere_reste_sans_marqueur():
    assert K._etat_arbre("[DECISION 19/10 : GO] texte libre sans marqueur") == "SANS_MARQUEUR"


def test_prefixe_de_priorite_puis_decision_prise():
    assert K._etat_arbre("P1: [DECISION 19/10 : GO] [PARTIEL 2026-10-19 : reste = x]") == "PARTIEL"
