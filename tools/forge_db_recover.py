"""forge_db_recover.py — Recovery de %NOKIDO_DATA%\\embeddings.db corrompue (Bad ptr map / rowid
out of order). Salvage row-par-row TOLÉRANT aux pages corrompues -> nouvelle base
propre. Rebuild FTS + index + triggers. Integrity check. PAS de swap auto (vérif avant).
Lancer writers STOPPÉS (Master down + run_jobs tués)."""
import os
import sqlite3
import sys
import time

SRC = r"%NOKIDO_DATA%\embeddings.db"
DST = r"%NOKIDO_DATA%\embeddings_recovered.db"
SHADOW = ("_data", "_idx", "_content", "_docsize", "_config")


def copy_table(s, d, name):
    cols = [r[1] for r in s.execute(f'PRAGMA table_info("{name}")')]
    if not cols:
        return 0, 0
    ins = f'INSERT OR IGNORE INTO "{name}" VALUES ({",".join("?" * len(cols))})'
    try:
        mx = s.execute(f'SELECT MAX(rowid) FROM "{name}"').fetchone()[0]
    except Exception:
        mx = None
    copied = lost = 0
    if not mx:  # table sans rowid utilisable ou vide -> full copy best-effort
        try:
            rows = s.execute(f'SELECT * FROM "{name}"').fetchall()
            d.executemany(ins, rows)
            return len(rows), 0
        except Exception as e:
            print(f"    full-copy fail {name}: {str(e)[:60]}")
            return 0, 0
    step = 2000
    for lo in range(1, mx + 1, step):
        try:
            rows = s.execute(f'SELECT * FROM "{name}" WHERE rowid BETWEEN ? AND ?', (lo, lo + step - 1)).fetchall()
            d.executemany(ins, rows)
            copied += len(rows)
        except Exception:  # chunk corrompu -> row par row pour sauver le max
            for rid in range(lo, lo + step):
                try:
                    r = s.execute(f'SELECT * FROM "{name}" WHERE rowid=?', (rid,)).fetchall()
                    if r:
                        d.executemany(ins, r)
                        copied += 1
                except Exception:
                    lost += 1
    return copied, lost


def main():
    t0 = time.time()
    if os.path.exists(DST):
        os.remove(DST)
    s = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True, timeout=30)
    d = sqlite3.connect(DST, timeout=120)
    d.execute("PRAGMA journal_mode=OFF")
    d.execute("PRAGMA synchronous=OFF")
    master = s.execute("SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL").fetchall()
    tables = [(n, sql) for t, n, sql in master if t == "table" and not n.startswith("sqlite_")
              and "VIRTUAL TABLE" not in (sql or "").upper() and not any(n.endswith(x) for x in SHADOW)]
    virtuals = [(n, sql) for t, n, sql in master if t == "table" and "VIRTUAL TABLE" in (sql or "").upper()]
    indexes = [(n, sql) for t, n, sql in master if t == "index"]
    triggers = [(n, sql) for t, n, sql in master if t == "trigger"]
    print(f"[recover] tables={len(tables)} fts={len(virtuals)} idx={len(indexes)} trig={len(triggers)}", flush=True)
    tot_c = tot_l = 0
    for n, sql in tables:
        try:
            d.execute(sql)
        except Exception as e:
            print(f"  create {n} fail: {str(e)[:60]}")
            continue
        c, l = copy_table(s, d, n)
        tot_c += c
        tot_l += l
        print(f"  {n}: copied={c} lost={l} ({round(time.time() - t0)}s)", flush=True)
    d.commit()
    for n, sql in virtuals:  # FTS5 external-content -> recreate + rebuild depuis la table source
        try:
            d.execute(sql)
            d.execute(f'INSERT INTO "{n}"("{n}") VALUES(\'rebuild\')')
            print(f"  fts {n}: rebuilt", flush=True)
        except Exception as e:
            print(f"  fts {n}: {str(e)[:80]}")
    for n, sql in indexes:
        try:
            d.execute(sql)
        except Exception as e:
            print(f"  idx {n}: {str(e)[:50]}")
    for n, sql in triggers:
        try:
            d.execute(sql)
        except Exception as e:
            print(f"  trig {n}: {str(e)[:50]}")
    d.commit()
    ic = d.execute("PRAGMA integrity_check(5)").fetchall()
    rc = d.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0] if tables else 0
    s.close()
    d.close()
    print(f"[recover] DONE {round(time.time() - t0)}s copied={tot_c} lost={tot_l} rag_chunks={rc}", flush=True)
    print(f"[recover] integrity: {ic}", flush=True)
    print("[recover] RESULT: " + ("CLEAN" if ic == [("ok",)] else "NOT_CLEAN"), flush=True)


if __name__ == "__main__":
    main()
