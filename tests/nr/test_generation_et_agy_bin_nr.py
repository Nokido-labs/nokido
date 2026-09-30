# -*- coding: utf-8 -*-
"""Non-regression — registre de generations, et resolution du binaire AGY.

Deux modules neufs du 2026-08-28, tous deux exiges par le cliquet de couverture :
`forge_generation` et `forge_patch_agy_bin_resolution`.

CE QUI EST GARDE
================
1. Une generation ne se DECLARE pas stable, elle le DEDUIT de ses tests. C'est le
   contrat entier du module : le jour meme, un juge avait note OPTIMAL une tache
   dont tous les providers avaient echoue, parce qu'il notait la FORME du resultat
   et jamais son issue.
2. Une generation est IMMUABLE. Un etat valide qu'on peut reecrire n'est plus un
   point de retour, c'est un fichier d'etat de plus.
3. On ne restaure jamais tout seul : `plan_restauration` RECOMMANDE, il n'execute
   pas, et il verifie que les sha existent encore avant de promettre un retour.
4. La resolution du binaire AGY ne depend plus du seul PATH du process. Present-
   hors-PATH et absent rendaient le meme `WinError 2`, qui se lit « AGY n'est pas
   installe » alors que le fichier est la.

Hermetique : `DOSSIER` est detourne vers tmp_path, aucune generation reelle n'est
ecrite, aucun binaire n'est lance.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture()
def gen(tmp_path, monkeypatch):
    """Le module, avec son dossier de generations isole."""
    mod = pytest.importorskip("forge_generation")
    monkeypatch.setattr(mod, "DOSSIER", tmp_path / "generations")
    return mod


# ───────────────────────────────── le statut se DEDUIT

def test_suites_vertes_donnent_stable(gen):
    g = gen.capturer(tests={"nr": "PASS", "integration": "PASS"}, agent="TEST")
    assert g["statut"] == "STABLE", g["statut_raison"]


def test_une_suite_en_echec_rejette(gen):
    g = gen.capturer(tests={"nr": "PASS", "integration": "FAIL"}, agent="TEST")
    assert g["statut"] == "REJETEE", g


def test_une_suite_non_mesuree_ne_donne_pas_stable(gen):
    """LE point : « non mesure » n'est pas « vert ». Sans cette distinction, un
    etat non teste se declarerait bon et deviendrait une fausse reference."""
    g = gen.capturer(tests={"nr": "PASS", "integration": "NON_MESURE"}, agent="TEST")
    assert g["statut"] == "CANDIDATE", g


def test_sans_aucun_test_le_statut_reste_candidate(gen):
    g = gen.capturer(tests={}, agent="TEST")
    assert g["statut"] == "CANDIDATE"
    assert "aucune suite" in g["statut_raison"]


# ───────────────────────────────── une generation est IMMUABLE

def test_deux_captures_ne_se_marchent_pas_dessus(gen):
    a = gen.capturer(tests={"nr": "PASS"}, agent="TEST")
    b = gen.capturer(tests={"nr": "PASS"}, agent="TEST")
    assert a["generation"] != b["generation"], "la seconde capture a repris le meme numero"
    assert len(gen.lister()) == 2


def test_une_generation_existante_n_est_jamais_ecrasee(gen, tmp_path):
    g = gen.capturer(tests={"nr": "PASS"}, agent="TEST")
    chemin = (tmp_path / "generations") / ("%s.json" % g["generation"])
    assert chemin.exists()
    # on force la collision : le module doit REFUSER, pas reecrire
    monkey = gen._prochain_numero
    gen._prochain_numero = lambda: int(g["generation"].split("-")[1])
    try:
        with pytest.raises(FileExistsError):
            gen.capturer(tests={"nr": "PASS"}, agent="TEST")
    finally:
        gen._prochain_numero = monkey


def test_l_environnement_est_inscrit(gen):
    """Un meme sha ne se comporte pas pareil sous un autre torch : sans
    l'environnement, une generation n'est pas reproductible."""
    g = gen.capturer(tests={"nr": "PASS"}, agent="TEST")
    env = g["environnement"]
    assert env["python"] and env["executable"]
    assert set(env["paquets"]), "aucun paquet temoin releve"


# ───────────────────────────────── capture automatique idempotente

def test_capturer_si_absent_ne_double_pas_un_sha(gen, monkeypatch):
    """Le chainon de l'automatisation : relancer la CI sur le meme etat ne doit
    PAS empiler des generations. Sans ce garde, chaque run vert ferait du bruit."""
    monkeypatch.setattr(gen, "_git", lambda *a, **k: "shafixe123" if a[:1] == ("rev-parse",) else "")
    a = gen.capturer_si_absent(tests={"nr": "PASS"}, agent="CI")
    assert "skip" not in a, "la premiere capture d'un sha doit ecrire"
    b = gen.capturer_si_absent(tests={"nr": "PASS"}, agent="CI")
    assert b.get("skip"), "le meme sha a ete capture deux fois"
    assert len(gen.lister()) == 1


# ───────────────────────────────── restaurer se PROPOSE

def test_le_plan_ne_restaure_rien_et_previent(gen):
    g = gen.capturer(tests={"nr": "PASS"}, agent="TEST")
    plan = gen.plan_restauration(g["generation"])
    assert plan["commandes"], "aucune commande proposee"
    assert "irreversible" in plan["avertissement"]
    assert any("worktree" in c for c in plan["commandes"]), (
        "la restauration doit passer par un worktree : mesurer l'ancien etat sans "
        "ecraser le courant")


def test_plan_sur_generation_inconnue_refuse(gen):
    assert gen.plan_restauration("GEN-99999")["ok"] is False


def test_comparer_montre_les_ecarts(gen):
    a = gen.capturer(tests={"nr": "PASS"}, agent="TEST")
    b = gen.capturer(tests={"nr": "FAIL"}, agent="TEST")
    d = gen.comparer(a["generation"], b["generation"])
    assert d["ok"] and "nr" in d["tests_differents"]


def test_derniere_stable_ignore_les_candidates(gen):
    gen.capturer(tests={"nr": "PASS"}, agent="TEST")          # STABLE
    gen.capturer(tests={"nr": "NON_MESURE"}, agent="TEST")     # CANDIDATE
    assert gen.derniere_stable()["statut"] == "STABLE"


# ──────────────────── resolution du binaire AGY (forge_patch_agy_bin_resolution)

def test_la_resolution_agy_ne_depend_plus_du_seul_path():
    """EFFET du patcher `forge_patch_agy_bin_resolution` : le registry doit offrir
    un chemin explicite quand le PATH du compte de service ne montre pas `agy`.

    On lit le RESULTAT dans forge_mcp_registry plutot que d'executer le patcher :
    celui-ci agit au niveau module sur un CRITICAL_FILE, le rejouer dans un test
    modifierait le depot."""
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8", errors="replace")
    assert "agy_bin" in src, "resolution du binaire AGY introuvable (renommee ?)"
    debut = src.index("agy_bin")
    bloc = src[max(0, debut - 800):debut + 800]
    assert "LAFORGE_AGY_BIN" in bloc, (
        "la resolution est redevenue un `which` seul : sous le compte de service le "
        "PATH de l'owner n'existe pas, et un binaire PRESENT rendra le meme "
        "'WinError 2' qu'un binaire absent")


def test_le_patcher_agy_reste_idempotent_et_sur():
    """Le patcher doit refuser d'ecrire deux fois, et ne jamais ecrire un fichier
    qui ne compile pas. Verifie sur sa source : l'executer toucherait le depot."""
    p = ROOT / "tools" / "forge_patch_agy_bin_resolution.py"
    if not p.exists():
        pytest.skip("forge_patch_agy_bin_resolution absent de cette copie")
    src = p.read_text(encoding="utf-8", errors="replace")
    assert "already patched" in src, "aucune garde d'idempotence"
    assert "compile(" in src, "le patcher n'ecrit pas apres verification syntaxique"
    i_compile, i_write = src.index("compile("), src.rindex(".write(")
    assert i_compile < i_write, "compile() doit preceder l'ecriture, pas la suivre"
    assert "count(OLD)" in src or "text.count" in src, (
        "aucun controle d'unicite du motif : un remplacement multiple passerait")
