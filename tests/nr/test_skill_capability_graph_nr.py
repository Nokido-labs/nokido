"""NR — graphe de CAPACITES : ce qu'un skill exige, ce qu'il produit.

Couche 3 sur 3 :

    CATALOGUE  forge_skill_catalogue   quels skills EXISTENT
    RETRIEVAL  forge_skill_retrieval   lesquels sont PERTINENTS
    CAPACITES  ce module               lesquels PERMETTENT d'atteindre un but

Le planner ne raisonne plus par ressemblance textuelle mais par dependance de
connaissances : A produit F1, B exige F1, B produit F2. La question passe de
« quel skill ressemble a ma question ? » a « quels skills me permettent
d'atteindre cet objectif compte tenu de ce que je sais deja ? ».

CONTRAT EPROUVE SUR 5 SKILLS REELS ET VOLONTAIREMENT DISSEMBLABLES, choisis
pour casser le modele s'il est trop simple — leurs descriptions ont ete LUES,
jamais supposees :

  forge-anatomy             lecture pure, effets purement EPISTEMIQUES
  skill-creator             ecriture locale, reversible par git
  netcfg-agent              effecteur DISTANT, deploy SSH irreversible
  forge-veille-approfondie  depend de services tiers, ecrit en base
  forge-m2m-debat-mesure    depend d'un PAIR VIVANT, effet non garanti

Trois faits de conception que ces cinq ont IMPOSES (aucun n'etait prevu) :

  1. Un skill porte N capacites, pas une. `netcfg-agent` declare
     « preview/dry-run avant deploy SSH » : le preview observe, le deploy
     modifie un equipement reseau. Un seul contrat pour les deux serait faux
     dans un sens ou dans l'autre.
  2. Une postcondition EPISTEMIQUE (« je sais X ») n'est pas une postcondition
     PHYSIQUE (« le monde a change »). Les confondre laisserait un planner
     croire qu'un deploiement SSH se defait comme on oublie un fait.
  3. Un effet peut etre NON GARANTI. `forge-m2m-debat-mesure` porte dans sa
     propre description « delivered != lu ». Chainer sur un effet seulement
     demande, c'est REQUESTED != ACHIEVED — la faute que la constitution
     interdit explicitement.
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


def test_les_cinq_skills_temoins_sont_declares():
    """Le contrat doit etre eprouve sur des skills REELS, pas sur des exemples."""
    couverts = {c.skill for c in cg.CAPACITES}
    attendus = {"forge-anatomy", "skill-creator", "netcfg-agent",
                "forge-veille-approfondie", "forge-m2m-debat-mesure"}
    assert attendus <= couverts, (
        "les 5 familles temoins doivent rester declarees : elles sont ce qui "
        "empeche le modele de n'etre valide que sur un seul type de skill")


def test_un_skill_peut_porter_plusieurs_capacites():
    """netcfg-agent : observer n'est pas deployer."""
    caps = [c for c in cg.CAPACITES if c.skill == "netcfg-agent"]
    assert len(caps) >= 2, (
        "preview/dry-run et deploy SSH sont deux capacites : un contrat unique "
        "serait soit trop permissif pour le deploy, soit trop bloquant pour le "
        "preview")
    modes = {c.mode for c in caps}
    assert len(modes) == len(caps), "chaque capacite d'un skill a un mode distinct"


def test_epistemique_et_physique_ne_se_confondent_pas():
    """Lire l'anatomie ne change rien ; deployer par SSH change le monde."""
    anat = cg.capacite("forge-anatomy", "diagnostiquer")
    assert all(e.nature == "EPISTEMIQUE" for e in anat.postconditions)
    assert anat.reversible is True
    assert not anat.side_effects, "lire l'anatomie ne produit aucun effet de bord"

    deploy = next(c for c in cg.CAPACITES
                  if c.skill == "netcfg-agent" and c.mode == "deployer")
    assert any(e.nature == "PHYSIQUE" for e in deploy.postconditions), (
        "un deploiement SSH modifie un equipement : le declarer epistemique "
        "laisserait le planner croire qu'il peut le rejouer ou l'annuler")
    assert deploy.reversible is False
    assert deploy.risque == "HAUT"


