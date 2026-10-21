"""NR -- la dette d'embeddings de forge_remediation se lit sur le snapshot du PRODUCTEUR, jamais sur rag_chunks.

Mesure 20/10 (owner : « ce n'est pas admissible ces usures disques abusives », « critères ajustés au réel de la base
RAG ») : NokidoCoagulation lisait ~85 Mo/s et ~22 000 op/s de 4 Ko quasi en continu. Cause : check_embed_backlog fait
`SELECT count(*) FROM rag_chunks WHERE embedding IS NULL AND <CASE a LIKE>` sur 46,6 Go (SCAN USING INDEX
idx_emb_null_origin + une lecture de table par ligne, ~260 s), a chaque cycle de soin (~5 min). Or la base reelle
(snapshot forge_memory_availability) compte 6 887 715 chunks REFUSES par politique et 77 seulement en attente qualifiee :
le balayage relisait 6,9 M lignes pour un chiffre deja produit. Contrat : lire forge_memory_availability.snapshot()
(qui ne calcule JAMAIS) ; seuil sur vector_pending (qualifie, hors refus de politique) ; snapshot perime ou absent =
INCONNU, sans signal et sans balayage de repli. Meme faute que l'organ_pulse du 04/09 (107 Mo/s).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_remediation as R  # noqa: E402


def _brancher(monkeypatch, snap):
    def interdit(*a, **k):
        raise AssertionError("check_embed_backlog a ouvert une base : la dette se LIT chez le producteur")

    monkeypatch.setattr(R.sqlite3, "connect", interdit)
    signaux = []
    monkeypatch.setattr(R, "_signal", lambda nom, *a, **k: signaux.append(nom) or 1)
    import forge_memory_availability as MA
    monkeypatch.setattr(MA, "snapshot", lambda *a, **k: dict(snap))
    return signaux


def test_la_dette_reelle_vient_du_snapshot_qualifie(monkeypatch):
    signaux = _brancher(monkeypatch, {"frais": True, "vector_pending": 77, "vector_refused": 6887715, "age_s": 60})
    out = R.check_embed_backlog(False)
    assert out["vector_pending"] == 77 and out["etat"] == "MESURE" and not signaux, out
    assert out.get("vector_refused") == 6887715, "le refus par politique est DIT, et n'est pas une dette"


def test_une_vraie_dette_qualifiee_est_signalee(monkeypatch):
    signaux = _brancher(monkeypatch, {"frais": True, "vector_pending": R.EMBED_BACKLOG_ALERT + 1, "age_s": 60})
    out = R.check_embed_backlog(False)
    assert out.get("signaled") and "embed_consolidation_debt" in signaux, out


def test_snapshot_perime_rend_inconnu_sans_balayage_ni_signal(monkeypatch):
    signaux = _brancher(monkeypatch, {"frais": False, "vector_pending": None, "age_s": 50000,
                                      "raison": "snapshot perime"})
    out = R.check_embed_backlog(False)
    assert out["etat"] == "INCONNU" and out["vector_pending"] is None and not signaux, out
    assert "perime" in out.get("raison", "")
