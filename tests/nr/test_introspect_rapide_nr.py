# -*- coding: utf-8 -*-
"""NR : introspect ne relit plus tout le depot a chaque appel (passe d'efficacite, owner 16/10 et 18/10).

Mesure du 2026-10-18 (cProfile, 3 questions, job_7f63b8339602) : introspect = 16 % du temps mural des outils MCP
sur 7 j (122 appels, p50 14,8 s, p95 128 s). Deux postes font presque tout :
  - forge_callgraph_jit._grep_files : grep en PYTHON pur (ripgrep absent du poste) -> 63 259 lectures de fichiers
    pour 3 questions ; l'outil natif existant `git grep` est present ;
  - forge_panorama_builder.scan_forge_modules : RE-PARSE les ~1 190 modules a chaque appel (ast.parse + ast.walk).
Regle owner : outil natif existant d'abord ; gain final MESURE, NR identique avant/apres.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT / "app"), str(ROOT / "tools"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_callgraph_jit as CG  # noqa: E402
import forge_panorama_builder as PB  # noqa: E402


def _git(repo, *a):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env=env)


def _depot(tmp_path):
    repo = tmp_path / "depot"
    (repo / "app").mkdir(parents=True)
    (repo / "tools").mkdir()
    (repo / "app" / "forge_a.py").write_text("def aiguille_cible():\n    return 1\n", encoding="utf-8")
    (repo / "tools" / "outil_b.py").write_text("x = 'rien ici'\n", encoding="utf-8")
    (repo / "tools" / "outil_c.py").write_text("from forge_a import aiguille_cible\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "v1")
    (repo / "app" / "forge_neuf.py").write_text("aiguille_cible()\n", encoding="utf-8")   # NON suivi
    return repo


def test_le_grep_passe_par_un_outil_natif_et_rend_le_meme_resultat(tmp_path, monkeypatch):
    repo = _depot(tmp_path)
    monkeypatch.setattr(CG, "ROOT", repo)
    monkeypatch.setattr(CG, "_SCAN_ROOTS", ("app", "tools"))
    attendu = {str(repo / "app" / "forge_a.py"), str(repo / "tools" / "outil_c.py"),
               str(repo / "app" / "forge_neuf.py")}
    lectures = []
    vrai = Path.read_text

    def compte(self, *a, **k):
        lectures.append(str(self))
        return vrai(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", compte)
    trouves = {str(Path(p)) for p in CG._grep_files("aiguille_cible")}
    assert trouves == attendu, trouves
    assert not lectures, "%d fichier(s) relus en Python : le grep natif n'est pas emprunte" % len(lectures)


def test_hors_racine_de_depot_le_repli_python_trouve_quand_meme(tmp_path, monkeypatch):
    """Mesure 18/10 : un ROOT qui n'est pas la racine d'un depot (dossier de test sous sandbox/, ignore par le
    depot parent) faisait rendre une liste VIDE a git grep -- 12 NR rouges. Le repli Python doit reprendre."""
    racine = tmp_path / "pas_un_depot"
    (racine / "app").mkdir(parents=True)
    (racine / "app" / "forge_q.py").write_text("def aiguille_isolee():\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(CG, "ROOT", racine)
    monkeypatch.setattr(CG, "_SCAN_ROOTS", ("app", "tools"))
    assert {str(Path(p)) for p in CG._grep_files("aiguille_isolee")} == {str(racine / "app" / "forge_q.py")}


def test_un_second_scan_ne_reparse_rien_et_un_fichier_modifie_est_reparse(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    (app / "forge_x.py").write_text("import forge_y\n", encoding="utf-8")
    (app / "forge_y.py").write_text("import os\n", encoding="utf-8")
    (app / "forge_z.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(PB, "APP_DIR", app)
    parses = []
    vrai = PB.ast.parse

    def compte(src, *a, **k):
        parses.append(k.get("filename"))
        return vrai(src, *a, **k)

    monkeypatch.setattr(PB.ast, "parse", compte)
    g1 = PB.scan_forge_modules(include_virtual_roots=False)
    assert g1["forge_x"] == {"forge_y"} and len(parses) == 3, (g1, parses)
    parses.clear()
    assert PB.scan_forge_modules(include_virtual_roots=False) == g1
    assert not parses, "second scan sans modification : %d fichier(s) re-parses" % len(parses)
    z = app / "forge_z.py"
    z.write_text("import forge_x\n", encoding="utf-8")
    st = z.stat()
    os.utime(z, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))
    g3 = PB.scan_forge_modules(include_virtual_roots=False)
    assert g3["forge_z"] == {"forge_x"}, g3
    assert len(parses) == 1, "seul le fichier modifie doit etre re-parse : %s" % parses
