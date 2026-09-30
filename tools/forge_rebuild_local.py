"""
forge_rebuild_local.py — Rebuild embeddings RAG 100% LOCAL.
============================================================
bge-m3 Q8 GGUF sur iGPU Radeon 780M via llama.cpp Vulkan (~7.7 chunks/s).
Souverain (zero donnee au cloud), zero quota, resumable.

Lance llama-server --embedding --pooling cls en sous-processus, draine
rag_chunks, ecrit les vecteurs (bge-m3 canonique, cosine 0.9997 verifie).
Reprend le checkpoint partage avec forge_rebuild_embeddings (continuite
cloud -> local : ne re-embedde pas ce qui est deja fait).

Run :
  # Sequential (legacy)
  __import__("os").path.expanduser("~/miniforge3/python.exe") tools/forge_rebuild_local.py
  # Parallel 3.14t nogil (WORKERS=4, llama-server --parallel 4)
  __import__("os").path.expanduser("~/miniforge3/envs/laforge_py314t/python.exe") tools/forge_rebuild_local.py 4
Relancer reprend au checkpoint.
"""

import json
import os
import sqlite3
import struct as _struct
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

try:
    import psutil
except ImportError:
    psutil = None

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
CKPT = ROOT / "sandbox" / "rebuild_embeddings.ckpt"
PAUSE_FLAG = ROOT / "sandbox" / "embed_rebuild_pause"
SERVER = __import__("os").path.expanduser(r"~\llama-vulkan\llama-server.exe")
GGUF = str(ROOT / "data" / "llm_models" / "bge-m3-Q8_0.gguf")
PORT = 8099
BATCH = 64
MAXCHARS = 2000  # ~512 tokens — coherent avec max_length de forge_npu
# Workers > 1 : 3.14t free-threaded + llama-server --parallel N
# Usage : python forge_rebuild_local.py [workers]   (default=1)
WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 1

# Resource gating — incident 2026-05-25 : rebuild a brule 5GB RAM + 7 cores
# sans gate, saturation systeme 90% RAM. Apres sleep PC, process suspended
# reprend au wake sans verifier l'etat des ressources. Patch : check avant
# chaque batch, sleep+retry si sature. Surchargeable via env vars pour CI.
MAX_RAM_PCT = float(os.environ.get("LAFORGE_EMBEDREBUILD_MAX_RAM_PCT", "70"))
MAX_CPU_PCT = float(os.environ.get("LAFORGE_EMBEDREBUILD_MAX_CPU_PCT", "60"))
GATE_SLEEP_S = float(os.environ.get("LAFORGE_EMBEDREBUILD_GATE_SLEEP_S", "30"))


def _resource_gate_wait() -> None:
    """Bloque tant que RAM > MAX_RAM_PCT, CPU > MAX_CPU_PCT, ou flag pause.
    No-op si psutil absent (fail-open)."""
    if psutil is None:
        return
    iters = 0
    while True:
        if PAUSE_FLAG.exists():
            if iters % 10 == 0:
                print(f"[gate] PAUSE_FLAG present ({PAUSE_FLAG.name}) — wait", flush=True)
            time.sleep(GATE_SLEEP_S)
            iters += 1
            continue
        ram = psutil.virtual_memory().percent
        cpu = psutil.cpu_percent(interval=1.0)
        if ram < MAX_RAM_PCT and cpu < MAX_CPU_PCT:
            return
        print(
            f"[gate] saturated ram={ram:.1f}% (max {MAX_RAM_PCT}%) "
            f"cpu={cpu:.1f}% (max {MAX_CPU_PCT}%) — sleep {GATE_SLEEP_S}s",
            flush=True,
        )
        time.sleep(GATE_SLEEP_S)
        iters += 1
        if iters > 240:  # 2h de gating consecutif = trop, exit clean
            print("[gate] saturated > 2h — abort rebuild for safety", flush=True)
            sys.exit(0)


# Tiering RAG — politique partagee (forge_tier_policy). Seul le contenu
# genuinement Nokido est vectorise ; l'externe (gitingest libs, PDF, vendor,
# bruit) reste FTS-only. Filtre par source+domain car le `domain` seul ment.
from nokido_agent.tools.forge_tier_policy import HOT_TIER_SQL  # noqa: E402


