"""NR : `comparer_canal_memoire` sans moteur fourni ne charge jamais le corpus.

`RAGEngine()` parcourt toute `rag_chunks` (`_load_embeddings`) : balayage interdit par l'owner le 24/10.
Payé le 6/11 : deux jobs tués à 6,5 et 12,1 Go avant la moindre sortie.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_golden_rappel as GR  # noqa: E402


def test_sans_moteur_fourni_rend_no_verdict_sans_instancier(monkeypatch):
    def interdit():
        raise AssertionError("RAGEngine instancie : balayage de rag_chunks")

    monkeypatch.setattr(GR, "_instancier_engine", interdit)
    monkeypatch.setattr(GR, "_ram_libre_go", lambda: 64.0)
    monkeypatch.setattr(GR, "_dense_vivant", lambda: (True, "ok"))

    res = GR.comparer_canal_memoire([], verifier_gardes=True)

    assert res["ok"] is False
    assert res["verdict"] == "NO_VERDICT"
    assert "balayage" in res["refus"]
