"""
forge_rebuild_embeddings.py — Rebuild complet des embeddings RAG (parallele).
==============================================================================
A lancer APRES le fix pooling de forge_npu.py (mean -> CLS). Re-embed les
~418k chunks rag_chunks en bge-m3 CANONIQUE (CLS pooling).

PARALLELE : un thread par provider, tous en meme temps (le debit = somme des
providers, pas le plus lent). Batching par BUDGET DE TOKENS (evite le 400
"max context" de Cloudflare). Reprise via checkpoint = plus vieux pool en vol
(redo idempotent au pire).

Providers : HF / Nvidia / Cloudflare (gratuits) -> DeepInfra (payant) ->
brain_worker local. Chacun auto-desactive si sa cle manque dans Nokido.env.

Run :
  PYTHONNOUSERSITE=1 PYTHONIOENCODING=utf-8 \\
    __import__("os").path.expanduser("~/miniforge3/python.exe") tools/forge_rebuild_embeddings.py
"""

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
from nokido_agent.tools.forge_tier_policy import HOT_TIER_SQL  # filtre tier (ne vectorise que le hot)

try:
    import psutil
except ImportError:
    psutil = None

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
CKPT = ROOT / "sandbox" / "rebuild_embeddings.ckpt"
PAUSE_FLAG = ROOT / "sandbox" / "embed_rebuild_pause"

# Resource gate — partage la meme config que forge_rebuild_local.
MAX_RAM_PCT = float(os.environ.get("LAFORGE_EMBEDREBUILD_MAX_RAM_PCT", "70"))
MAX_CPU_PCT = float(os.environ.get("LAFORGE_EMBEDREBUILD_MAX_CPU_PCT", "60"))
GATE_SLEEP_S = float(os.environ.get("LAFORGE_EMBEDREBUILD_GATE_SLEEP_S", "30"))


def _resource_gate_wait() -> None:
    """Bloque tant que RAM > MAX_RAM_PCT, CPU > MAX_CPU_PCT, ou flag pause.

    Aligne sur `forge_rebuild_local` (2026-08-02). Avant : les deux plafonds de
    240 iterations faisaient un `return` MUET — le rebuild repartait donc en pleine
    saturation, et une PAUSE demandee par l'owner etait contournee au bout de 2 h
    sans que rien ne le dise. Un garde qui renonce doit ABANDONNER le travail, pas
    le laisser passer ; et il doit le dire, sinon son silence se lit comme un feu vert.
    """
    if psutil is None:
        print("[gate] psutil absent : AUCUN gating de ressources sur ce rebuild", flush=True)
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
        if iters > 240:  # 2h de gating consecutif = trop, on ABANDONNE au lieu de forcer
            print("[gate] saturated > 2h — abort rebuild for safety", flush=True)
            sys.exit(0)


POOL_SIZE = 128  # lignes par pool (granularite checkpoint)
TOKEN_BUDGET = 5000  # budget tokens estimes / requete (CF-safe)
MAX_PER_REQ = 48  # plafond chunks / requete
MODEL = "BAAI/bge-m3"


