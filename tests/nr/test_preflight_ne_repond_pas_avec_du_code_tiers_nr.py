"""NR — une lecon du corps ne vient JAMAIS d'un depot tiers en veille.

MESURE DU 2026-09-20, sur une erreur REELLE tiree de `network_log` :

    erreur     ERR:401  agent=RESCUE  ring=-1   8 occurrences en 3 h
    fingerprint « 401 unauthorized agent RESCUE ring -1 admin »
    preflight_check(...) ->
        [PREFLIGHT] Match pour '401 unauthorized agent RESCUE ring -1 ad'
        (source=gemini_cli/packages/core/src/agents/a2a-, score=26.35)
        : //example.com/card'

Le raffineur a repondu avec un chunk de CODE TIERS (`gemini_cli`) contenant
`example.com/card`. Aucun rapport avec un 401. Le corps indexe 509 016 chunks de
depots tiers (`origin = 'external-lib'`) et le retrieval de lecons ne les
distingue pas de ses propres ancrages.

POURQUOI CE N EST PAS UN ACCIDENT. `preflight_check` ne rend `None` que si
`results` est VIDE, et son pipeline a trois niveaux se termine par
`_like_fallback`, decrit dans le module comme « fallback ultime, toujours
disponible ». Il est donc construit pour TOUJOURS rendre quelque chose : il ne
peut presque jamais dire « je ne sais pas ». Un retrieval qui ne rend jamais vide
transforme UNKNOWN en reponse affirmative -- c'est la faute que ce depot combat,
appliquee a sa propre memoire.

CE QUE CE NR NE FAIT PAS, et c'est delibere : il n'introduit AUCUN seuil de
score. Les trois niveaux (`RAGEngine`, `FTS5 BM25`, `LIKE`) rendent des scores
d'ECHELLES DIFFERENTES ; un seuil unique serait faux par construction, et je n'ai
pas mesure leurs distributions. On corrige ce qui est FACTUEL : la provenance.

PORTEE DITE : ce NR garde la PROVENANCE d'une reponse de preflight. Il ne juge ni
la pertinence semantique, ni le rappel, ni le classement.
"""
from __future__ import annotations

import pytest


def _module():
    for nom in ("nokido_agent.app.forge_self_correction", "app.forge_self_correction",
                "forge_self_correction"):
        try:
            mod = __import__(nom, fromlist=["preflight_check"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "preflight_check"):
            return mod
    pytest.skip("forge_self_correction introuvable sous ses trois noms d'import")


def _niveaux(monkeypatch, mod, resultats):
    """Force les TROIS niveaux du pipeline a rendre la meme chose.

    On patche les trois : patcher le premier seul laisserait le repli produire
    le resultat et le test passerait pour une mauvaise raison.
    """
    for nom in ("_ragengine_search", "_fts5_search", "_like_fallback"):
        monkeypatch.setattr(mod, nom, lambda q, limit=5, _r=resultats: list(_r),
                            raising=False)


# ⚠️ FIXTURE CORRIGEE APRES MESURE RUNTIME. Ma premiere version prefixait cette
# source de « gitingest: », d'apres la colonne generee `origin` de rag_chunks.
# La VRAIE source, relevee sur le chemin reel, n'a AUCUN prefixe :
#
#     (source=gemini_cli/packages/core/src/agents/a2a-, score=26.35)
#
# Le NR passait donc au vert sur des donnees que j'avais fabriquees, pendant que
# le correctif ne mordait pas en production. « Un durcissement non appele est une
# panne en attente » -- ici, un durcissement TESTE SUR LA MAUVAISE FORME.
#
# Et la mesure va plus loin : ces chunks portent `origin = 'laforge'` (31 416 pour
# gemini_cli, 6 080 en cold-legacy), parce que la regle CASE de rag_chunks ne
# classe `external-lib` que `source LIKE 'gitingest%'` et met tout le reste dans
# son ELSE. Le corps compte donc du code Google comme le sien.
# => une LISTE NOIRE de prefixes tiers est structurellement insuffisante ; seule
#    une LISTE BLANCHE des ancrages du corps tient (RULES_SHARED : « n'est sain
#    que ce qui est PROUVE sain »).
TIERS = [(26.35, "//example.com/card' const AGENT_CARD_PATH = ...",
          "gemini_cli/packages/core/src/agents/a2a-client.ts")]
CORPS = [(12.0, "SOLUTION : le jeton propre d'un organe doit etre accepte par /admin",
          "session:2026-09-20:solution")]


def test_une_reponse_issue_d_un_depot_TIERS_est_ecartee(monkeypatch):
    """LE COEUR DU CONTRAT.

    Mesure du jour : le raffineur a repondu `gemini_cli` a une question sur un
    401 du hub. Une lecon du corps ne peut pas naitre d'un depot en veille.
    """
    mod = _module()
    _niveaux(monkeypatch, mod, TIERS)
    r = mod.preflight_check("401 unauthorized agent RESCUE ring -1 admin")
    assert r is None or "gemini_cli" not in r, (
        f"le raffineur repond avec du code tiers : {r}")


def test_une_reponse_issue_du_CORPS_passe_toujours(monkeypatch):
    """Le symetrique, sans lequel filtrer trop large passerait pour un correctif."""
    mod = _module()
    _niveaux(monkeypatch, mod, CORPS)
    r = mod.preflight_check("401 unauthorized agent RESCUE ring -1 admin")
    assert r, "une lecon ancree par le corps a ete ecartee -- filtre trop large"
    assert "SOLUTION" in r or "jeton propre" in r


def test_quand_TOUT_est_tiers_le_raffineur_DIT_qu_il_ne_sait_pas(monkeypatch):
    """`UNKNOWN` doit rester `UNKNOWN`.

    Rendre le meilleur chunk tiers « faute de mieux » fabrique une reponse
    affirmative a partir d'une absence -- exactement ce qu'un `None` honnete
    evite.
    """
    mod = _module()
    _niveaux(monkeypatch, mod, TIERS)
    r = mod.preflight_check("question sans aucune lecon dans le corps")
    assert r is None, (
        f"le raffineur affirme alors qu'il n'a QUE des sources tierces : {r}")


def test_un_melange_garde_la_source_du_CORPS(monkeypatch):
    """Le tri doit preferer le corps, pas simplement rejeter en bloc."""
    mod = _module()
    _niveaux(monkeypatch, mod, TIERS + CORPS)   # le tiers a le MEILLEUR score
    r = mod.preflight_check("401 unauthorized agent RESCUE ring -1 admin")
    assert r, "un resultat du corps existait et rien n'a ete rendu"
    assert "gemini_cli" not in r, f"le tiers mieux score a gagne : {r}"
