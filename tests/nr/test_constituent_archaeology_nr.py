#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tests/nr/test_constituent_archaeology_nr.py — la Phase 6 detecte-t-elle vraiment ?

Cas fondateur, mesure du 2026-08-16 : `tools/forge_regression_sweep.py` portait 12
axes au commit 14405a05 (683 LOC) et n'en porte plus que 3 (450 LOC). Aucun fichier
n'a ete supprime, le commit de reduction se presente comme un `feat`, la CI est
verte -- l'archeologie de Phase 1 (fichiers supprimes) ne pouvait rien en voir.

Ces tests fixent le comportement qui permet de le voir, et surtout les deux facons
de se tromper : confondre un USAGE retire avec une DEFINITION perdue, et confondre
un nom parti ailleurs avec un nom perdu.

Hermetiques : aucun acces git, aucun working tree (leçon du 2026-08-15).
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.136)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


# ── detecter : une DEFINITION supprimee, jamais un usage ────────────────────

def test_definition_supprimee_est_detectee():
    import forge_constituent_archaeology as A

    assert A.detecter("-def axe_workflows() -> None:") == ("fonction", "axe_workflows")
    assert A.detecter("-    async def _charger(self):") == ("fonction", "_charger")
    assert A.detecter("-class ProviderSlot:") == ("classe", "ProviderSlot")
    assert A.detecter("-export function routeTask(x) {") == ("fonction_js", "routeTask")


def test_entree_de_registre_supprimee_est_detectee():
    """C'est par la que sortent providers, tools, actions et routes -- sans qu'aucun
    fichier ne disparaisse."""
    import forge_constituent_archaeology as A

    assert A.detecter('-    "lmstudio_native": {') == ("entree_registre", "lmstudio_native")
    assert A.detecter('-    "poll": 3,') == ("entree_registre", "poll")


def test_usage_retire_nest_pas_une_perte():
    """`-  resultat = axe_tools()` est un appel retire, pas un constituant perdu.

    Les confondre ferait crier l'outil a chaque refactor et le rendrait inutile.
    """
    import forge_constituent_archaeology as A

    assert A.detecter("-    resultat = axe_tools()") is None
    assert A.detecter("-    from forge_llm_router import LLMRouter") is None
    assert A.detecter("+def axe_workflows():") is None  # ligne AJOUTEE
    assert A.detecter("-# def axe_mort(): ancien") is None


def test_ce_qui_nest_pas_un_nom_de_code_est_ecarte():
    """Le motif d'entree de registre capture toute cle `"x":`, donc aussi la doc.

    Mesure du 2026-08-16 : le palmares des orphelins etait occupe par ADR-001,
    B.3.1, Accept-Encoding et Access-Control-Allow-Origin -- rien qu'on puisse
    perdre. `mem.swap_pct`, lui, est un vrai canal de vitals : on le garde.
    """
    import forge_constituent_archaeology as A

    for faux in ("ADR-001", "B.3.1", "Accept-Encoding", "Access-Control-Allow-Origin"):
        assert not A.est_nom_de_code(faux), faux
        assert A.detecter(f'-    "{faux}": 1,') is None
    for vrai in ("lmstudio_native", "mem.swap_pct", "axe_workflows", "ToolRegistry"):
        assert A.est_nom_de_code(vrai), vrai


def test_noms_de_fichier_et_sigles_courts_ecartes():
    """Seconde passe du 2026-08-16 : une fois ADR-001 ecarte, le palmares s'est
    rempli de `CMakeLists.txt`, `Cargo.toml`, `EP`, `G`, `Ok` — des noms de fichier
    et des sigles d'une ou deux lettres, que personne ne peut « perdre »."""
    import forge_constituent_archaeology as A

    for faux in ("CMakeLists.txt", "Cargo.toml", "settings.json", "EP", "G", "Ok"):
        assert not A.est_nom_de_code(faux), faux


def test_dunder_et_noms_trop_courts_ignores():
    import forge_constituent_archaeology as A

    assert A.detecter("-def __init__(self):") is None
    assert A.detecter("-def ab():") is None


# ── classement : absence ici n'est pas perte ───────────────────────────────

def test_nom_revenu_dans_le_meme_depot_est_reecrit():
    import forge_constituent_archaeology as A

    etat, hotes = A.classer_constituant("axe_tools", "nokido", {"nokido": {"axe_tools"}})
    assert etat == "REECRIT" and hotes == ["nokido"]


def test_nom_vivant_ailleurs_est_migre_pas_disparu():
    """Une feature partie vers un autre depot n'est pas une perte (leçon Phase 1)."""
    import forge_constituent_archaeology as A

    etat, hotes = A.classer_constituant(
        "netcfg_ping", "nokido", {"nokido": set(), "netcfg-agent": {"netcfg_ping"}})
    assert etat == "MIGRE" and hotes == ["netcfg-agent"]


def test_nom_introuvable_partout_est_disparu():
    import forge_constituent_archaeology as A

    etat, hotes = A.classer_constituant(
        "axe_workflows", "nokido", {"nokido": {"axe_valeur_et_config"}, "autre": set()})
    assert etat == "DISPARU" and hotes == []


# ── bruit : ne jamais compter un vendor comme du patrimoine ────────────────

def test_le_bruit_est_ecarte():
    import forge_constituent_archaeology as A

    for c in ("app/_attic/vieux.py", "x/node_modules/y.js", "z/.venv/lib/m.py",
              "RAG/swebench/eval_repos/p/q.py", "tools/tmp_essai.py",
              "data/docsets/JavaScript.docset/a.js"):
        assert A._est_bruit(c), c
    for c in ("app/forge_llm_router.py", "tools/forge_regression_sweep.py"):
        assert not A._est_bruit(c), c


# ── observabilite : jamais « 0 disparu » sans avoir regarde ────────────────

def test_aucun_depot_lisible_rend_indetermine(tmp_path):
    """Un dossier sans git n'est pas un ecosysteme vide : c'est une non-mesure."""
    import forge_constituent_archaeology as A

    res = A.analyser({"faux": str(tmp_path)}, max_lignes=10)
    assert res.get("observable") is False
    assert "faux" in res.get("raison", "")


def test_depots_par_defaut_nomment_le_workspace():
    """Phase 1 declarait nokido-workspace ABSENT alors qu'il porte 786 disparus
    (56 % du total mesure le 2026-08-16). Le workspace doit etre dans le peigne."""
    import forge_constituent_archaeology as A

    assert "nokido-workspace" in A.DEPOTS_DEFAUT
    assert "nokido" in A.DEPOTS_DEFAUT
