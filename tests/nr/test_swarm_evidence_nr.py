# -*- coding: utf-8 -*-
"""Le swarm compte des preuves, pas des voix -- verrouillage.

Chaque test ici correspond a une maniere CONNUE de se tromper en agregeant des
reponses de LLM. Ce ne sont pas des tests de forme : ils echouent si l'arbitre
se remet a voter.
"""
from __future__ import annotations

import pytest

from app.forge_swarm_evidence import (
    CONTESTED, PROPOSED, REJECTED, SUPPORTED, UNKNOWN,
    AUTH, GENERATION_EMPTY, PATCH_INVALID, QUOTA, SECURITY_REJECTION,
    TEST_FAILURE, TRANSPORT_TIMEOUT, PROVIDER_UNAVAILABLE,
    Tentative, arbitrer, classer_erreur, famille_modele,
    groupe_independance, strategie_reprise,
)


def _t(modele, solution, tests=None, preuves=(), strategie="", erreur=None,
       transport_ok=True):
    return Tentative(modele=modele, solution_id=solution, test_ok=tests,
                     preuves=list(preuves), strategie=strategie, erreur=erreur,
                     transport_ok=transport_ok)


# --- 1. Un echec de transport ne dit RIEN de la tache ---------------------

@pytest.mark.parametrize("message,attendu", [
    ("Read timed out after 60s", TRANSPORT_TIMEOUT),
    ("HTTP 429 Too Many Requests", "RATE_LIMIT"),
    ("401 Unauthorized", AUTH),
    ("cle ECARTEE par la rotation", QUOTA),
    ("HTTP 503 server busy", PROVIDER_UNAVAILABLE),
    ("REFUS DU GARDE DE MUTATION -- classe perdue", SECURITY_REJECTION),
    ("patch failed: does not apply", PATCH_INVALID),
    ("AssertionError: expected 3", TEST_FAILURE),
    ("", GENERATION_EMPTY),
    (None, GENERATION_EMPTY),
])
def test_classes_ancrees_sur_des_messages_reels(message, attendu):
    assert classer_erreur(message) == attendu


def test_securite_avant_format():
    """Un refus de garde cite souvent le format. La sûrete doit gagner."""
    assert classer_erreur("REFUS DU GARDE: format SEARCH/REPLACE suspect") == SECURITY_REJECTION


def test_un_refus_de_surete_ne_se_retente_jamais():
    s = strategie_reprise(SECURITY_REJECTION)
    assert s["autre_provider"] is False and s["meme_provider"] is False, (
        "retenter un refus de sûrete jusqu'a passer, c'est contourner le garde")
    assert s["escalade"] is True


def test_quota_change_de_source_mais_pas_de_tache():
    s = strategie_reprise(QUOTA)
    assert s["autre_provider"] is True and s["meme_provider"] is False


def test_echec_de_tache_reste_exploitable():
    s = strategie_reprise(TEST_FAILURE)
    assert s["escalade"] is True and s["autre_provider"] is True


# --- 2. L'independance : trois routes, une voix ---------------------------

@pytest.mark.parametrize("modele,famille", [
    ("claude-opus-5", "anthropic"),
    ("anthropic/claude-sonnet-5", "anthropic"),
    ("gpt-5.6-terra", "openai"),
    ("gemini-3-pro", "google"),
    ("mistral-large-latest", "mistral"),
    ("qwen3-coder-30b", "qwen"),
])
def test_familles_cognitives(modele, famille):
    assert famille_modele(modele) == famille


def test_meme_modele_par_trois_passerelles_est_une_seule_voix():
    """Le coeur du sujet : openrouter/together/direct servent le MEME modele."""
    voix = {groupe_independance(m) for m in
            ("claude-opus-5", "anthropic/claude-opus-5", "openrouter:claude-opus-5")}
    assert len(voix) == 1


def test_meme_modele_sous_deux_angles_fait_deux_voix():
    """Un angle different apporte une information neuve, contrairement a une
    simple redirection reseau."""
    a = groupe_independance("qwen3-coder", "corriger_minimalement")
    b = groupe_independance("qwen3-coder", "cause_racine")
    assert a != b


def test_deux_modeles_inconnus_ne_sont_pas_fondus_ensemble():
    assert groupe_independance("modele-maison-a") != groupe_independance("modele-maison-b")


# --- 3. L'arbitrage ne vote pas ------------------------------------------

