# -*- coding: utf-8 -*-
"""NR — corpus de classification des signaux d'agent, et la dette qu'il borne.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la classification report vs verdict"

POURQUOI CE CORPUS (2026-09-07). Trois remontées M2M `ERR_TEST_FAIL` en un jour, **trois
causes différentes, zéro test en échec** : un gate `capacites` rouge, un `ui-acceptance`
jamais mesuré, une étape interrompue sans conclusion. Et symétriquement un exécuteur qui
rend `FAILURE / timeout waiting for response` sur **deux travaux réellement accomplis**.

`forge_swarm_evidence.classer_erreur` est la bonne brique — sa thèse est écrite depuis le
2026-08-20 : *« un timeout de transport n'est pas un verdict sur le problème »*. Mais la
MESURE dit qu'elle n'est pas encore un oracle utilisable pour la CI :

    'ERR_TEST_FAIL'   -> TEST_FAILURE      elle LIT L'ETIQUETTE ET CONCLUT
    '' / None         -> GENERATION_EMPTY  l'absence devient une classe SUBSTANTIELLE
    'assert 1 == 2'   -> UNKNOWN           un vrai echec de test n'est pas reconnu

Les deux premiers cas violent les propriétés visées :
  * `intent` seul n'est JAMAIS un verdict ;
  * moins d'information doit donner `UNKNOWN`, jamais un défaut plausible (monotonie).

Ce fichier ne corrige rien. Il **verrouille le comportement actuel** pour qu'aucune
régression ne passe, et il **borne la dette** : dès qu'un cas est réparé, le test de
dette rougit et force la mise à jour du corpus. C'est le socle du test différentiel
Python <-> WASM à venir — un composant ne doit pas hériter des deux défauts ci-dessus.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_swarm_evidence as ev  # noqa: E402

# (entree, classe VISEE par la doctrine, classe MESUREE aujourd'hui) — 2026-09-07.
# Les entrées viennent toutes d'observations RÉELLES de la nuit, aucune n'est inventée.
CORPUS = [
    ("timeout waiting for response",                      "TRANSPORT_TIMEOUT", "TRANSPORT_TIMEOUT"),
    ("1 gate(s) bloquant(s) en echec",                    "CI_FAILURE",        "UNKNOWN"),
    ("assert 1 == 2",                                     "TEST_FAILURE",      "UNKNOWN"),
    ("UNKNOWN - interface injoignable, contrat NON JUGE", "UNKNOWN",           "UNKNOWN"),
    ("Process completed with exit code 1",                "UNKNOWN",           "UNKNOWN"),
    ("ERR_TEST_FAIL",                                     "UNKNOWN",           "TEST_FAILURE"),
    ("Contrat d'acceptation UI : step sans conclusion",   "INTERRUPTED",       "UNKNOWN"),
    ("",                                                  "UNKNOWN",           "GENERATION_EMPTY"),
    (None,                                                "UNKNOWN",           "GENERATION_EMPTY"),
]

DETTE_CONNUE = {texte for texte, vise, mesure in CORPUS if vise != mesure}


def test_le_comportement_mesure_ne_regresse_pas() -> None:
    """Cliquet : la colonne MESUREE est la vérité du jour, pas un souhait."""
    for texte, _vise, mesure in CORPUS:
        assert ev.classer_erreur(texte) == mesure, (
            "classification de %r modifiee sans mise a jour du corpus" % (texte,))


def test_la_dette_est_bornee_et_nommee() -> None:
    """Si un cas est REPARE, ce test rougit et force la mise a jour du corpus.

    Une dette qu'on ne compte pas se referme en silence — ou grossit en silence."""
    reelle = {texte for texte, vise, _m in CORPUS
              if ev.classer_erreur(texte) != vise}
    assert reelle == DETTE_CONNUE, (
        "l'ecart doctrine/mesure a change. Repare : %s | Apparu : %s"
        % (sorted(DETTE_CONNUE - reelle), sorted(reelle - DETTE_CONNUE)))
    # SIX, pas cinq : `''` et `None` sont DEUX entrees distinctes. Le compte ecrit
    # a la main disait cinq, ce test l'a corrige a son premier passage — un chiffre
    # qu'on n'a pas fait compter par la machine est une estimation.
    assert len(DETTE_CONNUE) == 6, "six ecarts mesures le 2026-09-07"


def test_l_etiquette_ne_doit_pas_suffire_a_conclure() -> None:
    """PROPRIETE VISEE, aujourd'hui VIOLEE — documentee, pas masquee.

    `ERR_TEST_FAIL` est un nom d'intention, pas une observation. Le classifier le lit
    et rend `TEST_FAILURE` : sur les trois runs du 2026-09-07 il aurait donc CONFIRME
    l'erreur au lieu de l'attraper. Le test constate l'etat present et nomme la cible ;
    quand la propriete sera tenue, il faudra basculer l'assertion."""
    assert ev.classer_erreur("ERR_TEST_FAIL") == "TEST_FAILURE", (
        "si ceci a change, la propriete `intent seul != verdict` est peut-etre tenue : "
        "basculer ce test sur UNKNOWN et retirer l'entree du corpus de dette")


def test_moins_d_information_ne_doit_pas_donner_plus_de_certitude() -> None:
    """MONOTONIE, aujourd'hui VIOLEE sur l'entree vide.

    `''` et `None` rendent `GENERATION_EMPTY`, une affirmation SUBSTANTIELLE (« le
    generateur n'a rien produit ») la ou l'on n'a rien observe du tout. La classe est
    juste dans son contexte d'origine et fausse des qu'on s'en sert comme classifieur
    general de signal."""
    for vide in ("", None):
        assert ev.classer_erreur(vide) == "GENERATION_EMPTY", (
            "si ceci rend UNKNOWN, la monotonie est tenue : mettre le corpus a jour")


def test_le_seul_cas_deja_juste_est_le_transport() -> None:
    """Ce que la brique fait DEJA bien, et qu'il ne faut pas casser en l'etendant.

    C'est le cas qui aurait redresse le verdict de l'executeur AGY : deux travaux
    reellement accomplis rapportes en FAILURE parce que le CANAL avait expire."""
    assert ev.classer_erreur("timeout waiting for response") == "TRANSPORT_TIMEOUT"
    strat = ev.strategie_reprise("TRANSPORT_TIMEOUT")
    assert strat.get("escalade") is False, (
        "un timeout de transport ne dit RIEN sur la tache : il ne doit pas escalader")


def test_la_classe_inconnue_reste_honnete() -> None:
    """Le defaut du module est bon et doit le rester : ne rien affirmer."""
    strat = ev.strategie_reprise("UNKNOWN")
    assert strat.get("escalade") is True
    assert "ne rien affirmer" in strat.get("motif", ""), (
        "la classe inconnue doit garder tout ouvert, jamais trancher")


def test_le_corpus_ne_contient_que_des_observations_reelles() -> None:
    """Garde-fou de methode : pas de taxonomie « au cas ou ».

    Chaque entree vient d'une observation datee du 2026-09-07 (runs 34039560199,
    34047222436, 34072606903, et les deux retours de l'executeur de taches)."""
    assert len(CORPUS) == 9
    assert len({t for t, _v, _m in CORPUS}) == 9, "aucun doublon"
    vises = {v for _t, v, _m in CORPUS}
    assert vises <= {"TRANSPORT_TIMEOUT", "CI_FAILURE", "TEST_FAILURE",
                     "INTERRUPTED", "UNKNOWN"}, (
        "quatre classes utiles plus UNKNOWN : n'en ajouter qu'a la demande d'une "
        "observation reelle")
