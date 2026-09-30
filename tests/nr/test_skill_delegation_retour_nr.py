"""NR — RETOUR de delegation : fermer la boucle multi-agent.

Nokido sait suspendre un plan en attendant un autre effecteur. Il ne savait
pas encore recevoir son resultat, le verifier, et reprendre. Sans ce morceau,
le graphe n'est qu'un emetteur de missions.

CYCLE VISE

    DELEGUE -> RESULTAT_RECU -> EFFET_VERIFIE   -> COMPLETED
                             -> EFFET_DECLARE   -> COMPLETED (marque)
                             -> EFFET_INFIRME   -> STEP_FAILED -> REPLAN

LE POINT DUR, ET POURQUOI IL NE SE CONTOURNE PAS
------------------------------------------------
Un client qui rend « j'ai produit F » affirme quelque chose. `REQUESTED !=
ACHIEVED` interdit de le prendre pour un fait. Mais pour un effet purement
EPISTEMIQUE — « la pathologie est nommee » — Nokido n'a AUCUN observateur
independant : il ne peut ni confirmer ni infirmer.

Refuser tous ces effets bloquerait toute delegation. Les accepter en silence
ferait passer une affirmation pour une mesure. La seule sortie honnete est de
les distinguer et de porter la distinction jusque dans la preuve :

    EFFET_VERIFIE   un observateur Nokido a confirme l'etat resultant
    EFFET_DECLARE   le client l'affirme, rien ne le confirme — utilisable,
                    mais JAMAIS presente comme mesure

C'est la meme famille que `SIGNAL != PREUVE DE VIE` : un battement frais ne
prouve pas qu'un organe est vivant, il prouve que quelque chose a battu.

RATTACHEMENT
------------
Un retour qui ne se rattache pas a la lignee est REJETE. Sans cela, n'importe
quel message pourrait fermer l'etape d'un autre et injecter un fait dans un
plan auquel il n'appartient pas.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_skill_capability_graph as cg  # noqa: E402
import forge_skill_execution as ex  # noqa: E402


def _trace_suspendue():
    """Un plan reellement suspendu sur une delegation a claude."""
    plan = cg.planifier(but=cg.Fait("pathologie_nommee"), connus=set())
    trace = ex.executer_plan(plan, realisations={})
    assert trace.verdict == "PLAN_SUSPENDU_DELEGATION", trace.motif
    return trace


def _tous_les_effets(trace):
    """Les effets ACQUIS que la capacite deleguee declare — TOUS.

    Un retour partiel est refuse, et c'est voulu : une capacite qui ne tient
    pas toute sa declaration a une declaration fausse. La regle vaut pour le
    retour d'un client comme pour une execution locale.
    """
    e = trace.executions[-1]
    skill, mode = e.capability_id.split("::", 1)
    cap = cg.capacite(skill, mode)
    return [p.fait for p in cap.postconditions if p.garantie == cg.ACQUISE]


def _retour(trace, effets, execution_id=None, racine=None):
    e = trace.executions[-1]
    return {
        "execution_id": execution_id or e.execution_id,
        "execution_racine": racine or trace.execution_racine,
        "effets_declares": [str(f) for f in effets],
        "contenu": "conclusion rendue par le client",
    }


def test_un_retour_hors_lignee_est_rejete():
    """Un message etranger ne ferme pas l'etape d'un plan.

    Sans ce controle, n'importe quel retour pourrait injecter un fait dans un
    plan auquel il n'appartient pas — et la provenance ne vaudrait plus rien.
    """
    trace = _trace_suspendue()
    faux = _retour(trace, _tous_les_effets(trace), racine="exec_etranger")

    with pytest.raises(ValueError, match="lignee"):
        ex.recevoir_resultat(trace, faux)


def test_un_retour_sur_une_etape_non_deleguee_est_rejete():
    trace = _trace_suspendue()
    faux = _retour(trace, _tous_les_effets(trace),
                   execution_id="exec_inexistant")

    with pytest.raises(ValueError):
        ex.recevoir_resultat(trace, faux)


def test_sans_observateur_l_effet_est_DECLARE_jamais_verifie():
    """Une affirmation de client n'est pas une mesure.

    Nokido ne peut pas confirmer « la pathologie est nommee ». Il accepte le
    fait pour continuer, et le MARQUE : la preuve dira que cet effet repose
    sur une declaration.
    """
    trace = _trace_suspendue()
    e = ex.recevoir_resultat(trace, _retour(trace, _tous_les_effets(trace)))

    assert e.statut == "STEP_COMPLETED"
    assert e.qualite_effet == "EFFET_DECLARE"
    assert "declar" in e.motif.lower()
    assert cg.Fait("pathologie_nommee") in set(e.faits_acquis)


def test_avec_observateur_qui_confirme_l_effet_est_VERIFIE():
    trace = _trace_suspendue()
    attendus = _tous_les_effets(trace)
    observateurs = {"forge-anatomy::diagnostiquer": lambda ctx: set(attendus)}
    e = ex.recevoir_resultat(trace, _retour(trace, attendus),
                             observateurs=observateurs)

    assert e.statut == "STEP_COMPLETED"
    assert e.qualite_effet == "EFFET_VERIFIE"


def test_un_observateur_qui_INFIRME_fait_echouer_l_etape():
    """Le client affirme, l'etat dit non. L'etat gagne.

    C'est REQUESTED != ACHIEVED applique au multi-agent : sans ce controle,
    un effecteur qui se trompe — ou qui ment — propagerait un faux fait dans
    tout le reste du plan.
    """
    trace = _trace_suspendue()
    observateurs = {"forge-anatomy::diagnostiquer": lambda ctx: set()}
    e = ex.recevoir_resultat(trace, _retour(trace, _tous_les_effets(trace)),
                             observateurs=observateurs)

    assert e.statut == "STEP_FAILED"
    assert e.qualite_effet == "EFFET_INFIRME"
    assert not e.faits_acquis, "un effet infirme n'entre pas dans les acquis"


def test_un_effet_non_declare_par_le_client_n_est_pas_invente():
    """Le retour ne vaut que pour ce qu'il porte."""
    trace = _trace_suspendue()
    e = ex.recevoir_resultat(trace, _retour(trace, []))

    assert e.statut == "STEP_FAILED"
    assert not e.faits_acquis


