# -*- coding: utf-8 -*-
"""NR — un depot portant un chemin invalide sous Windows se clone quand meme.

Mesure du 2026-09-23 : `searxng/searxng` contient
`utils/templates/etc/httpd/sites-available/searxng.conf:socket`. Sous NTFS le `:`
est interdit : git clone reussit, le CHECKOUT echoue, et la veille entiere du
depot est perdue pour un seul fichier de configuration.

Contrat : le chemin invalide est EXCLU et NOMME ; tout le reste est extrait.
Le cas est reproduit sur un vrai depot git local : Windows ne sait pas creer
`a:b.txt`, mais git l'inscrit dans son arbre par plomberie (`update-index
--cacheinfo`) -- exactement la forme qui a casse searxng.
"""
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

# PAYE LE 2026-09-29 (CI de reference d9d7a6fd2) : `git archive` en sous-processus a depasse
# les 30 s du timeout par test, et le thread de pytest-timeout a tue TOUTE la suite pure
# (SUITE_INCOMPLETE, aucun echec). Un vrai git sous charge n'a pas de duree bornee a 30 s :
# meme borne que ses voisins de clone (test_veille_substance_nr, test_veille_intake_autolance_nr).
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
V = importlib.import_module("forge_veille_clone_ingest")


def _g(repo, *a, entree=None):
    return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(repo)] + list(a),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", input=entree).stdout.strip()


def test_chemins_invalides_reconnus():
    ok = ["src/main.py", "docs/a b.md", "x.conf"]
    ko = ["etc/searxng.conf:socket", "a/b?c", "CON", "dir/nul.txt", "fin.", "fin "]
    assert V.chemins_invalides_windows(ok + ko) == ko


def test_depot_avec_chemin_invalide_se_clone_sans_lui(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _g(src, "init", "-q", "-b", "main")
    _g(src, "config", "user.email", "t@t")
    _g(src, "config", "user.name", "t")
    (src / "valide.py").write_text("print(1)\n", encoding="utf-8")
    _g(src, "add", "valide.py")
    blob = _g(src, "hash-object", "-w", "--stdin", entree="socket\n")
    # protectNTFS refuse d'INSCRIRE un tel chemin sous Windows : la fixture le
    # desactive pour l'inscription seulement -- le clone, lui, garde le defaut,
    # exactement comme face a un depot concu sous Linux.
    _g(src, "-c", "core.protectNTFS=false", "update-index", "--add", "--cacheinfo",
       "100644,%s,conf/app.conf:socket" % blob)
    _g(src, "-c", "core.protectNTFS=false", "commit", "-q", "-m", "c")
    # CONTRE-EPREUVE : sans elle, une fixture qui aurait perdu le chemin rendrait
    # ce test vert sur un clone trivial (mesure : c'est arrive a la 1re version).
    assert "conf/app.conf:socket" in _g(src, "ls-tree", "-r", "--name-only", "HEAD")
    dst = tmp_path / "dst"
    assert V.clone(src.as_uri(), str(dst)) is True
    assert (dst / "valide.py").read_text(encoding="utf-8").strip() == "print(1)"
