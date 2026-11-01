"""NR -- une reponse faite seulement d'espaces Unicode (largeur nulle, NBSP, BOM) est VIDE, jamais OK.

Mesure 24/10 : dans l'essaim, groq:allam-2-7b a rendu 1 caractere (U+200B) et `_classer` l'a compte OK :
str.strip() ne retire pas l'espace de largeur nulle. Caracteres construits par chr() : aucun invisible litteral.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.forge_mesure import _classer  # noqa: E402

ZW, NBSP, BOM, WJ = chr(0x200B), chr(0x00A0), chr(0xFEFF), chr(0x2060)


def test_espace_de_largeur_nulle_est_vide():
    assert _classer(True, ZW, None) == "VIDE"


def test_espaces_unicode_divers_sont_vides():
    assert _classer(True, ZW + NBSP + BOM + " " + WJ + "\n", None) == "VIDE"


def test_vraie_reponse_reste_ok():
    assert _classer(True, ZW + "Bonjour", None) == "OK"
