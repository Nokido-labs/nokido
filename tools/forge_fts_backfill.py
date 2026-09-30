"""forge_fts_backfill.py — rattrape les chunks INVISIBLES au lexical.

DOCTRINE.md §1 : le lexical PRIME. Un chunk present dans `rag_chunks` mais absent de
`rag_fts` n'est retrouvable que par le canal dense — et pas du tout s'il n'a pas encore
de vecteur. Il est en base, il est perdu, et rien ne le signale.

Mesure 2026-07-25 : 708 411 chunks en base, 596 078 en FTS -> 112 333 invisibles (16 %).
Cause historique : plusieurs chemins d'ingestion ecrivaient `rag_chunks` sans doubler
l'ecriture dans `rag_fts` (la table FTS5 n'a AUCUN trigger), dont l'indexeur de doctrine
lui-meme — 121 chunks de doctrine, 0 en lexical.

METHODE — deux lectures sequentielles, jamais de jointure : un `LEFT JOIN` entre deux
tables de ~700 k lignes dont une FTS5 a fait TOMBER le hub le 25/07. On charge les
`chunk_id` deja indexes en memoire (~600 k identifiants) puis on parcourt `rag_chunks`.

Usage :
    LAFORGE_PYTHON tools/forge_fts_backfill.py           # mesure + rattrapage
    LAFORGE_PYTHON tools/forge_fts_backfill.py --dry-run # mesure seule
    LAFORGE_PYTHON tools/forge_fts_backfill.py --limit 20000
"""
from __future__ import annotations

__FORGE_COLOR__ = "memoire/rag : rattrape les chunks invisibles au lexical"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nokido_agent.app.forge_db_path import open_writer, write_retry  # noqa: E402

BATCH = 2000


def main() -> int:
    ap = argparse.ArgumentParser()
    # L'effet utile est le DEFAUT : `run_job` ignore le parametre `args`, un drapeau
    # obligatoire rendrait l'outil silencieusement inoperant en deporte.
    ap.add_argument("--dry-run", action="store_true", help="mesurer sans ecrire")
    ap.add_argument("--limit", type=int, default=0,
                    help="plafond de chunks rattrapes (0 = tous)")
    args = ap.parse_args()

    conn = open_writer(timeout=180.0)
    t0 = time.time()

    print("[1/3] lecture des chunk_id deja indexes en lexical...", flush=True)
    indexed = {r[0] for r in conn.execute("SELECT chunk_id FROM rag_fts") if r[0]}
    print(f"      {len(indexed)} chunk_id presents dans rag_fts ({time.time() - t0:.1f}s)",
          flush=True)

    print("[2/3] parcours de rag_chunks, detection des invisibles...", flush=True)
    manquants: list = []
    par_domaine: Counter = Counter()
    total = 0
    for cid, text, source, domain in conn.execute(
            "SELECT id, text, source, domain FROM rag_chunks"):
        total += 1
        if not cid or cid in indexed:
            continue
        if not (text or "").strip():
            continue  # un chunk vide n'a rien a indexer — ce n'est pas une perte
        par_domaine[domain or "(null)"] += 1
        manquants.append((cid, text, source, domain))
    print(f"      {total} chunks parcourus, {len(manquants)} INVISIBLES au lexical "
          f"({time.time() - t0:.1f}s)\n", flush=True)

    print("      par domaine :", flush=True)
    for d, n in par_domaine.most_common(15):
        print(f"        {str(d):<26} {n:>7}", flush=True)

    if args.dry_run:
        print("\n[3/3] DRY-RUN — rien ecrit. Relancer sans --dry-run pour rattraper.",
              flush=True)
        conn.close()
        return 0

    todo = manquants[:args.limit] if args.limit else manquants
    print(f"\n[3/3] rattrapage de {len(todo)} chunks (lots de {BATCH})...", flush=True)
    done = fail = 0
    for i in range(0, len(todo), BATCH):
        lot = todo[i:i + BATCH]

        def _ecrire(c, _lot=lot):
            # PAS de DELETE ici — et c'est le coeur de la performance. Ailleurs
            # (reindexation d'un chunk existant) le DELETE est OBLIGATOIRE, car
            # `INSERT OR IGNORE` ne met pas a jour le texte d'une table FTS5 et
            # laisserait survivre l'ancienne version. Mais ici les cibles sont
            # ABSENTES de rag_fts par construction : elles viennent d'etre detectees
            # comme telles.
            #
            # `DELETE ... WHERE chunk_id = ?` sur une FTS5 declenche un SCAN COMPLET
            # (aucun index sur cette colonne) : 2 000 suppressions par lot x 596 000
            # lignes = quadratique. Mesure 25/07 : 23 minutes de CPU plein pour ZERO
            # ligne ecrite. Sans le DELETE, l'insertion est lineaire.
            c.execute("BEGIN IMMEDIATE")
            try:
                c.executemany("INSERT INTO rag_fts (chunk_id, text, source, domain)"
                              " VALUES (?,?,?,?)", _lot)
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

        try:
            # `write_retry` et NON un BEGIN IMMEDIATE nu : le daemon d'embed ecrit en
            # continu dans la meme base, et un lot bloque fige tout le rattrapage sans
            # rien afficher. Mesure 25/07 : premiere version restee coincee sur son lot
            # initial, zero ligne ecrite, zero erreur — j'avais ecrit write_retry le
            # matin meme sans m'en servir ici.
            write_retry(_ecrire, attempts=5, timeout=60.0)
            done += len(lot)
        except Exception as e:  # noqa: BLE001
            fail += len(lot)
            print(f"      lot {i // BATCH}: ECHEC {type(e).__name__}: {str(e)[:90]}",
                  flush=True)
        if (i // BATCH) % 10 == 0 and i:
            print(f"      {done}/{len(todo)} rattrapes ({time.time() - t0:.0f}s)", flush=True)

    reste = conn.execute("SELECT count(*) FROM rag_fts").fetchone()[0]
    print(f"\n=== BILAN === {done} indexes, {fail} echecs | rag_fts = {reste} lignes "
          f"| {time.time() - t0:.0f}s", flush=True)
    conn.close()
    print("FIN", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
