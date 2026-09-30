"""Backfill ULTRA-CONSERVATIVE : CPU-only brain_worker + IDLE priority +
sleep generous + resource_manager gate. Non-bloquant UI.

Lance brain_worker dans subprocess CPU mode (env LAFORGE_EMBED_DEVICE=cpu).
Throttle si CPU >70% ou RAM >75%. Sleep 2s entre batches. Process priority IDLE.
"""

import argparse
import json
import logging
import os
import shutil
import sqlite3
import struct
import sys
import time
from pathlib import Path

try:
    import msgpack  # plus utilisé depuis le repoint :8099 — optionnel (sandbox run_job sans zmq)
except Exception:  # pragma: no cover
    msgpack = None
try:
    import zmq  # idem : ex-transport brain_worker :5557, mort
except Exception:  # pragma: no cover
    zmq = None

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

# Garde-disque (2026-07-06, incident V: sature a 0) : le drain STOP net si le
# volume de la db passe sous ce seuil -- plus jamais d'ecriture embed a l'aveugle.
MIN_FREE_GB = 5.0
_DB_DRIVE = (os.path.splitdrive(str(DB))[0] or "C:") + os.sep
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("cool_backfill")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ZMQ = "tcp://127.0.0.1:5557"


def set_idle_priority():
    """Set current Python process to IDLE priority (lowest CPU scheduling)."""
    try:
        import ctypes

        IDLE_PRIORITY_CLASS = 0x40
        h = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(h, IDLE_PRIORITY_CLASS)
        logger.info("[priority] python set to IDLE")
    except Exception as e:
        logger.warning(f"[priority] failed: {e}")


def should_throttle(cpu_max=70.0, ram_max=75.0):
    """Return True si systeme trop charge -> attendre."""
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.2)
        ram = psutil.virtual_memory().percent
        return cpu > cpu_max or ram > ram_max, cpu, ram
    except Exception:
        return False, 0.0, 0.0


def brain_batch(texts, timeout_s=180.0):
    """Repointe 2026-07-05 (fix autoregulation vectorisation) : :5557 brain_worker
    (DISABLED OOM 2026-06-03, 62 echecs consecutifs -> daemon mort 9j) -> :8099
    NokidoLlamaEmbed (BGE-M3 GGUF GPU, souverain, SANS egress) via
    forge_embed_router._llama8099_call. Volontairement PAS embed_batch_fast : sa
    cascade Modal/Voyage/Jina = egress cloud, interdit sur un backfill 656k chunks.
    Contrat inchange : retourne [vec...] aligne sur texts (1024D), ou None."""
    try:
        import sys as _sys
        from pathlib import Path as _P

        _app = _P(__file__).resolve().parent.parent / "app"
        if str(_app) not in _sys.path:
            _sys.path.insert(0, str(_app))
        from nokido_agent.app.forge_embed_router import _llama8099_call

    except Exception:
        return None
    # 1) essai batch (rapide, 1 RTT pour N textes)
    try:
        vecs = _llama8099_call(texts, timeout=timeout_s)
        if vecs and len(vecs) == len(texts):
            return vecs
    except Exception:
        pass
    # 2) ROBUSTESSE : le batch a échoué -> 1 chunk pathologique (trop gros / encodage)
    # empoisonne les 32. Fallback chunk-par-chunk -> liste alignée [vec|None] : les bons
    # passent, les mauvais = None (marqués SKIP_8099 côté backfill pour ne pas re-spin).
    out = []
    for _t in texts:
        try:
            _v = _llama8099_call([_t], timeout=timeout_s)
            out.append(_v[0] if _v and len(_v) == 1 else None)
        except Exception:
            out.append(None)
    return out


def encode_blob(vec):
    return struct.pack(f"{len(vec)}f", *vec)


_QDRANT_UPSERT_URL = os.environ.get("LAFORGE_QDRANT_UPSERT_URL", "http://127.0.0.1:8098/upsert")
_qdrant_dead = False


def qdrant_upsert_best_effort(items):
    """Fraicheur post-cutover (chantier Qdrant 2026-07-06/07) : pousse les
    embeddings fraichement ecrits vers le sidecar :8098 (best-effort, JAMAIS
    bloquant — le re-fill periodique rattrape si le sidecar est down).
    items = [{"id", "dense", "text"}]. Kill-switch LAFORGE_QDRANT_UPSERT=0."""
    global _qdrant_dead
    if _qdrant_dead or not items or os.environ.get("LAFORGE_QDRANT_UPSERT", "1") == "0":
        return 0
    import json as _j
    import urllib.request as _u

    try:
        body = _j.dumps({"chunks": items}).encode()
        req = _u.Request(
            _QDRANT_UPSERT_URL, data=body,
            headers={"Content-Type": "application/json"}, method="POST")
        with _u.urlopen(req, timeout=10) as r:
            return _j.loads(r.read()).get("upserted", 0)
    except Exception as e:
        _qdrant_dead = True  # un seul warn par run, le drain continue
        logger.warning(f"[qdrant] upsert off pour ce run: {e}")
        return 0


