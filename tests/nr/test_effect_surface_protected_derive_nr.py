"""NR — `PROTECTED` ne doit jamais pouvoir être atteint par accumulation.

Ce NR ne corrige pas un défaut : il FIGE un contrat, pour que les chantiers
suivants ne puissent pas le relâcher. C'est la réponse au motif récurrent
« 100 NR verts donc c'est sûr » — un raisonnement qui a toujours manqué le
chemin que personne n'avait essayé.

Cinq conditions, toutes nécessaires :

    PROTECTED = INVENTORIED
            AND DECISION_PROVEN
            AND ENFORCEMENT_PROVEN
            AND EXHAUSTIVENESS_PROVEN
            AND aucun EFFECT_EQUIVALENT_PATH_NOT_COVERED

Et `EFFECT_BLOCKED` est une preuve du MONDE, pas la parole d'un garde :

    état_avant + tentative + DENY + état_après == état_avant
                + executor NON atteint

Les cas dangereux testés ici sont ceux qu'un système pressé range du côté sain :
un `DENY` pendant que le monde change (canal latéral), un executor atteint quand
même, une décision absente, un état non capturé.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_effect_surface as ES  # noqa: E402


def _chemin_couvert(nom="Edit", cat="DIRECT"):
    return ES.Chemin(nom=nom, categorie=cat, ingress="hook", instrumente=True,
                     effet="EFFECT_BLOCKED")


def _classe_ideale():
    """Le SEUL cas qui doit rendre PROTECTED : les douze dimensions vraies.

    Sans ce contrôle positif, un modèle qui ne rendrait JAMAIS `PROTECTED`
    passerait tous les autres tests — « sûr » parce qu'inutile.
    """
    c = ES.ClasseEffet(nom="X", description="effet temoin",
                       chemins=[_chemin_couvert()])
    c.decouverte_adversariale_faite = True
    c.primitives_non_classees = []
    c.surfaces_du_monde = ["fichier"]
    c.surfaces_du_monde_couvertes = True
    c.executor_unique = "executor unique demontre"
    c.toctou_joue = True
    c.meta_effets = [ES.MetaEffet("gate de X", "gate.py", "WRITE", "racine hors depot")]
    # Chaîne qui ATTEINT une racine : le garde n'est pas modifiable par l'effet
    # qu'il protège.
    c.chaine_confiance = {
        "X": ES.NoeudConfiance("X", protege_par="gate de X"),
        "gate de X": ES.NoeudConfiance("gate de X", protege_par=""),
    }
    c.preuve_roles = ES.Preuve3Roles("producteur", "observateur", "verificateur")
    return c


# --------------------------------------------------- PROTECTED est dérivé

def test_le_cas_ideal_est_bien_protege():
    """Contrôle positif : sans lui, tous les tests suivants passeraient sur une
    implémentation qui ne rend JAMAIS `PROTECTED`."""
    assert _classe_ideale().etat()["verdict"] == "PROTECTED"


def test_un_seul_axe_manquant_suffit_a_refuser():
    for axe_casse in ("inventaire", "decision", "enforcement", "exhaustivite"):
        c = _classe_ideale()
        if axe_casse == "inventaire":
            c.chemins = []
        elif axe_casse == "decision":
            c.chemins[0].effet = "NON_CERTIFIANT"
        elif axe_casse == "enforcement":
            c.chemins[0].effet = "EFFECT_OBSERVED"
        else:
            c.decouverte_adversariale_faite = False
        assert c.etat()["verdict"] == "NON_CERTIFIANT", (
            "axe %r casse et pourtant PROTECTED" % axe_casse)


def test_un_chemin_equivalent_non_couvert_interdit_protected():
    """LE test central : quatre axes verts NE SUFFISENT PAS s'il reste une route
    vers le même effet dont le blocage n'est pas prouvé."""
    c = _classe_ideale()
    c.chemins.append(ES.Chemin(nom="Bash>redirect", categorie="ALIAS",
                               instrumente=False))
    etat = c.etat()
    assert etat["verdict"] == "NON_CERTIFIANT"
    assert "Bash>redirect" in etat[ES.EQUIV_NON_COUVERT]