def test_un_effet_non_garanti_ne_satisfait_pas_une_precondition():
    """delivered != lu — la faute REQUESTED != ACHIEVED, rendue impossible.

    Un effet `A_VERIFIER` est une intention, pas un acquis. Le planner doit
    exiger une observation avant de chainer dessus.
    """
    debat = cg.capacite("forge-m2m-debat-mesure", "debattre")
    non_garantis = [e for e in debat.postconditions if e.garantie != "ACQUISE"]
    assert non_garantis, (
        "la description du skill dit elle-meme « delivered != lu » : au moins "
        "un de ses effets ne peut pas etre declare acquis")

    effet = non_garantis[0]
    assert not cg.satisfait({effet}, effet.fait), (
        "un effet seulement DEMANDE ne satisfait pas une precondition ; il "
        "faut l'avoir OBSERVE")

    acquis = cg.Effet(effet.fait, garantie="ACQUISE", nature=effet.nature)
    assert cg.satisfait({acquis}, effet.fait), (
        "le MEME fait, une fois observe, satisfait la precondition : c'est la "
        "garantie qui tranche, pas le fait")


def test_une_precondition_hors_controle_est_nommee_comme_telle():
    """Un pair vivant, un service tiers : Nokido ne les garantit pas.

    Une precondition qu'on ne peut pas produire soi-meme ne doit pas etre
    traitee comme un sous-but ordinaire : aucun skill ne la produira, et le
    planner tournerait en rond a chercher un producteur.
    """
    debat = cg.capacite("forge-m2m-debat-mesure", "debattre")
    veille = cg.capacite("forge-veille-approfondie", "veiller")
    externes = [p for p in list(debat.preconditions) + list(veille.preconditions)
                if p.hors_controle]
    assert externes, (
        "un pair M2M vivant et les services de veille (SearXNG, Ollama, Groq) "
        "sont hors du controle de Nokido : le dire evite une recherche de "
        "producteur qui ne peut aboutir")


def test_le_pont_vers_goap_produit_une_action_valide():
    """Reutiliser le moteur existant, ne pas en ecrire un second.

    forge_goap_hub_bridge.Action porte deja preconditions/effects/cost : le
    graphe de capacites s'y projette au lieu d'inventer un planner parallele.
    """
    anat = cg.capacite("forge-anatomy", "diagnostiquer")
    action = cg.vers_action_goap(anat)
    assert isinstance(action.get("preconditions"), dict)
    assert isinstance(action.get("effects"), dict)
    assert action.get("cost", 0) > 0, "un cout nul rendrait tout plan equivalent"
    assert action["effects"], "une capacite sans effet ne ferait avancer aucun plan"


def test_chainage_reel_deux_skills_vers_un_objectif():
    """Le cas qui justifie toute la couche : B consomme ce que A produit."""
    plan = cg.planifier(but=cg.Fait("cause_de_panne_connue", service="webhub"),
                        connus=set())
    assert plan.verdict == "PLAN_TROUVE", plan.motif
    assert len(plan.etapes) >= 2, (
        "atteindre la cause d'une panne demande d'observer AVANT de conclure : "
        "un plan a une seule etape signifierait qu'un skill fait tout")

    produits: set = set()
    for etape in plan.etapes:
        cap = cg.capacite(etape.skill, etape.mode)
        for p in cap.preconditions:
            assert p.hors_controle or p in produits or p in plan.connus_initiaux, (
                "chaque precondition doit etre satisfaite AVANT son etape : "
                "sinon l'ordre du plan ne veut rien dire")
        produits |= {e.fait for e in cap.postconditions if e.garantie == "ACQUISE"}


def test_plan_impossible_nomme_le_fait_manquant():
    """Un echec de plan doit etre ACTIONNABLE, pas un simple « non ».

    Nommer le fait manquant est ce qui permet l'autonomie : Nokido peut alors
    chercher un skill qui PRODUIT ce fait au lieu d'abandonner.
    """
    plan = cg.planifier(but=cg.Fait("recette_de_cassoulet_connue"), connus=set())
    assert plan.verdict in ("AUCUN_PRODUCTEUR", "PLAN_IMPOSSIBLE")
    assert plan.manquants, "le fait qu'on n'a pas su produire doit etre NOMME"
    assert "cassoulet" in str(plan.manquants).lower()


def test_capacite_inconnue_leve_plutot_que_de_rendre_none():
    """Un None silencieux se propagerait jusqu'a un plan vide inexplicable."""
    with pytest.raises(KeyError):
        cg.capacite("skill-qui-n-existe-pas", "mode-imaginaire")
