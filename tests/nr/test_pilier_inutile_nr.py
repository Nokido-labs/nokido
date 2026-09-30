# -*- coding: utf-8 -*-
"""NR — decharge des piliers RAG sur INUTILITE (forge_llama_keeper._pilier_inutile).

Mesure 2026-08-19 : reranker :8100 (1,43 Go) et embedder :8099 (3,23 Go) tournaient
avec `rerank.wanted` perime depuis 1137 s et ZERO connexion — la decharge existait
mais etait conditionnee a `ram >= FREE_AT` (80 %), or la RAM etait retombee a 58 %.
Reguler sur la seule pression, c'est attendre la detresse pour agir.

Ce qui est teste ici, ce sont surtout les cas ou il ne faut PAS couper : un garde
qui coupe a tort se fait desarmer dans la semaine.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_llama_keeper as K  # noqa: E402

RERANK = ("NokidoLlamaReranker", 8100, "rerank.wanted")
EMBED = ("NokidoLlamaEmbed", 8099, "embed.wanted")


@pytest.fixture
def perimee(monkeypatch):
    monkeypatch.setattr(K, "_intention_perimee", lambda _d, **_k: True)


def test_reranker_perime_et_oisif_est_inutile(perimee):
    assert K._pilier_inutile(*RERANK, conns=0, up=True) is True


def test_qui_sert_n_est_jamais_inutile(perimee):
    assert K._pilier_inutile(*RERANK, conns=2, up=True) is False


def test_deja_eteint_rien_a_faire(perimee):
    assert K._pilier_inutile(*RERANK, conns=0, up=False) is False


def test_intention_fraiche_protege(monkeypatch):
    monkeypatch.setattr(K, "_intention_perimee", lambda _d, **_k: False)
    assert K._pilier_inutile(*RERANK, conns=0, up=True) is False


def test_intention_absente_ne_touche_pas_a_l_outil_de_l_owner(monkeypatch):
    """Drapeau ABSENT = Nokido n'a JAMAIS demande ce backend : s'il tourne, c'est
    l'owner qui l'a lance. On ne retire pas un outil des mains de son proprietaire."""
    monkeypatch.setattr(K, "_intention_perimee", lambda _d, **_k: None)
    assert K._pilier_inutile(*RERANK, conns=0, up=True) is False


def test_embedder_protege_tant_qu_il_reste_de_la_dette(perimee, monkeypatch):
    """Le drain travaille par rafales : conns=0 a l'instant du tick ne veut pas
    dire oisif. Couper la relance le cercle du 2026-08-10 (embedder eteint ->
    drain ne demarre pas -> la dette ne peut que croitre)."""
    monkeypatch.setattr(K, "_dette_embed", lambda: 4200)
    assert K._pilier_inutile(*EMBED, conns=0, up=True) is False


def test_embedder_liberable_quand_la_dette_est_resorbee(perimee, monkeypatch):
    monkeypatch.setattr(K, "_dette_embed", lambda: 0)
    assert K._pilier_inutile(*EMBED, conns=0, up=True) is True


def test_capteur_de_dette_muet_interdit_l_arret(perimee, monkeypatch):
    """-1 = capteur ILLISIBLE. Une non-mesure n'autorise pas un arret : sinon on
    coupe l'embedder sur une absence de mesure au lieu d'une mesure d'absence."""
    monkeypatch.setattr(K, "_dette_embed", lambda: -1)
    assert K._pilier_inutile(*EMBED, conns=0, up=True) is False


def test_le_garde_dette_ne_s_applique_qu_a_l_embedder(perimee, monkeypatch):
    """Le reranker n'a pas besoin du garde : perte BORNEE (-0.10 R@1) et deux
    filets (Cohere, lexical). Une dette d'embedding ne doit pas le proteger."""
    monkeypatch.setattr(K, "_dette_embed", lambda: 99999)
    assert K._pilier_inutile(*RERANK, conns=0, up=True) is True
