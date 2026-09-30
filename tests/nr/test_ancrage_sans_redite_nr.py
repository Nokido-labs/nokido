# -*- coding: utf-8 -*-
"""Non-regression — une leçon deja apprise ne se re-apprend pas.

Mesure 2026-08-26, sur la base reelle : `domain='autonomous'` portait **5132 chunks pour
566 textes distincts**, soit **9,1 copies par lecon**. Une seule d'entre elles (« Providers
LLM injoignables… ») etait repetee **35 fois dans la journee**.

La cause tenait en une ligne. `anchor_solution` construisait
`lesson_sol_<empreinte>_<timestamp>` puis inserait en `INSERT OR IGNORE`. L'empreinte est
bien deterministe — mais le suffixe temporel rendait chaque clef NEUVE, donc le
`OR IGNORE` ne pouvait **jamais** se declencher. Un garde present, annule par la ligne qui
le precede : le meme motif que `governed_edit` et les gardes SSE le meme jour.

Pourquoi ca compte au-dela du volume : ces chunks sont indexes et cherchables. Neuf copies
d'une meme lecon ne rendent pas la memoire plus sure, elles **evincent** neuf resultats
differents dans un top-k. La redite ne remplit pas la memoire, elle l'appauvrit.

Le suffixe est CONSERVE (`forge_skill_enricher` le parse pour dater) : c'est l'ECRITURE
redondante qui est empechee, pas le format d'identifiant.

Hermetique : base SQLite temporaire, `_DB` du module redirige.
"""

from __future__ import annotations

import sqlite3
import sys
import types
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.127)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

SC = pytest.importorskip("forge_self_correction")


@pytest.fixture
def base(tmp_path, monkeypatch):
    """Base minimale + neutralisation des effets de bord (fichier de lecons, ZMQ, gate).

    LE GATE MEMOIRE EST NEUTRALISE, et c'est indispensable. `anchor_solution` consulte
    `forge_memory_gate.should_ingest`, une porte anti-confabulation qui REJETTE les
    contenus triviaux — or les contenus d'un test le sont par construction (« panne X »,
    « remede Y »).

    Ce fichier a d'abord ete ecrit sans cette neutralisation, et il PASSAIT : en local le
    module n'est pas importable (`ModuleNotFoundError`), donc le `except` d'anchor_solution
    saute la porte. En CI il est trouvable, la porte s'applique, et les 8 memes tests
    tombent. Un test dont le verdict depend de la PRESENCE d'un module ne mesure pas ce
    qu'il croit : il faut fixer l'environnement, pas esperer qu'il coincide.

    On teste ici l'anti-redite, pas la porte — celle-ci a ses propres tests."""
    faux_gate = types.ModuleType("forge_memory_gate")
    faux_gate.should_ingest = lambda *a, **k: {"ok": True}
    monkeypatch.setitem(sys.modules, "forge_memory_gate", faux_gate)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_memory_gate", faux_gate)

    db = tmp_path / "embeddings.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, source TEXT, "
                "domain TEXT, role_hint TEXT, meta TEXT, embedding BLOB, created_at REAL)")
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id, text, source, domain)")
    con.commit()
    con.close()
    # LES DEUX INSTANCES, PAS UNE. Ce module est atteignable sous deux noms --
    # `forge_self_correction` (via sys.path) et `nokido_agent.app.forge_self_correction`
    # (via le pont de namespace) -- et Python en garde alors DEUX objets distincts,
    # avec deux `_DB`. Patcher le seul nom court suffit en ISOLATION, ou rien
    # d'autre n'a charge l'autre forme ; en SUITE COMPLETE un test voisin charge le
    # nom long, et l'ancrage ecrit dans une base que la fixture n'a pas redirigee.
    # C'est exactement ce qui s'est passe : CI GitHub du 2026-09-16 sur 1ff685e16,
    # `test_erreur_repetee_ne_duplique_pas` rend `deja_connue = None` sur le runner
    # et PASSE en isolation avec le MEME interpreteur (3.14.4, 11/11).
    # La fixture le faisait deja pour `forge_memory_gate`, sous ses deux noms --
    # elle ne le faisait pas pour le module qu'elle teste.
    # Meme famille que la mesure du 2026-09-10 : `X is nokido_agent.app.X` -> False.
    _formes = ["forge_self_correction", "nokido_agent.app.forge_self_correction"]
    _patchees = 0
    for _nom in _formes:
        _mod = sys.modules.get(_nom)
        if _mod is None:
            try:
                import importlib  # noqa: PLC0415

                _mod = importlib.import_module(_nom)
            except Exception:  # noqa: BLE001 - forme absente = rien a patcher, on le compte
                continue
        monkeypatch.setattr(_mod, "_DB", db, raising=False)
        monkeypatch.setattr(_mod, "_LESSONS", tmp_path / "lessons.md", raising=False)
        monkeypatch.setattr(_mod, "_zmq_nudge_brain", lambda *a, **k: None, raising=False)
        _patchees += 1
    assert _patchees, "aucune forme du module n'a pu etre redirigee : le test ecrirait dans la vraie base"
    return db