def test_la_lignee_survit_au_saut_inter_client():
    """Le retour reste sous la MEME racine que l'objectif initial."""
    trace = _trace_suspendue()
    racine = trace.execution_racine
    e = ex.recevoir_resultat(trace, _retour(trace, _tous_les_effets(trace)))

    assert e.execution_racine == racine
    assert any(ev["type"] == "RESULTAT_RECU" for ev in trace.evenements)
    assert all(ev["execution_racine"] == racine for ev in trace.evenements)


def test_le_plan_reprend_apres_le_retour():
    """La boucle se ferme : apres le retour, la suite s'execute vraiment."""
    trace = _trace_suspendue()
    ex.recevoir_resultat(trace, _retour(trace, _tous_les_effets(trace)))

    suite = ex.reprendre(trace, realisations={
        "forge-workflow-autopsy::autopsier": ex.Realisation(
            mode=ex.NOKIDO_NATIF, transport="test",
            agir=lambda ctx: {"rc": 0},
            observer=lambda ctx: {cg.Fait("consommateur_vivant_connu"),
                                  cg.Fait("cause_de_panne_connue")}),
    }, but=cg.Fait("cause_de_panne_connue"))

    assert suite.verdict == "PLAN_COMPLETED", suite.motif
    assert suite.execution_racine == trace.execution_racine, (
        "la reprise reste dans la lignee de l'objectif initial")


def test_le_journal_et_le_resume_disent_la_meme_chose():
    """Un chiffre faux dans le journal est pire que dans l'affichage.

    Mesure : apres une reprise, `trace.motif` disait « 3 etapes menees a leur
    effet » pendant que l'evenement PLAN_COMPLETED portait encore « 0 etape »
    — le plan de reprise etait vide et son motif n'avait pas ete recalcule.
    Corriger la seule vue humaine laisse le mensonge dans ce qui sert de
    PREUVE exploitable par une machine.
    """
    trace = _trace_suspendue()
    ex.recevoir_resultat(trace, _retour(trace, _tous_les_effets(trace)))
    suite = ex.reprendre(trace, realisations={}, but=cg.Fait("pathologie_nommee"))

    finaux = [e for e in suite.evenements if e["type"] == "PLAN_COMPLETED"]
    assert finaux, "un plan conclu doit porter son evenement de cloture"
    assert finaux[-1]["motif"] == suite.motif, (
        "le journal et le resume doivent porter le MEME compte d'etapes")
    assert "0 etape" not in finaux[-1]["motif"], (
        "une chaine qui a mene des etapes a leur effet ne s'annonce pas a zero")


def test_la_preuve_porte_la_qualite_des_effets():
    """Un plan boucle sur des effets DECLARES ne se presente pas comme mesure."""
    trace = _trace_suspendue()
    ex.recevoir_resultat(trace, _retour(trace, _tous_les_effets(trace)))

    resume = ex.resume_qualite(trace)
    assert resume["EFFET_DECLARE"] >= 1
    assert resume["repose_sur_declaration"] is True, (
        "quand une etape au moins repose sur une declaration, la preuve "
        "entiere doit le dire")
