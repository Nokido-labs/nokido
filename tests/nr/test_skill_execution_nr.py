"""NR — EXECUTION gouvernee et PROVENANCE d'un plan de skills.

Couche 4. Les trois precedentes savent dire quels skills existent, lesquels
sont pertinents, et dans quel ordre les employer. Aucune ne fait AGIR Nokido.
Tant que cette couche n'existe pas, le systeme est un excellent planificateur
declaratif et rien de plus.

LE VERROU QUE CE MODULE DOIT RESOUDRE EN LE DISANT
--------------------------------------------------
« Executer forge-anatomy » n'a pas de sens litteral : c'est une grille de
lecture, du texte destine a un LLM. Une capacite n'est executable PAR NOKIDO
que si elle est reliee a une route gouvernee (outil du hub, script, job).
Sinon elle est executable par un CLIENT, ce qui n'est pas la meme chose et ne
doit pas etre confondu — un plan qui pretend executer ce qu'il ne peut pas
produit un faux succes.

D'ou `execution_mode` a valeurs distinctes, et un plan qui refuse plutot que
de simuler.

INVARIANTS, tous adosses a une faute deja payee
-----------------------------------------------
  * `REQUESTED != ACHIEVED` : un rc=0, un « message envoye », un `.rc` present
    ne sont PAS des postconditions. Un effet n'est acquis que s'il est
    OBSERVE apres coup. Le push qui sort en rc=1 apres avoir reussi et le
    `job_status` qui dit `running` apres un kill sont la meme famille.
  * `DELIVERED != READ` : un effet declare `A_VERIFIER` ne devient jamais
    acquis du seul fait qu'on a agi.
  * Une lignee d'execution unique : sans `execution_id` commun et parentage
    correct, on ne peut rattacher aucun resultat a l'objectif qui l'a demande.
  * Un replan se decide sur les FAITS observes, pas sur une regeneration libre
    du LLM — sinon l'autonomie n'est qu'une hallucination mieux presentee.

Les realisations sont INJECTEES dans ces tests : c'est le CONTRAT qui est
verifie ici. La preuve d'execution reelle se fait par le CLI sur le depot
vivant, pas par un mock au dernier etage.
"""

from __future__ import annotations

import dataclasses
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_skill_capability_graph as cg  # noqa: E402
import forge_skill_execution as ex  # noqa: E402


def _realisation_ok(faits):
    """Realisation qui agit ET dont l'etat resultant est reellement observable."""
    return ex.Realisation(
        mode=ex.NOKIDO_NATIF, transport="test",
        agir=lambda ctx: {"rc": 0},
        observer=lambda ctx: set(faits),
    )


def _realisation_menteuse(faits_promis):
    """Agit avec succes apparent, mais l'etat resultant ne change PAS.

    C'est le cas qui compte : rc=0 et rien d'observe.
    """
    return ex.Realisation(
        mode=ex.NOKIDO_NATIF, transport="test",
        agir=lambda ctx: {"rc": 0},
        observer=lambda ctx: set(),
    )


def test_un_rc_zero_ne_vaut_pas_postcondition():
    """Le coeur du contrat : on conclut sur l'ETAT OBSERVE, jamais sur l'appel."""
    cap = cg.capacite("forge-anatomy", "diagnostiquer")
    trace = ex.executer_etape(
        cap, _realisation_menteuse([f.fait for f in cap.postconditions]),
        contexte={}, execution_racine="exec_test")

    assert trace.statut == "STEP_FAILED", (
        "l'appel a rendu rc=0 et AUCUN effet n'est observable : declarer un "
        "succes ici, c'est REQUESTED != ACHIEVED")
    assert not trace.faits_observes
    assert "observ" in trace.motif.lower(), "le motif doit nommer ce qui manque"


def test_un_effet_observe_vaut_postcondition():
    cap = cg.capacite("forge-anatomy", "diagnostiquer")
    attendus = [e.fait for e in cap.postconditions]
    trace = ex.executer_etape(cap, _realisation_ok(attendus), contexte={},
                              execution_racine="exec_test")

    assert trace.statut == "STEP_COMPLETED"
    assert set(trace.faits_observes) == set(attendus)


