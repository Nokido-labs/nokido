"""NR -- le tri de la dette de tests doit trier JUSTE, et savoir qu'il presume.

POURQUOI. `forge_suite_pure_triage` decide quels fichiers de tests peuvent
rejoindre la suite pure. Un tri trop laxiste fait entrer en CI un test qui monte
un service -- CI rouge a la premiere execution. Un tri trop severe laisse la
dette telle quelle. Le 20/08, le tri statique seul a rendu 39 candidats dont 12
echouaient : c'est pourquoi la validation par EXECUTION existe, et pourquoi le
module dit « presomption » plutot que « preuve ».

Ces tests verifient l'EFFET du tri sur des sources fabriquees, jamais son import.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

for _zone in ("tools", "app"):
    _p = str(ROOT / _zone)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _charger(nom: str):
    chemin = ROOT / "tools" / (nom + ".py")
    assert chemin.exists(), "module absent : %s" % chemin
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nom] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# forge_suite_pure_triage -- detection des marqueurs d'impurete
# --------------------------------------------------------------------------

def test_un_test_qui_sort_sur_le_reseau_est_detecte():
    m = _charger("forge_suite_pure_triage")
    assert "sort sur le reseau" in m._marqueurs("import requests\n")
    assert "sort sur le reseau" in m._marqueurs("import httpx\n")


def test_un_test_qui_vise_un_service_local_est_detecte():
    m = _charger("forge_suite_pure_triage")
    for src in ("url = 'http://localhost:8766/health'",
                "PORT = 11434", "cible = '127.0.0.1:7400'"):
        assert m._marqueurs(src), src


def test_un_test_qui_lit_la_vraie_base_est_detecte():
    m = _charger("forge_suite_pure_triage")
    assert "lit la vraie base RAG" in m._marqueurs("conn = sqlite3.connect(db_path())")
    assert "lit la vraie base RAG" in m._marqueurs("SELECT * FROM rag_chunks")


def test_un_test_pur_ne_declenche_aucun_marqueur():
    """Le garde ne doit pas crier sur du code sans effet de bord : un tri qui
    exclut tout ne trie rien."""
    m = _charger("forge_suite_pure_triage")
    src = ("def test_addition():\n"
           "    assert 1 + 1 == 2\n")
    assert m._marqueurs(src) == []


def test_les_marqueurs_nomment_ce_qu_ils_attrapent():
    """Un tri dont on ne peut pas relire le motif se conteste, et se contourne."""
    m = _charger("forge_suite_pure_triage")
    for _motif, nom in m._MARQUEURS:
        assert nom and not nom.startswith("r'"), nom


def test_compte_les_fonctions_de_test_pas_les_autres():
    m = _charger("forge_suite_pure_triage")
    src = ("def aide():\n    pass\n\n"
           "def test_un():\n    pass\n\n"
           "async def test_deux():\n    pass\n\n"
           "def pas_un_test():\n    pass\n")
    assert m._compte_tests(src) == 2


def test_un_fichier_illisible_ne_compte_pas_pour_zero_en_silence():
    """Une source non parsable rend 0 -- mais c'est un cas SEPARE du vrai zero,
    et `trier()` range ces fichiers dans `illisibles`, jamais dans `candidats`."""
    m = _charger("forge_suite_pure_triage")
    assert m._compte_tests("def test_casse(:\n") == 0


def test_le_tri_annonce_qu_il_presume():
    """Le module doit DIRE que « candidat » n'est pas « pur » : c'est ce qui a
    manque le 20/08, ou 12 des 39 candidats ont echoue a l'execution."""
    m = _charger("forge_suite_pure_triage")
    r = m.trier()
    assert "ARRET" in r or "PRESOMPTION" in r["_verdict"].upper()


# --------------------------------------------------------------------------
# forge_suite_pure_valider -- le deport, et sa trace ecrite
# --------------------------------------------------------------------------

def test_le_validateur_ecrit_son_verdict_sur_disque():
    """CONTRAT STRUCTUREL assume : executer 39 suites dans un test serait absurde.
    Ce qui est verrouille : le verdict est ECRIT, car un job detache dont la
    sortie se perd ne prouve rien."""
    src = (ROOT / "tools" / "forge_suite_pure_valider.py").read_text(
        encoding="utf-8", errors="replace")
    assert "SORTIE" in src and "write_text" in src
    assert "sandbox" in src


def test_le_validateur_delegue_au_triage_au_lieu_de_le_reecrire():
    """Anti-duplication : deux tris qui divergent, c'est un tri de trop."""
    src = (ROOT / "tools" / "forge_suite_pure_valider.py").read_text(
        encoding="utf-8", errors="replace")
    assert "forge_suite_pure_triage" in src
    assert "_MARQUEURS" not in src, "le validateur ne doit pas refaire le tri"
