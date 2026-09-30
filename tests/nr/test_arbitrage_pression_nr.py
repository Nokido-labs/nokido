# -*- coding: utf-8 -*-
"""NR — selecteur d'arbitrage adaptatif (forge_resource_manager.arbitrer_pression).

Test d'effet HERMETIQUE : la decision est PURE, aucun service touche, aucune
lecture disque. On atteste le COMPORTEMENT (quel demandeur sert-on selon l'etat),
pas l'existence du code. Chaque cas est un etat mesurable du corps.

Owner 2026-08-19 : « adaptatif selon l'effet recherche ». Les strategies :
  B_hyperemie     — interactif : l'organe qui sert garde sa place.
  C_consolidation — repos : le coder oisif cede pour que l'embedder draine.
  A_plancher/noop — rien a arbitrer.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "app"))

from forge_resource_manager import arbitrer_pression as A  # noqa: E402


def _d(**kw):
    """Etat de base = le DEADLOCK mesure le 2026-08-19 : repos, coder oisif a
    4,4 Go (conns=0), embedder affame (backlog 100k), 2 Go libres.

    CONTRAT ELARGI le 2026-09-02 : l'arbitre recoit desormais `demande_active`
    et `inutile_s`. Les deux valent ici « aucune demande » et « inactif depuis
    longtemps », ce qui EST l'etat du deadlock d'origine -- l'ancien appel les
    laissait implicites. Sans eux, l'arbitre protege (l'incertitude est
    conservatrice) et la branche de consolidation devient inatteignable.
    """
    base = dict(
        rhythm="CONSERVE", coder_up=True, coder_conns=0, chains_active=0,
        embed_wanted=True, backlog=100000, embedder_up=False,
        coder_ram_gb=4.4, free_gb=2.0, seuil_backlog=5000, seuil_confort_gb=5.0,
        demande_active=False, inutile_s=3600.0,
    )
    base.update(kw)
    return A(**base)


def test_repos_coder_oisif_embed_affame_cede():
    # Le cas qui a motive le cablage : le coder cede, l'embedder pourra charger.
    r = _d()
    assert r["action"] == "yield_coder"
    assert r["strategie"] == "C_consolidation"
    assert r["ram_gain_gb"] == 4.4


def test_coder_fraichement_allume_protege():
    # REGRESSION 2026-07-26 : coder allume par l'owner, conns pas encore
    # montees. NE JAMAIS l'evincer. Le garde a CHANGE DE NATURE le 2026-09-02
    # sans changer de but : ce n'est plus le rythme qui protege (`NORMAL`
    # protegeait TOUT, en permanence, meme un organe inactif depuis des heures)
    # mais le DELAI DE GRACE -- la duree continue a zero connexion, qui elle ne
    # triche pas.
    r = _d(rhythm="NORMAL", inutile_s=10.0)
    assert r["action"] == "protect_coder"
    assert r["strategie"] == "B_hyperemie"

def test_rythme_normal_ne_protege_plus_A_LUI_SEUL():
    # LE defaut corrige : eveille + rien qui travaille + inactif au-dela de la
    # grace => l'organe redevient arbitrable. Mesure du 2026-09-02 : `NORMAL`,
    # conns=0, chains=0, backlog 150x le seuil -> protege quand meme, avec pour
    # raison « l'organe qui SERT garde sa place » alors qu'il ne servait personne.
    r = _d(rhythm="NORMAL", inutile_s=3600.0)
    assert r["action"] == "yield_coder"

def test_une_demande_ouverte_protege_meme_inactif():
    # La demande n'evince jamais : elle ne fait qu'ajouter de la protection.
    r = _d(demande_active=True)
    assert r["action"] == "protect_coder"

def test_demande_INCONNUE_protege():
    # Un trou de telemetrie n'est pas une autorisation d'eteindre.
    r = _d(demande_active=None)
    assert r["action"] == "protect_coder"

def test_inactivite_INCONNUE_protege():
    r = _d(inutile_s=None)
    assert r["action"] == "protect_coder"


def test_coder_sert_protege_meme_au_repos():
    # Meme au repos, s'il a des connexions, il TRAVAILLE : hyperemie active.
    r = _d(coder_conns=3)
    assert r["action"] == "protect_coder"


def test_chaines_actives_protege():
    r = _d(chains_active=2)
    assert r["action"] == "protect_coder"


def test_conns_inconnu_ne_cede_jamais():
    # -1 = mesure MANQUANTE -> prudence, on n'evince pas sur une non-mesure.
    r = _d(coder_conns=-1)
    assert r["action"] != "yield_coder"


def test_place_suffisante_ne_cede_pas():
    # 8 Go libres : l'embedder peut charger A COTE, pas besoin d'evincer.
    r = _d(free_gb=8.0)
    assert r["action"] == "noop"


def test_backlog_faible_pas_affame():
    # Sous le seuil : l'assimilation n'est pas affamee, on ne perturbe rien.
    r = _d(backlog=10)
    assert r["action"] == "noop"


def test_embed_non_voulu_pas_affame():
    r = _d(embed_wanted=False)
    assert r["action"] == "noop"


def test_embedder_deja_up_rien_a_faire():
    r = _d(embedder_up=True)
    assert r["action"] == "noop"


def test_coder_absent_rien_a_liberer():
    r = _d(coder_up=False)
    assert r["action"] == "noop"


def test_decision_toujours_lisible():
    # Toute decision porte une raison non vide et les cles attendues.
    for kw in ({}, {"rhythm": "NORMAL"}, {"coder_conns": -1}, {"free_gb": 9.0},
               {"backlog": 0}, {"embed_wanted": False}):
        r = _d(**kw)
        assert set(r) >= {"strategie", "action", "cible", "ram_gain_gb", "raison"}
        assert r["raison"]
        assert r["action"] in {"protect_coder", "yield_coder", "noop"}


def test_seuil_confort_est_la_frontiere():
    # Juste sous le confort -> cede ; juste au-dessus -> pas besoin.
    assert _d(free_gb=4.9, seuil_confort_gb=5.0)["action"] == "yield_coder"
    assert _d(free_gb=5.1, seuil_confort_gb=5.0)["action"] == "noop"
