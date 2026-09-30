# -*- coding: utf-8 -*-
"""NR - `forge_module_census --check` : gate anatomie en LECTURE SEULE (2026-09-06).

Contrats :
  1. rend 1 et NOMME le module quand un module app/ ou tools/ n'est classe par aucun
     filet (carte, nom, dossier, imports, declaration) ; 0 quand tout est classe ;
  2. n'ecrit RIEN (ni carte, ni inventaire, ni non_classes.json) : un gate CI ne
     produit pas d'artefact, et surtout pas dans sandbox/ que le scan de references
     de l'audit exclut pour ne pas lire sa propre sortie ;
  3. ignore _attic et tmp_* comme le census complet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

C = pytest.importorskip("forge_module_census")


def _corps(tmp_path, monkeypatch, fichiers):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    for rel, texte in fichiers.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(texte, encoding="utf-8")


def test_un_module_sans_organe_rend_1_et_le_nomme(tmp_path, monkeypatch, capsys):
    _corps(tmp_path, monkeypatch, {
        "tools/zzq_sans_rien.py": '"""rien de reconnaissable"""\nimport os\n',
        "tools/zzq_declare.py": '"""doc"""\n__FORGE_COLOR__ = "immunitaire/guard : x"\n',
        "tools/tmp_brouillon.py": '"""ignore"""\n',
    })
    assert C.check() == 1
    out = capsys.readouterr().out
    assert "NON CLASSE  tools/zzq_sans_rien.py" in out
    assert "zzq_declare" not in out and "tmp_brouillon" not in out
    assert "2 modules" in out, "le denominateur est dit (tmp_* exclu)"


def test_tout_classe_rend_0(tmp_path, monkeypatch):
    _corps(tmp_path, monkeypatch, {
        "app/zzq_a.py": '"""doc"""\n__FORGE_COLOR__ = "memoire/rag : a"\n',
        "tools/zzq_b.py": '"""doc"""\n__FORGE_COLOR__ = "vegetatif/heartbeat : b"\n',
    })
    assert C.check() == 0


def test_le_point_d_entree_check_a_ses_imports():
    """Mesure 2026-09-06 : `check()` passait ses NR (appelee directement) pendant que
    `python forge_module_census.py --check` mourait en NameError sur `sys` -- le
    point d'entree n'etait couvert par rien. Un test qui n'emprunte pas le chemin
    reel ne protege pas le chemin reel."""
    assert getattr(C, "sys", None) is not None, "le __main__ lit sys.argv : sys doit etre importe"


def test_check_n_ecrit_aucun_artefact(tmp_path, monkeypatch):
    _corps(tmp_path, monkeypatch, {
        "tools/zzq_sans_rien.py": '"""rien"""\nimport os\n',
    })
    C.check()
    assert not (tmp_path / "sandbox").exists(), "un gate en lecture seule ne produit rien"
