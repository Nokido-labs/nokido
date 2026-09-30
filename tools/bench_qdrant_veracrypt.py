#!/usr/bin/env python3
"""bench_qdrant_veracrypt.py — Benchmark d'empreinte disque et latence mmap NVMe à travers VeraCrypt.

Objectif (Garde G3 Claude) :
1. Mesurer le temps d'insertion et l'empreinte disque sur le volume chiffré (RAG_DIR / V:).
2. Évaluer la latence de lecture mmap sur les matrices ColBERT (on_disk=True) + Cosine INT8.
3. Vérifier que la recherche hybride RRF + Rerank reste sous la barre des 20 ms à travers le pilote de chiffrement.

Usage :
  python tools/bench_qdrant_veracrypt.py [--chunks 500] [--queries 50]
"""
from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
sys.modules["redis"] = None  # Contournement PermissionError sur opentelemetry sous Windows
import time
from pathlib import Path
from typing import List

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from qdrant_client import QdrantClient
from qdrant_client.http import models

# Import du sidecar SSoT
from tools.forge_qdrant_sidecar import (
    COLLECTION_NAME,
    QDRANT_STORAGE_PATH,
    check_disk_pressure,
    init_sovereign_db,
    search_hybrid,
    upsert_chunks,
)

BENCH_DIR = QDRANT_STORAGE_PATH.parent / "bench_storage"
BENCH_COLLECTION = "nokido_bench_veracrypt"


