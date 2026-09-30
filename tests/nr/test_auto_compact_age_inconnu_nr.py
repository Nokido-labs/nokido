"""Tests NR : la compaction ne traite pas « age inconnu » comme « ancien ».

Test d'EFFET hermetique : base SQLite temporaire, schema minimal, et on execute
les requetes EXPOSEES PAR LE MODULE (`SQL_CANDIDATS`, `SQL_ECARTES_SANS_DATE`),
jamais une copie. Un test qui recopie le SQL valide sa copie, pas le code qui
tourne -- erreur payee le 2026-08-30 sur un decoupage de sortie git.

Ce qui est verrouille : `created_at IS NULL` (82,8 % du corpus reel) ne doit
plus faire entrer un chunk dans le champ de la compaction.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.forge_auto_compact import (  # noqa: E402
    SQL_CANDIDATS,
    SQL_ECARTES_SANS_DATE,
    THIRTY_DAYS,
)

VIEUX = int(time.time()) - THIRTY_DAYS - 86_400
RECENT = int(time.time()) - 3_600
CUTOFF = int(time.time()) - THIRTY_DAYS


class Base:
    """Petit banc : `sqlite3.Connection` n'accepte pas d'attribut arbitraire."""

    def __init__(self, chemin):
        self.conn = sqlite3.connect(chemin)
        self.conn.execute(
            "CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, text TEXT, "
            "domain TEXT, created_at INTEGER, access_count INTEGER, embedding BLOB)"
        )

    def ajouter(self, cid, created_at, access_count=0, domain="doc", embedding=b"\x00\x00\x00\x00"):
        self.conn.execute(
            "INSERT INTO rag_chunks (id, source, text, domain, created_at, "
            "access_count, embedding) VALUES (?,?,?,?,?,?,?)",
            (cid, "s", "t", domain, created_at, access_count, embedding),
        )

    def execute(self, *a):
        return self.conn.execute(*a)

    def fermer(self):
        self.conn.close()


@pytest.fixture()
def base(tmp_path):
    """Schema minimal portant les seules colonnes que la requete interroge."""
    b = Base(tmp_path / "t.db")
    yield b
    b.fermer()


def candidats(base):
    return [r[0] for r in base.execute(SQL_CANDIDATS, (CUTOFF, 1000)).fetchall()]


# --- le coeur de la regression -------------------------------------------
def test_age_inconnu_nest_pas_candidat(base):
    """LE test : created_at NULL ne doit plus valoir « ancien ».

    Avant correctif, la clause `created_at IS NULL OR created_at < ?` faisait
    entrer 82,8 % du corpus par pur defaut.
    """
    base.ajouter("sans_date", None)
    assert candidats(base) == []


def test_age_connu_et_ancien_reste_candidat(base):
    """Le correctif ne doit pas desarmer la compaction sur son vrai domaine."""
    base.ajouter("vieux", VIEUX)
    assert candidats(base) == ["vieux"]


def test_recent_nest_pas_candidat(base):
    base.ajouter("recent", RECENT)
    assert candidats(base) == []


def test_les_trois_cas_ensemble_ne_retiennent_que_l_ancien_date(base):
    base.ajouter("sans_date", None)
    base.ajouter("vieux", VIEUX)
    base.ajouter("recent", RECENT)
    assert candidats(base) == ["vieux"]


# --- les autres criteres restent actifs -----------------------------------
def test_chunk_consulte_est_epargne(base):
    """access_count >= 3 protege un chunk ancien : le signal d'usage prime."""
    base.ajouter("lu", VIEUX, access_count=3)
    assert candidats(base) == []


def test_seuil_dusage_est_strict(base):
    base.ajouter("presque", VIEUX, access_count=2)
    assert candidats(base) == ["presque"]


def test_deja_compacte_nest_pas_recompacte(base):
    base.ajouter("deja", VIEUX, domain="compacted")
    assert candidats(base) == []


def test_chunk_sans_embedding_est_ignore(base):
    """Sans vecteur, le resume ne peut pas etre rattache : hors champ."""
    base.ajouter("sans_vec", VIEUX, embedding=None)
    assert candidats(base) == []


def test_access_count_null_reste_candidat(base):
    """NULL sur le compteur d'usage = jamais lu, ce qui EST le cas cible."""
    base.ajouter("jamais_lu", VIEUX, access_count=None)
    assert candidats(base) == ["jamais_lu"]


# --- le denominateur ------------------------------------------------------
def test_les_ecartes_sont_comptes_et_non_silencieux(base):
    """« 0 candidat » doit se distinguer de « je n'ai pas pu voir »."""
    base.ajouter("sans_date_1", None)
    base.ajouter("sans_date_2", None)
    base.ajouter("vieux", VIEUX)
    assert base.execute(SQL_ECARTES_SANS_DATE).fetchone()[0] == 2


def test_ecartes_ninclut_pas_ce_qui_est_hors_champ_pour_une_autre_raison(base):
    """Un chunk deja compacte n'est pas « ecarte faute de date »."""
    base.ajouter("deja", None, domain="compacted")
    assert base.execute(SQL_ECARTES_SANS_DATE).fetchone()[0] == 0


def test_ordre_par_anciennete_reelle(base):
    base.ajouter("plus_vieux", VIEUX - 10_000)
    base.ajouter("vieux", VIEUX)
    assert candidats(base) == ["plus_vieux", "vieux"]
