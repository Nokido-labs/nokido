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
    monkeypatch.setattr(K, "_activite_recente", lambda port: False)   # fenetre couverte sans decodage
    assert K._pilier_inutile(*EMBED, conns=0, up=True) is True


def test_un_embedder_qui_decode_entre_deux_lots_n_est_pas_inutile(perimee, monkeypatch):
    """15-16/10 (plan CI §3 bis, fait keeper_arrete_embedder_en_usage_sans_intention_20261015) : `conns == 0` A
    L'INSTANT du tick ne dit pas « oisif » -- un client par lots (pack natif 19:36:39, mesures du 16/10) est vu idle
    entre deux lots et l'embedder est coupe en plein travail. L'activite se juge sur une FENETRE (n_decode de /metrics)."""
    monkeypatch.setattr(K, "_dette_embed", lambda: 0)
    monkeypatch.setattr(K, "_activite_recente", lambda port: True, raising=False)
    assert K._pilier_inutile(*EMBED, conns=0, up=True) is False


def test_sous_pression_ram_un_embedder_qui_decode_n_est_pas_idle(monkeypatch):
    """L'arret RELLEMENT journalise le 15/10 (logs/supervisor/NokidoLlamaKeeper.log, 19:36:39 « sans intention +
    idle + ram 86% >= 80% », en plein pack natif) passe par la branche PRESSION RAM de `_piliers_on_demand`, pas par
    `_pilier_inutile` : `conns == 0` au tick y suffisait aussi. Un pilier qui a decode sur la fenetre n'est pas idle."""
    monkeypatch.setattr(K, "_PILIERS", (EMBED,))
    monkeypatch.setattr(K, "_supervisor_claimed", lambda: {8099: "NokidoLlamaEmbed"})
    monkeypatch.setattr(K, "_intention_voulue", lambda _d, **_k: False)
    monkeypatch.setattr(K, "_pilier_accorde", lambda _d: True)
    monkeypatch.setattr(K, "_observer_signal", lambda _s: None)
    monkeypatch.setattr(K, "_conns_port", lambda _p: 0)
    monkeypatch.setattr(K, "_dette_embed", lambda: 0)
    monkeypatch.setattr(K, "_intention_perimee", lambda _d, **_k: True)
    monkeypatch.setattr(K, "_activite_recente", lambda _p: True)
    monkeypatch.setattr(K, "MONITOR_ONLY", True)
    actes = K._piliers_on_demand(ram=K.FREE_AT + 6)
    assert not [a for a in actes if "stopped" in a], actes


def test_activite_illisible_interdit_l_arret(perimee, monkeypatch):
    monkeypatch.setattr(K, "_dette_embed", lambda: 0)
    monkeypatch.setattr(K, "_activite_recente", lambda port: None)
    assert K._pilier_inutile(*EMBED, conns=0, up=True) is False


def _releves(monkeypatch, releves):
    """Rejoue des couples (instant, compteur /metrics) sans reseau ni horloge reelle."""
    import types

    file = list(releves)
    courant = {}

    def compteur(port):
        courant["t"], n = file.pop(0)
        return n

    monkeypatch.setattr(K, "_compteur_metrics", compteur)
    monkeypatch.setattr(K, "time", types.SimpleNamespace(time=lambda: courant["t"]))
    monkeypatch.setattr(K, "_echantillons_activite", {})
    return [K._activite_recente(8099) for _ in releves]


def test_metrics_illisible_rend_inconnu(monkeypatch):
    assert _releves(monkeypatch, [(0.0, None)]) == [None]


def test_fenetre_non_couverte_rend_inconnu(monkeypatch):
    f = K._FENETRE_ACTIVITE_S
    assert _releves(monkeypatch, [(0.0, 5.0), (f / 3, 5.0)]) == [None, None]


def test_fenetre_couverte_sans_decodage_rend_oisif(monkeypatch):
    f = K._FENETRE_ACTIVITE_S
    assert _releves(monkeypatch, [(0.0, 5.0), (f, 5.0)])[-1] is False


def test_un_lot_dans_la_fenetre_rend_actif(monkeypatch):
    f = K._FENETRE_ACTIVITE_S
    assert _releves(monkeypatch, [(0.0, 5.0), (f / 3, 9.0), (f, 9.0)])[-1] is True


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