def print_progress(current: int, total: int, prefix: str = "", length: int = 40):
    """Affiche une barre de progression ASCII souveraine (Règle user_global)."""
    percent = (current / total) * 100
    filled = int(length * current // total)
    bar = "█" * filled + "-" * (length - filled)
    sys.stdout.write(f"\r{prefix} |{bar}| {percent:.1f}% ({current}/{total})")
    sys.stdout.flush()
    if current == total:
        print()


def generate_synthetic_chunk(idx: int) -> dict:
    """Génère un chunk synthétique complet avec vecteurs Dense (1024d), Sparse et ColBERT (30x1024d)."""
    dense = [random.uniform(-1.0, 1.0) for _ in range(1024)]
    
    # Vecteur creux (BM25 simulé, 10 à 20 tokens actifs)
    num_sparse = random.randint(10, 20)
    indices = sorted(random.sample(range(10000), num_sparse))
    values = [random.uniform(0.1, 5.0) for _ in range(num_sparse)]
    
    # Matrice ColBERT (ex: 30 tokens de 1024 dim)
    colbert = [[random.uniform(-1.0, 1.0) for _ in range(1024)] for _ in range(30)]
    
    return {
        "id": f"bench_chunk_{idx}",
        "path": f"tools/bench/module_{idx % 10}.py",
        "git_hash": f"hash_{idx:04d}",
        "domain": "nokido_bench",
        "tier": 1,
        "dense": dense,
        "sparse": {"indices": indices, "values": values},
        "colbert": colbert,
        "text": f"Contenu synthétique pour le chunk de benchmark numéro {idx} dans Nokido."
    }


def run_benchmark(num_chunks: int = 200, num_queries: int = 30):
    print("=" * 70)
    print("🚀 BENCHMARK QDRANT SOVEREIGN — LATENCE & EMPREINTE VERACRYPT")
    print("=" * 70)
    print(f"📁 Répertoire cible : {BENCH_DIR.absolute()}")
    
    # Vérification garde pression disque
    try:
        check_disk_pressure(path=BENCH_DIR, min_free_gb=2.0)
    except Exception as e:
        print(f"❌ Arrêt prématuré : {e}")
        return

    # Nettoyage d'un éventuel run précédent
    if BENCH_DIR.exists():
        shutil.rmtree(BENCH_DIR, ignore_errors=True)
    BENCH_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[1/4] Initialisation du moteur Qdrant en mode Embedded (sur disque)...")
    t0 = time.perf_counter()
    client = QdrantClient(path=str(BENCH_DIR))
    
    # Création collection bench avec les paramètres exacts du SSoT
    client.create_collection(
        collection_name=BENCH_COLLECTION,
        vectors_config={
            "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE, on_disk=False),
            "colbert": models.VectorParams(
                size=1024,
                distance=models.Distance.COSINE,
                on_disk=True,  # ColBERT sur disque
                multivector_config=models.MultiVectorConfig(
                    comparator=models.MultiVectorComparator.MAX_SIM
                ),
            ),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(index=models.SparseIndexParams(on_disk=False))
        },
        hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
        quantization_config=models.ScalarQuantization(
            scalar=models.ScalarQuantizationConfig(
                type=models.ScalarType.INT8, quantile=0.99, always_ram=True
            )
        ),
    )
    t_init = (time.perf_counter() - t0) * 1000
    print(f"✅ Collection '{BENCH_COLLECTION}' créée en {t_init:.2f} ms.")

    print(f"\n[2/4] Génération et insertion de {num_chunks} chunks multi-vecteurs...")
    batch_size = 25
    t_upsert_start = time.perf_counter()
    
    # Patch temporaire pour que upsert_chunks utilise BENCH_COLLECTION
    import tools.forge_qdrant_sidecar as sidecar_mod
    orig_col = sidecar_mod.COLLECTION_NAME
    sidecar_mod.COLLECTION_NAME = BENCH_COLLECTION

    try:
        for i in range(0, num_chunks, batch_size):
            batch = [generate_synthetic_chunk(j) for j in range(i, min(i + batch_size, num_chunks))]
            upsert_chunks(client, batch, skip_disk_check=True)
            print_progress(min(i + batch_size, num_chunks), num_chunks, prefix="Upsert")
    finally:
        sidecar_mod.COLLECTION_NAME = orig_col

    t_upsert_total = time.perf_counter() - t_upsert_start
    print(f"✅ {num_chunks} chunks insérés en {t_upsert_total:.2f} s ({num_chunks/t_upsert_total:.1f} chunks/s).")

    # Mesure empreinte disque
    disk_bytes = sum(f.stat().st_size for f in BENCH_DIR.rglob("*") if f.is_file())
    disk_mb = disk_bytes / (1024 * 1024)
    mb_per_chunk = disk_mb / max(num_chunks, 1)
    print(f"\n[3/4] Mesure de l'empreinte sur disque chiffré :")
    print(f"   - Poids total du stockage Qdrant : {disk_mb:.2f} Mo")
    print(f"   - Poids moyen par chunk          : {mb_per_chunk * 1024:.2f} Ko/chunk")
    print(f"   - Empreinte estimée pour 650k chunks : {(mb_per_chunk * 650000) / 1024:.2f} Go")

    print(f"\n[4/4] Benchmark de latence mmap NVMe (Recherche Hybride RRF + ColBERT)...")
    sidecar_mod.COLLECTION_NAME = BENCH_COLLECTION
    latencies = []
    
    try:
        for q in range(num_queries):
            query_dense = [random.uniform(-1.0, 1.0) for _ in range(1024)]
            query_sparse = {"indices": [10, 50, 100], "values": [1.0, 2.0, 1.5]}
            query_colbert = [[random.uniform(-1.0, 1.0) for _ in range(1024)] for _ in range(5)]
            
            t_q0 = time.perf_counter()
            res = search_hybrid(
                client,
                query_dense=query_dense,
                query_sparse=query_sparse,
                query_colbert=query_colbert,
                top_k=5,
            )
            t_q_end = (time.perf_counter() - t_q0) * 1000
            latencies.append(t_q_end)
            print_progress(q + 1, num_queries, prefix="Query ")
    finally:
        sidecar_mod.COLLECTION_NAME = orig_col

    avg_lat = sum(latencies) / len(latencies)
    min_lat = min(latencies)
    max_lat = max(latencies)
    p95_lat = sorted(latencies)[int(0.95 * len(latencies))]

    print("\n" + "=" * 70)
    print("📊 RÉSULTATS DE LATENCE (à travers chiffrement VeraCrypt)")
    print("=" * 70)
    print(f"   - Latence moyenne : {avg_lat:.2f} ms")
    print(f"   - Latence min     : {min_lat:.2f} ms")
    print(f"   - Latence max     : {max_lat:.2f} ms")
    print(f"   - Latence P95     : {p95_lat:.2f} ms")
    print("=" * 70)

    if avg_lat < 20.0:
        print("🎯 SUCCÈS : Objectif SLA (< 20 ms) respecté haut la main sur matériel local !")
    else:
        print("⚠️ ATTENTION : La latence moyenne dépasse 20 ms. Une optimisation de préfetch peut être requise.")

    # Nettoyage
    client.close()
    if BENCH_DIR.exists():
        shutil.rmtree(BENCH_DIR, ignore_errors=True)
    print("🧹 Répertoire de bench nettoyé.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bench Qdrant VeraCrypt")
    parser.add_argument("--chunks", type=int, default=100, help="Nombre de chunks à tester (défaut: 100)")
    parser.add_argument("--queries", type=int, default=20, help="Nombre de requêtes de test (défaut: 20)")
    args = parser.parse_args()

    run_benchmark(num_chunks=args.chunks, num_queries=args.queries)
