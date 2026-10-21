"""
forge_db_backup.py — Backup nightly embeddings.db (SQLite Online Backup + zstd).

Pattern :
  1. sqlite3 .backup API (Online, safe pendant écritures concurrentes)
  2. Compression zstd (~4-6x ratio vs raw)
  3. Rotation : garde N derniers (default 7)
  4. Destination configurable (env LAFORGE_BACKUP_DIR ou --dir)

Pas de hub interférence — sqlite3.Connection.backup() ne lock pas exclusif.

--controle-fts TABLE (20/10, decision owner « chantier dedie, mesurer d'abord ») : la commande FTS5 `integrity-check`
passe par un INSERT, donc un verrou d'ECRITURE -- elle se joue sur la COPIE brute, jamais sur la base vivante.
La copie tient un instantane de lecture : le WAL de la base vivante ne se checkpointe pas et grossit sur SON volume
(V: : 36,8 Go libres le 20/10) -- d'ou un minimum de place exige sur le volume de la base ET sur la destination.

USAGE :
    LAFORGE_PYTHON tools/forge_db_backup.py
    LAFORGE_PYTHON tools/forge_db_backup.py --dir D:/backups/nokido --keep 14
    LAFORGE_PYTHON tools/forge_db_backup.py --no-zstd   # raw .db si zstd absent

CRON typique (Windows Task Scheduler) :
    Daily 03:00 -> schtasks /create /sc daily /st 03:00 ...
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


def dossier_par_defaut(environ=None, existe=None) -> Path:
    """Dossier de sauvegarde par defaut : LAFORGE_BACKUP_DIR, sinon E:/nokido_backups si le VOLUME E: existe, sinon
    ROOT/_backups. Decision owner 19/10 : archive externe sur E: -- jamais 50 Go dans le depot (GREEN MISTRAL 20/10)."""
    environ = os.environ if environ is None else environ
    existe = existe or (lambda p: Path(p).exists())
    if environ.get("LAFORGE_BACKUP_DIR"):
        return Path(environ["LAFORGE_BACKUP_DIR"])
    if existe(Path("E:/")):
        return Path("E:/nokido_backups")
    return ROOT / "_backups"


DEFAULT_BACKUP_DIR = dossier_par_defaut()


def _hr(b: int) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.2f} {u}"
        b /= 1024
    return f"{b:.2f} TB"


def _has_zstd() -> bool:
    try:
        import zstandard  # noqa

        return True
    except ImportError:
        return False


def online_backup(src: Path, dst: Path) -> dict:
    """sqlite3 .backup() — copie consistente même pendant writes concurrents."""
    t0 = time.time()
    src_conn = sqlite3.connect(str(src), timeout=30)
    dst_conn = sqlite3.connect(str(dst), timeout=30)
    try:
        # Online backup API : copy par pages
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()
    return {
        "src_bytes": src.stat().st_size,
        "dst_bytes": dst.stat().st_size,
        "elapsed_s": round(time.time() - t0, 1),
    }


def compress_zstd(src: Path, dst: Path, level: int = 9) -> dict:
    """Compress src -> dst.zst via zstandard streaming."""
    import zstandard as zstd

    t0 = time.time()
    cctx = zstd.ZstdCompressor(level=level)
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        cctx.copy_stream(fin, fout)
    return {
        "src_bytes": src.stat().st_size,
        "dst_bytes": dst.stat().st_size,
        "ratio": round(src.stat().st_size / max(dst.stat().st_size, 1), 2),
        "elapsed_s": round(time.time() - t0, 1),
    }


def rotate_backups(backup_dir: Path, keep: int) -> dict:
    """Garde les `keep` plus récents *.db.zst (ou *.db)."""
    files = sorted(
        list(backup_dir.glob("embeddings_*.db.zst")) + list(backup_dir.glob("embeddings_*.db")),
        key=lambda p: p.stat().st_mtime,
    )
    to_delete = files[:-keep] if len(files) > keep else []
    freed = 0
    for f in to_delete:
        try:
            sz = f.stat().st_size
            f.unlink()
            freed += sz
        except Exception:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_db_backup.py', 99, exc_info=True)
    return {"kept": min(len(files), keep), "deleted": len(to_delete), "freed_bytes": freed}


_NOM_TABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LIBRE_MIN_VOLUME_BASE = 10 * 1024 ** 3


def controler_fts(copie, tables) -> dict:
    """{table: "OK" | "CORROMPU: <message>" | "ABSENTE"} par la commande FTS5 `integrity-check`, sur une COPIE.
    Refuse (ValueError) la base vivante et tout nom qui n'est pas un identifiant -- AVANT toute ouverture (20/10)."""
    if Path(copie).resolve() == Path(DB).resolve():
        raise ValueError("controle FTS refuse sur la base vivante : %s" % copie)
    for t in tables:
        if not _NOM_TABLE.fullmatch(str(t)):
            raise ValueError("nom de table invalide : %r" % (t,))
    resultat = {}
    con = sqlite3.connect(str(copie))
    try:
        for t in tables:
            if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone() is None:
                resultat[t] = "ABSENTE"
                continue
            try:
                con.execute("INSERT INTO %s(%s, rank) VALUES('integrity-check', 1)" % (t, t))
                con.commit()
                resultat[t] = "OK"
            except sqlite3.DatabaseError as e:
                resultat[t] = "CORROMPU: %s" % e
    finally:
        con.close()
    return resultat


