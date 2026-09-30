#!/usr/bin/env python3
"""forge_qdrant_sidecar.py — Module Sidecar Qdrant (SSoT RAG Nokido 2026 - Multi-CLI Safe).

Successeur direct de forge_faiss_sidecar :8097, implémentant l'architecture "Local Daemon + IPC" (G1 & G3 Claude) :
1. Isolation du moteur vectoriel hors de l'event-loop du Hub (pas de GIL-lock).
2. Schéma SSoT Multi-Vecteurs :
   - Dense 1024d Cosine + Quantification INT8 (always_ram=True).
   - Sparse BM25 (en RAM).
   - ColBERT 1024d Cosine + MAX_SIM (on_disk=True -> 0% impact RAM, anti-OOM ~390 Go).
3. Garde pression disque VeraCrypt V: (DISK_PRESSURE, seuil 5 Go).
4. Mutex distribué cross-platform (Windows msvcrt / Unix fcntl via portalocker ou fallback) pour synchroniser
   le cycle atomique Chunking -> Qdrant Upsert -> Git Commit.
5. Requête Hybride 2 étages : Prefetch RRF (Top 30) -> Reranking ColBERT MaxSim (Top k).

CLI :
  --serve [--port 8098]   Lance le serveur HTTP sidecar en tâche de fond
  --init                  Initialise la collection dans Qdrant
  --stats                 Affiche le nombre de points et la consommation mémoire/disque
  --selftest              Exécute un test d'intégrité de bout en bout
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
sys.modules["redis"] = None  # Contournement PermissionError sur opentelemetry sous Windows
import threading
import time
import uuid
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

# Configuration par défaut
ROOT_DIR = Path(__file__).resolve().parent.parent
RAG_DIR = ROOT_DIR / "RAG"
QDRANT_STORAGE_PATH = RAG_DIR / "qdrant_storage"
COLLECTION_NAME = "nokido_sovereign_rag"
DEFAULT_PORT = 8098
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
# Lock HORS racine repo (sandbox/ = writable tous rings ; "hub.lock" à la
# racine cassait les tests hors-owner et polluait le working tree).
LOCK_FILE = ROOT_DIR / "sandbox" / "qdrant_sidecar.lock"
DISK_PRESSURE_THRESHOLD_GB = 5.0  # Garde V: VeraCrypt (G3 Claude)


class DiskPressureError(RuntimeError):
    """Levée lorsque l'espace disque disponible chute sous le seuil critique (VeraCrypt V:)."""
    pass


def check_disk_pressure(path: str | Path = RAG_DIR, min_free_gb: float = DISK_PRESSURE_THRESHOLD_GB) -> None:
    """Vérifie l'espace disque disponible sur le volume hébergeant le RAG.
    
    Lève une DiskPressureError (hormone DISK_PRESSURE) si l'espace libre est < min_free_gb.
    """
    target_path = Path(path)
    if not target_path.exists():
        target_path = target_path.parent
    if not target_path.exists():
        target_path = Path(".")

    usage = shutil.disk_usage(target_path)
    free_gb = usage.free / (1024 ** 3)
    
    if free_gb < min_free_gb:
        msg = (
            f"[DISK_PRESSURE] Espace libre critique sur {target_path.absolute()} : "
            f"{free_gb:.2f} Go disponibles (< seuil de {min_free_gb:.2f} Go). Écriture bloquée."
        )
        raise DiskPressureError(msg)


class SovereignFileLock:
    """Verrou OS multi-plateforme (Windows msvcrt / Unix fcntl via portalocker ou fallback) sans dépendance bloquante."""
    def __init__(self, lock_file: str | Path = LOCK_FILE):
        self.lock_file = str(lock_file)
        self.fd = None

    def acquire(self) -> None:
        self.fd = os.open(self.lock_file, os.O_CREAT | os.O_RDWR)
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(self.fd, msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(self.fd, fcntl.LOCK_EX)

    def release(self) -> None:
        if self.fd is not None:
            if os.name == "nt":
                import msvcrt
                try:
                    os.lseek(self.fd, 0, os.SEEK_SET)
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


def get_qdrant_client(path: str | Path = QDRANT_STORAGE_PATH, prefer_daemon: bool | None = None) -> QdrantClient:
    """Retourne un client Qdrant. Blueprint SSoT = EMBEDDED EXCLUSIF par défaut ;
    le daemon :6333 est un opt-in explicite (LAFORGE_QDRANT_PREFER_DAEMON=1),
    jamais une bascule silencieuse (un conteneur qui écoute :6333 ne doit pas
    détourner le RAG local)."""
    if isinstance(path, str) and path == ":memory:":
        return QdrantClient(":memory:")

    if prefer_daemon is None:
        prefer_daemon = os.environ.get("LAFORGE_QDRANT_PREFER_DAEMON", "0") == "1"
    if prefer_daemon:
        try:
            client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=1.0)
            client.get_collections()
            return client
        except Exception:
            pass  # Fallback sur Embedded

    os.makedirs(path, exist_ok=True)
    return QdrantClient(path=str(path))


