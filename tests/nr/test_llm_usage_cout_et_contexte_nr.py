"""NR A4 — semantique des COMPTEURS et des COUTS. Rouge avant implementation.

Deux faux etablis par la mesure du 2026-09-12 sur `token_usage`
(cf. `docs/baselines/chemins_entree_usage_2026-09-12.md`) :

  1. TOTAL FAUX. Une ligne Claude reelle porte `total_tokens = 4` alors que
     `cache_read_tokens = 433309`. `total = input + output` ignore le cache et
     sous-estime de cinq ordres de grandeur. Un champ ainsi nomme sera lu comme
     << la consommation >> par le premier tableau de bord venu.

  2. FAUX ZERO COMPTABLE. `cost_usd = 0.0` sur 4663 lignes sur 7859 (59 %),
     avec ZERO NULL. Le tarif inconnu et la gratuite reelle sont indiscernables :
     ollama (979) est gratuit, groq (1149) et gemini_cli (744) ne le sont pas,
     tous portent 0.0. Additionner cette colonne rend un cout fauxvement bas,
     et surtout faussement PRECIS.

D'ou trois etats pour le cout, comme pour la mesure :

    KNOWN            -> tarif applique, cost_usd = valeur
    FREE             -> gratuite PROUVEE, cost_usd = 0
    UNKNOWN_PRICING  -> pas de tarif fiable, cost_usd = NULL

`FREE` et `UNKNOWN_PRICING` produisent tous deux un affichage a 0 si on les
confond : c'est precisement pour cela qu'ils doivent etre distincts EN BASE, et
pas seulement dans le rendu.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

from forge_llm_usage_event import (  # noqa: E402
    COUTS,
    ErreurContrat,
    context_tokens,
    creer,
)

BASE = dict(
    execution_id="E1",
    provenance="CLAUDE",
    execution_mode="INTERACTIVE",
    transport="CLI_HTTP",
    provider="anthropic",
    model="claude-opus-5",
    measurement_kind="REPORTED",
    measurement_source="provider_usage",
)


def test_les_trois_etats_de_cout_existent():
    assert set(COUTS) == {"KNOWN", "FREE", "UNKNOWN_PRICING"}


def test_tarif_inconnu_rend_NULL_jamais_zero():
    ev = creer(**dict(BASE, cost_kind="UNKNOWN_PRICING"))
    assert ev["cost_usd"] is None, "un tarif inconnu qui vaut 0 se somme en silence"
    assert ev["cost_kind"] == "UNKNOWN_PRICING"


def test_gratuite_prouvee_vaut_zero_et_se_distingue():
    ev = creer(**dict(BASE, provider="ollama", cost_kind="FREE", cost_usd=0.0))
    assert ev["cost_usd"] == 0.0
    assert ev["cost_kind"] == "FREE"
    inconnu = creer(**dict(BASE, cost_kind="UNKNOWN_PRICING"))
    assert ev["cost_kind"] != inconnu["cost_kind"], (
        "FREE et UNKNOWN_PRICING doivent rester distincts EN BASE")


def test_un_cout_inconnu_ne_peut_pas_porter_de_valeur():
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, cost_kind="UNKNOWN_PRICING", cost_usd=0.0))
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, cost_kind="UNKNOWN_PRICING", cost_usd=1.25))


def test_un_cout_connu_exige_une_valeur():
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, cost_kind="KNOWN", cost_usd=None))
    ev = creer(**dict(BASE, cost_kind="KNOWN", cost_usd=0.0123,
                      cost_source="pricing_table"))
    assert ev["cost_usd"] == 0.0123
    assert ev["cost_source"] == "pricing_table"


def test_gratuite_annoncee_sans_zero_est_refusee():
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, cost_kind="FREE", cost_usd=None))
    with pytest.raises(ErreurContrat):
        creer(**dict(BASE, cost_kind="FREE", cost_usd=0.5))


def test_cout_non_declare_vaut_UNKNOWN_PRICING():
    ev = creer(**BASE)
    assert ev["cost_kind"] == "UNKNOWN_PRICING"
    assert ev["cost_usd"] is None


def test_verite_comptable_le_cas_reel_du_12_septembre():
    """in=2, CR=433309, CW=4874, out=2 : le contexte n'est PAS 4."""
    ev = creer(**dict(BASE, input_tokens=2, output_tokens=2,
                      cache_read_tokens=433309, cache_creation_tokens=4874))
    ctx = context_tokens(ev)
    assert ctx == 2 + 433309 + 4874 == 438185
    assert ctx != ev["input_tokens"] + ev["output_tokens"], (
        "le contexte traite ne se resume pas a input + output")
    assert "total_tokens" not in ev, (
        "pas de champ `total_tokens` ambigu dans l'evenement canonique : "
        "une metrique agregee doit porter une definition explicite")


def test_le_contexte_est_None_des_qu_un_composant_manque():
    partiel = creer(**dict(BASE, input_tokens=2, output_tokens=2,
                           cache_read_tokens=433309))
    assert context_tokens(partiel) is None, (
        "sommer en traitant l'inconnu comme 0 fabriquerait un contexte trop "
        "petit, presente avec la meme assurance qu'une mesure complete")


def test_le_contexte_d_un_evenement_non_mesure_est_None():
    ev = creer(**dict(BASE, measurement_kind="UNKNOWN", measurement_source=None))
    assert context_tokens(ev) is None


def test_cache_read_et_creation_restent_deux_grandeurs():
    ev = creer(**dict(BASE, input_tokens=2, output_tokens=2,
                      cache_read_tokens=433309, cache_creation_tokens=4874))
    assert ev["cache_read_tokens"] != ev["cache_creation_tokens"]
    assert context_tokens(ev) == 438185
