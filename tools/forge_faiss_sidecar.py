#!/usr/bin/env python3
"""forge_faiss_sidecar.py — P1 hub_concurrency : vector-search en PROCESS SÉPARÉ.

POURQUOI (HUB_CONCURRENCY_MIGRATION P1) : forge_rag_engine.search fait la sim vectorielle
in-process (numpy, to_thread = P0, GIL partagé). Le P1 réel = amputer le vector-search HORS
de l'event-loop du hub vers un SIDECAR : process dédié, faiss IndexFlatIP chargé 1×, bound+
timeout. Le hub redevient routeur async mince. **ID-based** : retourne (chunk_id, sim), PAS un
row-index → découplé de l'ordre des chunks en mémoire du hub (robuste).

CLI :
  --serve [--port 8097]   worker : charge l'index 1×, sert POST /search + GET /health (HTTP)
  --selftest              charge + query (vecteur du 1er chunk) + vérifie self-match top-1 (E2E)
  --stats                 compte les chunks embeddés (sans charger faiss)

Client hub : search_remote(qvec, k) -> [(chunk_id, sim)] ; lève si down -> fallback numpy hub.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import os as _os

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
# Switch dual-read (chantier Qdrant 2026) : le hub et les clients lisent le
# port ici -> pointer le sidecar Qdrant (:8098, même API /health /search)
# via env, sans toucher forge_rag_engine.
DEFAULT_PORT = int(_os.environ.get("LAFORGE_VEC_SIDECAR_PORT", "8097"))
DIM = 1024

# index chargé 1× dans le worker (process-global)
_IDX: dict = {"faiss": None, "mat": None, "ids": [], "loaded_at": 0.0, "n": 0}


def _decode_emb(blob):
    """BLOB float32 1024D OU JSON TEXT (miroir forge_rag_engine._decode_embedding_blob)."""
    import numpy as np
    if blob is None:
        return None
    if isinstance(blob, (bytes, bytearray)):
        if blob[:1] == b"[":
            try:
                a = np.asarray(json.loads(bytes(blob).decode("utf-8")), dtype="float32")
                return a if a.size == DIM else None
            except Exception:
                return None
        if len(blob) % 4:
            return None
        a = np.frombuffer(bytes(blob), dtype="float32")
        return a if a.size == DIM else None
    if isinstance(blob, str):
        try:
            a = np.asarray(json.loads(blob), dtype="float32")
            return a if a.size == DIM else None
        except Exception:
            return None
    return None


def _load_rows():
    """(ids, matrice float32 N×DIM) des chunks embeddés. SQL borné, decode robuste."""
    import numpy as np
    conn = sqlite3.connect(str(DB), timeout=15)
    conn.row_factory = None
    rows = conn.execute(
        "SELECT id, embedding FROM rag_chunks WHERE embedding IS NOT NULL"
    ).fetchall()
    conn.close()
    ids, vecs = [], []
    for cid, blob in rows:
        v = _decode_emb(blob)
        if v is not None:
            ids.append(cid)
            vecs.append(v)
    mat = np.vstack(vecs).astype("float32") if vecs else np.zeros((0, DIM), dtype="float32")
    return ids, mat


def load_index() -> dict:
    """Charge l'index 1× (faiss IndexFlatIP normalisé = cosine ; fallback numpy si faiss absent)."""
    import numpy as np
    t0 = time.time()
    ids, mat = _load_rows()
    faiss_idx = None
    if len(mat):
        try:
            import faiss
            m = mat.copy()
            faiss.normalize_L2(m)
            faiss_idx = faiss.IndexFlatIP(DIM)
            faiss_idx.add(m)
        except Exception:
            faiss_idx = None  # fallback numpy (normes pré-calculées)
    # normes : SEULEMENT pour le fallback numpy (faiss normalise sa propre copie). float64
    # pour éviter l'overflow float32 sur les embeddings à valeurs énormes (data sale).
    norms = None
    if faiss_idx is None and len(mat):
        norms = np.linalg.norm(mat.astype("float64"), axis=1).astype("float32")
    _IDX.update({"faiss": faiss_idx, "mat": mat, "norms": norms, "ids": ids,
                 "loaded_at": time.time(), "n": len(ids),
                 "backend": "faiss" if faiss_idx is not None else "numpy"})
    _IDX["load_ms"] = int((time.time() - t0) * 1000)
    return _IDX


def _db_count() -> int:
    """Compte rapide des chunks embeddés (fingerprint cheap, sans charger faiss)."""
    try:
        conn = sqlite3.connect(str(DB), timeout=5)
        n = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        return _IDX["n"]