def _compte(db, texte_partiel="%"):
    con = sqlite3.connect(str(db))
    try:
        return con.execute("SELECT COUNT(*) FROM rag_chunks WHERE text LIKE ?",
                           (texte_partiel,)).fetchone()[0]
    finally:
        con.close()


def test_premier_ancrage_ecrit(base):
    r = SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    assert r.get("ok") is True
    assert not r.get("deja_connue")
    assert _compte(base) == 1


def test_second_ancrage_identique_ne_duplique_pas(base):
    """LE test : c'est ce qui produisait 9,1 copies par lecon."""
    SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    r = SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    assert r.get("ok") is True
    assert r.get("deja_connue") is True, "la redite doit etre reconnue, pas re-ecrite"
    assert _compte(base) == 1, "une seconde copie a ete ecrite"


def test_trente_cinq_repetitions_donnent_une_seule_entree(base):
    """Reproduction du cas reel : 35 ancrages du meme contenu dans la journee."""
    for _ in range(35):
        SC.anchor_solution("Providers LLM injoignables", "cle ecartee ou quota",
                           domain="autonomous")
    assert _compte(base) == 1


def test_le_retour_garde_la_meme_forme(base):
    """Un appelant ne doit pas avoir a savoir quelle branche l'a servi."""
    premier = SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    second = SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    for r in (premier, second):
        assert set(("ok", "anchored", "chunk_id")).issubset(r), r
    assert second["anchored"] == premier["anchored"]
    assert second["chunk_id"] == premier["chunk_id"], (
        "la redite doit pointer le chunk EXISTANT, pas un identifiant neuf")


def test_une_solution_differente_est_bien_ecrite(base):
    """Le garde ne doit pas etouffer l'apprentissage reel."""
    SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    SC.anchor_solution("panne X", "remede AUTRE", domain="autonomous")
    assert _compte(base) == 2


def test_un_probleme_different_est_bien_ecrit(base):
    SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    SC.anchor_solution("panne Z", "remede Y", domain="autonomous")
    assert _compte(base) == 2


def test_l_index_lexical_ne_recoit_pas_la_redite(base):
    """Le lexical PRIME dans la recherche : le polluer serait pire que la table."""
    for _ in range(5):
        SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    con = sqlite3.connect(str(base))
    try:
        n = con.execute("SELECT COUNT(*) FROM rag_fts").fetchone()[0]
    finally:
        con.close()
    assert n == 1, "%d entrees lexicales pour une seule lecon" % n


# ------------------------------------------- anchor_error portait le MEME defaut

def test_erreur_repetee_ne_duplique_pas(base):
    SC.anchor_error("timeout provider", "contexte", domain="autonomous")
    r = SC.anchor_error("timeout provider", "contexte", domain="autonomous")
    assert r.get("deja_connue") is True
    assert _compte(base) == 1


def test_erreur_differente_est_bien_ecrite(base):
    SC.anchor_error("timeout provider", "contexte", domain="autonomous")
    SC.anchor_error("quota depasse", "contexte", domain="autonomous")
    assert _compte(base) == 2


def test_erreur_et_solution_ne_se_confondent_pas(base):
    """Les deux familles ont des prefixes d'id distincts : le garde de l'une ne doit
    pas etouffer l'autre."""
    SC.anchor_error("panne X", "contexte", domain="autonomous")
    SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    assert _compte(base) == 2


def test_le_suffixe_temporel_est_conserve(base):
    """`forge_skill_enricher` parse ce suffixe pour dater les lecons."""
    r = SC.anchor_solution("panne X", "remede Y", domain="autonomous")
    cid = r["chunk_id"]
    assert cid.startswith("lesson_sol_")
    queue = cid.rsplit("_", 1)[-1]
    assert queue.isdigit(), "le suffixe horodate a disparu : un consommateur le lit"
