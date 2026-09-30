"""NR — un mode ou le keeper SERT les piliers RAG sans TOUCHER au coder.

POURQUOI CE MODE EXISTE, mesure du 2026-09-20 :

`NokidoLlamaKeeper` est `disabled = true` depuis le 2026-09-05. Motif inscrit
dans services.toml :

    « rallumait le coder (4,8 Go) sur llama.wanted pose en boucle par
      forge_viable_system -> deadlock documente 19/08 »

Le defaut est donc UNE des sept sections de `tick()` -- la recharge du coder
(`_start_local()` sous `WANT_LOCAL`). Le gel a emporte les six autres, dont
`_piliers_on_demand`, seul consommateur de `rerank.wanted` et `embed.wanted`.
Consequence mesuree : :8100 ferme, `NokidoEpistemicSoif` en defer eternel,
dernier pouls du keeper `2026-09-05T20:36:02` -- la minute exacte de sa mort.

Un organe entier eteint pour un defaut sur UNE de ses fonctions.

CE QUE LE MODE DOIT GARANTIR, et c'est tout le contrat teste ici :
  - AUCUN `_kill` n'est atteignable (les trois sections coder qui tuent, plus le
    reconcile zombie-gap qui tue des listeners revendiques) ;
  - AUCUN `_start_local` (la section EXACTEMENT en cause dans le gel) ;
  - `_piliers_on_demand` est bien APPELE -- sinon le mode ne sert a rien, et un
    keeper qui tourne sans rallumer serait un faux calme de plus.

MONITOR_ONLY NE CONVIENT PAS, et c'est pour cela qu'un drapeau distinct existe :
il neutralise AUSSI les piliers (`if MONITOR_ONLY: return [would ...]`). Observer
n'est pas servir.

PORTEE DITE : ce NR ne demarre aucun service et ne juge pas l'etat de la machine.
Il verifie que le CHEMIN D'EXECUTION du mode n'atteint pas les primitives
destructrices -- une propriete du code, verifiable partout de la meme facon.
"""
from __future__ import annotations

import importlib
import os

import pytest


def _keeper(monkeypatch, piliers_only: bool):
    """Recharge le module avec l'environnement voulu.

    Le drapeau est lu au niveau module : sans `reload`, on testerait la valeur
    figee a la premiere importation -- et le test passerait pour de mauvaises
    raisons (« lire la valeur IMPORTEE, jamais le texte ecrit », 2026-09-20).
    """
    monkeypatch.setenv("LAFORGE_LLAMA_KEEPER_PILIERS_ONLY", "1" if piliers_only else "0")
    monkeypatch.setenv("LAFORGE_LLAMA_KEEPER_MONITOR_ONLY", "0")
    for nom in ("nokido_agent.tools.forge_llama_keeper", "tools.forge_llama_keeper",
                "forge_llama_keeper"):
        try:
            mod = importlib.import_module(nom)
        except Exception:  # noqa: BLE001
            continue
        return importlib.reload(mod)
    pytest.skip("forge_llama_keeper introuvable sous ses trois noms d'import")