def ensure_ram_profile(client: QdrantClient) -> dict:
    """Applique le profil RAM (HNSW on_disk + INT8 NON resident) a une collection DEJA creee.

    create_collection ne vaut QUE pour la creation : sur une collection existante, les
    parametres economes passes plus bas sont ignores en silence et le gain RAM annonce
    est FICTIF. Rend un dict a etat EXPLICITE (applique / deja_conforme / echec /
    illisible) : un capteur incapable de distinguer -rien a faire- de -je ne peux pas
    voir- fabrique des faux negatifs.

    Limite assumee : le placement on_disk des VECTEURS eux-memes (dense / colbert) nest
    pas modifiable a chaud sur toutes les versions de Qdrant. Si le rapport rend
    dense_on_disk False, seule une RECREATION de la collection le corrigera.
    """
    import logging as _lg

    _log = _lg.getLogger(__name__)

    def _read() -> dict:
        info = client.get_collection(COLLECTION_NAME)
        cfg = info.config
        _sc = getattr(getattr(cfg, "quantization_config", None), "scalar", None)
        _vec = getattr(getattr(cfg, "params", None), "vectors", None) or {}
        _dense = _vec.get("dense") if isinstance(_vec, dict) else None
        return {
            "always_ram": getattr(_sc, "always_ram", None),
            "hnsw_on_disk": getattr(getattr(cfg, "hnsw_config", None), "on_disk", None),
            "dense_on_disk": getattr(_dense, "on_disk", None),
        }

    try:
        before = _read()
    except Exception as exc:
        _log.warning("qdrant ensure_ram_profile: etat ILLISIBLE (%r)", exc)
        return {"state": "illisible", "reason": repr(exc)}

    if before.get("always_ram") is False and before.get("hnsw_on_disk") is True:
        return {"state": "deja_conforme", "before": before}

    try:
        client.update_collection(
            collection_name=COLLECTION_NAME,
            hnsw_config=models.HnswConfigDiff(on_disk=True),
            quantization_config=models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(
                    type=models.ScalarType.INT8, quantile=0.99, always_ram=False
                )
            ),
        )
    except Exception as exc:
        _log.warning("qdrant ensure_ram_profile: update REFUSE (%r) | etat=%s", exc, before)
        return {"state": "echec", "before": before, "reason": repr(exc)}

    try:
        after = _read()
    except Exception as exc:
        return {"state": "applique_non_verifie", "before": before, "reason": repr(exc)}

    if after.get("dense_on_disk") is False:
        _log.warning(
            "qdrant: HNSW/quantization economes appliques MAIS dense_on_disk=False "
            "-> les vecteurs restent en RAM ; recreer la collection pour le gain complet"
        )
    _log.info("qdrant ensure_ram_profile: %s -> %s", before, after)
    return {"state": "applique", "before": before, "after": after}


def init_sovereign_db(client: Optional[QdrantClient] = None, path: str | Path = QDRANT_STORAGE_PATH) -> QdrantClient:
    """Initialise le schéma vectoriel SSoT Nokido dans Qdrant."""
    if client is None:
        client = get_qdrant_client(path)

    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE, on_disk=True),
                "colbert": models.VectorParams(
                    size=1024,
                    distance=models.Distance.COSINE,
                    on_disk=True,  # CRITIQUE : Évite l'allocation de ~390 Go RAM
                    multivector_config=models.MultiVectorConfig(
                        comparator=models.MultiVectorComparator.MAX_SIM
                    ),
                ),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(index=models.SparseIndexParams(on_disk=True))
            },
            hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100, full_scan_threshold=10000, on_disk=True),
            quantization_config=models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(
                    type=models.ScalarType.INT8, quantile=0.99, always_ram=False
                )
            ),
        )
    else:
        ensure_ram_profile(client)
    return client


