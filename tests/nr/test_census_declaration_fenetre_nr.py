# -*- coding: utf-8 -*-
"""NR - la declaration d'organe est LUE par le census (2026-09-06).

Contrats :
  1. `DECL_RE` ne prend qu'une ligne qui COMMENCE par la marque : une mention dans un
     commentaire (`# ... __FORGE_COLOR__ = "GREEN"`) n'est pas une declaration — la
     regex non ancree classait forge_organ_declare.py sur son propre commentaire ;
  2. la fenetre `_read_head` couvre HEAD_CHARS >= 12 000 caracteres : une declaration
     posee apres une longue docstring (nokido.py ligne 22, nokido_cutover_owner.py
     ligne 52, mesure 2026-09-06 — « non classe » EN portant leur declaration) est lue ;
  3. `organ()` classe un module sur cette declaration quand nom, dossier et imports
     ne disent rien.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

C = pytest.importorskip("forge_module_census")


def test_une_mention_en_commentaire_n_est_pas_une_declaration():
    src = ('"""doc"""\n# l ancien en-tete portait __FORGE_COLOR__ = "GREEN"\n'
           '__FORGE_COLOR__ = "immunitaire/guard : x"\n')
    m = C.DECL_RE.search(src)
    assert m and m.group(1).startswith('"immunitaire/guard'), m
    assert C.DECL_RE.search('# seule mention : __FORGE_COLOR__ = "GREEN"\n') is None


def test_la_fenetre_couvre_une_longue_docstring(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    d = tmp_path / "zz"
    d.mkdir()
    long_doc = '"""' + ("x" * 90 + "\n") * 60 + '"""\n'      # ~5 500 chars, > 3 ko
    (d / "forge_zzz.py").write_text(long_doc + '__FORGE_COLOR__ = "immunitaire/guard : y"\n',
                                    encoding="utf-8")
    assert C.HEAD_CHARS >= 12_000
    tete = C._read_head("forge_zzz.py", "zz/forge_zzz.py")
    assert "__FORGE_COLOR__" in tete, "la declaration doit tenir dans la fenetre lue"


def test_le_filet_imports_ne_depend_pas_d_un_artefact_genere(tmp_path, monkeypatch):
    """Mesure 2026-09-06 : le gate CI `anatomie` (bloquant) etait ROUGE sur le runner GitHub
    pour un seul module, classe localement par ses imports via sandbox/workspace/
    module_cards.json -- un artefact genere que le depot ne porte pas. Sans cartes, les
    imports se relisent a la source (AST) : le verdict du gate est le meme partout."""
    monkeypatch.setattr(C, "ROOT", tmp_path)
    monkeypatch.setattr(C, "_CARDS", {})          # aucune carte disponible
    d = tmp_path / "tools"
    d.mkdir()
    (d / "zzq_par_imports.py").write_text(
        '"""doc"""\nimport os\nimport forge_rag_engine\nfrom forge_rag_store import x\n', encoding="utf-8")
    imps = C._imports_of("zzq_par_imports.py")
    assert "forge_rag_engine" in imps and "forge_rag_store" in imps, imps


def test_organ_classe_sur_la_declaration_apres_une_mention_et_une_longue_docstring(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", tmp_path)
    d = tmp_path / "zz"
    d.mkdir()
    long_doc = '"""' + ("x" * 90 + "\n") * 60 + '"""\n'
    (d / "forge_zzy.py").write_text(
        long_doc + '# en-tete historique : __FORGE_COLOR__ = "GREEN"\n'
        '__FORGE_COLOR__ = "immunitaire/guard : z"\nimport os\n', encoding="utf-8")
    assert "Immunitaire" in C.organ("forge_zzy", fname="forge_zzy.py", relpath="zz/forge_zzy.py")
