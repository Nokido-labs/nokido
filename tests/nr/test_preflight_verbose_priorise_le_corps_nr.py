"""NR — `preflight_check_verbose` place les lecons du CORPS avant les sources tierces.

POURQUOI CE NR EXISTE : j'ai corrige la mauvaise fonction.

Le 2026-09-20 j'ai filtre les sources tierces dans `preflight_check` (3771eb8fd).
Mesure des appelants reels, faite APRES :

    preflight_check_verbose  ->  forge_dsl · forge_epistemic_veille ·
                                 forge_extern_patterns · forge_grounder ·
                                 forge_debate_job · forge_rag_llama_query ·
                                 forge_rescue · forge_self_patcher ·
                                 nokido_hub:4245 · bench_rag        = 10 sites
    preflight_check          ->  app/nokido_core.py:1458             = 1 site

Le corps passe donc par la version VERBOSE, qui n'avait aucun filtre de
provenance. C'est le motif « le correctif etait juste et applique au jumeau
mort » (2026-09-20), paye une seconde fois dans la meme journee.

⚠️ ET IL Y A TROIS `preflight_check` HOMONYMES dans le depot :
    forge_self_correction.preflight_check(action, context)   <- RAG, le notre
    forge_snapshot.preflight_check(mode)                     <- snapshot
    forge_ps_sandbox.preflight_check(code)                   <- sandbox
Un grep sur le NOM seul ne distingue pas les trois.

POURQUOI TRIER ET NON FILTRER, contrairement a `preflight_check`. La version
verbose rend la `source` de CHAQUE resultat -- l'appelant peut decider. Elle sert
aussi a `bench_rag`, qui mesure le RAPPEL : y supprimer des lignes fausserait la
mesure. On reordonne donc (corps d'abord) et on MARQUE l'origine, sans rien
retirer. L'appelant qui prend `results[0]` obtient le corps ; celui qui veut tout
garde tout.

PORTEE DITE : ce NR garde l'ORDRE et le MARQUAGE. Il ne juge ni la pertinence
semantique, ni le score, ni le `tier`.
"""
from __future__ import annotations

import pytest


def _module():
    for nom in ("nokido_agent.app.forge_self_correction", "app.forge_self_correction",
                "forge_self_correction"):
        try:
            mod = __import__(nom, fromlist=["preflight_check_verbose"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "preflight_check_verbose"):
            return mod
    pytest.skip("forge_self_correction introuvable sous ses trois noms d'import")


def _niveaux(monkeypatch, mod, resultats):
    """Les TROIS niveaux rendent la meme chose : patcher le premier seul
    laisserait le repli produire le resultat (faux vert)."""
    for nom in ("_ragengine_search", "_fts5_search", "_like_fallback"):
        monkeypatch.setattr(mod, nom, lambda q, limit=5, _r=resultats: list(_r),
                            raising=False)


# Forme REELLE relevee sur le chemin d'execution, sans prefixe `gitingest:`.
TIERS = (26.35, "//example.com/card' const AGENT_CARD_PATH = ...",
         "gemini_cli/packages/core/src/agents/a2a-client.ts")
CORPS = (12.0, "SOLUTION : le jeton doit etre lu depuis le coffre du hub",
         "session:2026-09-13:solution")


def test_le_corps_passe_devant_meme_avec_un_score_INFERIEUR(monkeypatch):
    """LE COEUR. Le tiers a le meilleur score et doit quand meme ceder la place.

    Sans cela, l'appelant qui prend `results[0]` -- c'est-a-dire la quasi-totalite
    des dix sites -- recoit du code tiers en guise de lecon.
    """
    mod = _module()
    _niveaux(monkeypatch, mod, [TIERS, CORPS])
    v = mod.preflight_check_verbose("401 unauthorized agent RESCUE ring -1 admin")
    assert v["results"], "aucun resultat rendu"
    assert "session:" in v["results"][0]["source"], (
        f"le tiers mieux score occupe la premiere place : {v['results'][0]['source']}")


def test_RIEN_n_est_supprime(monkeypatch):
    """On trie, on ne filtre pas : `bench_rag` mesure le rappel sur cette sortie."""
    mod = _module()
    _niveaux(monkeypatch, mod, [TIERS, CORPS])
    v = mod.preflight_check_verbose("401 unauthorized")
    assert len(v["results"]) == 2, (
        f"des resultats ont ete supprimes ({len(v['results'])}/2) -- cela fausserait "
        "la mesure de rappel de bench_rag")


def test_chaque_resultat_porte_son_ORIGINE(monkeypatch):
    """L'appelant doit pouvoir decider sans re-deviner le prefixe lui-meme."""
    mod = _module()
    _niveaux(monkeypatch, mod, [TIERS, CORPS])
    v = mod.preflight_check_verbose("401 unauthorized")
    for r in v["results"]:
        assert "du_corps" in r, f"resultat sans marquage d'origine : {r}"
    par_source = {r["source"]: r["du_corps"] for r in v["results"]}
    assert par_source["session:2026-09-13:solution"] is True
    assert par_source["gemini_cli/packages/core/src/agents/a2a-client.ts"] is False


def test_l_ordre_RELATIF_est_preserve_dans_chaque_groupe(monkeypatch):
    """Un tri stable : on remonte le corps, on ne rebat pas les cartes."""
    mod = _module()
    corps_fort = (30.0, "SOLUTION : A", "session:a:solution")
    corps_faible = (5.0, "SOLUTION : B", "session:b:solution")
    _niveaux(monkeypatch, mod, [corps_fort, TIERS, corps_faible])
    v = mod.preflight_check_verbose("q")
    srcs = [r["source"] for r in v["results"]]
    assert srcs.index("session:a:solution") < srcs.index("session:b:solution"), (
        f"l'ordre relatif du corps a ete casse : {srcs}")


def test_aucun_resultat_reste_aucun_resultat(monkeypatch):
    """Le tri ne doit pas fabriquer une reponse a partir d'un vide."""
    mod = _module()
    _niveaux(monkeypatch, mod, [])
    v = mod.preflight_check_verbose("question sans reponse")
    assert v["results"] == []
    assert v["tier"] == "none"