def test_un_suspect_compte_contre():
    """Un chemin soupçonné mais ni confirmé ni écarté n'est pas neutre."""
    c = _classe_ideale()
    c.suspects.append(ES.Chemin(nom="git apply", categorie="INDIRECT"))
    assert c.etat()["verdict"] == "NON_CERTIFIANT"


def test_exhaustivite_exige_une_decouverte_adversariale():
    """On ne DÉCLARE pas l'exhaustivité : il faut avoir cherché des chemins non
    déclarés."""
    c = _classe_ideale()
    c.decouverte_adversariale_faite = False
    assert c.verdicts()[ES.EXHAUSTIVENESS_PROVEN] is False


def test_un_chemin_jamais_tente_n_est_pas_couvert():
    c = ES.Chemin(nom="ps_clm", categorie="PS_CLM", instrumente=True, effet=None)
    assert c.couvert() is False, "jamais tenté ne vaut pas bloqué"


# ------------------------------------------- EFFECT_BLOCKED = preuve du monde

def test_deny_avec_monde_change_est_un_canal_lateral():
    """Le cas le plus grave : le garde dit non, l'effet a lieu quand même."""
    p = ES.Preuve(etat_avant="h1", etat_apres="h2", decision="DENY",
                  executor_atteint=False)
    assert ES.effet_observe(p).startswith("EFFECT_OBSERVED")


def test_deny_monde_inchange_et_executor_non_atteint_est_bloque():
    p = ES.Preuve(etat_avant="h1", etat_apres="h1", decision="DENY",
                  executor_atteint=False)
    assert ES.effet_observe(p) == "EFFECT_BLOCKED"


def test_executor_atteint_malgre_deny_n_est_pas_bloque():
    """Un refus arrivé après l'executor n'est pas une barrière."""
    p = ES.Preuve(etat_avant="h1", etat_apres="h1", decision="DENY",
                  executor_atteint=True)
    assert ES.effet_observe(p).startswith("NON_CERTIFIANT")


def test_executor_inconnu_ne_vaut_pas_bloque():
    """`None` = non instrumenté. Le ranger du côté sain serait le fail-open."""
    p = ES.Preuve(etat_avant="h1", etat_apres="h1", decision="DENY",
                  executor_atteint=None)
    assert ES.effet_observe(p).startswith("NON_CERTIFIANT")


def test_absence_de_decision_n_est_pas_un_refus():
    p = ES.Preuve(etat_avant="h1", etat_apres="h1", decision=None,
                  executor_atteint=False)
    assert ES.effet_observe(p).startswith("NON_CERTIFIANT")


def test_etat_du_monde_non_capture_interdit_tout_verdict():
    p = ES.Preuve(etat_avant=None, etat_apres=None, decision="DENY",
                  executor_atteint=False)
    assert ES.effet_observe(p).startswith("NON_CERTIFIANT")


# ------------------------------------------------- transitions interdites

def test_les_transitions_interdites_sont_toutes_motivees():
    attendues = [
        ("REQUESTED", "EFFECT_COMMITTED"), ("DENIED", "ALLOW_BY_RETRY"),
        ("DENIED", "SAME_EFFECT_ALIAS"), ("DECLARED", "VERIFIED"),
        ("INDECIDABLE", "ALLOW"), ("DISABLED_BY_POLICY", "RESOURCE_ERROR"),
        ("DELEGATED", "COMPLETED"), ("STALE_VERDICT", "ALLOW"),
        ("UNKNOWN_SCOPE", "EXECUTE"), ("CHILD_AUTHORITY", "GREATER_THAN_PARENT"),
        ("LEARNED_RULE", "POLICY_OVERRIDE"), ("MEMORY_WRITE", "AUTHORITY_GRANT"),
        ("AUTHORIZED_A", "EXECUTE_B"), ("TOCTOU", "EXECUTE"),
    ]
    for a, b in attendues:
        assert ES.transition_interdite(a, b), "transition %s -> %s non gardee" % (a, b)