def test_aucune_quantite_d_accord_ne_renverse_un_refus_de_surete():
    v = arbitrer([
        _t("claude-opus-5", "A", tests=True, preuves=["test::x"]),
        _t("mistral-large", "A", tests=True, preuves=["test::x"]),
        _t("qwen3", "A", tests=True, preuves=["test::x"]),
        _t("gemini-3", None, erreur="REFUS DU GARDE: secret en clair"),
    ])
    assert v.etat == REJECTED and v.action == "abstain"


def test_un_timeout_ne_vote_ni_pour_ni_contre():
    v = arbitrer([
        _t("gemini-3", "", erreur="Read timed out", transport_ok=False),
        _t("groq-llama", "", erreur="ECARTEE par la rotation", transport_ok=False),
    ])
    assert v.etat == UNKNOWN and v.action == "retry"
    assert "ne disent rien de la tache" in v.motif


def test_trois_echos_du_meme_modele_ne_font_pas_un_consensus():
    """Trois routes vers Claude, tests verts : PROUVEE mais UNE seule voix."""
    v = arbitrer([
        _t("claude-opus-5", "A", tests=True, preuves=["test::x"]),
        _t("anthropic/claude-opus-5", "A", tests=True, preuves=["test::x"]),
        _t("openrouter:claude-opus-5", "A", tests=True, preuves=["test::x"]),
    ], min_voix=2)
    assert v.voix_independantes == 1
    assert v.etat == PROPOSED and v.action == "challenge"


def test_deux_familles_distinctes_soutiennent_reellement():
    v = arbitrer([
        _t("claude-opus-5", "A", tests=True, preuves=["test::x"]),
        _t("qwen3-coder", "A", tests=True, preuves=["test::x"]),
    ], min_voix=2)
    assert v.etat == SUPPORTED and v.action == "accept" and v.solution == "A"


def test_la_preuve_bat_la_popularite():
    """Trois modeles disent A sans preuve ; un seul dit B, tests verts. B gagne."""
    v = arbitrer([
        _t("claude-opus-5", "A"),
        _t("gemini-3", "A"),
        _t("mistral-large", "A"),
        _t("qwen3-coder", "B", tests=True, preuves=["test::b", "ast::sym"]),
    ], min_voix=1)
    assert v.solution == "B", "la majorite l'a emporte sur la preuve"


def test_deux_solutions_prouvees_donnent_un_desaccord_pas_un_gagnant():
    v = arbitrer([
        _t("claude-opus-5", "A", tests=True, preuves=["test::a"]),
        _t("mistral-large", "A", tests=True, preuves=["test::a"]),
        _t("qwen3-coder", "B", tests=True, preuves=["test::b"]),
    ], min_voix=1)
    assert v.etat == CONTESTED and v.action == "challenge", (
        "3 contre 1 a tranche a la majorite alors que les deux sont prouvees")


def test_sans_preuve_deterministe_on_s_abstient():
    v = arbitrer([
        _t("claude-opus-5", "A"),
        _t("qwen3-coder", "B"),
        _t("mistral-large", "C"),
    ])
    assert v.etat == UNKNOWN and v.action == "abstain"
    assert "REUSSITE" in v.motif


def test_toutes_rouges_est_un_rejet_franc():
    v = arbitrer([
        _t("claude-opus-5", "A", tests=False),
        _t("qwen3-coder", "B", tests=False),
    ])
    assert v.etat == REJECTED and v.action == "retry"


def test_un_seul_etat_autorise_a_conclure():
    """Asymetrie : si un autre etat se met a rendre `accept`, ce test tombe."""
    cas = [
        [_t("claude-opus-5", "A")],                                   # UNKNOWN
        [_t("claude-opus-5", "A", tests=False)],                      # REJECTED
        [_t("c", "", erreur="timeout", transport_ok=False)],          # UNKNOWN
        [_t("claude-opus-5", "A", tests=True, preuves=["t::a"]),
         _t("qwen3", "B", tests=True, preuves=["t::b"])],             # CONTESTED
    ]
    for tentatives in cas:
        v = arbitrer(tentatives, min_voix=2)
        assert v.action != "accept", "%s a conclu sans soutien prouve" % v.etat


def test_un_test_non_mesure_n_est_pas_un_test_vert():
    """`test_ok=None` veut dire NON MESURE. Il ne doit jamais valoir True."""
    v = arbitrer([
        _t("claude-opus-5", "A", tests=None, preuves=["ast::sym"]),
        _t("qwen3-coder", "A", tests=None, preuves=["ast::sym"]),
    ], min_voix=2)
    assert v.action != "accept"
