"""
forge_knowledge_pack.py — distribute the RAG DB efficiently (not the raw 16 GB).

The vector DB (RAG/embeddings.db) is ~16 GB float32 — too big for git/GitHub.
This ships a small, quantized **Knowledge Pack** (int8) of a chosen domain as a
single sqlite file = a GitHub Release asset, and rebuilds the full DB locally from
source. Sovereign: embeddings stay local; GitHub distributes source + a tiny pack.

Modes:
  --export <out.db> [--domain nokido_code] [--limit N]
      Dump rag_chunks of a domain, embeddings quantized float32 -> int8 (per-vector
      scale). ~4x smaller than int32, ~16x vs float32 + the text.
  --import <pack.db>
      Load a pack into RAG/embeddings.db (dequantize int8 -> float32 blob).
  --rebuild
      Re-embed code+docs from SOURCE into embeddings.db (wraps forge_rag_warmup) —
      the zero-egress rebuild path (local NPU/embedder).

Pack format (sqlite): kp_chunks(id,text,domain,scale,vec int8 BLOB) + kp_meta(k,v).
Version tag in kp_meta: 'version' = 0.1.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT / "RAG" / "embeddings.db"
PACK_VERSION = "0.1"


def _decode_embedding(blob):
    if not blob:
        return None
    if isinstance(blob, (bytes, bytearray)):
        if blob[:1] == b"[":
            try:
                return json.loads(blob.decode("utf-8"))
            except Exception:
                return None
        n = len(blob) // 4
        return list(struct.unpack(f"{n}f", blob[: n * 4])) if n else None
    try:
        return json.loads(blob)
    except Exception:
        return None


def export_pack(out_db, src_db=None, domain=None, limit=None):
    import sqlite3
    src = sqlite3.connect(str(src_db or DEFAULT_SRC))
    src.row_factory = sqlite3.Row
    out = sqlite3.connect(str(out_db))
    out.executescript(
        "CREATE TABLE IF NOT EXISTS kp_chunks (id TEXT PRIMARY KEY, text TEXT, "
        "domain TEXT, scale REAL, vec BLOB);"
        "CREATE TABLE IF NOT EXISTS kp_meta (k TEXT PRIMARY KEY, v TEXT);")
    n, dim = 0, None
    if domain:
        q = "SELECT id, text, embedding, domain FROM rag_chunks WHERE domain=? AND embedding IS NOT NULL"
        params = (domain,)
    else:
        q = "SELECT id, text, embedding, domain FROM rag_chunks WHERE embedding IS NOT NULL"
        params = ()
    if limit:
        q += f" LIMIT {int(limit)}"
    for r in src.execute(q, params):
        vec = _decode_embedding(r["embedding"])
        if not vec:
            continue
        import math as _m
        if dim is None:
            dim = len(vec)
        if len(vec) != dim:
            continue
        fv = [float(x) if _m.isfinite(float(x)) else 0.0 for x in vec]
        scale = max((abs(x) for x in fv), default=1.0) or 1.0
        if not _m.isfinite(scale) or scale == 0.0:
            scale = 1.0
        ints = [max(-127, min(127, int(round(x / scale * 127)))) for x in fv]
        out.execute("INSERT OR REPLACE INTO kp_chunks VALUES (?,?,?,?,?)",
                    (r["id"], r["text"], r["domain"], scale,
                     struct.pack(f"{len(ints)}b", *ints)))
        n += 1
    out.executemany("INSERT OR REPLACE INTO kp_meta VALUES (?,?)",
                    [("dim", str(dim)), ("count", str(n)), ("domain", domain or "all"),
                     ("version", PACK_VERSION)])
    out.commit()
    out.close()
    src.close()
    size = Path(out_db).stat().st_size if Path(out_db).exists() else 0
    return {"ok": True, "exported": n, "dim": dim, "domain": domain,
            "pack_bytes": size, "out": str(out_db)}


def import_pack(pack_db, dst_db=None):
    import sqlite3
    pk = sqlite3.connect(str(pack_db))
    pk.row_factory = sqlite3.Row
    meta = {r["k"]: r["v"] for r in pk.execute("SELECT k,v FROM kp_meta")}
    dst = sqlite3.connect(str(dst_db or DEFAULT_SRC))
    n = 0
    for r in pk.execute("SELECT id,text,domain,scale,vec FROM kp_chunks"):
        ints = struct.unpack(f"{len(r['vec'])}b", r["vec"])
        floats = [i * float(r["scale"]) / 127.0 for i in ints]
        blob = struct.pack(f"{len(floats)}f", *floats)
        try:
            dst.execute("INSERT OR REPLACE INTO rag_chunks (id, text, domain, embedding) "
                        "VALUES (?,?,?,?)", (r["id"], r["text"], r["domain"], blob))
            n += 1
        except Exception:  # noqa: BLE001
            pass
    dst.commit()
    dst.close()
    pk.close()
    return {"ok": True, "imported": n, "version": meta.get("version"),
            "domain": meta.get("domain")}


def rebuild_from_source(force=True):
    """Re-embed code+docs from SOURCE into embeddings.db (zero-egress, local
    embedder). Wraps forge_rag_warmup."""
    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_rag_warmup import warmup_rag
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"forge_rag_warmup unavailable: {exc}"}
    try:
        res = warmup_rag(force=force, batch_size=200)
        return {"ok": True, "warmup": str(res)[:300]}
    except TypeError:
        try:
            res = warmup_rag(force)
            return {"ok": True, "warmup": str(res)[:300]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:300]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


def _selftest():
    import sqlite3
    import tempfile
    import os
    d = tempfile.mkdtemp()
    src = os.path.join(d, "src.db")
    pack = os.path.join(d, "pack.db")
    dst = os.path.join(d, "dst.db")
    # synthetic source
    c = sqlite3.connect(src)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, domain TEXT, embedding BLOB)")
    vec = [0.5, -0.25, 1.0, -1.0] + [0.0] * 1020
    c.execute("INSERT INTO rag_chunks VALUES (?,?,?,?)",
              ("c1", "hello", "nokido_code", struct.pack(f"{len(vec)}f", *vec)))
    c.commit()
    c.close()
    ex = export_pack(pack, src_db=src, domain="nokido_code")
    c = sqlite3.connect(dst)
    c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, domain TEXT, embedding BLOB)")
    c.commit()
    c.close()
    im = import_pack(pack, dst_db=dst)
    c = sqlite3.connect(dst)
    row = c.execute("SELECT embedding FROM rag_chunks WHERE id='c1'").fetchone()
    c.close()
    got = struct.unpack("4f", row[0][:16])
    # int8 round-trip: 1.0 exact (scale=1.0), 0.5->~0.5, within tolerance
    ok = (ex["exported"] == 1 and im["imported"] == 1
          and abs(got[2] - 1.0) < 0.02 and abs(got[0] - 0.5) < 0.02
          and abs(got[3] + 1.0) < 0.02)
    for p in (src, pack, dst):
        try:
            os.remove(p)
        except Exception:  # noqa: BLE001
            pass
    print(json.dumps({"export": ex["exported"], "import": im["imported"],
                      "roundtrip": [round(x, 3) for x in got[:4]], "pass": ok}))
    return 0 if ok else 1


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Nokido Knowledge Pack (export/import/rebuild)")
    ap.add_argument("--export", metavar="OUT.db")
    ap.add_argument("--import", dest="imp", metavar="PACK.db")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--domain", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    if a.export:
        print(json.dumps(export_pack(a.export, domain=a.domain, limit=a.limit)))
    elif a.imp:
        print(json.dumps(import_pack(a.imp)))
    elif a.rebuild:
        print(json.dumps(rebuild_from_source()))
    else:
        print(json.dumps({"usage": "--export OUT.db | --import PACK.db | --rebuild"}))


if __name__ == "__main__":
    main()