def test_une_transition_ordinaire_reste_permise():
    """Contrôle négatif : le garde ne doit pas tout refuser."""
    assert ES.transition_interdite("REQUESTED", "AUTHORIZED") is None


# ----------------------------------------- racine de confiance et meta-effets

def test_une_boucle_d_auto_confiance_n_est_pas_une_racine():
    """Mesuré le 2026-09-12 sur le cas réel : `forge_tool_gate.py` protège les
    écritures du dépôt ET vit dans le dépôt. Le garde est modifiable par l'effet
    qu'il garde — la chaîne se referme au lieu d'atteindre une racine."""
    c = _classe_ideale()
    c.chaine_confiance = {
        "X": ES.NoeudConfiance("X", protege_par="gate de X"),
        "gate de X": ES.NoeudConfiance("gate de X", protege_par="X"),
    }
    assert c.cycles_de_confiance(), "cycle non detecte"
    etat = c.etat()
    assert etat["verdict"] == "NON_CERTIFIANT"
    assert etat["cycle_de_confiance"][0] == etat["cycle_de_confiance"][-1]


def test_un_meta_effet_non_protege_interdit_protected():
    """Pouvoir modifier le garde vaut pouvoir produire l'effet."""
    c = _classe_ideale()
    c.meta_effets = [ES.MetaEffet("gate de X", "gate.py", "WRITE", "")]
    etat = c.etat()
    assert etat["verdict"] == "NON_CERTIFIANT"
    assert "gate de X" in etat["meta_effets_non_proteges"]


def test_une_preuve_auto_certifiee_ne_compte_pas():
    """Producteur == observateur == vérificateur : la preuve est produite par la
    surface qui a intérêt au verdict."""
    c = _classe_ideale()
    c.preuve_roles = ES.Preuve3Roles("moi", "moi", "moi")
    assert c.preuve_roles.auto_certifiee() is True
    assert c.etat()["verdict"] == "NON_CERTIFIANT"


def test_absence_de_roles_declares_vaut_auto_certifiee():
    """`None` n'est pas neutre : sans rôles séparés, la preuve s'auto-certifie."""
    c = _classe_ideale()
    c.preuve_roles = None
    assert c.dimensions()["PROOF_NOT_SELF_CERTIFIED"] is False


def test_une_primitive_non_classee_rend_la_surface_incomplete():
    """« Le scanner a fini » n'est pas « il n'y a rien d'autre »."""
    c = _classe_ideale()
    c.primitives_non_classees = ["lien symbolique"]
    etat = c.etat()
    assert etat.get(ES.SURFACE_INCOMPLETE) is True
    assert etat["verdict"] == "NON_CERTIFIANT"


def test_les_surfaces_du_monde_non_couvertes_interdisent_protected():
    """Un DENY avec une surface non observée n'est pas un blocage prouvé."""
    c = _classe_ideale()
    c.surfaces_du_monde_couvertes = False
    assert c.dimensions()["WORLD_STATE_COVERAGE_PROVEN"] is False
    assert c.etat()["verdict"] == "NON_CERTIFIANT"


def test_toctou_non_joue_interdit_protected():
    """Interdire la transition ne vaut pas avoir joué le scénario."""
    c = _classe_ideale()
    c.toctou_joue = False
    assert c.dimensions()["TOCTOU_SAFE"] is False
    assert c.etat()["verdict"] == "NON_CERTIFIANT"


def test_sans_executor_unique_l_execution_n_est_pas_mediee():
    c = _classe_ideale()
    c.executor_unique = ""
    assert c.dimensions()["EXECUTION_MEDIATED"] is False


def test_les_douze_dimensions_sont_toutes_exposees():
    """Aucun score global : chaque axe doit rester lisible séparément."""
    d = _classe_ideale().etat()["dimensions"]
    assert set(d) == set(ES.DIMENSIONS), "dimensions manquantes ou en trop"
    assert len(ES.DIMENSIONS) == 12
