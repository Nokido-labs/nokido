"""
tools/rotate_logs.py — Rotation logs fichiers Nokido
Regles:
  - .log > 5MB    → compresse en .log.gz, repart a zero
  - .log > 1MB    → truncate aux 10000 dernières lignes
  - .json sandbox > 500KB et non-critiques → suppression
  - .md sandbox > 200KB → suppression si pas dans liste whitelist
  - Retention gz: 5 fichiers max par log
Lance par: python tools/rotate_logs.py
Daemon: ajouter dans forge_bell ou cron Windows (hebdo)
"""

import datetime
import glob
import gzip
import os
import shutil

BASE = str(__import__("pathlib").Path(__file__).resolve().parents[1])
LOG_DIRS = [
    os.path.join(BASE, "logs"),
    os.path.join(BASE, "sandbox"),
]
MAX_LOG_MB = 5
TAIL_LOG_MB = 1
MAX_JSON_KB = 500
RETAIN_GZ = 5

# Fichiers critiques a ne jamais supprimer
WHITELIST = {
    "lessons_learned.md",
    "INFRA.md",
    "clawhub_catalog.json",
    "dedup_ids.json",
    "mcp_audit.log",
}


def rotate_log(path):
    size_mb = os.path.getsize(path) / 1024 / 1024
    name = os.path.basename(path)
    if name in WHITELIST:
        return f"SKIP(whitelist) {name}"

    if size_mb > MAX_LOG_MB:
        # Compresser
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        gz_path = path + f".{ts}.gz"
        with open(path, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        open(path, "w").close()  # reset
        # Purge vieux gz
        gz_list = sorted(glob.glob(path + ".*.gz"))
        for old in gz_list[:-RETAIN_GZ]:
            os.remove(old)
        return f"ROTATE {name} ({size_mb:.1f}MB) -> {os.path.basename(gz_path)}"

    elif size_mb > TAIL_LOG_MB:
        # Garder les 10000 dernieres lignes
        with open(path, errors="replace") as f:
            lines = f.readlines()
        if len(lines) > 10000:
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(lines[-10000:])
            return f"TAIL {name} ({size_mb:.1f}MB) -> 10000 lignes"

    return None


def purge_sandbox_data(d):
    results = []
    for f in os.listdir(d):
        if f in WHITELIST:
            continue
        path = os.path.join(d, f)
        if not os.path.isfile(path):
            continue
        size_kb = os.path.getsize(path) / 1024
        ext = os.path.splitext(f)[1]

        if (
            ext == ".json"
            and size_kb > MAX_JSON_KB
            and f not in WHITELIST
            or ext == ".md"
            and size_kb > 200
            and f not in WHITELIST
            or ext in (".bin", ".npz", ".npy")
            and size_kb > 1000
        ):
            os.remove(path)
            results.append(f"DEL {f} ({size_kb:.0f}KB)")
    return results


if __name__ == "__main__":
    print(f"=== rotate_logs {datetime.datetime.now().isoformat()[:19]} ===")
    for d in LOG_DIRS:
        if not os.path.isdir(d):
            continue
        print(f"\n{d}:")
        for fname in os.listdir(d):
            fpath = os.path.join(d, fname)
            if os.path.isfile(fpath) and fname.endswith((".log", ".err")):
                r = rotate_log(fpath)
                if r:
                    print(f"  {r}")
        # Purge sandbox data
        if "sandbox" in d:
            for r in purge_sandbox_data(d):
                print(f"  {r}")
    print("\nDone.")
