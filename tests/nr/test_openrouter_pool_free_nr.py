"""NR — pool OpenRouter gratuit : mesure du catalogue, pas confiance au nom.

Trois régressions gardées ici, toutes payées avant le 2026-09-01 :

1. `list_free_models` filtrait sur le prix d'ENTRÉE seul, avec en plus un
   `or ":free" in id` : un modèle free-in / paid-out passait, et un slug `:free`
   retiré passait aussi. C'est croire un NOM plutôt qu'une MESURE.
2. Le filtre par prix seul laisse entrer des modèles qui ne servent aucune
   cascade de texte (lyria sort de l'audio, content-safety est un classifieur
   sans tool-calling). Mesure du 2026-09-01 : 21 gratuits, 18 utilisables.
3. `refresh_openrouter_free_slugs` ANNONÇAIT mettre à jour le routeur et se
   contentait de journaliser un compte — récepteur déclaré, écriture absente.
   Le slot restait donc figé sur UN slug, point de défaillance unique.

Zéro service externe : le catalogue est un faux objet, `urlopen` est remplacé,
et le slot global est restauré après chaque test.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))


def _catalogue() -> dict:
    """Catalogue calqué sur la forme RÉELLE mesurée le 2026-09-01."""
    return {"data": [
        {"id": "openrouter/free", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"output_modalities": ["text"]}, "supported_parameters": ["tools"]},
        {"id": "z-ai/glm-5.2:free", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"output_modalities": ["text"]}, "supported_parameters": ["tools"]},
        # sortie AUDIO : gratuit, mais inutilisable dans une cascade de texte
        {"id": "google/lyria-3-pro-preview", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"output_modalities": ["text", "audio"]}, "supported_parameters": []},
        # classifieur : pas de tool-calling annoncé
        {"id": "nvidia/nemotron-3.5-content-safety:free", "pricing": {"prompt": "0", "completion": "0"},
         "architecture": {"output_modalities": ["text"]}, "supported_parameters": []},
        # LE piège : entrée gratuite, sortie PAYANTE
        {"id": "piege/free-in-paid-out:free", "pricing": {"prompt": "0", "completion": "0.0000012"},
         "architecture": {"output_modalities": ["text"]}, "supported_parameters": ["tools"]},
        {"id": "cher/modele", "pricing": {"prompt": "0.000003", "completion": "0.000009"},
         "architecture": {"output_modalities": ["text"]}, "supported_parameters": ["tools"]},
    ]}


class _Reponse:
    def __init__(self, blob: bytes) -> None:
        self._blob = blob

    def read(self) -> bytes:
        return self._blob

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> bool:
        return False


@pytest.fixture
def openrouter(monkeypatch):
    import forge_openrouter
    monkeypatch.setattr(forge_openrouter, "_get_key", lambda: "sk-test", raising=False)
    return forge_openrouter


@pytest.fixture
def slot_restaure():
    """Le slot est un dict GLOBAL : le rendre tel quel après le test."""
    from forge_llm_router import PROVIDERS
    origine = list(PROVIDERS["openrouter_free"]["models"])
    yield PROVIDERS
    PROVIDERS["openrouter_free"]["models"] = origine


def _servir(monkeypatch, charge: dict) -> None:
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _Reponse(json.dumps(charge).encode()))


def test_pool_filtre_sur_le_prix_entree_ET_sortie(openrouter, monkeypatch):
    _servir(monkeypatch, _catalogue())
    pool = openrouter.list_free_models()

    assert "piege/free-in-paid-out:free" not in pool, (
        "sortie payante retenue : le filtre est retombé sur le prix d'entrée seul")
    assert "cher/modele" not in pool
    assert "z-ai/glm-5.2:free" in pool


def test_pool_ecarte_ce_qui_ne_sert_aucune_cascade_de_texte(openrouter, monkeypatch):
    _servir(monkeypatch, _catalogue())
    pool = openrouter.list_free_models()

    assert "google/lyria-3-pro-preview" not in pool, "sortie audio admise dans la cascade"
    assert "nvidia/nemotron-3.5-content-safety:free" not in pool, "modèle sans tool-calling admis"
    # chat_only=False = filtre PRIX seul : les deux reviennent
    large = openrouter.list_free_models(chat_only=False)
    assert "google/lyria-3-pro-preview" in large


def test_routeur_serveur_en_tete_du_pool(openrouter, monkeypatch):
    _servir(monkeypatch, _catalogue())
    pool = openrouter.list_free_models()

    assert pool[0] == "openrouter/free", (
        "`openrouter/free` doit mener : c'est le seul slug qui survive au retrait "
        "d'un modèle, OpenRouter choisissant lui-même")


def test_catalogue_injoignable_ne_vaut_pas_pool_vide(openrouter, monkeypatch, slot_restaure):
    def _coupe(*_a, **_k):
        raise OSError("reseau coupe")

    monkeypatch.setattr(urllib.request, "urlopen", _coupe)
    assert openrouter.list_free_models() == []

    import forge_agent_proxy
    avant = list(slot_restaure["openrouter_free"]["models"])
    assert forge_agent_proxy.refresh_openrouter_free_slugs() == 0
    assert slot_restaure["openrouter_free"]["models"] == avant, (
        "un catalogue muet a VIDÉ le slot : un silence n'est pas une mesure")


def test_le_rafraichisseur_ECRIT_vraiment_dans_le_slot(openrouter, monkeypatch, slot_restaure):
    _servir(monkeypatch, _catalogue())
    import forge_agent_proxy

    n = forge_agent_proxy.refresh_openrouter_free_slugs()
    modeles = slot_restaure["openrouter_free"]["models"]

    assert n == 2, f"pool attendu de 2 modèles utilisables, rendu {n}"
    assert modeles == ["openrouter/openrouter/free", "openrouter/z-ai/glm-5.2:free"], (
        "le rafraîchisseur n'a pas écrit le pool dans le slot — c'était le défaut "
        "d'avant le 2026-09-01 : il journalisait un compte et rien d'autre")
    assert len(modeles) > 1, "un slot à un seul slug est un point de défaillance unique"


def test_socle_hors_ligne_du_slot_respecte_la_convention_litellm():
    """Sans réseau, le slot doit déjà porter des slugs appelables tels quels."""
    from forge_llm_router import PROVIDERS

    modeles = PROVIDERS["openrouter_free"]["models"]
    assert modeles[0] == "openrouter/openrouter/free", (
        "litellm attend le préfixe fournisseur : get_llm_provider("
        "'openrouter/openrouter/free') rend ('openrouter/free', 'openrouter')")
    assert all(m.startswith("openrouter/") for m in modeles)
