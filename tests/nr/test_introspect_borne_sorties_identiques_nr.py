# -*- coding: utf-8 -*-
"""NR : l'optimisation d'introspect ne change PAS ses sorties, et ne fige aucune lecture.

- jeu d'or : sorties JSON des 5 questions reelles (28/10) posees AVANT toute modification de
  app/forge_introspect.py, dans tests/nr/data/introspect_or_q<N>.json ; comparaison OCTET POUR OCTET.
  (Regenerer : `python -m pytest -m mesure tests/nr/test_introspect_borne_sorties_identiques_nr.py -k ecrire`.)
- « fichier modifie relu » : un fichier edite entre deux appels est relu (pas de cache de duree processus).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parent / "data"
for _p in (str(ROOT / "app"), str(ROOT / "tools"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.nr.test_introspect_bench_mesure import QUESTIONS  # noqa: E402


def _rendu(q: str) -> bytes:
    from app import forge_introspect as fi
    return json.dumps(fi.introspect(q), ensure_ascii=False, indent=1).encode("utf-8")


@pytest.mark.mesure
def test_ecrire_le_jeu_d_or(request):
    if "mesure" not in (request.config.getoption("-m") or ""):
        pytest.skip("ecriture du jeu d'or : lancer avec -m mesure")
    DATA.mkdir(exist_ok=True)
    for i, q in enumerate(QUESTIONS, 1):
        (DATA / ("introspect_or_q%d.json" % i)).write_bytes(_rendu(q))


@pytest.mark.mesure
@pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
def test_sortie_identique_au_jeu_d_or(n):
    """28/10 (integrateur) : introspect lit le depot VIVANT -- ses sorties changent a chaque commit. La comparaison
    au jeu d'or prouve l'equivalence AVANT/APRES une optimisation, sur un meme etat du depot ; en suite permanente
    elle casserait au commit suivant. D'ou `mesure` : ecrire le jeu d'or, optimiser, comparer, dans la meme passe."""
    f = DATA / ("introspect_or_q%d.json" % n)
    if not f.exists():
        pytest.skip("jeu d'or absent : l'ecrire d'abord (-m mesure -k ecrire), sur le meme etat du depot")
    attendu = f.read_bytes()
    assert _rendu(QUESTIONS[n - 1]) == attendu


def test_un_fichier_modifie_entre_deux_appels_est_relu(tmp_path, monkeypatch):
    import forge_callgraph_jit as CG
    from app import forge_introspect as fi
    repo = tmp_path / "depot"
    (repo / "app").mkdir(parents=True)
    (repo / "tools").mkdir()
    f = repo / "app" / "forge_cible.py"
    f.write_text("def aiguille_relue():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(CG, "ROOT", repo)
    monkeypatch.setattr(CG, "_SCAN_ROOTS", ("app", "tools"))
    absent = tmp_path / "absent.json"

    def appel():
        return fi.introspect("aiguille_relue", jit=CG, index_enquetes=absent, oplog=absent)

    r1 = appel()
    assert [s["definitions"][0]["line"] for s in r1["symboles_trouves"]] == [1]
    f.write_text("# ligne ajoutee\n\ndef aiguille_relue():\n    return 2\n", encoding="utf-8")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    r2 = appel()
    assert [s["definitions"][0]["line"] for s in r2["symboles_trouves"]] == [3], r2["symboles_trouves"]