def _tick_instrumente(monkeypatch, mod):
    """Fait tourner UN tick en enregistrant les primitives destructrices atteintes.

    On ne simule pas l'absence par un mock qui leve : un appel qui leve pourrait
    etre avale par un `except` et passer pour « pas appele ». On COMPTE.
    """
    appels: dict[str, int] = {"_kill": 0, "_start_local": 0, "_piliers_on_demand": 0}

    monkeypatch.setattr(mod, "_kill", lambda pid: appels.__setitem__(
        "_kill", appels["_kill"] + 1) or True, raising=False)
    monkeypatch.setattr(mod, "_start_local", lambda: appels.__setitem__(
        "_start_local", appels["_start_local"] + 1), raising=False)
    monkeypatch.setattr(mod, "_piliers_on_demand", lambda ram: appels.__setitem__(
        "_piliers_on_demand", appels["_piliers_on_demand"] + 1) or [], raising=False)

    # Un corps FICTIF qui declencherait TOUTES les sections coder si elles
    # tiraient : deux coders, zero connexion, RAM basse (donc recharge) et haute
    # (donc decharge) selon le cas. On force le pire cas possible.
    monkeypatch.setattr(mod, "_llama_pids", lambda: [(4_800_000_000, 111),
                                                     (4_800_000_000, 222)], raising=False)
    monkeypatch.setattr(mod, "_is_coder", lambda pid: True, raising=False)
    monkeypatch.setattr(mod, "_active_conns", lambda: 0, raising=False)
    monkeypatch.setattr(mod, "_ollama_child_pids", lambda pids: [], raising=False)
    monkeypatch.setattr(mod, "_gemma_up", lambda: False, raising=False)
    monkeypatch.setattr(mod, "_supervisor_claimed", lambda: {}, raising=False)
    monkeypatch.setattr(mod, "_intention_voulue", lambda *a, **k: False, raising=False)
    monkeypatch.setattr(mod, "_intention_perimee", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(mod, "_maj_inutilite", lambda conns, coder: 99_999, raising=False)
    monkeypatch.setattr(mod, "_drain_on_demand", lambda ram: [], raising=False)
    monkeypatch.setattr(mod, "_ollama_fige", lambda: None, raising=False)
    monkeypatch.setattr(mod, "WANT_LOCAL", True, raising=False)

    mod.tick()
    return appels


def test_le_drapeau_piliers_only_existe_et_est_lu_de_l_environnement(monkeypatch):
    """Garde l'instrument d'abord : sans le drapeau, les autres tests ne prouvent rien."""
    mod = _keeper(monkeypatch, piliers_only=True)
    assert hasattr(mod, "PILIERS_ONLY"), (
        "le mode n'existe pas : LAFORGE_LLAMA_KEEPER_PILIERS_ONLY n'est lu nulle part")
    assert mod.PILIERS_ONLY is True, (
        "le drapeau existe mais ne suit pas l'environnement -- valeur figee ?")


def test_en_mode_piliers_only_AUCUNE_primitive_destructrice_n_est_atteinte(monkeypatch):
    """LE COEUR DU CONTRAT : c'est ce qui rend le degel sûr."""
    mod = _keeper(monkeypatch, piliers_only=True)
    appels = _tick_instrumente(monkeypatch, mod)
    assert appels["_kill"] == 0, (
        f"_kill atteint {appels['_kill']} fois en mode piliers_only -- "
        "le mode ne protege pas le coder, donc il ne rend pas le degel sûr")
    assert appels["_start_local"] == 0, (
        "_start_local atteint : c'est EXACTEMENT la section citee dans le motif "
        "du gel du 2026-09-05 (« rallumait le coder sur llama.wanted en boucle »)")


def test_en_mode_piliers_only_les_piliers_sont_QUAND_MEME_servis(monkeypatch):
    """Le symetrique, sans lequel le mode serait un faux calme de plus."""
    mod = _keeper(monkeypatch, piliers_only=True)
    appels = _tick_instrumente(monkeypatch, mod)
    assert appels["_piliers_on_demand"] == 1, (
        "le mode n'appelle pas _piliers_on_demand : un keeper qui tourne sans "
        "rallumer ne rouvrirait jamais :8100, et rien ne le dirait")


def test_hors_mode_le_comportement_HISTORIQUE_est_intact(monkeypatch):
    """On AJOUTE un mode, on ne change pas celui qui existe.

    Sans ce test, un correctif qui neutraliserait le keeper en toutes
    circonstances passerait pour une reussite.
    """
    mod = _keeper(monkeypatch, piliers_only=False)
    appels = _tick_instrumente(monkeypatch, mod)
    assert appels["_kill"] > 0, (
        "hors mode piliers_only, le keeper ne tue plus les doublons coder -- "
        "le correctif a desarme la fonction historique au lieu de l'encadrer")
    assert appels["_piliers_on_demand"] == 1, (
        "les piliers ne sont plus servis hors du mode : regression")