def test_une_capacite_sans_route_nokido_est_DELEGUEE_pas_impossible():
    """DELEGUE n'est pas NON_EXECUTABLE.

    Nokido ne pretend pas executer un corpus d'instructions — mais un autre
    effecteur le peut. Confondre les deux ferait lire une impossibilite la ou
    il y a seulement un client a solliciter : meme famille que
    DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE.
    """
    cap = cg.capacite("forge-anatomy", "diagnostiquer")
    trace = ex.executer_etape(cap, None, contexte={}, execution_racine="exec_test")

    assert trace.statut == "STEP_DELEGUE"
    assert trace.client_cible == "claude"
    assert trace.transport, "le canal par lequel joindre ce client doit etre dit"
    assert not trace.faits_acquis, (
        "deleguer n'acquiert rien : l'effet reste a observer en retour")


def test_l_ordre_de_mission_porte_la_lignee():
    """Un saut inter-client ne doit pas rompre la provenance.

    Sans lignee dans l'ordre de mission, ce que le client renverra ne pourra
    pas etre rattache a l'objectif qui l'a demande.
    """
    cap = cg.capacite("forge-anatomy", "diagnostiquer")
    e = ex.executer_etape(cap, None, contexte={}, execution_racine="exec_racine",
                          parent="exec_parent")
    ordre = e.ordre_de_mission()

    for champ in ("execution_id", "parent_execution_id", "execution_racine",
                  "skill_id", "capability_id", "transport", "client_cible"):
        assert champ in ordre, "champ de provenance manquant : %s" % champ
    assert ordre["execution_racine"] == "exec_racine"
    assert ordre["parent_execution_id"] == "exec_parent"
    assert ordre["a_observer_en_retour"] is True, (
        "un effet delegue ne devient jamais acquis du seul fait de l'envoi")


def test_une_capacite_que_personne_ne_peut_executer_le_dit():
    """Aucune route gouvernee ET aucun client capable : la, c'est impossible."""
    cap = dataclasses.replace(cg.capacite("forge-anatomy", "diagnostiquer"),
                              clients=())
    trace = ex.executer_etape(cap, None, contexte={}, execution_racine="exec_test")

    assert trace.statut == "STEP_NON_EXECUTABLE"
    assert "personne" in trace.motif.lower()


def test_le_plan_suspend_sur_delegation_au_lieu_d_echouer():
    """Attendre un autre effecteur n'est ni un echec ni un succes."""
    plan = cg.planifier(but=cg.Fait("pathologie_nommee"), connus=set())
    trace = ex.executer_plan(plan, realisations={})

    assert trace.verdict == "PLAN_SUSPENDU_DELEGATION", trace.motif
    evt = [e for e in trace.evenements if e["type"] == "STEP_DELEGUE"]
    assert evt and evt[0]["client_cible"] == "claude"
    assert evt[0]["ordre_de_mission"]["execution_racine"] == trace.execution_racine


def test_provenance_lignee_unique_et_parentage():
    """Tout ce qui decoule d'un objectif se rattache a UNE lignee."""
    plan = cg.planifier(but=cg.Fait("cause_de_panne_connue"), connus=set())
    realisations = {
        "forge-anatomy::diagnostiquer": _realisation_ok(
            [cg.Fait("organe_identifie"), cg.Fait("pathologie_nommee")]),
        "forge-workflow-autopsy::autopsier": _realisation_ok(
            [cg.Fait("consommateur_vivant_connu"), cg.Fait("cause_de_panne_connue")]),
    }
    trace = ex.executer_plan(plan, realisations)

    assert trace.verdict == "PLAN_COMPLETED", trace.motif
    assert len(trace.executions) == 2

    racines = {e.execution_racine for e in trace.executions}
    assert len(racines) == 1, "une seule lignee pour un objectif"

    assert trace.executions[0].parent_execution_id is None
    assert trace.executions[1].parent_execution_id == trace.executions[0].execution_id, (
        "la seconde etape descend de la premiere : sans ce parentage, l'ordre "
        "reel de la chaine n'est pas reconstituable")

    ids = [e.execution_id for e in trace.executions]
    assert len(set(ids)) == len(ids), "deux etapes ne partagent pas un identifiant"