def _to_qdrant_id(raw_id: Any) -> str | int:
    """Convertit un ID arbitraire (string SQLite) en ID Qdrant valide (int ou UUID)."""
    if isinstance(raw_id, int):
        return raw_id
    if isinstance(raw_id, str):
        if raw_id.isdigit():
            return int(raw_id)
        try:
            uuid.UUID(raw_id)
            return raw_id
        except ValueError:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, raw_id))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, str(raw_id)))


def upsert_chunks(client: QdrantClient, chunks: List[Dict[str, Any]], skip_disk_check: bool = False) -> int:
    """Insère ou met à jour des chunks vectorisés avec protection de pression disque et verrou OS."""
    if not chunks:
        return 0

    if not skip_disk_check and not (isinstance(client._client, object) and getattr(client._client, "_location", "") == ":memory:"):
        check_disk_pressure()

    points = []
    for item in chunks:
        chunk_id = item.get("id") or str(item.get("chunk_index", 0))
        qdrant_id = _to_qdrant_id(chunk_id)
        dense_vec = item.get("dense")
        sparse_vec = item.get("sparse")
        colbert_vec = item.get("colbert")

        vectors: Dict[str, Any] = {}
        if dense_vec is not None:
            vectors["dense"] = dense_vec
        if sparse_vec is not None:
            if isinstance(sparse_vec, dict):
                vectors["sparse"] = models.SparseVector(
                    indices=sparse_vec.get("indices", []),
                    values=sparse_vec.get("values", [])
                )
            elif isinstance(sparse_vec, models.SparseVector):
                vectors["sparse"] = sparse_vec
        if colbert_vec is not None:
            vectors["colbert"] = colbert_vec

        payload = {k: v for k, v in item.items() if k not in ("dense", "sparse", "colbert")}
        payload["chunk_id"] = str(chunk_id)  # Mémorise l'ID SQLite d'origine pour le mapping inverse

        points.append(
            models.PointStruct(
                id=qdrant_id,
                vector=vectors,
                payload=payload,
            )
        )

    with SovereignFileLock():
        client.upsert(collection_name=COLLECTION_NAME, points=points)

    return len(points)


def search_hybrid(
    client: QdrantClient,
    query_dense: Optional[List[float]] = None,
    query_sparse: Optional[models.SparseVector | Dict[str, List]] = None,
    query_colbert: Optional[List[List[float]]] = None,
    top_k: int = 5,
    domain_filter: Optional[str] = None,
    limit_prefetch: int = 30,
) -> List[Dict[str, Any]]:
    """Requête Hybride 2 étages : Prefetch RRF (dense+sparse) -> Reranking ColBERT MaxSim."""
    query_filter = None
    if domain_filter:
        query_filter = models.Filter(
            must=[models.FieldCondition(key="domain", match=models.MatchValue(value=domain_filter))]
        )

    prefetches = []
    if query_dense is not None:
        prefetches.append(
            models.Prefetch(query=query_dense, using="dense", limit=limit_prefetch, filter=query_filter)
        )
    if query_sparse is not None:
        if isinstance(query_sparse, dict):
            sparse_obj = models.SparseVector(
                indices=query_sparse.get("indices", []),
                values=query_sparse.get("values", [])
            )
        else:
            sparse_obj = query_sparse
        prefetches.append(
            models.Prefetch(query=sparse_obj, using="sparse", limit=limit_prefetch, filter=query_filter)
        )

    if not prefetches and query_colbert is None:
        return []

    # Construction de la requête principale
    if len(prefetches) > 1:
        rrf_prefetch = [
            models.Prefetch(
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                prefetch=prefetches,
                limit=limit_prefetch,
            )
        ]
    else:
        rrf_prefetch = prefetches

    # Précision (parité mesurée 2026-07-06, 544k points, golden set 20 req) :
    # HNSW défauts (m=16, ef_construct=100) = recall 0.66 ; ef=256+rescore =
    # 0.735 ; exact=True = 1.00 à p50 71ms / max 234ms (SIMD Rust + INT8
    # rescoré) — meilleur que le faiss :8097 (~120ms). EXACT par défaut ;
    # repasser en HNSW seulement après rebuild d'index (m>=32, ef_construct
    # >=256) ET re-parité >=0.95. Override : LAFORGE_QDRANT_EXACT=0.
    _search_params = models.SearchParams(
        exact=os.environ.get("LAFORGE_QDRANT_EXACT", "1") != "0",
        hnsw_ef=256,
        quantization=models.QuantizationSearchParams(rescore=True, oversampling=2.0),
    )

    if query_colbert is not None and rrf_prefetch:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=rrf_prefetch,
            query=query_colbert,
            using="colbert",
            limit=top_k,
            with_payload=True,
        )
    elif query_colbert is not None:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_colbert,
            using="colbert",
            limit=top_k,
            with_payload=True,
        )
    elif len(prefetches) > 1:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=prefetches,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
    else:
        # Vecteur UNIQUE (ex: dense seul, chemin Phase A) : query directe AVEC
        # `using=` — sans lui Qdrant cherche le vecteur anonyme "" -> 500
        # « Dense vector '' is not found in the collection ».
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=prefetches[0].query,
            using=prefetches[0].using,
            limit=top_k,
            with_payload=True,
            search_params=_search_params,
        )

    formatted = []
    for pt in results.points:
        formatted.append({
            "id": pt.payload.get("chunk_id", pt.id) if pt.payload else pt.id,
            "qdrant_id": pt.id,
            "score": pt.score,
            "payload": pt.payload or {},
        })
    return formatted


