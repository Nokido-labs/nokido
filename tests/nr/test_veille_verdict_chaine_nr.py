"""NR — `completed` doit etre un verdict de CHAINE, pas un compteur de retention.

MESURE QUI A MOTIVE CE FICHIER (2026-08-31, 45 jobs de `watch_jobs`) : QUATRE
jobs portaient un verdict plus optimiste que leurs propres etapes. Le cas net :

    wj_aef42808d : keywords ✓ verify_kw ✓ search ✓ refine ✓ crawl ✓
                   ingest FAILED (« database is locked »)   store completed
                   -> job « completed », n_ingested=220, n_stored=4

Le verdict etait deduit du SEUL compteur de retention. Une etape OBLIGATOIRE
cassee restait donc invisible des lors que le stockage avait ecrit quelque chose.
Trois autres jobs lisaient `completed` en portant au moins un node `degraded`.

Ce que ces tests protegent :
  1. une etape cassee ne peut plus etre effacee par un compteur non nul ;
  2. `degraded` (vide ASSUME) ne vaut pas `casse` — sinon SearXNG a terre
     ferait echouer une veille que l'academique a nourrie ;
  3. une chaine INACHEVEE n'a pas de verdict (`en_cours`), ce qui interdit a un
     restart de transformer une veille incomplete en succes ;
  4. le chemin DIRECT (aucun node) rend exactement le verdict d'avant.

HERMETIQUE : aucune base reelle, aucun service. Le seul test qui touche SQLite
construit sa propre base dans `tmp_path`.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 (code appele) (l.182)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT, _ROOT / "app", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app import forge_watch_agent as wa  # noqa: E402

_OK = "completed"


def _chaine(**surcharges) -> list:
    """Les 7 etapes reelles d'une veille, toutes completed sauf surcharge."""
    base = [("keywords", _OK), ("verify_kw", _OK), ("search", _OK),
            ("refine", _OK), ("crawl", _OK), ("ingest", _OK), ("store", _OK)]
    return [(n, surcharges.get(n, s)) for n, s in base]


# ── 1-2 : la recherche ──────────────────────────────────────────────────────
def test_1_recherche_sans_source_et_rien_retenu_est_un_ECHEC():
    """`search` est obligatoire : cassee et sans retention, ce n'est pas un vide."""
    assert wa.verdict_chaine(_chaine(search="failed"), 0) == "failed"


def test_2_recherche_avec_sources_et_retention_est_un_SUCCES():
    assert wa.verdict_chaine(_chaine(), 12) == "completed"


# ── 3-4 : le vide ASSUME n'est pas une panne ────────────────────────────────
def test_3_contenu_vide_apres_crawl_reste_un_vide_assume():
    """`degraded` = l'etape a tourne et n'a rien rendu. Pas une casse."""
    assert wa.verdict_chaine(_chaine(crawl="degraded"), 0) == "completed_empty"


def test_4_ingestion_vide_sans_casse_est_EMPTY_pas_FAILED():
    assert wa.verdict_chaine(_chaine(ingest="degraded", store="degraded"),
                             0) == "completed_empty"


def test_4bis_deja_possede_n_est_pas_a_sec():
    """DEJA-CONNU != A SEC : la base avait deja ces documents, rien n'a echoue."""
    assert wa.verdict_chaine(_chaine(store="degraded"), 0,
                             dedup=True) == "completed_dedup"


# ── 5-6 : le defaut mesure ──────────────────────────────────────────────────
def test_5_ingestion_partielle_ne_degrade_pas_le_verdict():
    """`partial_success` est un resultat REDUIT, pas une etape cassee."""
    assert wa.verdict_chaine(_chaine(ingest="partial_success"), 7) == "completed"


def test_6_LE_CAS_MESURE_wj_aef42808d_ne_peut_plus_lire_completed():
    """Regression exacte : ingest FAILED, store completed, n_stored=4."""
    nodes = _chaine(ingest="failed")
    assert wa.verdict_chaine(nodes, 4) == "completed_partial"
    assert wa.verdict_chaine(nodes, 4) != "completed"


def test_6bis_une_etape_en_attente_de_reprise_casse_aussi_le_verdict():
    """`retry_pending` n'est pas terminal-sain : la chaine n'a pas fait son travail."""
    assert wa.verdict_chaine(_chaine(ingest="retry_pending"), 9) == "completed_partial"


# ── 7 : dependance OPTIONNELLE ──────────────────────────────────────────────
def test_7_une_etape_non_obligatoire_degradee_ne_fait_pas_echouer():
    """SearXNG a terre, l'academique nourrit encore : bloquer priverait la veille
    de la couverture qui lui reste (doctrine de `213e30193dea`)."""
    assert wa.verdict_chaine(_chaine(verify_kw="degraded"), 5) == "completed"


# ── 8-9 : restart et reprise ────────────────────────────────────────────────
def test_8_une_chaine_INACHEVEE_n_a_pas_de_verdict():
    """LE verrou anti-restart : `en_cours` n'est ni un succes ni un echec. Sans ce
    troisieme etat, une veille coupee en plein vol se solde sur ce qui etait
    deja ecrit -- donc en succes, sans preuve nouvelle."""
    assert wa.verdict_chaine(_chaine(ingest="pending", store="pending"),
                             0) == "en_cours"
    assert wa.verdict_chaine(_chaine(store="running"), 30) == "en_cours"


def test_9_la_reprise_aboutie_rend_bien_le_succes():
    """Meme chaine qu'au test 8, une fois les etapes reprises et terminees."""
    assert wa.verdict_chaine(_chaine(), 30) == "completed"