def _watch_loop(interval: float = 20.0):
    """Refresh AUTO : si la DB change (reindex live d'un autre agent) -> reload l'index.
    Évite le stale quand Gemini réindexe embeddings.db en tâche de fond."""
    def _run():
        while True:
            time.sleep(interval)
            try:
                c = _db_count()
                delta = abs(c - _IDX["n"])
                age = time.time() - _IDX.get("loaded_at", 0)
                # Anti-churn (RCA 2026-07-06) : un reload prend 20-80s sous
                # contention ; recharger à CHAQUE delta pendant un drain/flux
                # vivant = sidecar quasi toujours en reload -> le hub le croit
                # mort (sidecar_alive 0.5s) et retombe sur la matrice numpy.
                # Reload seulement si delta significatif OU index vieux d'1h.
                if delta and (delta > 500 or age > 3600):
                    print(f"[faiss-sidecar] DB changée ({_IDX['n']} -> {c}, age {int(age)}s) — reload index", flush=True)
                    load_index()
            except Exception:
                pass
    threading.Thread(target=_run, daemon=True).start()


def _search_local(qvec, k: int) -> list:
    """top-k (chunk_id, sim) sur l'index chargé. faiss si dispo, sinon numpy dot."""
    import numpy as np
    if not _IDX["ids"]:
        return []
    q = np.asarray(qvec, dtype="float32")
    if q.size != DIM:
        return []
    k = max(1, min(int(k), _IDX["n"]))
    if _IDX["faiss"] is not None:
        qn = q / (np.linalg.norm(q) + 1e-9)
        sims, idxs = _IDX["faiss"].search(qn.reshape(1, -1), k)
        return [(_IDX["ids"][i], float(s)) for s, i in zip(sims[0], idxs[0]) if i >= 0]
    sims = np.dot(_IDX["mat"], q) / (_IDX["norms"] * (np.linalg.norm(q) + 1e-9) + 1e-9)
    top = np.argsort(sims)[::-1][:k]
    return [(_IDX["ids"][i], float(sims[i])) for i in top]


# ───────────────────────────── WORKER (serve) ──────────────────────────────
class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            # PAS de _db_count() ici : COUNT full-scan à chaque GET = health
            # lent sous contention -> liveness check du hub (0.5s) échoue à tort.
            self._send(200, {"ok": True, "n": _IDX["n"], "backend": _IDX.get("backend"),
                             "loaded_at": _IDX["loaded_at"], "load_ms": _IDX.get("load_ms")})
        elif self.path.startswith("/reload"):
            load_index()
            self._send(200, {"ok": True, "reloaded": True, "n": _IDX["n"], "load_ms": _IDX.get("load_ms")})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/search"):
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n).decode("utf-8"))
            res = _search_local(req.get("qvec", []), int(req.get("k", 10)))
            self._send(200, {"results": res, "n": _IDX["n"]})
        except Exception as e:  # noqa
            self._send(500, {"error": str(e)})


def serve(port: int = DEFAULT_PORT) -> int:
    load_index()
    _watch_loop()  # auto-refresh si la DB change (reindex live)
    print(f"[faiss-sidecar] index chargé n={_IDX['n']} backend={_IDX.get('backend')} "
          f"({_IDX.get('load_ms')}ms) — serve :{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), _H).serve_forever()
    return 0


# ───────────────────────────── CLIENT (hub) ────────────────────────────────
def search_remote(qvec, k: int = 10, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                  timeout: float = 1.5) -> list:
    """CÔTÉ HUB : interroge le sidecar -> [(chunk_id, sim)]. Lève si down (caller fallback numpy)."""
    import urllib.request
    body = json.dumps({"qvec": list(qvec), "k": int(k)}).encode("utf-8")
    req = urllib.request.Request(f"http://{host}:{port}/search", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode("utf-8", "replace"))
    return [(cid, sim) for cid, sim in out.get("results", [])]


def sidecar_alive(host: str = "127.0.0.1", port: int = DEFAULT_PORT, timeout: float = 0.5) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace")).get("ok", False)
    except Exception:
        return False


# ───────────────────────────── CLI ─────────────────────────────────────────
def selftest() -> int:
    """Charge l'index + query avec le vecteur du 1er chunk -> doit self-matcher en top-1."""
    import numpy as np
    load_index()
    if not _IDX["ids"]:
        print(json.dumps({"selftest_ok": False, "reason": "0 chunk embeddé"}))
        return 1
    q = _IDX["mat"][0]
    res = _search_local(q, 5)
    ok = bool(res) and res[0][0] == _IDX["ids"][0] and res[0][1] > 0.99
    print(json.dumps({"selftest_ok": ok, "n": _IDX["n"], "backend": _IDX.get("backend"),
                      "load_ms": _IDX.get("load_ms"), "top1": res[0] if res else None,
                      "top5_ids": [r[0] for r in res]}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def stats() -> int:
    conn = sqlite3.connect(str(DB), timeout=10)
    n = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NOT NULL").fetchone()[0]
    conn.close()
    print(json.dumps({"embedded_chunks": n, "dim": DIM, "db": str(DB)}))
    return 0


def main(argv: list) -> int:
    if "--selftest" in argv:
        return selftest()
    if "--stats" in argv:
        return stats()
    if "--serve" in argv:
        port = DEFAULT_PORT
        if "--port" in argv:
            try:
                port = int(argv[argv.index("--port") + 1])
            except Exception:
                pass
        return serve(port)
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