def _env(key: str, default: str = "") -> str:
    try:
        for ln in (ROOT / "Nokido.env").read_text("utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if ln.startswith(key + "="):
                return ln.split("=", 1)[1].split("#")[0].strip().strip('"').strip("'")
    except Exception:
        pass
    return default


HF_TOKEN = _env("HF_TOKEN")
DEEPINFRA = _env("DEEPINFRA")
NVIDIA = _env("NVIDIA_NIM_API_KEY") or _env("NVIDIA_API_KEY")
CF_ACCOUNT = _env("CLOUDFLARE_ACCOUNT_ID")
CF_KEY = _env("CLOUDFLARE_AI_API_KEY")


def _post(url: str, headers: dict, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as exc:  # noqa: BLE001
        # HTTPError PORTE le corps de la reponse : c'est la seule source qui
        # explique un 400 (payload refuse, entree vide, limite de taille...).
        # Sans cette relecture l'erreur est muette et le diagnostic devient de
        # la speculation -- mesure 2026-07-31, trois jours perdus sur ce 400.
        code = getattr(exc, "code", None)
        body = ""
        reader = getattr(exc, "read", None)
        if callable(reader):
            try:
                body = reader()[:500].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                body = "<corps illisible>"
        if code is None and not body:
            raise  # timeout / URLError : rien a enrichir, on ne masque pas
        raise RuntimeError(f"HTTP {code} sur {url} :: {body}") from exc


def hf_embed(texts: list) -> list:
    d = _post(
        "https://router.huggingface.co/hf-inference/models/BAAI/bge-m3/pipeline/feature-extraction",
        {"Authorization": f"Bearer {HF_TOKEN}"},
        {"inputs": texts, "options": {"wait_for_model": True}},
    )
    if not (
        isinstance(d, list)
        and len(d) == len(texts)
        and isinstance(d[0], list)
        and len(d[0]) == 1024
    ):
        raise RuntimeError(f"HF shape inattendue ({type(d)})")
    return d


def _openai_embed(url: str, key: str, texts: list, extra: dict = None) -> list:
    payload = {"model": MODEL, "input": texts}
    if extra:
        payload.update(extra)
    d = _post(url, {"Authorization": f"Bearer {key}"}, payload)
    items = sorted(d["data"], key=lambda x: x.get("index", 0))
    vecs = [it["embedding"] for it in items]
    if len(vecs) != len(texts) or len(vecs[0]) != 1024:
        raise RuntimeError("OpenAI-compat shape inattendue")
    return vecs


def deepinfra_embed(texts: list) -> list:
    return _openai_embed("https://api.deepinfra.com/v1/openai/embeddings", DEEPINFRA, texts)


def nvidia_embed(texts: list) -> list:
    return _openai_embed(
        "https://integrate.api.nvidia.com/v1/embeddings",
        NVIDIA,
        texts,
        {"model": "baai/bge-m3", "input_type": "passage", "encoding_format": "float"},
    )


def cloudflare_embed(texts: list) -> list:
    d = _post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/@cf/baai/bge-m3",
        {"Authorization": f"Bearer {CF_KEY}"},
        {"text": texts},
    )
    res = d.get("result", {})
    data = res.get("data") or res.get("response") or res.get("embeddings")
    if not data or len(data) != len(texts):
        raise RuntimeError("CF shape inattendue")
    return data


_local_lock = threading.Lock()


def local_embed(texts: list) -> list:
    import msgpack
    import zmq

    with _local_lock:  # brain_worker = 1 seul a la fois
        ctx = zmq.Context()
        s = ctx.socket(zmq.REQ)
        s.setsockopt(zmq.LINGER, 0)
        s.connect("tcp://localhost:5557")
        try:
            s.send(
                msgpack.packb({"cmd": "submit", "type": "embed", "texts": texts}, use_bin_type=True)
            )
            if not s.poll(20_000):
                raise TimeoutError("submit")
            tid = msgpack.unpackb(s.recv(), raw=False)["task_id"]
            for _ in range(240):
                s.send(msgpack.packb({"cmd": "check", "task_id": tid}, use_bin_type=True))
                if not s.poll(60_000):
                    raise TimeoutError("check")
                res = msgpack.unpackb(s.recv(), raw=False)
                st = res.get("status")
                if st == "completed":
                    dd = res.get("data")
                    v = dd.get("vecs", []) if isinstance(dd, dict) else dd
                    if len(v) != len(texts):
                        raise RuntimeError("local count mismatch")
                    return v
                if st == "error":
                    raise RuntimeError(res.get("error", "local error"))
                time.sleep(0.5)
            raise TimeoutError("local never completed")
        finally:
            s.close()
            ctx.term()


PROVIDERS = [
    {"name": "HF", "fn": hf_embed, "enabled": bool(HF_TOKEN)},
    {"name": "Nvidia", "fn": nvidia_embed, "enabled": bool(NVIDIA)},
    {"name": "Cloudflare", "fn": cloudflare_embed, "enabled": bool(CF_ACCOUNT and CF_KEY)},
    {"name": "DeepInfra", "fn": deepinfra_embed, "enabled": bool(DEEPINFRA)},
    {"name": "local", "fn": local_embed, "enabled": True},
]

# ── Etat partage ─────────────────────────────────────────────────────────────
_lock = threading.Lock()
_cursor = 0  # rowid distribue jusqu'a
_inflight: set = set()  # rowid de debut des pools en cours
_done = 0
_total = 0
_t0 = 0.0
_stop = False


def _next_pool():
    """Renvoie le prochain pool de lignes (thread-safe) ou None si fini."""
    global _cursor
    with _lock:
        conn = sqlite3.connect(str(DB), timeout=30)
        conn.execute("PRAGMA busy_timeout=15000")
        rows = conn.execute(
            f"SELECT rowid, id, text FROM rag_chunks WHERE rowid > ? AND {HOT_TIER_SQL} ORDER BY rowid LIMIT ?",
            (_cursor, POOL_SIZE),
        ).fetchall()
        conn.close()
        if not rows:
            return None
        _cursor = rows[-1][0]
        _inflight.add(rows[0][0])
        return rows


def _pool_done(pool_start: int) -> None:
    """Marque un pool fini, recalcule + ecrit le checkpoint."""
    with _lock:
        _inflight.discard(pool_start)
        ckpt = min(_inflight) - 1 if _inflight else _cursor
        try:
            CKPT.write_text(str(ckpt))
        except Exception:
            pass


def _subbatches(pool: list) -> list:
    """Decoupe un pool en sous-batches par budget de tokens."""
    out, i = [], 0
    while i < len(pool):
        sub, tok = [], 0
        while i < len(pool) and len(sub) < MAX_PER_REQ:
            txt = (pool[i][2] or " ")[:8000]
            est = len(txt) // 3 + 8
            if sub and tok + est > TOKEN_BUDGET:
                break
            sub.append((pool[i][0], pool[i][1], txt))
            tok += est
            i += 1
        out.append(sub)
    return out


def _write(sub: list, vecs: list) -> None:
    conn = sqlite3.connect(str(DB), timeout=30)
    conn.execute("PRAGMA busy_timeout=15000")
    try:
        for (rid, cid, _), vec in zip(sub, vecs):
            conn.execute("UPDATE rag_chunks SET embedding=? WHERE id=?", (json.dumps(vec), cid))
        conn.commit()
    finally:
        conn.close()


def worker(p: dict) -> None:
    """Thread d'un provider : prend des pools, embed, ecrit."""
    global _done
    name = p["name"]
    while not _stop:
        pool = _next_pool()
        if pool is None:
            return
        pstart = pool[0][0]
        for sub in _subbatches(pool):
            texts = [s[2] for s in sub]
            while not _stop:
                _resource_gate_wait()
                try:
                    vecs = p["fn"](texts)
                    _write(sub, vecs)
                    with _lock:
                        _done += len(sub)
                        dc = _done
                    el = time.time() - _t0
                    print(
                        f"[{name}] +{len(sub)} | {dc}/{_total} "
                        f"({100 * dc / max(_total, 1):.1f}%) | {dc / el if el else 0:.1f}/s global",
                        flush=True,
                    )
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (401, 402, 403):
                        body = ""
                        try:
                            body = e.read()[:80].decode("utf-8", "replace")
                        except Exception:
                            pass
                        print(
                            f"[{name}] HTTP {e.code} ({body}) — provider HS, thread arrete",
                            flush=True,
                        )
                        _pool_done(pstart)
                        return
                    print(f"[{name}] HTTP {e.code} — rate-limit, pause 90s", flush=True)
                    time.sleep(90)
                except Exception as e:
                    print(f"[{name}] {type(e).__name__}: {str(e)[:80]} — pause 30s", flush=True)
                    time.sleep(30)
        _pool_done(pstart)


def main() -> None:
    global _cursor, _total, _done, _t0
    if CKPT.exists():
        try:
            _cursor = int(CKPT.read_text().strip())
        except Exception:
            _cursor = 0
    conn = sqlite3.connect(str(DB), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
    _total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
    _done = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE rowid <= ?", (_cursor,)).fetchone()[
        0
    ]
    conn.close()

    actifs = [p for p in PROVIDERS if p["enabled"]]
    print(
        f"[rebuild] {len(actifs)} providers paralleles: {[p['name'] for p in actifs]}", flush=True
    )
    print(f"[rebuild] reprise rowid > {_cursor} | {_done}/{_total} deja faits", flush=True)

    _t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(actifs)) as ex:
        list(ex.map(worker, actifs))

    print(f"[rebuild] TERMINE — {_done}/{_total}", flush=True)
    if _done >= _total:
        CKPT.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
