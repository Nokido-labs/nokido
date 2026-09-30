#!/usr/bin/env python3
"""Tests unitaires pour tools/forge_qdrant_sidecar.py (TDD — SSoT Nokido 2026).

Vérifie :
1. Garde pression disque sur VeraCrypt / V: (seuil 5 Go — G3 Claude).
2. Verrou OS cross-platform (Windows msvcrt / Unix fcntl via portalocker ou fallback).
3. Initialisation du schéma de collection Qdrant (Dense INT8 + Sparse + ColBERT on_disk MAX_SIM).
4. Upsert et recherche hybride 2 étages (Prefetch RRF -> Reranking ColBERT MaxSim).
5. Service HTTP sidecar (/health, /search, /stats).
"""
import json
import os
import shutil
import tempfile
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models

from tools.forge_qdrant_sidecar import (
    COLLECTION_NAME,
    DiskPressureError,
    SovereignFileLock,
    check_disk_pressure,
    init_sovereign_db,
    upsert_chunks,
    search_hybrid,
    SidecarHTTPServer,
)


def test_disk_pressure_guard():
    """Vérifie que check_disk_pressure lève une erreur si l'espace libre est insuffisant."""
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        # Test avec un seuil irréaliste (ex: 100 000 Go) pour forcer le déclenchement de l'erreur
        with pytest.raises(DiskPressureError) as exc_info:
            check_disk_pressure(path=tmp_dir, min_free_gb=100000.0)
        assert "DISK_PRESSURE" in str(exc_info.value)
        
        # Test avec un seuil de 0.001 Go (doit passer sur n'importe quel disque sain)
        check_disk_pressure(path=tmp_dir, min_free_gb=0.001)


def test_sovereign_file_lock():
    """Vérifie que le verrou OS s'acquiert et se libère proprement sur Windows/Linux."""
    with tempfile.TemporaryDirectory(dir=".") as tmp_dir:
        lock_path = Path(tmp_dir) / "test_hub.lock"
        lock = SovereignFileLock(str(lock_path))
        
        lock.acquire()
        assert lock_path.exists()
        lock.release()


def test_init_sovereign_db_memory():
    """Vérifie la création du schéma SSoT dans Qdrant (en mémoire pour le test rapide)."""
    client = QdrantClient(":memory:")
    init_sovereign_db(client)
    
    assert client.collection_exists(COLLECTION_NAME)
    info = client.get_collection(COLLECTION_NAME)
    
    # Vérification des configs vectorielles
    assert "dense" in info.config.params.vectors
    assert info.config.params.vectors["dense"].size == 1024
    
    assert "sparse" in info.config.params.sparse_vectors
    assert "colbert" in info.config.params.vectors
    assert info.config.params.vectors["colbert"].on_disk is True
    assert info.config.params.vectors["colbert"].multivector_config.comparator == models.MultiVectorComparator.MAX_SIM


def test_upsert_and_search_hybrid():
    """Vérifie un cycle complet d'insertion et de recherche hybride 2 étages."""
    client = QdrantClient(":memory:")
    init_sovereign_db(client)
    
    # Création de vecteurs synthétiques (1024d)
    dense_1 = [0.1] * 1024
    dense_2 = [0.9] * 1024
    
    sparse_1 = models.SparseVector(indices=[10, 20, 30], values=[1.0, 2.0, 3.0])
    sparse_2 = models.SparseVector(indices=[10, 50, 60], values=[0.5, 1.0, 1.5])
    
    colbert_1 = [[0.1] * 1024, [0.2] * 1024]
    colbert_2 = [[0.8] * 1024, [0.9] * 1024]
    
    chunks = [
        {
            "id": "chunk_alpha",
            "path": "tools/alpha.py",
            "git_hash": "abc1234",
            "domain": "nokido_code",
            "tier": 1,
            "dense": dense_1,
            "sparse": sparse_1,
            "colbert": colbert_1,
            "text": "Code alpha"
        },
        {
            "id": "chunk_beta",
            "path": "tools/beta.py",
            "git_hash": "def5678",
            "domain": "nokido_code",
            "tier": 1,
            "dense": dense_2,
            "sparse": sparse_2,
            "colbert": colbert_2,
            "text": "Code beta"
        }
    ]
    
    count = upsert_chunks(client, chunks, skip_disk_check=True)
    assert count == 2
    
    # Recherche ciblant chunk_beta
    results = search_hybrid(
        client,
        query_dense=dense_2,
        query_sparse=sparse_2,
        query_colbert=colbert_2,
        top_k=5
    )
    
    assert len(results) >= 1
    assert results[0]["id"] == "chunk_beta"
    assert "score" in results[0]


def test_sidecar_http_endpoints():
    """Vérifie que le serveur HTTP sidecar répond aux requêtes /health et /stats."""
    client = QdrantClient(":memory:")
    init_sovereign_db(client)
    
    server = SidecarHTTPServer(client=client, host="127.0.0.1", port=0)
    port = server.server_port
    
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    
    try:
        time.sleep(0.1)
        conn = HTTPConnection("127.0.0.1", port, timeout=3)
        
        # Test /health
        conn.request("GET", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert data["status"] == "ok"
        assert data["collection"] == COLLECTION_NAME
        
        # Test /stats
        conn.request("GET", "/stats")
        resp = conn.getresponse()
        assert resp.status == 200
        stats_data = json.loads(resp.read().decode("utf-8"))
        assert "points_count" in stats_data
        
    finally:
        server.shutdown()
        server.server_close()