# ── 10 : compatibilite du chemin direct ─────────────────────────────────────
def test_10_le_chemin_DIRECT_sans_node_garde_le_comportement_d_avant():
    """Aucune etape en base = rien a contredire. Changer ce chemin serait une
    regression deguisee en correctif."""
    assert wa.verdict_chaine([], 0) == "completed_empty"
    assert wa.verdict_chaine([], 0, dedup=True) == "completed_dedup"
    assert wa.verdict_chaine([], 3) == "completed"


# ── ABSENT / VIDE / ILLISIBLE : les trois etats de la LECTURE des etapes ─────
class _ConnKO:
    """Base momentanement inaccessible — le cas mesure le plus banal du depot
    (`database is locked` est deja la cause du faux succes de `wj_aef42808d`)."""

    def execute(self, *a, **k):
        raise sqlite3.OperationalError("database is locked")


def test_10bis_etapes_illisibles_ne_valent_PAS_etapes_absentes():
    """`_nodes_du_job` rend None, jamais []. Rendre [] ferait passer une base
    inaccessible pour une veille sans etapes."""
    assert wa._nodes_du_job(_ConnKO(), "wj_x") is None
    assert wa._nodes_du_job(_ConnKO(), "wj_x") != []


def test_11_lecture_impossible_ne_peut_JAMAIS_rendre_completed():
    """Une erreur de LECTURE ne doit pas se transformer en preuve de SUCCES."""
    assert wa.verdict_chaine(None, 0) == "indetermine"
    assert wa.verdict_chaine(None, 0, dedup=True) == "indetermine"


def test_12_lecture_impossible_AVEC_retention_reste_indeterminee():
    """LE cas dangereux : la retention seule suffisait a ecrire `completed`."""
    for n in (1, 42, 9999):
        v = wa.verdict_chaine(None, n)
        assert v == "indetermine", "n_stored=%d a rendu %s" % (n, v)
        assert v != "completed"


def test_13_bout_en_bout_lecture_KO_puis_verdict(tmp_path):
    """Les deux maillons ensemble : c'est leur ENCHAINEMENT qui produisait le
    faux succes, pas l'un des deux pris isolement."""
    etapes = wa._nodes_du_job(_ConnKO(), "wj_x")
    assert wa.verdict_chaine(etapes, 220) == "indetermine"


def test_14_les_trois_etats_de_lecture_donnent_trois_verdicts_DIFFERENTS():
    """Le contrat, verifie d'un bloc : absent != vide-mais-lu != illisible."""
    absent = wa.verdict_chaine([], 5)                      # chemin direct
    sain = wa.verdict_chaine(_chaine(), 5)                 # etapes lues, saines
    illisible = wa.verdict_chaine(None, 5)                 # pas pu lire
    assert absent == "completed"
    assert sain == "completed"
    assert illisible == "indetermine"
    assert illisible not in (absent, sain)


# ── la cloture d'une chaine soldee ──────────────────────────────────────────
def test_une_chaine_soldee_ecrit_AUSSI_le_verdict_du_job(tmp_path):
    """Sans cela le node est solde et le job garde le verdict de l'etape ecrite
    avant l'incident : une veille morte en route se lit « en cours » pour
    toujours, ou pire, garde un succes qu'elle n'a pas obtenu."""
    from app import forge_chain_executor as ce

    db = tmp_path / "chaine.db"
    ex = ce.ChainExecutor(db_path=db)
    conn = ex._get_conn()
    conn.execute(
        "CREATE TABLE watch_jobs (id TEXT PRIMARY KEY, theme TEXT, step TEXT, "
        "status TEXT, n_ingested INTEGER, n_stored INTEGER, error TEXT, "
        "updated_at TEXT)")
    conn.execute("INSERT INTO watch_jobs (id, theme, step, status, n_stored) "
                 "VALUES ('wj_test', 'sujet', 'ingest', 'running', 0)")
    for i, (nom, statut) in enumerate(
            [("keywords", _OK), ("search", _OK), ("ingest", "pending")]):
        conn.execute(
            "INSERT INTO agent_chain_nodes (id, chain_id, step_index, step_name, "
            "status) VALUES (?,?,?,?,?)",
            ("n%d" % i, "wj_test", i, nom, statut))
    conn.commit()
    conn.close()

    restants = [{"id": "n2", "chain_id": "wj_test"}]
    ex._marquer_stalled(restants, 2000.0)

    conn = ex._get_conn()
    job = conn.execute("SELECT step, status, error FROM watch_jobs "
                       "WHERE id='wj_test'").fetchone()
    node = conn.execute("SELECT status FROM agent_chain_nodes "
                        "WHERE id='n2'").fetchone()
    conn.close()
    assert node[0] == "stalled"
    assert job[0] == "done"
    # `ingest` obligatoire soldee `stalled`, rien de retenu -> ECHEC, jamais succes.
    assert job[1] == "failed"
    assert "budget de chaine epuise" in (job[2] or "")


def test_le_verdict_ne_peut_pas_valoir_completed_avec_une_etape_cassee():
    """Regle absolue de l'enonce, verifiee sur TOUTES les etapes obligatoires."""
    for etape in wa._STEPS_OBLIGATOIRES:
        for casse in wa._NODE_CASSE:
            v = wa.verdict_chaine(_chaine(**{etape: casse}), 99)
            assert v != "completed", "%s=%s a rendu completed" % (etape, casse)