def backfill(limit, batch_size, sleep_between, cpu_max, ram_max, exclude_domains=None):
    set_idle_priority()
    conn = sqlite3.connect(str(DB), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")

    # 2026-07-05 : exclude_domains = domaines couverts par un pipeline EXTERNE
    # (embed Kaggle des domaines publics) -> le drain local se concentre sur le
    # reste au lieu de dupliquer le travail. None = comportement inchange.
    _excl_sql = ""
    _excl_args = ()
    if exclude_domains:
        _excl_args = tuple(exclude_domains)
        _excl_sql = " AND (domain IS NULL OR domain NOT IN (%s))" % ",".join("?" * len(_excl_args))

    # LECTEUR PRINCIPAL DE L'HOMEOSTASIE (2026-09-23). Ce compte ET les lots passaient par
    # `idx_emb_null_origin` (partiel, SANS `embedding_model`) : chaque chunk sans embedding
    # etait LU pour tester la colonne — 9,8 Go en 3 min pendant l'ingestion 6f. Le compte ne
    # sert qu'au journal et a l'ETA : on le prend sur l'index partiel SEUL et on le DECLARE
    # borne haute (il inclut les SKIP_*). NR : tests/nr/test_backfill_sans_relecture_nr.py
    total = conn.execute(
        "SELECT COUNT(*) FROM rag_chunks INDEXED BY idx_embedding_null WHERE embedding IS NULL"
    ).fetchone()[0]
    logger.info(
        f"NULL chunks (BORNE HAUTE, SKIP_* inclus): {total} | batch={batch_size} sleep={sleep_between}s "
        f"throttle cpu>{cpu_max}% ram>{ram_max}%"
    )
    # CURSEUR `id > dernier` : un chunk n'est lu qu'UNE fois. Sans lui, les SKIP_TIER (embedding
    # toujours NULL) etaient relus a chaque lot, et un lot que l'embedder ne vectorise pas etait
    # RE-SELECTIONNE en boucle jusqu'a `limit`. Garde d'un appel a l'autre dans le processus.
    curseur = getattr(backfill, "_curseur", "")
    reparti = False

    processed = 0
    success = 0
    skipped = 0
    t_start = time.time()
    throttle_waits = 0

    while processed < limit:
        # GARDE-DISQUE (2026-07-06, incident V: plein) : STOP net si le volume
        # de la db passe sous le seuil -- jamais d'ecriture embed a l'aveugle.
        _free_gb = shutil.disk_usage(_DB_DRIVE).free / 1e9
        if _free_gb < MIN_FREE_GB:
            logger.error(
                f"[disk-guard] {_DB_DRIVE} libre {_free_gb:.2f}GB < seuil {MIN_FREE_GB}GB "
                f"-> STOP drain (processed={processed} success={success} skipped={skipped})")
            conn.close()
            return {
                "processed": processed, "success": success, "skipped": skipped,
                "elapsed_min": round((time.time() - t_start) / 60, 1),
                "stopped": "disk_guard", "free_gb": round(_free_gb, 2),
            }
        # 2026-07-05 : ORDER BY ingested_at DESC RETIRÉ — il forçait un tri du sous-ensemble
        # NULL (645k) à CHAQUE boucle = batch 1.5s -> 4s+, et menaçait le drain pluripotent
        # borné sous timeout tick 90s. L'ordre d'embedding est indifférent (tout le backlog
        # est traité) -> scan-order = rapide.
        rows = conn.execute(
            "SELECT id, text FROM rag_chunks INDEXED BY idx_embedding_null WHERE embedding IS NULL "
            "AND id > ? AND embedding_model IS NULL AND text IS NOT NULL AND length(text) > 50"
            + _excl_sql + " ORDER BY id LIMIT ?",
            (curseur, *_excl_args, batch_size),
        ).fetchall()
        if not rows:
            if curseur and not reparti:
                # fin de l'index atteinte : UN seul tour depuis le debut (lignes inserees derriere)
                curseur, reparti = "", True
                continue
            backfill._curseur = ""
            logger.info("done")
            break
        curseur = rows[-1][0]
        backfill._curseur = curseur

        # Throttle gate
        while True:
            throttle, cpu, ram = should_throttle(cpu_max, ram_max)
            if not throttle:
                break
            throttle_waits += 1
            logger.info(f"[throttle] cpu={cpu:.0f}% ram={ram:.0f}% wait 5s")
            time.sleep(5)

        # PROBE-FIRST (v4 2026-07-06) : teste forge_tier_guard AVANT d'embedder.
        # Sentinelle x'00' (si rowcount=1 -> autorise, REVERT immediat MEME
        # transaction ; rowcount=0 -> tier refuse -> SKIP_TIER sans payer l'embed).
        # Zones refusees : ~2000/min au lieu de ~150/min (l'embed etait gaspille).
        allowed = []
        for _cid, _txt in rows:
            _p = conn.execute(
                "UPDATE rag_chunks SET embedding=x'00' WHERE id=? AND embedding IS NULL", (_cid,))
            if _p.rowcount == 1:
                conn.execute("UPDATE rag_chunks SET embedding=NULL WHERE id=?", (_cid,))
                allowed.append((_cid, _txt))
            else:
                conn.execute(
                    "UPDATE rag_chunks SET embedding_model='SKIP_TIER' WHERE id=?", (_cid,))
                skipped += 1
        conn.commit()  # sentinelles toutes REVERTEES dans cette transaction
        if not allowed:
            processed += len(rows)
            logger.info(f"batch {len(rows)} SKIP_TIER integral | processed={processed} skipped={skipped}")
            time.sleep(sleep_between)
            continue
        ids = [r[0] for r in allowed]
        texts = [r[1] for r in allowed]
        first_written = None  # 1er cid avec rowcount==1 (vrai write) pour le read-back
        t0 = time.time()
        vecs = brain_batch(texts, timeout_s=180.0)
        dt = time.time() - t0

        if vecs and len(vecs) == len(ids):
            fresh_points = []  # (chantier Qdrant) points ecrits ce batch -> upsert :8098
            for cid, vec, _txt in zip(ids, vecs, texts):
                if vec and len(vec) >= 256:
                    cur = conn.execute(
                        "UPDATE rag_chunks SET embedding=?, embedding_model='bge-m3' WHERE id=?",
                        (encode_blob(vec), cid),
                    )
                    # RCA 2026-07-06 : rowcount=0 = REFUS du trigger forge_tier_guard
                    # (politique hot/cold : seuls nokido/laforge-code/laforge-memory/
                    # web-crawl sont vectorisables ; le reste = RAISE(IGNORE) silencieux).
                    # On marque SKIP_TIER (colonne non gardee) -> sort du working set
                    # et du calcul TSH, reversible (embedding_model=NULL). Le trigger
                    # reste l'UNIQUE source de verite de la taxonomie (zero duplication).
                    if cur.rowcount != 1:
                        conn.execute(
                            "UPDATE rag_chunks SET embedding_model='SKIP_TIER' WHERE id=?", (cid,))
                        skipped += 1
                    else:
                        success += 1
                        fresh_points.append({"id": cid, "dense": vec, "text": _txt})
                        if first_written is None:
                            first_written = cid
                else:
                    # chunk non-embeddable -> marque SKIP_8099 (embedding reste NULL mais
                    # sort du working-set via 'embedding_model IS NULL') = anti-spin + auditable
                    conn.execute(
                        "UPDATE rag_chunks SET embedding_model='SKIP_8099' WHERE id=?", (cid,)
                    )
                    skipped += 1
            conn.commit()
            if fresh_points:
                qdrant_upsert_best_effort(fresh_points)
        else:
            logger.warning(f"batch {len(rows)} returned {len(vecs) if vecs else 0} vecs")

        # FAIL-LOUD read-back (1er batch avec succes REEL) : la 1re row ecrite doit
        # etre relue NON-NULL par une CONNEXION NEUVE (detecte write invisible).
        if first_written and not getattr(backfill, "_rb_done", False):
            _wid = first_written
            if _wid:
                _chk = sqlite3.connect(str(DB), timeout=30)
                _ok = _chk.execute(
                    "SELECT embedding IS NOT NULL FROM rag_chunks WHERE id=?", (_wid,)
                ).fetchone()
                _chk.close()
                if not _ok or not _ok[0]:
                    logger.error(f"READ-BACK FAIL: id={_wid!r} toujours NULL -> ABORT")
                    conn.close()
                    return {"error": "readback_fail", "id": str(_wid)}
                backfill._rb_done = True
                logger.info(f"read-back OK (id={_wid!r} persiste)")

        processed += len(rows)
        elapsed = time.time() - t_start
        rate = processed / elapsed if elapsed > 0 else 0
        eta = (total - processed) / rate if rate > 0 else 0
        logger.info(
            f"batch {len(rows)} in {dt:.1f}s | TOTAL processed={processed} "
            f"success={success} rate={rate * 60:.0f}/min ETA={eta / 60:.0f}min "
            f"throttle_waits={throttle_waits}"
        )

        # Sleep generous entre batches (CPU breathing)
        time.sleep(sleep_between)

    conn.close()
    return {
        "processed": processed,
        "success": success,
        "elapsed_min": round((time.time() - t_start) / 60, 1),
        "throttle_waits": throttle_waits,
        "null_borne_haute": total,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5000)
    ap.add_argument(
        "--batch-size", type=int, default=4, help="Small batch = less spike. Default 4."
    )
    ap.add_argument(
        "--sleep", type=float, default=2.0, help="Sleep secs between batches. Default 2s."
    )
    ap.add_argument("--cpu-max", type=float, default=70.0)
    ap.add_argument("--ram-max", type=float, default=75.0)
    args = ap.parse_args()
    print(
        json.dumps(
            backfill(args.limit, args.batch_size, args.sleep, args.cpu_max, args.ram_max), indent=2
        )
    )


if __name__ == "__main__":
    main()
