"""NR — la campagne qui pose l'observation du routeur sur son canal reel.

`forge_patch_router_observation` deplace l'appel a `forge_retrieval_router.observer`
depuis `RAGEngine.search()` — que `rag action=search` n'emprunte PAS — vers
`handle_rag`/`_rag_dense_search`, le chemin reellement pris. Un garde pose a cote
de son canal ne garde rien : le journal restait vide et `forge_router_replay`
rendait `lues: 0`.

Ces tests tiennent que le patch soit DEJA applique ou non : ils portent sur les
proprietes de la campagne, pas sur l'etat du disque a un instant donne.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _campagne():
    chemin = ROOT / "tools" / "forge_patch_router_observation.py"
    if not chemin.exists():
        pytest.skip("campagne absente")
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location("forge_patch_router_observation",
                                                  chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_forge_patch_router_observation_reste_en_shadow():
    """Le patch OBSERVE, il n'ACTIVE pas : aucune decision de routage appliquee.

    L'activation doit rester une DONNEE (`LAFORGE_ROUTER_MODE`). Si le remplacement
    branchait la RouteDecision sur le resultat, il changerait le comportement de la
    recherche sous couvert d'observabilite.
    """
    m = _campagne()
    assert "_rt_observer(" in m.APRES, "le patch doit poser l'observation"
    assert "_rt_decider(" in m.APRES
    # La decision ne doit jamais etre utilisee pour trier ou filtrer le resultat.
    for interdit in ("_res = _rt_", "docs = _rt_", "sort(", "filter("):
        assert interdit not in m.APRES, (
            "le patch modifie le resultat au lieu de seulement l'observer : %s"
            % interdit)


def test_forge_patch_router_observation_journalise_en_warning():
    """Le bloc d'origine loggait en `debug` — invisible en production, ce qui a
    masque le probleme. Un echec d'observation doit s'entendre."""
    m = _campagne()
    assert ".warning(" in m.APRES
    assert ".debug(" not in m.APRES, "un debug se perd : le silence a deja coute"


def test_forge_patch_router_observation_preserve_le_retour():
    """Le patch capture le resultat et le REND : ne rien casser sur le chemin chaud."""
    m = _campagne()
    assert "_res = await" in m.APRES and "return _res" in m.APRES


def test_forge_patch_router_observation_est_idempotent():
    """Sentinelle presente dans le remplacement : rejouer la campagne ne double
    jamais le bloc (garantie du harnais `forge_patch_muted_paths`)."""
    m = _campagne()
    assert m.SENTINELLE and m.SENTINELLE in m.APRES
    assert m.SENTINELLE not in m.AVANT


def test_forge_patch_router_observation_cible_le_bon_chemin():
    """L'ancre vise `_rag_dense_search` — le chemin que `rag search` emprunte
    vraiment, pas `RAGEngine.search()` ou vivait le cablage inefficace."""
    m = _campagne()
    assert "_rag_dense_search" in m.AVANT
    assert m.CIBLE.name == "forge_mcp_registry.py"


def test_le_patch_est_applique_ou_l_ancre_existe_encore():
    """Trois etats, jamais deux : applique · applicable · NI L'UN NI L'AUTRE.

    Ce dernier cas est le seul dangereux — il signifie que la cible a change et
    que la campagne ne mordra plus, sans que personne ne le sache.
    """
    m = _campagne()
    if not m.CIBLE.exists():
        pytest.skip("cible absente de cet arbre")
    src = m.CIBLE.read_text(encoding="utf-8", errors="replace")
    applique = m.SENTINELLE in src
    applicable = src.count(m.AVANT) == 1
    assert applique or applicable, (
        "ni sentinelle ni ancre : la campagne est devenue inoperante sur cette "
        "cible — a reecrire avant de compter dessus")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
