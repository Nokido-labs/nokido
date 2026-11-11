"""NR -- FileLock inter-processus et option no_rag_scan sur tools/forge_golden_rappel.py.

Contrat (CORRECTION 06, lot 6 campagne 20261109) :
  1. Deux ecritures concurrentes via FileLock ne corrompent pas le fichier de sortie
     (lecture JSON valide, integrite preservee).
  2. no_rag_scan=True (parametre et flag CLI) n'ouvre AUCUNE connexion a la base RAG
     (embeddings.db) et n'instancie jamais RAGEngine (verdict NO_VERDICT immediat).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_golden_rappel as GR  # noqa: E402


def test_deux_ecritures_concurrentes_ne_corrompent_pas_le_fichier(tmp_path):
    target = tmp_path / "sortie_concurrente.json"
    nb_workers = 10

    def worker(i):
        data = {
            "worker_id": i,
            "mesurees": 5,
            "verdict": "VALIDE",
            "payload": "chunk_" * 200,
        }
        GR.ecrire_sortie(target, data)
        return True

    with ThreadPoolExecutor(max_workers=nb_workers) as pool:
        succes = list(pool.map(worker, range(nb_workers)))

    assert all(succes)
    assert target.exists()
    # Le fichier doit contenir un JSON strictement valide et non tronque
    lu = json.loads(target.read_text(encoding="utf-8"))
    assert "worker_id" in lu
    assert lu["verdict"] == "VALIDE"
    assert lu["payload"] == "chunk_" * 200


def test_no_rag_scan_comparer_canal_memoire_sans_connexion_rag(monkeypatch):
    real_connect = sqlite3.connect

    def connect_bloquant(*args, **kwargs):
        cible = str(args[0]) if args else str(kwargs.get("database", ""))
        if "embeddings.db" in cible:
            raise AssertionError("Interdit : sqlite3.connect appele sur embeddings.db avec no_rag_scan=True !")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect_bloquant)

    # Sans moteur fourni et avec no_rag_scan=True -> refus NO_VERDICT sans connexion ni balayage
    res = GR.comparer_canal_memoire(
        questions=[{"id": "q1", "question": "test ?", "sources_attendues": ["s1"]}],
        engine=None,
        verifier_gardes=False,
        no_rag_scan=True,
    )
    assert res.get("verdict") == "NO_VERDICT"
    assert "instanciation de RAGEngine = balayage de rag_chunks" in res.get("refus", "")
    assert "no_rag_scan" in res.get("pourquoi", "")


def test_main_cli_no_rag_scan_ouvre_aucune_connexion_rag(tmp_path, monkeypatch):
    real_connect = sqlite3.connect

    def connect_bloquant(*args, **kwargs):
        cible = str(args[0]) if args else str(kwargs.get("database", ""))
        if "embeddings.db" in cible:
            raise AssertionError("Interdit : connexion a embeddings.db avec --no-rag-scan !")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect_bloquant)

    jeu_factice = tmp_path / "jeu.json"
    jeu_factice.write_text(json.dumps({
        "questions": [
            {"id": "q1", "question": "question factice ?", "sources_attendues": ["fake_chunk#1"]}
        ]
    }), encoding="utf-8")

    sortie_factice = tmp_path / "sortie_refus.json"

    # Execution de main avec --no-rag-scan et --comparer-canal-memoire
    code_retour = GR.main([
        "--jeu", str(jeu_factice),
        "--sortie", str(sortie_factice),
        "--comparer-canal-memoire",
        "--no-rag-scan",
    ])

    assert code_retour == 3  # Refus NO_VERDICT
    assert sortie_factice.exists()
    donnees = json.loads(sortie_factice.read_text(encoding="utf-8"))
    assert donnees.get("verdict") == "NO_VERDICT"
    assert "no_rag_scan" in donnees.get("pourquoi", "")


def test_sans_no_rag_scan_le_refus_de_balayage_tient(monkeypatch):
    """9/11 : la livraison AGY remplacait le refus par une instanciation sous FileLock (balayage serialise,
    pas empeche). Par DEFAUT (no_rag_scan=False), engine=None doit rester un refus, sans jamais instancier."""
    def instanciation_interdite(*_a, **_k):
        raise AssertionError("RAGEngine instancie : balayage de rag_chunks")

    monkeypatch.setattr(GR, "_instancier_engine", instanciation_interdite, raising=False)
    res = GR.comparer_canal_memoire(
        questions=[{"id": "q1", "question": "test ?", "sources_attendues": ["s1"]}],
        engine=None,
        verifier_gardes=False,
    )
    assert res.get("verdict") == "NO_VERDICT"
    assert "balayage de rag_chunks" in res.get("refus", "")