def rerank_remote(query: str, results: List[Dict[str, Any]], top_n: int = 5, port: int = 8100) -> List[Dict[str, Any]]:
    """Rerank HORS-HUB (lot C1 2026-07-07) via l'endpoint llama-server local (:8100 /v1/rerank).
    
    Exécuté dans le process du sidecar Qdrant (:8098), ne bloque jamais l'event-loop asyncio du Hub.
    Fallback gracieux sur l'ordre de pertinence Qdrant si le reranker est indisponible.
    """
    if not query or not results:
        return results[:top_n]
    try:
        import urllib.request
        docs_text = [r.get("payload", {}).get("text", "") or str(r.get("id", "")) for r in results]
        body = json.dumps({"model": "bge-reranker", "query": query, "documents": docs_text}).encode("utf-8")
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/rerank",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("results", data.get("data", []))
            for item in items:
                idx = item.get("index")
                if idx is not None and 0 <= idx < len(results):
                    results[idx]["rerank_score"] = item.get("relevance_score", item.get("score", 0.0))
            results.sort(key=lambda r: r.get("rerank_score", r.get("score", 0.0)), reverse=True)
    except Exception as e:
        pass
    return results[:top_n]


class SidecarHTTPRequestHandler(BaseHTTPRequestHandler):
    """Gestionnaire HTTP pour le process sidecar Qdrant."""
    server: SidecarHTTPServer

    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "collection": COLLECTION_NAME,
                "engine": "qdrant_sidecar",
            })
        elif self.path == "/stats":
            try:
                info = self.server.client.get_collection(COLLECTION_NAME)
                self._send_json(200, {
                    "points_count": info.points_count,
                    "vectors_count": getattr(info, "vectors_count", info.points_count),
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "Endpoint inconnu"})

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            self._send_json(400, {"error": "JSON invalide"})
            return

        if self.path == "/search":
            try:
                # Compat contrat hub (forge_faiss_sidecar.search_remote, cf
                # COMMUNICATIONS.md 2026-07-06T18:05) : {qvec, k} en entrée ->
                # réponse [[chunk_id, score]]. Le format riche AGY
                # (query_dense/query_sparse/query_colbert/top_k) reste intact.
                hub_compat = "qvec" in payload
                top_k_req = int(payload.get("top_k") or payload.get("k") or 5)
                do_rerank = payload.get("rerank", False) and (q_text := (payload.get("query_text") or payload.get("query") or payload.get("q")))
                fetch_k = top_k_req * 4 if do_rerank else top_k_req
                res = search_hybrid(
                    self.server.client,
                    query_dense=payload.get("query_dense") or payload.get("qvec"),
                    query_sparse=payload.get("query_sparse"),
                    query_colbert=payload.get("query_colbert"),
                    top_k=fetch_k,
                    domain_filter=payload.get("domain"),
                )
                if do_rerank:
                    res = rerank_remote(str(q_text), res, top_n=top_k_req)
                if hub_compat:
                    self._send_json(200, {"results": [[r["id"], r.get("rerank_score", r["score"])] for r in res]})
                else:
                    self._send_json(200, {"results": res})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        elif self.path == "/upsert":
            try:
                chunks = payload.get("chunks", [])
                count = upsert_chunks(self.server.client, chunks)
                self._send_json(200, {"status": "ok", "upserted": count})
            except DiskPressureError as dpe:
                self._send_json(507, {"error": str(dpe), "hormone": "DISK_PRESSURE"})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        elif self.path == "/delete_by_path":
            try:
                target_path = payload.get("path")
                if not target_path:
                    self._send_json(400, {"error": "Paramètre 'path' requis"})
                    return
                with SovereignFileLock():
                    self.server.client.delete(
                        collection_name=COLLECTION_NAME,
                        points_selector=models.FilterSelector(
                            filter=models.Filter(
                                must=[models.FieldCondition(key="path", match=models.MatchValue(value=target_path))]
                            )
                        ),
                    )
                self._send_json(200, {"status": "ok", "deleted_path": target_path})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
        else:
            self._send_json(404, {"error": "Endpoint inconnu"})


