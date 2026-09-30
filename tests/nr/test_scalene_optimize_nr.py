# -*- coding: utf-8 -*-
"""NR — logique pure de forge_scalene_optimize (l'optimisation IA scalene en CLI).

On teste ce qui casse silencieusement l'outil si ça derive : extraction du JSON
scalene d'un flux melange, cout/classement des lignes, region a optimiser.
L'appel Ollama et le run scalene ne sont PAS testes ici (I/O) : ils sont couverts
par un run reel (--from-json) et par le mecanisme d'intention. Aucun reseau, aucun
subprocess dans ce test.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

import forge_scalene_optimize as O  # noqa: E402


def test_extraire_json_dans_flux_melange():
    # stdout scalene = sortie du programme PUIS le JSON.
    flux = "cpu : 42\nmem : 0\n{\"files\": {\"a.py\": {\"lines\": []}}}\n"
    obj = O._extraire(flux)
    assert obj is not None and "files" in obj


def test_extraire_ignore_un_json_sans_files():
    assert O._extraire('{"autre": 1} puis {"files": {}}')["files"] == {}


def test_extraire_rend_none_si_pas_de_json():
    assert O._extraire("aucun json ici") is None


def test_cout_somme_cpu_et_pondere_memoire():
    l = {"n_cpu_percent_python": 3, "n_cpu_percent_c": 20, "n_malloc_mb": 10}
    assert O._cout(l) == 3 + 20 + 0.5 * 10


def test_lignes_chaudes_classe_et_seuille():
    profil = {"files": {"a.py": {"lines": [
        {"lineno": 1, "line": "x\n", "n_cpu_percent_python": 0, "n_cpu_percent_c": 0, "n_malloc_mb": 0},
        {"lineno": 2, "line": "chaud\n", "n_cpu_percent_python": 5, "n_cpu_percent_c": 25, "n_malloc_mb": 4},
        {"lineno": 3, "line": "tiede\n", "n_cpu_percent_python": 0.5, "n_cpu_percent_c": 0.5, "n_malloc_mb": 0},
    ]}}}
    chaudes = O._lignes_chaudes(profil, top=5, seuil=2.0)
    assert [c[1]["lineno"] for c in chaudes] == [2]  # seule la ligne 2 depasse le seuil
    # la plus couteuse d'abord
    profil["files"]["a.py"]["lines"][2].update(n_cpu_percent_c=50)
    chaudes = O._lignes_chaudes(profil, top=5, seuil=2.0)
    assert chaudes[0][1]["lineno"] == 3


def test_region_prend_la_fonction_englobante():
    # Le LLM optimise BIEN mieux une unite complete : toute la fonction.
    src = ["x = 1\n", "def f():\n", "    for i in r:\n", "        s += i\n", "    return s\n"]
    region = O._region({"lineno": 4}, src)
    assert "def f" in region and "for i in r" in region and "s += i" in region
    assert "x = 1" not in region  # borne a la fonction, pas le module


def test_region_fallback_boucle_hors_fonction():
    # Pas de def englobant -> on retombe sur la boucle reperee par scalene.
    src = ["for i in r:\n", "    s += i\n", "    t += i\n"]
    region = O._region(
        {"lineno": 2, "start_outermost_loop": 1, "end_outermost_loop": 3}, src)
    assert "for i in r" in region and "s += i" in region


def test_ligne_optimisable_ecarte_import_def_commentaire():
    for muet in ("import numpy as np", "from x import y", "# note", "", "   ",
                 "def f():", "class C:", "@deco"):
        assert O._ligne_optimisable(muet) is False
    for vif in ("total += (i % 7) * 0.5", "a = np.random.rand(k, k)", "return sum(x)"):
        assert O._ligne_optimisable(vif) is True


def test_lignes_chaudes_ecarte_les_non_optimisables():
    profil = {"files": {"a.py": {"lines": [
        {"lineno": 1, "line": "import numpy as np\n", "n_cpu_percent_python": 0, "n_cpu_percent_c": 40, "n_malloc_mb": 0},
        {"lineno": 2, "line": "total += i\n", "n_cpu_percent_python": 3, "n_cpu_percent_c": 5, "n_malloc_mb": 0},
    ]}}}
    chaudes = O._lignes_chaudes(profil, top=5, seuil=2.0)
    # l'import (cout 40, le plus chaud) est ECARTE ; seule la vraie ligne reste.
    assert [c[1]["lineno"] for c in chaudes] == [2]


def test_region_fallback_contexte_sans_boucle():
    src = ["a\n", "b\n", "c\n", "d\n", "e\n"]
    ligne = {"lineno": 3}  # pas de boucle -> +/- 2
    region = O._region(ligne, src)
    assert "c\n" in region


def test_intention_consommee(tmp_path, monkeypatch):
    import json as _j
    (tmp_path / "sandbox").mkdir()
    wf = tmp_path / "sandbox" / "scalene_optimize.wanted"
    wf.write_text(_j.dumps({"model": "m32", "top": 2}), encoding="utf-8")
    # _intention resout dirname(dirname(abspath(__file__)))/sandbox/... : on fait
    # pointer abspath sur tmp/tools/x.py -> racine = tmp.
    monkeypatch.setattr(O.os.path, "abspath", lambda _p: str(tmp_path / "tools" / "x.py"))
    conf = O._intention()
    assert conf.get("model") == "m32" and conf.get("top") == 2
    assert not wf.exists()  # consommee : une intention ne se rejoue pas


def test_intention_absente_rend_vide(monkeypatch):
    monkeypatch.setattr(O.os.path, "abspath", lambda _p: r"Z:\nowhere\tools\x.py")
    assert O._intention() == {}


def test_lignes_chaudes_lit_la_source_du_fichier_reel(tmp_path):
    f = tmp_path / "cible.py"
    f.write_text("def g():\n    return HEAVY\n", encoding="utf-8")
    profil = {"files": {str(f): {"lines": [
        {"lineno": 2, "line": "PLACEHOLDER\n", "n_cpu_percent_c": 30,
         "n_cpu_percent_python": 0, "n_malloc_mb": 0},
    ]}}}
    _, _ligne, src = O._lignes_chaudes(profil, top=1, seuil=2.0)[0]
    assert any("HEAVY" in s for s in src)          # source lue du FICHIER
    assert not any("PLACEHOLDER" in s for s in src)  # pas le 'line' du JSON


def test_forge_scalene_demo_produit_les_trois_profils():
    """La cible de demo doit mixer CPU/memoire/numpy sans lever."""
    import forge_scalene_demo as D

    assert D.boucle_cpu(1000) > 0       # CPU pur (sans dependance)
    assert D.alloc_memoire(1000) == 0.0  # 1000 zeros -> somme 0.0
    # calcul_numpy fait un matmul BLAS : on ne l'INVOQUE pas ici (une install
    # numpy/MKL cassee -> Windows fatal exception 0xc06d007f, NON rattrapable et
    # tuant tout le process pytest). On atteste qu'il existe ; son effet reel est
    # exerce par le profil scalene, la ou l'env porte un numpy sain.
    assert callable(D.calcul_numpy)
