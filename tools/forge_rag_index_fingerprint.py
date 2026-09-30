"""Index d'EXPRESSION sur le fingerprint : la dedup cesse de balayer 22,8 Go.

DEFAUT MESURE le 2026-09-03. `forge_ingest_pipeline.store_chunks` deduplique par

    SELECT json_extract(meta,'$.fingerprint') FROM rag_chunks
     WHERE json_extract(meta,'$.fingerprint') IN (...)

`json_extract(meta, ...)` est une EXPRESSION, pas une colonne : aucun index ne peut
la servir. Chaque appel — soit UNE FOIS PAR DOCUMENT — balaie donc les 2 M lignes.
Mesure sur l'ingestion des RFC : **180,7 Go lus** pour 293 s de CPU, ~2-3 min par
RFC, le process a 98 % d'I/O et 0 % utile.

Ce n'est pas le premier round. Un commentaire du 31/07 dans `store_chunks` raconte
la version d'avant : un `meta LIKE '%fingerprint%'` **par chunk**, 3,49 s piece,
20 min pour une RFC de 339 chunks. Le correctif a groupe par lots de 500 — il a
divise le NOMBRE de scans, pas supprime le scan. On est passe de « un balayage par
chunk » a « un balayage par document ».

SQLite sait indexer une expression. L'index ci-dessous rend la dedup logarithmique :

    CREATE INDEX idx_rag_fingerprint ON rag_chunks(json_extract(meta,'$.fingerprint'))

PORTEE : tout passe par `store_chunks`. Ce n'est pas un correctif « RFC ».

COUT : la construction evalue `json_extract` sur chaque ligne — UNE fois, plusieurs
minutes, et elle prend un verrou en ecriture. Ne pas la lancer pendant une ingestion :
elle la ferait echouer. Le garde ci-dessous refuse si un ecrivain est actif.

Usage :
    python tools/forge_rag_index_fingerprint.py            # mesure seule (dry-run)
    python tools/forge_rag_index_fingerprint.py --apply    # cree l'index
"""

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "digestif/indexation-rag"

import sys
import time
from pathlib import Path

NOM = "idx_rag_fingerprint"
EXPR = "json_extract(meta,'$.fingerprint')"


def _db():
    """Chemin de la base, demande a forge_db_path — jamais code en dur."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from nokido_agent.app import forge_db_path as fdp
        for nom in ("DB_PATH", "RAG_DB", "EMBEDDINGS_DB", "db_path"):
            v = getattr(fdp, nom, None)
            if callable(v):
                v = v()
            if v and Path(str(v)).exists():
                return Path(str(v))
    except Exception as e:  # noqa: BLE001
        print("[index] forge_db_path indisponible (%s) — repli sur les chemins"
              " connus" % type(e).__name__, file=sys.stderr)
    for c in (Path("%NOKIDO_DATA%\embeddings.db"),
              Path(__file__).resolve().parents[1] / "RAG" / "embeddings.db"):
        if c.exists():
            return c
    return None


def _ecrivain_actif() -> str:
    """Un job d'ingestion en cours ? La construction le ferait echouer."""
    try:
        import psutil
    except ImportError:
        return ""      # pas de mesure possible : on le DIT, on ne rassure pas
    for p in psutil.process_iter(["pid", "name"]):
        try:
            cl = " ".join(p.cmdline())
        except Exception:  # noqa: BLE001  # muet-ok : cmdline d'un autre compte
            continue
        if any(m in cl for m in ("audit_rfc_compliance", "forge_ingest",
                                 "curriculum_ingest", "rag_warmup")):
            return "%s (pid %s)" % (Path(cl.split()[-1]).name, p.pid)
    return ""


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    appliquer = "--apply" in argv
    import sqlite3

    db = _db()
    if db is None:
        print("[index] aucune base joignable — RIEN fait", file=sys.stderr)
        return 3
    print("[index] base : %s" % db)

    ro = sqlite3.connect("file:%s?mode=ro" % str(db).replace("\\", "/"), uri=True)
    deja = [r[0] for r in ro.execute("SELECT name FROM sqlite_master "
                                     "WHERE type='index' AND name=?", (NOM,))]
    plan = " | ".join(r[-1] for r in ro.execute(
        "EXPLAIN QUERY PLAN SELECT %s FROM rag_chunks WHERE %s IN (?,?)"
        % (EXPR, EXPR), ("a", "b")))
    print("[index] present : %s" % ("OUI" if deja else "non"))
    print("[index] plan actuel : %s" % plan)
    if "SCAN" in plan.upper():
        print("        ^ SCAN = balayage complet : c'est le defaut mesure.")

    if deja:
        print("[index] rien a faire.")
        return 0
    if not appliquer:
        print("[index] DRY-RUN. Relancer avec --apply pour construire l'index"
              " (plusieurs minutes, verrou en ecriture).")
        return 0

    occupe = _ecrivain_actif()
    if occupe:
        print("[index] REFUS : un ecrivain est actif (%s). La construction "
              "prendrait un verrou et le ferait echouer." % occupe,
              file=sys.stderr)
        return 4

    t0 = time.time()
    con = sqlite3.connect(str(db), isolation_level=None, timeout=120)
    con.execute("PRAGMA busy_timeout=120000")
    try:
        con.execute("CREATE INDEX IF NOT EXISTS %s ON rag_chunks(%s)" % (NOM, EXPR))
    except sqlite3.Error as e:
        print("[index] ECHEC : %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
    dt = time.time() - t0

    plan2 = " | ".join(r[-1] for r in con.execute(
        "EXPLAIN QUERY PLAN SELECT %s FROM rag_chunks WHERE %s IN (?,?)"
        % (EXPR, EXPR), ("a", "b")))
    print("[index] cree en %.1f s" % dt)
    print("[index] plan apres : %s" % plan2)
    # Le verdict se lit sur le PLAN, pas sur l'absence d'erreur : un index peut
    # exister sans que l'optimiseur le choisisse.
    if "SCAN" in plan2.upper():
        print("[index] ATTENTION : le plan balaie TOUJOURS — index non retenu par"
              " l'optimiseur, le defaut n'est PAS corrige.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
