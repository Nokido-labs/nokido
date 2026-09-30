"""NR — contrat d'execution par etape de la facade harness (chantier harness controller, pas 2).

Invariants :
- douze colonnes, dans l'ordre du contrat ; une etape neuve vaut UNKNOWN partout et le DIT ;
- REQUESTED != ACCEPTED != ACHIEVED : un `completed` de trace GOAP n'est JAMAIS ACHIEVED ;
- liste BLANCHE : ACHIEVED exige ALLOW + EFFECT_OBSERVED + preuve acceptee + effet attendu declare ;
  retirer UNE piece suffit a retomber du cote non prouve ;
- INCERTAIN != FAILED : une observation qui ne tranche pas n'est pas un echec ;
- DENY + monde qui bouge = CONTRADICTION conservee, jamais un REFUSED silencieux.

Chemin REEL : la trace vient d'un vrai forge_trajectory.Trajectory (append/complete/fail). L'effet
reprend MOT POUR MOT les chaines de tools/forge_effect_surface.effet_observe : ce module n'est pas
versionne, un NR du lot pur ne peut donc pas l'importer. Hermetique : aucun DB, aucun reseau.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app.forge_harness_contract import (  # noqa: E402
    ACCEPTED, ACHIEVED, COLONNES, CONTRADICTION, FAILED, INCERTAIN, REFUSED, REQUESTED,
    UNKNOWN, EtapeContrat, depuis_trajectory_step, ligne, verdict_etape,
)
from nokido_agent.app.forge_trajectory import Trajectory  # noqa: E402

# Vocabulaire de tools/forge_effect_surface.effet_observe, recopie mot pour mot. Le module n'est
# PAS versionne : la 1re version de ce NR l'importait, verte en local, rouge sur checkout propre
# (CI GitHub run 36334347392, 2026-09-27 : ModuleNotFoundError au collect). Le contrat ne compare
# que des prefixes ; il n'a pas besoin du producteur, ce NR non plus.
_EFFET_CANAL_LATERAL = "EFFECT_OBSERVED: DENY rendu mais le monde a change — canal lateral"
_EFFET_BLOQUE = "EFFECT_BLOCKED"
_EFFET_OBSERVE = "EFFECT_OBSERVED"


def _prouvee(**surcharge) -> EtapeContrat:
    base = dict(
        objectif="indexer x", action={"method": "rag_search", "params": {}}, autorisation="ALLOW",
        observation={"ok": True, "retour": {"n": 3}}, effet_attendu="3 chunks indexes",
        effet_observe="EFFECT_OBSERVED", preuve="accept",
    )
    base.update(surcharge)
    return EtapeContrat(**base)


def test_douze_colonnes_dans_l_ordre_du_contrat():
    assert COLONNES == (
        "objectif", "etat_avant", "capacite", "preconditions", "autorisation", "action",
        "observation", "effet_attendu", "effet_observe", "preuve", "etat_apres",
        "prochain_objectif",
    )


def test_etape_neuve_inconnue_partout_et_le_dit():
    e = EtapeContrat()
    assert e.colonnes_inconnues() == list(COLONNES)
    assert verdict_etape(e)["statut"] == UNKNOWN


def test_etape_entierement_prouvee_est_achieved():
    assert verdict_etape(_prouvee())["statut"] == ACHIEVED


@pytest.mark.parametrize("piece", [
    {"autorisation": UNKNOWN},
    {"effet_observe": "NON_CERTIFIANT: ALLOW mais monde inchange — l'effet n'a pas eu lieu"},
    {"effet_observe": UNKNOWN},
    {"preuve": "abstain"},
    {"preuve": UNKNOWN},
    {"effet_attendu": UNKNOWN},
])
def test_une_piece_manquante_suffit_a_ne_pas_etre_achieved(piece):
    v = verdict_etape(_prouvee(**piece))
    assert v["statut"] == ACCEPTED
    assert "effet non prouve" in v["motif"]


def test_observation_qui_ne_tranche_pas_est_incertain_pas_failed():
    assert verdict_etape(_prouvee(observation={"retour": "?"}))["statut"] == INCERTAIN
    assert verdict_etape(_prouvee(observation="texte brut"))["statut"] == INCERTAIN


def test_deny_et_monde_qui_bouge_est_une_contradiction_conservee():
    v = verdict_etape(_prouvee(autorisation="DENY", effet_observe=_EFFET_CANAL_LATERAL))
    assert v["statut"] == CONTRADICTION
    assert "DENY" in v["motif"]


def test_deny_et_monde_inchange_est_refused():
    assert verdict_etape(_prouvee(autorisation="DENY", effet_observe=_EFFET_BLOQUE))["statut"] == REFUSED


def test_effet_reel_allow_monde_change_rend_achieved():
    assert verdict_etape(_prouvee(effet_observe=_EFFET_OBSERVE))["statut"] == ACHIEVED


# --- Chemin REEL : la trace GOAP telle que forge_goap._execute_subgoal la produit ---

def test_trace_completed_est_accepted_jamais_achieved():
    traj = Trajectory()
    traj.append({"method": "rag_search", "params": {"q": "x"}}, agent="goap")
    traj.complete(0, {"hits": 2})
    e = depuis_trajectory_step(traj.steps[0], objectif="trouver x")
    assert e.capacite == "rag_search"
    assert e.observation == {"ok": True, "retour": {"hits": 2}}
    assert verdict_etape(e)["statut"] == ACCEPTED
    # la trace ne sait pas le reste : dit, pas fabrique
    for c in ("etat_avant", "preconditions", "autorisation", "effet_attendu", "effet_observe",
              "preuve", "etat_apres", "prochain_objectif"):
        assert c in e.colonnes_inconnues()


def test_trace_failed_est_failed():
    traj = Trajectory()
    traj.append({"method": "notify", "params": {}}, agent="goap")
    traj.fail(0, "timeout")
    e = depuis_trajectory_step(traj.steps[0])
    assert verdict_etape(e)["statut"] == FAILED
    assert e.observation["retour"] == {"error": "timeout"}


def test_trace_pending_est_requested():
    traj = Trajectory()
    traj.append({"method": "notify", "params": {}}, agent="goap")
    assert verdict_etape(depuis_trajectory_step(traj.steps[0]))["statut"] == REQUESTED


def test_ligne_porte_les_douze_colonnes_et_le_statut():
    s = ligne(_prouvee())
    for c in COLONNES:
        assert c.upper() + "=" in s
    assert s.endswith("|| " + ACHIEVED)
