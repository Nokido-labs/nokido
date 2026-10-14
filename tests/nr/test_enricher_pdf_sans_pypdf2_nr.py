# -*- coding: utf-8 -*-
"""NR -- l'enricher lit les PDF sans PyPDF2, et DIT quand aucune bibliotheque PDF n'existe.

2026-10-13 : PyPDF2 3.0.1 (vulnerable, sain seulement en descente) quitte le miniforge base,
ou PyMuPDF, pdfplumber et pypdfium2 sont presents. `_extract_pdf` importait PyPDF2 dans un
`try/except Exception: return None` : son retrait aurait fait ignorer chaque PDF en silence.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "forge_deep_doc_enricher.py"


def _module():
    spec = importlib.util.spec_from_file_location("forge_deep_doc_enricher_nr", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sans(monkeypatch, *noms):
    for n in noms:
        monkeypatch.setitem(sys.modules, n, None)  # `import n` leve ImportError


def test_sans_aucune_bibliotheque_le_manque_est_DIT_une_fois(tmp_path, monkeypatch, capsys):
    m = _module()
    _sans(monkeypatch, "pypdf", "fitz", "PyPDF2")
    assert m._extract_pdf(tmp_path / "a.pdf") is None
    assert m._extract_pdf(tmp_path / "b.pdf") is None
    sortie = capsys.readouterr().out
    assert sortie.count("AUCUNE bibliotheque PDF") == 1, sortie


def test_pymupdf_suffit_quand_pypdf_et_pypdf2_manquent(tmp_path, monkeypatch):
    m = _module()
    _sans(monkeypatch, "pypdf", "PyPDF2")

    class _Page:
        def get_text(self):
            return "page lue par PyMuPDF"

    class _Doc(list):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    faux_fitz = types.ModuleType("fitz")
    faux_fitz.open = lambda chemin: _Doc([_Page(), _Page()])
    monkeypatch.setitem(sys.modules, "fitz", faux_fitz)

    assert m._extract_pdf(tmp_path / "a.pdf") == "page lue par PyMuPDF\npage lue par PyMuPDF"


def test_pypdf_est_prefere_quand_il_est_present(tmp_path, monkeypatch):
    m = _module()

    class _Page:
        def extract_text(self):
            return "page lue par pypdf"

    faux_pypdf = types.ModuleType("pypdf")
    faux_pypdf.PdfReader = lambda chemin: types.SimpleNamespace(pages=[_Page()])
    monkeypatch.setitem(sys.modules, "pypdf", faux_pypdf)
    _sans(monkeypatch, "fitz", "PyPDF2")

    assert m._extract_pdf(tmp_path / "a.pdf") == "page lue par pypdf"