def place_suffisante(dossier, minimum_octets: int) -> bool:
    """Place libre >= minimum sur le volume de `dossier` (le 1er ancetre existant) ; volume illisible = False."""
    p = Path(dossier)
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free >= minimum_octets
    except OSError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_BACKUP_DIR))
    ap.add_argument("--keep", type=int, default=7)
    ap.add_argument("--level", type=int, default=9, help="zstd compression level 1-22 (default 9)")
    ap.add_argument("--no-zstd", action="store_true", help="garde .db raw (pas de compression)")
    ap.add_argument("--controle-fts", action="append", default=None, metavar="TABLE",
                    help="controle FTS5 integrity-check de TABLE sur la COPIE brute (repetable)")
    ap.add_argument("--rapport", default=None, help="rapport JSON {copie, fts, horodatage, octets}")
    args = ap.parse_args()

    if not DB.exists():
        print(f"ERR: DB introuvable: {DB}")
        return 1

    if args.controle_fts:
        if not place_suffisante(Path(DB).parent, _LIBRE_MIN_VOLUME_BASE):
            print("ERR: moins de 10 Go libres sur le volume de la base : la copie bloquerait le checkpoint du WAL")
            return 2
        if not place_suffisante(Path(args.dir), Path(DB).stat().st_size):
            print("ERR: destination %s trop petite pour une copie brute de %s" % (args.dir, _hr(DB.stat().st_size)))
            return 2

    backup_dir = Path(args.dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y%m%d-%H%M%S")
    raw_path = backup_dir / f"embeddings_{ts}.db"

    print(f"DB         : {DB} ({_hr(DB.stat().st_size)})")
    print(f"Backup dir : {backup_dir}")
    print()

    # 1. Online backup
    print(f"[1] Online backup -> {raw_path.name}...")
    r1 = online_backup(DB, raw_path)
    print(f"   src={_hr(r1['src_bytes'])} -> dst={_hr(r1['dst_bytes'])} in {r1['elapsed_s']}s")

    # 2. Compress zstd
    final_path = raw_path
    if not args.controle_fts and not args.no_zstd and _has_zstd():
        zst_path = raw_path.with_suffix(".db.zst")
        print(f"\n[2] zstd compress -> {zst_path.name}...")
        r2 = compress_zstd(raw_path, zst_path, level=args.level)
        print(
            f"   {_hr(r2['src_bytes'])} -> {_hr(r2['dst_bytes'])} "
            f"(ratio {r2['ratio']}x) in {r2['elapsed_s']}s"
        )
        # Drop raw
        raw_path.unlink()
        final_path = zst_path
    elif not args.controle_fts and not args.no_zstd:
        print(
            f"\n[2] zstd absent (pip install zstandard) — backup raw "
            f"conservé : {_hr(raw_path.stat().st_size)}"
        )

    # 3. Rotate
    print(f"\n[3] Rotation (keep {args.keep})...")
    r3 = rotate_backups(backup_dir, args.keep)
    print(f"   kept={r3['kept']} deleted={r3['deleted']} freed={_hr(r3['freed_bytes'])}")

    # 4. Controle FTS sur la copie brute ; le rapport s'ecrit TOUJOURS, corruption comprise (20/10)
    if args.controle_fts:
        fts = controler_fts(raw_path, args.controle_fts)
        for table, etat in fts.items():
            print(f"[4] FTS {table} : {etat}")
        if args.rapport:
            Path(args.rapport).write_text(json.dumps(
                {"copie": str(raw_path), "fts": fts, "horodatage": ts, "octets": r1["src_bytes"]},
                ensure_ascii=False, indent=2), encoding="utf-8")
        if any(e.startswith("CORROMPU") for e in fts.values()):
            return 3

    print(
        f"\n[OK] backup final: {final_path.relative_to(ROOT.parent) if final_path.is_relative_to(ROOT.parent) else final_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