class SidecarHTTPServer(ThreadingHTTPServer):
    """Serveur HTTP Threadé pour Qdrant Sidecar."""
    def __init__(self, client: QdrantClient, host: str = "127.0.0.1", port: int = DEFAULT_PORT):
        super().__init__((host, port), SidecarHTTPRequestHandler)
        self.client = client


def run_selftest() -> bool:
    """Exécute un test d'intégrité E2E (Init, Upsert, Query, Delete, Lock, Pression Disque)."""
    print("[selftest] Initialisation client mémoire...")
    client = QdrantClient(":memory:")
    init_sovereign_db(client)
    
    print("[selftest] Upsert chunk test...")
    chunks = [{
        "id": "selftest_1",
        "path": "test/selftest.py",
        "git_hash": "a1b2c3d",
        "domain": "test",
        "dense": [0.5] * 1024,
        "text": "Hello Qdrant Sidecar"
    }]
    count = upsert_chunks(client, chunks, skip_disk_check=True)
    if count != 1:
        print("[selftest] ÉCHEC: Upsert n'a pas renvoyé 1.")
        return False

    print("[selftest] Recherche hybride...")
    res = search_hybrid(client, query_dense=[0.5] * 1024, top_k=1)
    if not res or res[0]["id"] != "selftest_1":
        print("[selftest] ÉCHEC: Recherche n'a pas trouvé selftest_1.")
        return False

    print("[selftest] Test de garde pression disque...")
    try:
        check_disk_pressure(path=".", min_free_gb=100000.0)
        print("[selftest] ÉCHEC: Pression disque n'a pas levé DiskPressureError.")
        return False
    except DiskPressureError:
        print("[selftest] Pression disque correctement interceptée (hormone DISK_PRESSURE).")

    print("[selftest] SUCCÈS COMPLET du selftest.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Forge Qdrant Sidecar Service (:8098)")
    parser.add_argument("--serve", action="store_true", help="Lance le serveur HTTP sidecar")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port HTTP (défaut: 8098)")
    parser.add_argument("--init", action="store_true", help="Initialise la collection dans Qdrant")
    parser.add_argument("--stats", action="store_true", help="Affiche les statistiques de la collection")
    parser.add_argument("--selftest", action="store_true", help="Exécute les diagnostics E2E")
    args = parser.parse_args()

    if args.selftest:
        sys.exit(0 if run_selftest() else 1)

    client = init_sovereign_db()

    if args.init:
        print(f"Collection '{COLLECTION_NAME}' initialisée avec succès.")
        sys.exit(0)

    if args.stats:
        info = client.get_collection(COLLECTION_NAME)
        print(f"Collection : {COLLECTION_NAME}")
        print(f"Points     : {info.points_count}")
        sys.exit(0)

    if args.serve:
        print(f"[QdrantSidecar] Démarrage du serveur sur http://127.0.0.1:{args.port}")
        server = SidecarHTTPServer(client=client, host="127.0.0.1", port=args.port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n[QdrantSidecar] Arrêt du serveur.")
            server.shutdown()
            server.server_close()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
