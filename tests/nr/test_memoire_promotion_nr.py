"""Non-regression : une reponse LLM non verifiee n'entre pas en memoire GLOBALE.

Defaut mesure le 2026-08-25 dans `ArchivalMemory._archive()` : CHAQUE message, role
`assistant` compris, etait copie dans `rag_chunks` avec `domain="laforge-memory"` — le
seul tier agent-memory vectorisable. Sans validation, sans confiance, sans statut,
sans separation fait / hypothese / reponse LLM. D'ou la boucle :

    reponse LLM -> rag_chunks global -> retrieval ulterieur -> nouveau prompt
                -> nouvelle reponse qui renforce l'erreur

Le remede n'ajoute AUCUNE colonne : il reutilise le tier guard existant. `conv_archive`
est deja un domaine SKIP_TIER — archive et auditable, jamais vectorise. Le journal brut
(`conv_archives` + FTS) garde TOUT dans les deux cas : on ne conditionne que la
PROMOTION vers la memoire globale, jamais la conservation.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_memory_archival as arch  # noqa: E402


# ------------------------------------------------------------- regle de tier

def test_une_reponse_assistant_est_un_brouillon_par_defaut():
    """Le coeur du correctif : elle est conservee, mais pas rendue globale."""
    domaine, statut = arch._tier_rag("assistant")
    assert domaine == arch._TIER_BROUILLON
    assert statut == "brouillon"
    assert domaine != arch._TIER_PROMU, "l'assistant atteint encore le tier global"


def test_un_message_owner_est_une_source_primaire():
    """Temoin : le garde ne doit pas rendre la memoire muette. Ce que dit l'humain
    reste promu, sinon on aurait remplace une contamination par une amnesie."""
    domaine, statut = arch._tier_rag("user")
    assert domaine == arch._TIER_PROMU
    assert statut == "promu"


def test_un_role_inconnu_ne_se_promeut_pas():
    """Trois etats plutot que deux : ce qui n'est pas une source primaire reconnue
    reste brouillon. On n'invente pas une autorite a partir d'un role inattendu."""
    for role in ("tool", "system", "", None):
        assert arch._tier_rag(role)[0] == arch._TIER_BROUILLON, role


def test_le_drapeau_retablit_lancien_comportement(monkeypatch):
    """Un choix, pas un accident : l'ancien comportement reste atteignable sans
    toucher au code."""
    monkeypatch.setattr(arch, "_PROMOUVOIR_ASSISTANT", True)
    assert arch._tier_rag("assistant")[0] == arch._TIER_PROMU


# -------------------------------------------------- effet a l'ecriture reelle

class _FausseConnexion:
    """Capture les INSERT sans toucher a la base reelle."""

    def __init__(self):
        self.appels = []

    def execute(self, sql, params=()):
        self.appels.append((" ".join(sql.split()), params))
        return self

    def commit(self):
        pass

    def close(self):
        pass


def _archiver(monkeypatch, role):
    conn = _FausseConnexion()
    am = arch.ArchivalMemory.__new__(arch.ArchivalMemory)
    am.agent_id = "agt_test"
    am.session_id = "s1"
    monkeypatch.setattr(am, "_conn", lambda: conn, raising=False)
    msg = arch.ConvMessage(role=role, content="une affirmation",
                           timestamp=1787000000.0)
    am._archive(msg)
    return conn


def _domaine_du_chunk(conn):
    for sql, params in conn.appels:
        if "INTO rag_chunks" in sql:
            return params[3]
    return None


def test_le_chunk_dune_reponse_assistant_va_dans_le_tier_brouillon(monkeypatch):
    conn = _archiver(monkeypatch, "assistant")
    assert _domaine_du_chunk(conn) == arch._TIER_BROUILLON


def test_le_chunk_dun_message_owner_va_dans_le_tier_global(monkeypatch):
    conn = _archiver(monkeypatch, "user")
    assert _domaine_du_chunk(conn) == arch._TIER_PROMU


def test_le_journal_brut_garde_tout_dans_les_deux_cas(monkeypatch):
    """On ne conditionne QUE la promotion. Effacer le journal reviendrait a soigner
    une contamination par une amputation."""
    for role in ("assistant", "user"):
        conn = _archiver(monkeypatch, role)
        sqls = " | ".join(s for s, _ in conn.appels)
        assert "INTO conv_archives" in sqls, role
        assert "conv_archives_fts" in sqls, role


def test_le_statut_voyage_avec_le_chunk(monkeypatch):
    """Sans statut lisible, une promotion ulterieure ne saurait pas quoi promouvoir."""
    conn = _archiver(monkeypatch, "assistant")
    for sql, params in conn.appels:
        if "INTO rag_chunks" in sql:
            assert "brouillon" in params[4], params[4]
            return
    pytest.fail("aucun INSERT rag_chunks capture")


# ============================================================================
# DATE D'ORIGINE AU RAPPEL
#
# `recall()` SELECTionnait `archived_at` puis le JETAIT au profit de `time.time()`
# dans ses DEUX branches (FTS et repli LIKE). Un message archive en juillet,
# rappele aujourd'hui, se declarait d'aujourd'hui : toute question temporelle
# devenait impossible sur l'objet remis au consommateur, alors que la colonne
# etait deja chargee. Mesure 2026-08-25.
# ============================================================================

import time as _t  # noqa: E402


def test_la_date_dorigine_survit_au_rappel():
    """Le coeur du correctif : un message de juillet reste de juillet."""
    ts, provenance = arch._epoch_archive("2026-07-04T00:00:29+00:00")
    assert provenance == "archived_at"
    assert _t.time() - ts > 30 * 86400, "la date a ete ecrasee par celle du rappel"


def test_une_date_illisible_est_declaree_et_non_inventee():
    """Trois etats : lue / illisible / absente. Quand on ne sait pas, on le DIT au
    lieu de laisser croire a une precision qu'on n'a pas."""
    ts, provenance = arch._epoch_archive("pas-une-date")
    assert provenance == "illisible"
    assert abs(_t.time() - ts) < 5


def test_une_date_absente_est_declaree():
    for vide in (None, "", 0):
        assert arch._epoch_archive(vide)[1] == "absente"


def test_la_provenance_de_la_date_voyage_dans_la_metadata():
    """Le consommateur doit pouvoir distinguer une date MESUREE d'un repli."""
    msg = arch._conv_depuis_ligne(
        ("assistant", "un contenu", "2026-07-04T00:00:29+00:00", 12, "{}"))
    assert msg.metadata["ts_source"] == "archived_at"
    assert _t.time() - msg.timestamp > 30 * 86400


def test_une_metadata_illisible_ne_casse_pas_le_rappel():
    """Un rappel qui leve sur une metadata corrompue perdrait TOUT le lot."""
    msg = arch._conv_depuis_ligne(("user", "c", "2026-07-04T00:00:29+00:00", 1, "{{"))
    assert msg.content == "c"
    assert msg.metadata["ts_source"] == "archived_at"
