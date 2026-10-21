# -*- coding: utf-8 -*-
"""NR : callers/definitions servis par un INDEX par fichier en cache (mtime, taille), resultats IDENTIQUES.

Reprofil du 2026-10-18 a cache chaud (job_832140d725ed) : apres 4b12c1cbb, callers = 8,2 s sur 11 pour 3
questions d'introspect -- chaque appel re-parse les fichiers candidats (237 ast.parse) et re-parcourt chaque
fonction (ast.walk, 2,2 M noeuds ; les fonctions imbriquees parcourues plusieurs fois). Gain mesure alors x1,6,
SOUS le seuil owner de x2.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "app"), str(ROOT / "tools"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_callgraph_jit as CG  # noqa: E402

APPELANTS = '''from forge_cible import cible as _c
import forge_cible


def appel_direct():
    return _c()


def passe_en_ref():
    return list(map(_c, [1]))


def externe():
    def interne():
        return forge_cible.cible()
    return interne


class Porteur:
    def methode(self):
        return cible_absente_ici()

    def cible(self):
        return 3


def sans_lien():
    return 2
'''


def _depot(tmp_path):
    repo = tmp_path / "depot"
    (repo / "app").mkdir(parents=True)
    (repo / "tools").mkdir()
    (repo / "app" / "forge_cible.py").write_text("def cible():\n    return 1\n", encoding="utf-8")
    (repo / "app" / "forge_appelants.py").write_text(APPELANTS, encoding="utf-8")
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    for a in (["init", "-q"], ["config", "user.name", "t"], ["config", "user.email", "t@t.local"],
              ["add", "."], ["commit", "-q", "-m", "v1"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env=env)
    return repo


def _reference(nom):
    """L'algorithme d'AVANT, recalcule tel quel : parse + _local_aliases + walk + _ref_kind."""
    etat = CG.ambiguite(nom).get("etat", CG.ILLISIBLE)
    out = []
    for fp in CG._grep_files(nom)[:CG._MAX_CALLER_FILES]:
        tree = ast.parse(Path(fp).read_text(encoding="utf-8", errors="replace"))
        cibles = CG._local_aliases(tree, nom)
        rel = os.path.relpath(fp, CG.ROOT).replace("\\", "/")
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                k = CG._ref_kind(n, cibles)
                if k:
                    out.append({"file": rel, "caller": n.name, "line": n.lineno, "via": k, "resolution": etat})
    return out


def _cle(d):
    return tuple(sorted(d.items()))


def _prepare(tmp_path, monkeypatch):
    repo = _depot(tmp_path)
    monkeypatch.setattr(CG, "ROOT", repo)
    monkeypatch.setattr(CG, "_SCAN_ROOTS", ("app", "tools"))
    return repo


def test_callers_rend_exactement_le_resultat_de_l_ancien_algorithme(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    for nom in ("cible", "interne", "sans_lien"):
        assert sorted(map(_cle, CG.callers(nom))) == sorted(map(_cle, _reference(nom))), nom


def test_un_second_appel_ne_reparse_rien_et_definitions_partage_l_index(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    parses = []
    vrai = CG.ast.parse

    def compte(*a, **k):
        parses.append(1)
        return vrai(*a, **k)

    monkeypatch.setattr(CG.ast, "parse", compte)
    CG.callers("cible")
    CG.definitions("cible")
    parses.clear()
    r1, d1 = CG.callers("cible"), CG.definitions("cible")
    assert r1 and d1, (r1, d1)
    assert not parses, "%d re-parse(s) sur des fichiers inchanges" % len(parses)


def test_un_fichier_modifie_est_reindexe(tmp_path, monkeypatch):
    repo = _prepare(tmp_path, monkeypatch)
    avant = {d["caller"] for d in CG.callers("cible")}
    f = repo / "app" / "forge_appelants.py"
    f.write_text(APPELANTS + "\n\ndef nouvel_appelant():\n    return _c()\n", encoding="utf-8")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    apres = {d["caller"] for d in CG.callers("cible")}
    assert apres - avant == {"nouvel_appelant"}, (avant, apres)