def _server_up() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def embed_parallel(rows: list) -> list:
    """Découpe rows en WORKERS tranches, embed concurrentes, ordre préservé."""
    size = max(1, (len(rows) + WORKERS - 1) // WORKERS)
    chunks = [rows[i : i + size] for i in range(0, len(rows), size)]

    def _embed_chunk(idx: int, chunk_rows: list):
        texts = [(r[2] or " ")[:MAXCHARS] for r in chunk_rows]
        return idx, embed(texts)

    with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
        futs = [ex.submit(_embed_chunk, i, c) for i, c in enumerate(chunks)]
        res_map = dict(f.result() for f in as_completed(futs))

    vecs = []
    for i in range(len(chunks)):
        vecs.extend(res_map[i])
    return vecs


def embed(texts: list) -> list:
    body = json.dumps({"input": texts}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/embeddings",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        d = json.loads(r.read())
    items = sorted(d["data"], key=lambda x: x.get("index", 0))
    vecs = [it["embedding"] for it in items]
    if not vecs or len(vecs) != len(texts) or len(vecs[0]) != 1024:
        raise RuntimeError(f"shape inattendue: {len(vecs)} vecs")
    return vecs


def _fetch_rows(start_rowid: int) -> list:
    conn = sqlite3.connect(str(DB), timeout=30)
    conn.execute("PRAGMA busy_timeout=15000")
    rows = conn.execute(
        f"SELECT rowid, id, text FROM rag_chunks "
        f"WHERE rowid>? AND embedding IS NULL AND {HOT_TIER_SQL} ORDER BY rowid LIMIT ?",
        (start_rowid, BATCH * WORKERS),
    ).fetchall()
    conn.close()
    return rows


def main() -> None:
    proc = None
    if _server_up():
        print("[local] llama-server deja up — reuse", flush=True)
    else:
        print("[local] demarrage llama-server Vulkan (iGPU 780M)...", flush=True)
        ctx_size = 2048 * max(1, WORKERS)
        server_cmd = [
            SERVER,
            "-m",
            GGUF,
            "--embedding",
            "--pooling",
            "cls",
            "-ngl",
            "99",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
            "-c",
            str(ctx_size),
            "-b",
            "2048",
            "--ubatch-size",
            "2048",
        ]
        if WORKERS > 1:
            server_cmd += ["--parallel", str(WORKERS)]
            print(f"[local] mode parallele WORKERS={WORKERS} ctx={ctx_size}", flush=True)
        proc = subprocess.Popen(server_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(90):
            time.sleep(2)
            if _server_up():
                break
        if not _server_up():
            print("[local] llama-server PAS UP apres 180s", flush=True)
            if proc:
                proc.kill()
            sys.exit(1)
        print("[local] server UP", flush=True)

    try:
        # NULL-fill : _fetch_rows filtre embedding IS NULL -> balayage depuis 0,
        # les chunks deja vectorises sont ignores (plus de checkpoint requis).
        start = 0
        conn = sqlite3.connect(str(DB), timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        total = conn.execute(f"SELECT COUNT(*) FROM rag_chunks WHERE {HOT_TIER_SQL}").fetchone()[0]
        done = conn.execute(
            f"SELECT COUNT(*) FROM rag_chunks WHERE rowid<=? AND {HOT_TIER_SQL}", (start,)
        ).fetchone()[0]
        conn.close()
        print(f"[local] reprise rowid>{start} | {done}/{total} deja faits", flush=True)

        wconn = sqlite3.connect(str(DB), timeout=30)
        wconn.execute("PRAGMA journal_mode=WAL")
        wconn.execute("PRAGMA busy_timeout=15000")
        wconn.execute("PRAGMA synchronous=NORMAL")
        t0 = time.time()
        session = 0
        # Prefetch: fetch batch N+1 pendant que GPU embed batch N
        with ThreadPoolExecutor(max_workers=1) as fetcher:
            prefetch = fetcher.submit(_fetch_rows, start)
            while True:
                rows = prefetch.result()
                if not rows:
                    break
                # Lancer fetch suivant avant embed (overlap I/O + GPU)
                prefetch = fetcher.submit(_fetch_rows, rows[-1][0])

                # Gate ressources : sleep si RAM/CPU saturés ou pause manuelle
                _resource_gate_wait()

                try:
                    vecs = (
                        embed_parallel(rows)
                        if WORKERS > 1
                        else embed([(r[2] or " ")[:MAXCHARS] for r in rows])
                    )
                except Exception as e:
                    print(
                        f"[local] embed err: {type(e).__name__}: {str(e)[:100]} "
                        f"— restart :{PORT} + attente",
                        flush=True,
                    )
                    # Auto-restart du serveur embed (il crashe sous charge soutenue).
                    try:
                        _rq = urllib.request.Request(
                            "http://127.0.0.1:8765/supervisor/restart/NokidoLlamaEmbed",
                            data=b"",
                            method="POST",
                        )
                        urllib.request.urlopen(_rq, timeout=15).read()
                    except Exception:
                        pass
                    for _ in range(50):
                        time.sleep(3)
                        if _server_up():
                            break
                    prefetch = fetcher.submit(_fetch_rows, start)  # retry même batch
                    continue

                try:
                    for (rid, cid, _), v in zip(rows, vecs):
                        # write par rowid : robuste meme si id IS NULL
                        wconn.execute(
                            "UPDATE rag_chunks SET embedding=? WHERE rowid=?",
                            (_struct.pack("1024f", *v), rid),
                        )
                    wconn.commit()
                except Exception as e:
                    print(f"[local] write err: {type(e).__name__}: {str(e)[:100]}", flush=True)
                    wconn.rollback()

                start = rows[-1][0]
                session += len(rows)
                CKPT.write_text(str(start))
                el = time.time() - t0
                rate = session / el if el else 0
                print(
                    f"[local] +{len(rows)} | {done + session}/{total} "
                    f"({100 * (done + session) / max(total, 1):.1f}%) | {rate:.1f}/s",
                    flush=True,
                )
        wconn.close()

        print(f"[local] TERMINE — {session} embeddes cette session", flush=True)
        if done + session >= total:
            CKPT.unlink(missing_ok=True)
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    main()
