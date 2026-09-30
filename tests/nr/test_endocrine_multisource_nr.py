# -*- coding: utf-8 -*-
"""Tests NR — sommation endocrinienne multi-source, et surtout : release ECRIT
LA OU read LIT.

Mesure du 2026-08-21, en verifiant une affirmation d'analyse externe (« deux
glandes s'ecrasent ») : la sommation etait deja corrigee (mandat owner du
26/07), mais deux DECLARATIONS peremees l'annoncaient encore a faire -- l'en-tete
du module (« LIMITE CONNUE, NON CORRIGEE ») et la docstring de release()
(« ecrase avec le nouveau niveau »). En sondant, un VRAI bug est apparu :

  release() ecrivait via forge_db_path.write_retry(), qui ouvre sa propre
  connexion vers db_path() -- alors que read_full() lit le global DB. Quand DB
  est redirige (ce que tests/conftest.py fait pour TOUS les tests), les deux
  chemins divergeaient :
    - la base redirigee restait vide       -> read() rendait 0.0
    - la ligne partait dans la base reelle -> pollution du vivant
  Donc tout test endocrinien passait sans rien mesurer, ET salissait la prod.

Ces tests exigent les DEUX proprietes. Ils ne peuvent passer que si l'ecriture
et la lecture partagent la meme base.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_endocrine as fe  # noqa: E402


@pytest.fixture
def db_isole(tmp_path, monkeypatch):
    """Redirige l'organe vers une base temp. C'est EXACTEMENT ce que fait
    tests/conftest.py en autouse ; on le refait explicitement pour que le test
    porte aussi quand on le lit seul."""
    monkeypatch.setattr(fe, "DB", tmp_path / "endocrine.db", raising=False)
    return tmp_path / "endocrine.db"


def _rows(db):
    if not Path(db).exists():
        return []
    c = sqlite3.connect(str(db))
    try:
        return c.execute("SELECT hormone, level, source FROM endocrine_signals").fetchall()
    finally:
        c.close()


# ── la propriete non negociable : ecrire ou l'on lit ────────────────────────


def test_release_ecrit_dans_la_base_que_read_lit(db_isole):
    """Le bug de fond. Sans lui, tout le reste de ce fichier passerait en
    mesurant du vide -- et polluerait la base de production."""
    fe.release("CORTISOL_QUOTA_CLOUD", 0.9, source="econome")
    # La ligne est dans la base REDIRIGEE...
    assert _rows(db_isole), "release() n'a rien ecrit dans la base redirigee"
    # ...et read() la retrouve la, pas ailleurs.
    assert fe.read("CORTISOL_QUOTA_CLOUD") == pytest.approx(0.9, abs=0.01)


def test_read_ne_voit_que_la_base_redirigee(db_isole):
    """Une hormone jamais emise dans CETTE base doit se lire a 0.0 -- sinon
    read() regarde une autre base (le vivant)."""
    assert fe.read("TSH_VECTORIZATION") == 0.0


# ── sommation multi-source (le point de la revue) ───────────────────────────


def test_deux_glandes_distinctes_s_additionnent(db_isole):
    fe.release("CORTISOL_QUOTA_CLOUD", 0.6, source="econome")
    fe.release("CORTISOL_QUOTA_CLOUD", 0.3, source="health_diagnostic")
    # Ecrasement (l'ancien defaut) aurait rendu 0.3.
    assert fe.read("CORTISOL_QUOTA_CLOUD") == pytest.approx(0.9, abs=0.02)


def test_meme_glande_rafraichit_sans_double_compter(db_isole):
    fe.release("CORTISOL_QUOTA_CLOUD", 0.6, source="econome")
    fe.release("CORTISOL_QUOTA_CLOUD", 0.6, source="econome")
    # Double comptage aurait rendu 1.2 ; rafraichissement rend 0.6.
    assert fe.read("CORTISOL_QUOTA_CLOUD") == pytest.approx(0.6, abs=0.02)


def test_la_somme_sature_au_plafond(db_isole):
    for g in ("a", "b", "c", "d"):
        fe.release("CORTISOL_QUOTA_CLOUD", 0.9, source=g)
    # Somme brute 3.6, plafonnee a SATURATION_CEILING.
    assert fe.read("CORTISOL_QUOTA_CLOUD") == pytest.approx(fe.SATURATION_CEILING, abs=0.02)


def test_les_contributions_sont_tenues_par_source(db_isole):
    fe.release("CORTISOL_QUOTA_CLOUD", 0.5, source="econome")
    fe.release("CORTISOL_QUOTA_CLOUD", 0.2, source="health_diagnostic")
    import json

    c = sqlite3.connect(str(db_isole))
    try:
        meta = json.loads(c.execute(
            "SELECT meta FROM endocrine_signals WHERE hormone=?",
            ("CORTISOL_QUOTA_CLOUD",)).fetchone()[0])
    finally:
        c.close()
    contrib = meta.get("_contrib") or {}
    assert set(contrib) == {"econome", "health_diagnostic"}
    assert contrib["econome"] == pytest.approx(0.5, abs=0.01)


def test_extinction_active_efface_tout_le_signal(db_isole):
    fe.release("CORTISOL_QUOTA_CLOUD", 0.6, source="econome")
    fe.release("CORTISOL_QUOTA_CLOUD", 0.3, source="health_diagnostic")
    # release(0.0) est le clear() du module : il eteint TOUT, pas une part.
    fe.release("CORTISOL_QUOTA_CLOUD", 0.0, source="econome")
    assert fe.read("CORTISOL_QUOTA_CLOUD") == 0.0


def test_un_dosage_extreme_n_est_pas_ecrete_sous_sa_demande(db_isole):
    """Le plafond ne doit jamais rendre MOINS que ce qu'une glande demande
    explicitement (dosage extreme > 1.0)."""
    fe.release("CORTISOL_QUOTA_CLOUD", 1.5, source="crise")
    assert fe.read("CORTISOL_QUOTA_CLOUD") >= 1.5 - 0.05
