"""Tri de la veille avant vectorisation — débloque le sous-ensemble de VALEUR.

Le backlog `domain='sdk_gitingest'` (≈234k chunks au 2026-09-01) est classé
`cold-legacy` par le trigger `forge_tier_guard`, qui refuse donc de le vectoriser
(RAISE IGNORE). Décision owner du 2026-09-01 : « trier PUIS vectoriser ». La
mesure du même jour a montré pourquoi le tri prime : 44 % du backlog est du
TEST/FIXTURE (bruit sémantique), et un dépôt entier (`exploitgym`, ≈40k) est
OFFENSIF — le vectoriser irait contre la purge du cœur faite le même jour.

Ce que fait l'outil : re-tague le `domain` des seuls chunks de VALEUR
(code/doc réel, longueur suffisante, dépôt NON offensif) de `sdk_gitingest` vers
`veille_code`. Ce domain ne figure dans aucune branche du trigger → le CASE tombe
sur ELSE='laforge', qui EST dans la whitelist → les chunks deviennent
vectorisables. Le trigger reste l'unique source de vérité de la taxonomie ; on ne
le touche pas, on déplace des chunks d'un tier bloqué vers un tier autorisé.

RÉVERSIBLE : `--rollback` ramène `veille_code` → `sdk_gitingest`.

Le re-tag NE vectorise pas : il DÉBLOQUE. La vectorisation est faite ensuite par
le drainer :8099 (`forge_embed_backfill_cool`), qui ne prend que ce que le
trigger autorise.

Usage :
    LAFORGE_PYTHON tools/forge_veille_triage_vectorisation.py            # dry-run (mesure)
    LAFORGE_PYTHON tools/forge_veille_triage_vectorisation.py --apply    # re-tag
    LAFORGE_PYTHON tools/forge_veille_triage_vectorisation.py --rollback --apply
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

__FORGE_COLOR__ = "digestif/tri-de-la-veille"

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
sys.path.insert(0, str(ROOT))
from nokido_agent.app.forge_utils import contient_un_mot  # prédicat partagé (cliquet clones)

# Dépôts / chemins offensifs : exclus du tri par cohérence avec la purge du cœur.
# Un chunk offensif vectorisé rentrerait dans la recherche sémantique du cœur.
OFFENSIF = ("exploitgym", "pentestgpt", "exploit", "ctf", "redteam",
            "metasploit", "payload", "/attack", "reverse_shell")

DOC_EXT = (".md", ".rst", ".txt", ".adoc")
CODE_EXT = (".rs", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".c", ".cc",
            ".cpp", ".h", ".hpp", ".java", ".rb", ".sh", ".kt", ".swift")
MIN_CHARS = 120


def _offensif(source: str) -> bool:
    return contient_un_mot(source, OFFENSIF)


def _kind(source: str) -> str:
    s = (source or "").lower()
    if "fixture" in s or "/test" in s or "test/" in s or "/tests/" in s \
            or s.endswith(("_test.rs", "_tests.rs", "_test.py", "_test.go")):
        return "TEST"
    if s.endswith(DOC_EXT):
        return "DOC"
    if s.endswith(CODE_EXT):
        return "CODE"
    if s.endswith((".json", ".toml", ".yaml", ".yml", ".lock", ".cfg", ".ini", ".xml")):
        return "DATA"
    return "AUTRE"


def _de_valeur(source: str, longueur: int) -> bool:
    return (_kind(source) in ("CODE", "DOC")
            and (longueur or 0) >= MIN_CHARS
            and not _offensif(source))


def _writer():
    """Writer autocommit/WAL/busy_timeout (contention concurrente sûre)."""
    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_db_path import open_writer  # type: ignore
        return open_writer(str(DB))
    except Exception:
        import sqlite3
        conn = sqlite3.connect(str(DB), timeout=60, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
        return conn


def selection(conn, source_domain: str) -> list[str]:
    """Ids des chunks NULL de `source_domain` à re-taguer (dry-run inclus)."""
    ids: list[str] = []
    types: Counter = Counter()
    depots: Counter = Counter()
    exclus_off = 0
    exclus_test = 0
    for cid, source, longueur in conn.execute(
        "SELECT id, source, length(text) FROM rag_chunks "
        "WHERE embedding IS NULL AND embedding_model IS NULL AND domain=?",
        (source_domain,),
    ):
        if _offensif(source):
            exclus_off += 1
            continue
        k = _kind(source)
        if k == "TEST":
            exclus_test += 1
            continue
        if _de_valeur(source, longueur):
            ids.append(cid)
            types[k] += 1
            depots[(source or "?").split("/")[0][:24]] += 1
    print(f"=== TRI depuis domain='{source_domain}' ===")
    print(f"  RETENUS (de valeur)   : {len(ids)}")
    print(f"    par type  : {dict(types)}")
    print(f"    par depot : {depots.most_common(12)}")
    print(f"  EXCLUS offensifs      : {exclus_off}")
    print(f"  EXCLUS tests/fixtures : {exclus_test}")
    return ids


def retag(conn, ids: list[str], cible: str, sec: bool) -> int:
    if not sec:
        print(f"  (dry-run : {len(ids)} chunks SERAIENT re-tagués -> '{cible}')")
        return 0
    n = 0
    CHUNK = 500
    for i in range(0, len(ids), CHUNK):
        lot = ids[i:i + CHUNK]
        q = ("UPDATE rag_chunks SET domain=? WHERE id IN (%s)"
             % ",".join("?" * len(lot)))
        conn.execute(q, (cible, *lot))
        n += len(lot)
        if i % 10000 == 0:
            print(f"    re-tag {n}/{len(ids)}")
    print(f"  re-tagués -> '{cible}' : {n}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="écrit (défaut : dry-run)")
    ap.add_argument("--rollback", action="store_true",
                    help="ramène veille_code -> sdk_gitingest (sur les NULL seulement)")
    ap.add_argument("--source-domain", default="sdk_gitingest")
    ap.add_argument("--cible", default="veille_code")
    args = ap.parse_args()

    if not DB.exists():
        print(f"DB introuvable: {DB}")
        return 2
    conn = _writer()

    if args.rollback:
        # Rollback : ne ramène que ce qui n'a pas encore été vectorisé (NULL),
        # pour ne pas rejeter un chunk déjà servi hors du tier autorisé.
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM rag_chunks WHERE domain=? AND embedding IS NULL",
            (args.cible,))]
        print(f"=== ROLLBACK '{args.cible}' -> '{args.source_domain}' : {len(ids)} chunks NULL")
        retag(conn, ids, args.source_domain, args.apply)
        return 0

    ids = selection(conn, args.source_domain)
    retag(conn, ids, args.cible, args.apply)
    if args.apply:
        print("\nProchaine étape : le drainer :8099 vectorisera ces chunks "
              "(ils sont désormais dans le tier 'laforge', autorisé).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
