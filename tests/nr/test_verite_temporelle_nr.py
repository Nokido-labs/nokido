"""Non-regression : validite temporelle des assertions, et supersession.

Defaut mesure le 2026-08-25. `forge_rag_truth` savait dire QUELLE CONFIANCE accorder
a une assertion (DRAFT / REVIEW / VERIFIED / GOLD) et pas DEPUIS QUAND ni JUSQU'A
QUAND elle vaut. Consequences :

  * deux chunks contradictoires coexistaient sans qu'aucun ne soit ferme ;
  * la decroissance portait sur `ingested_at` — la date d'INGESTION — et non sur la
    validite du fait, donc une source recente qui contredit une ancienne ne resolvait
    rien ;
  * le corps ne pouvait pas repondre « qu'est-ce qui etait vrai a T ».

Le remede ne cree AUCUN stock : il ajoute `valid_from` / `valid_to` / `superseded_by`
au `meta` JSON existant, aux cotes de `consensus_level` que ce module lit deja. Une
migration de schema sur plus d'un million de chunks serait un geste d'une autre
nature, a decider separement.

Hermetique : base en memoire, aucun ecrivain reel.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_memory_archival as arch  # noqa: E402
import forge_rag_truth as verite  # noqa: E402

T0 = "2026-07-01T00:00:00"
T1 = "2026-08-01T00:00:00"
T2 = "2026-09-01T00:00:00"


# ------------------------------------------------------------ question as-of

def test_une_assertion_vaut_dans_sa_fenetre():
    assert verite.est_valide_a({"valid_from": T0, "valid_to": T2}, T1) is True


def test_une_assertion_perimee_ne_vaut_plus_apres_sa_borne():
    """Le cas « A etait vrai hier, faux aujourd'hui » : les deux restent lisibles,
    un seul vaut MAINTENANT."""
    assert verite.est_valide_a({"valid_from": T0, "valid_to": T1}, T2) is False


def test_une_assertion_pas_encore_observee_ne_vaut_pas_avant():
    assert verite.est_valide_a({"valid_from": T2}, T1) is False


def test_valid_to_none_signifie_encore_valide_jamais_inconnu():
    """`None` doit dire « encore valide ». Le laisser signifier « inconnu » ferait
    disparaitre en silence toute assertion jamais fermee."""
    assert verite.est_valide_a({"valid_from": T0, "valid_to": None}, T2) is True


def test_une_borne_illisible_ne_retire_pas_lassertion_du_monde():
    """On ne supprime pas un fait parce que sa date est mal ecrite : on le montre et
    on le laisse refutable. Trois etats, pas deux."""
    assert verite.est_valide_a({"valid_from": "pas-une-date"}, T1) is True
    assert verite.est_valide_a("{ json casse", T1) is True
    assert verite.est_valide_a(None, T1) is True


def test_le_filtre_as_of_dit_ce_quil_ecarte():
    """Un filtre qui ne rend pas ses ecartes fait passer une vue partielle pour une
    vue complete - la regle payee ailleurs dans ce depot."""
    chunks = [
        {"id": "a", "meta": {"valid_from": T0, "valid_to": T1}},
        {"id": "b", "meta": {"valid_from": T0, "valid_to": None}},
    ]
    retenus, ecartes = verite.filtrer_as_of(chunks, T2)
    assert [c["id"] for c in retenus] == ["b"]
    assert [c["id"] for c in ecartes] == ["a"]


# ------------------------------------------------------------- supersession

class _Ecrivain:
    """Doublure d'ecrivain : `sqlite3.Connection` refuse les attributs dynamiques, et
    `superseder` ferme sa connexion — la fixture doit survivre a ce close pour que le
    test puisse RELIRE ce qui a ete ecrit."""

    def __init__(self, conn):
        self._c = conn

    def execute(self, *a, **k):
        return self._c.execute(*a, **k)

    def commit(self):
        self._c.commit()

    def close(self):
        pass  # la fixture garde la main sur la base en memoire


@pytest.fixture()
def base(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, meta TEXT)")
    conn.execute("INSERT INTO rag_chunks VALUES (?, ?)",
                 ("vieux", json.dumps({"valid_from": T0, "valid_to": None})))
    conn.commit()

    import forge_db_path

    monkeypatch.setattr(forge_db_path, "open_writer",
                        lambda *a, **k: _Ecrivain(conn), raising=False)
    monkeypatch.setattr(forge_db_path, "write_retry", lambda op: op(), raising=False)
    return conn


def _meta(conn, cid):
    return json.loads(conn.execute(
        "SELECT meta FROM rag_chunks WHERE id = ?", (cid,)).fetchone()[0])


def test_superseder_ferme_lancien_sans_leffacer(base):
    """Effacer l'ancienne assertion detruirait la capacite de repondre « qu'est-ce
    qui etait vrai a T » - precisement ce qu'on repare."""
    r = verite.superseder("vieux", "neuf", a_partir_de=T1, raison="mesure du jour")
    assert r["ok"] is True
    m = _meta(base, "vieux")
    assert m["valid_to"] == T1
    assert m["superseded_by"] == "neuf"
    assert base.execute("SELECT COUNT(*) FROM rag_chunks WHERE id='vieux'"
                        ).fetchone()[0] == 1, "l'ancienne assertion a ete effacee"


def test_lancien_reste_vrai_AVANT_sa_fermeture(base):
    """Le test qui donne son sens a tout le reste : apres supersession, la question
    « et a T0 ? » doit toujours avoir une reponse."""
    verite.superseder("vieux", "neuf", a_partir_de=T1)
    m = _meta(base, "vieux")
    assert verite.est_valide_a(m, T0) is True
    assert verite.est_valide_a(m, T2) is False


def test_superseder_deux_fois_est_refuse(base):
    verite.superseder("vieux", "neuf", a_partir_de=T1)
    r = verite.superseder("vieux", "encore_plus_neuf", a_partir_de=T2)
    assert r["ok"] is False and "deja fermee" in r["raison"]


def test_superseder_une_assertion_inconnue_le_DIT(base):
    r = verite.superseder("jamais_vue", "neuf")
    assert r["ok"] is False and "introuvable" in r["raison"]


# --------------------------------------- reconciliation avec l'etat de verite

def test_le_meta_ecrit_par_larchival_parle_le_vocabulaire_de_la_verite():
    """RECONCILIATION, pas mecanisme de plus : `consensus_level` est le champ que
    `promote_chunk` et `batch_promote_draft` savent deja promouvoir. Un statut ecrit
    dans un champ maison aurait fabrique une seconde verite qu'aucun appelant ne lit."""
    m = json.loads(arch._meta_verite("assistant", T1))
    assert m["consensus_level"] == "draft"
    assert m["valid_from"] == T1
    assert m["valid_to"] is None
    assert m["superseded_by"] is None


def test_une_source_primaire_entre_deja_verifiee():
    m = json.loads(arch._meta_verite("user", T1))
    assert m["consensus_level"] == "verified"


def test_le_meta_est_lisible_par_le_predicat_temporel():
    """Les deux modules doivent s'accorder : ecrit par l'un, lu par l'autre."""
    m = arch._meta_verite("user", T0)
    assert verite.est_valide_a(m, T2) is True
