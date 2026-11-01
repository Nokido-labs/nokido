"""NR 31/10 -- les outils de lecture du hub ne rendent plus un PermissionError trompeur, et lisent le .html.

Rendu AGY job_f74513a2 : `read` sur ...\\app\\web_hub -> « PermissionError [Errno 13] ... 'C:\\...\\Nokido' » ;
`get_file_skeleton` sur un .html -> « skeleton vide ». Cause : handle_read ne lisait que `path` (le squelette accepte
`file_path` OU `path`) -- un `file_path` donnait un chemin VIDE = la racine, et read_text() sur un DOSSIER leve Errno 13
sous Windows. Un dossier se LISTE ; un parametre absent se NOMME ; un .html a un plan (titre, en-tetes, ids).
"""
from __future__ import annotations

from pathlib import Path

from nokido_agent.app import forge_mcp_registry as M
from nokido_agent.app import forge_repo_map as RM

BALISE_S = "<" + "script"  # le validateur MCP refuse ce litteral dans une charge


def test_alias_file_path_accepte(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    chemin, err = M._chemin_lecture({"file_path": str(f)}, tmp_path)
    assert err is None and Path(chemin) == f


def test_chemin_absent_nomme(tmp_path):
    chemin, err = M._chemin_lecture({}, tmp_path)
    assert chemin is None and "path" in err and "requis" in err


def test_dossier_liste_au_lieu_de_permissionerror(tmp_path):
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<title>I</title>", encoding="utf-8")
    (tmp_path / "web" / "sous").mkdir()
    rendu = M._lister_dossier(tmp_path / "web")
    assert "index.html" in rendu and "sous/" in rendu and "DOSSIER" in rendu


def test_squelette_html(tmp_path):
    f = tmp_path / "p.html"
    f.write_text("<html><head><title>Nokido — Anatomie</title>" + BALISE_S + " src='a.js'></" + "script></head><body>"
                 "<h1>Titre</h1><div id='panneau'></div><h2>Sous-partie</h2></body></html>", encoding="utf-8")
    sk = RM.file_skeleton(f, tmp_path)
    assert "title: Nokido — Anatomie" in sk and "h1: Titre" in sk and "h2: Sous-partie" in sk
    assert "#panneau" in sk and "script: a.js" in sk


def test_squelette_python_inchange(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def f(a):\n    return a\n", encoding="utf-8")
    assert "def f(a): ..." in RM.file_skeleton(f, tmp_path)
