"""forge_db_recover_gold.py — filtre tolérant du dump `sqlite3 .recover`.

Le dump SQL de `.recover` sur une DB corrompue contient quelques rows pourris
(binaire PDF dans une colonne TEXT → quote ' non-fermée). Le CLI sqlite3 baile
dessus : la string non-terminée avale tout jusqu'au COMMIT → rollback → DB vide.

Ce script segmente le dump en statements via sqlite3.complete_statement, écrit
les bons dans recover_clean.sql et quarantaine les cassés. Sur runaway (quote
non-fermée qui dépasse CAP), il RESYNC sur la prochaine frontière de statement
(^INSERT/^CREATE/...) : il ne quarantaine QUE le statement cassé et récupère
les bonnes lignes avalées. Collatéral ≈ 0.

Réimport ensuite via le CLI : sqlite3 gold.db < recover_clean.sql
"""
import sqlite3
import os
import re

SRC = r"%NOKIDO_DATA%\recover.sql"
CLEAN = r"C:\tmp\recover_clean.sql"
QUAR = r"C:\tmp\recover_quarantine.sql"
CAP = 4_000_000  # >4MB sans clôture = statement runaway (quote non-fermée)

START_RE = re.compile(
    r"(?m)^(INSERT INTO |CREATE |PRAGMA |COMMIT|BEGIN|DELETE |UPDATE |ANALYZE|ROLLBACK|\.)"
)

# Bytes de contrôle (hors \t \n \r) + char de remplacement Unicode = contamination
# binaire (PDF brut dans une colonne TEXT). Le CLI sqlite3 (string C) tronque sur
# NUL → string non-terminée → avale le COMMIT → DB vide. Python complete_statement
# ne le voit pas. On quarantaine ces rows junk.
BINARY_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f�]")


def main():
    fin = open(SRC, encoding="utf-8", errors="replace")
    fout = open(CLEAN, "w", encoding="utf-8", newline="")
    fq = open(QUAR, "w", encoding="utf-8", newline="")

    buf = ""
    good = 0
    bad = 0
    quar_bytes = 0

    def flush_good(stmt):
        nonlocal good
        fout.write(stmt)
        if not stmt.endswith("\n"):
            fout.write("\n")
        good += 1

    def quarantine(text):
        nonlocal bad, quar_bytes
        fq.write(text)
        fq.write("\n-- ---QUAR-SEP---\n")
        bad += 1
        quar_bytes += len(text)

    for line in fin:
        buf += line
        if sqlite3.complete_statement(buf):
            if BINARY_RE.search(buf):
                quarantine(buf)
            else:
                flush_good(buf)
            buf = ""
            continue
        if len(buf) > CAP:
            # runaway : trouver la prochaine frontière de statement (hors pos 0)
            resync = None
            for m in START_RE.finditer(buf):
                if m.start() == 0:
                    continue
                resync = m.start()
                break
            if resync is None:
                quarantine(buf)
                buf = ""
            else:
                quarantine(buf[:resync])
                buf = buf[resync:]
                if sqlite3.complete_statement(buf):
                    if BINARY_RE.search(buf):
                        quarantine(buf)
                    else:
                        flush_good(buf)
                    buf = ""

    if buf.strip():
        if sqlite3.complete_statement(buf) and not BINARY_RE.search(buf):
            flush_good(buf)
        else:
            quarantine(buf)

    fin.close()
    fout.close()
    fq.close()
    print(f"good_blocks={good} quarantined={bad} quar_bytes={quar_bytes}", flush=True)
    print(
        f"clean_size={os.path.getsize(CLEAN)} quar_size={os.path.getsize(QUAR)}",
        flush=True,
    )


if __name__ == "__main__":
    main()
