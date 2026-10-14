# -*- coding: utf-8 -*-
"""Trois chemins muets signales le 2026-10-09 (lots 6 et 7) : chacun DIT desormais ce qu'il ecarte.

- forge_runas_launcher._preparer_dossier : icacls en `text=True` sans `errors=` -- sa sortie est dans la page OEM de
  la console (cp850 sur un Windows francais), un octet indecodable levait UnicodeDecodeError et faisait tomber le
  lanceur des services runAs au lieu de rendre un rc ;
- forge_path_portabilize : un fichier suivi illisible etait saute par `except Exception: continue` -- le rapport
  annoncait « 0 fichier » sans dire ce qu'il n'avait pas lu ;
- multi_llm_daemon._full_desc : des `parameters` illisibles retombaient en silence sur `text`, que le hub tronque.
Chaque test emprunte le chemin reel (fonction appelee, main() avec ses arguments), pas une lecture du source.
"""
from __future__ import annotations

import ast
import builtins
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.timeout(60)


def _module(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, ROOT / chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_icacls_du_lanceur_ne_peut_plus_lever_sur_un_octet_oem(monkeypatch, tmp_path):
    m = _module("forge_runas_launcher_muet_nr", "tools/forge_runas_launcher.py")
    vus = {}

    class _R:
        returncode = 0

    def faux_run(cmd, **kw):
        vus.update(kw)
        return _R()

    monkeypatch.setattr(m.subprocess, "run", faux_run)
    assert m._preparer_dossier(tmp_path / "svc", "*S-1-5-21-1") is True
    assert vus.get("text") is True and vus.get("errors") == "replace", vus


def test_le_portabiliseur_dit_les_fichiers_qu_il_n_a_pas_lus(monkeypatch, tmp_path, capsys):
    m = _module("forge_path_portabilize_muet_nr", "tools/forge_path_portabilize.py")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ferme.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(m, "tracked_files", lambda: iter(["ferme.py"]))
    vrai_open = builtins.open

    def open_ferme(chemin, *a, **kw):
        if str(chemin) == "ferme.py":
            raise PermissionError(13, "Permission denied")
        return vrai_open(chemin, *a, **kw)

    monkeypatch.setattr(m, "open", open_ferme, raising=False)
    sortie = tmp_path / "rapport.json"
    monkeypatch.setattr(sys, "argv", ["forge_path_portabilize", "--out", str(sortie)])
    m.main()
    rapport = json.loads(sortie.read_text(encoding="utf-8"))
    assert rapport["illisibles"] == [{"file": "ferme.py", "err": "PermissionError"}]
    ligne = capsys.readouterr().out.strip().splitlines()[-1]
    assert json.loads(ligne.split(" ", 1)[1])["illisibles"] == 1


def _full_desc_isole(journal):
    """_full_desc extrait de son module : l'importer configurerait la journalisation fichier du demon."""
    arbre = ast.parse((ROOT / "tools" / "multi_llm_daemon.py").read_text(encoding="utf-8"))
    fn = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "_full_desc")
    code = compile(ast.Module(body=[fn], type_ignores=[]), "multi_llm_daemon.py", "exec")
    corps = next(c for c in code.co_consts if isinstance(c, types.CodeType) and c.co_name == "_full_desc")
    return types.FunctionType(corps, {"ast": ast, "logger": journal, "__builtins__": builtins})


def test_le_repli_sur_un_texte_tronque_est_journalise():
    avertis = []

    class _Journal:
        def warning(self, msg, *a):
            avertis.append(msg % a)

    full_desc = _full_desc_isole(_Journal())
    assert full_desc({"parameters": "{'description': 'pleine'}", "text": "tronq"}) == "pleine"
    assert avertis == []
    assert full_desc({"parameters": "{'description': ", "text": "tronq"}) == "tronq"
    assert len(avertis) == 1 and "tronque" in avertis[0] and "SyntaxError" in avertis[0]