def test_le_journal_porte_les_evenements_attendus():
    plan = cg.planifier(but=cg.Fait("cause_de_panne_connue"), connus=set())
    realisations = {
        "forge-anatomy::diagnostiquer": _realisation_ok(
            [cg.Fait("organe_identifie"), cg.Fait("pathologie_nommee")]),
        # Les DEUX effets acquis declares par la capacite, pas un seul : une
        # realisation qui n'en produit qu'une partie fait echouer l'etape, et
        # c'est le comportement voulu — une declaration incomplete est fausse.
        "forge-workflow-autopsy::autopsier": _realisation_ok(
            [cg.Fait("consommateur_vivant_connu"), cg.Fait("cause_de_panne_connue")]),
    }
    trace = ex.executer_plan(plan, realisations)
    types = [e["type"] for e in trace.evenements]

    assert types[0] == "PLAN_CREATED"
    assert types[-1] == "PLAN_COMPLETED"
    for attendu in ("STEP_SELECTED", "STEP_STARTED", "STEP_COMPLETED"):
        assert attendu in types, "evenement manquant : %s" % attendu
    assert all("execution_racine" in e for e in trace.evenements), (
        "un evenement sans lignee est inexploitable pour la provenance")


def test_echec_d_etape_arrete_la_chaine_et_le_dit():
    """B ne s'execute pas sur un A qui n'a rien produit."""
    plan = cg.planifier(but=cg.Fait("cause_de_panne_connue"), connus=set())
    realisations = {
        "forge-anatomy::diagnostiquer": _realisation_menteuse([]),
        "forge-workflow-autopsy::autopsier": _realisation_ok(
            [cg.Fait("cause_de_panne_connue")]),
    }
    trace = ex.executer_plan(plan, realisations)

    assert trace.verdict in ("PLAN_FAILED", "REPLAN_REQUIS")
    assert any(e["type"] == "STEP_FAILED" for e in trace.evenements)
    executees = [e for e in trace.executions if e.statut == "STEP_COMPLETED"]
    assert not executees, (
        "aucune etape avale ne doit tourner quand sa precondition n'a pas ete "
        "reellement produite")


def test_replan_est_pilote_par_les_faits_observes():
    """Le replan repart de ce qu'on SAIT, pas d'une regeneration libre.

    Apres un echec, le fait manquant est nomme et sert d'entree a une nouvelle
    recherche de producteur. C'est une recherche dans le graphe, pas une
    invention.
    """
    plan = cg.planifier(but=cg.Fait("cause_de_panne_connue"), connus=set())
    realisations = {
        "forge-anatomy::diagnostiquer": _realisation_menteuse([]),
    }
    trace = ex.executer_plan(plan, realisations)

    besoin = ex.fait_manquant(trace)
    assert besoin is not None, "l'echec doit nommer le fait qui manque"

    replan = ex.replanifier(trace)
    assert replan.but.type == besoin.type or replan.verdict != "PLAN_TROUVE", (
        "le replan doit viser le fait manquant observe, pas repartir du but "
        "initial comme si rien ne s'etait passe")


def test_effet_a_verifier_ne_devient_pas_acquis_par_l_action():
    """DELIVERED != READ, jusque dans l'executeur.

    forge-m2m-debat-mesure emet un message (acquis) et espere un debat tenu
    (a verifier). Agir ne transforme pas le second en acquis.
    """
    cap = cg.capacite("forge-m2m-debat-mesure", "debattre")
    a_verifier = [e.fait for e in cap.postconditions if e.garantie != cg.ACQUISE]
    assert a_verifier, "le skill temoin doit porter un effet non garanti"

    # La realisation OBSERVE tout, y compris ce qui n'est pas garanti.
    trace = ex.executer_etape(
        cap, _realisation_ok([e.fait for e in cap.postconditions]),
        contexte={}, execution_racine="exec_test")

    acquis = set(trace.faits_acquis)
    assert a_verifier[0] not in acquis, (
        "meme observe au moment de l'action, un effet declare A_VERIFIER ne "
        "rejoint pas les faits acquis sans verification distincte")
