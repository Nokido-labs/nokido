"""forge_tier_guard_install.py — chokepoint DB anti-repollution du tier vectoriel.

PROBLEME : 10+ scripts/daemons font `UPDATE rag_chunks SET embedding=...` sur des
chunks `embedding IS NULL` SANS filtrer par forge_tier_policy.HOT_TIER_SQL. Patcher
chacun = whack-a-mole (le script N+1 re-polluera). Solution structurelle = UN garde
au niveau base : un trigger BEFORE UPDATE OF embedding qui IGNORE (laisse NULL)
tout chunk d'origine froide. Attrape TOUTES les voies present + futures.

Le trigger derive sa condition de `ORIGIN_EXPR`/`HOT_ORIGINS` (source unique de
verite) -> reste aligne si la politique evolue (re-lancer ce script).

INSERT non garde a dessein : IGNORE sur INSERT detruirait le chunk (perte FTS) ;
or l'ingestion pose embedding=NULL puis les scripts UPDATE -> le vecteur d'attaque
est l'UPDATE. Idempotent (drop+recreate). Self-test inclus (prouve block/allow).

Ecrit la DB -> lancer en trusted_script (LaForgeTrusted).
"""
from __future__ import annotations
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nokido_agent.tools.forge_tier_policy import ORIGIN_EXPR, HOT_ORIGINS  # noqa: E402

_DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"
_TRIGGER = "forge_tier_guard"

# ORIGIN_EXPR refere `source`/`domain` en colonnes nues ; dans un trigger il faut
# les qualifier NEW. -> on prefixe par regex word-boundary (les litteraux SQL ne
# contiennent pas ces mots entiers, le remplacement est sur).
_NEW_ORIGIN_EXPR = re.sub(r"\b(source|domain)\b", r"NEW.\1", " ".join(ORIGIN_EXPR.split()))
_HOT_LIST = ", ".join(f"'{o}'" for o in HOT_ORIGINS)

_TRIGGER_SQL = f"""
CREATE TRIGGER {_TRIGGER}
BEFORE UPDATE OF embedding ON rag_chunks
FOR EACH ROW
WHEN NEW.embedding IS NOT NULL
 AND ({_NEW_ORIGIN_EXPR}) NOT IN ({_HOT_LIST})
BEGIN
  SELECT RAISE(IGNORE);
END;
"""


def install(db: Path = _DB) -> dict:
    conn = sqlite3.connect(db)
    conn.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER}")
    conn.execute(_TRIGGER_SQL)
    conn.commit()

    # --- self-test : un cold doit rester NULL, un hot doit accepter ---
    res = {"installed": True, "trigger": _TRIGGER}
    dummy = b"\x00\x00\x00\x00"  # blob factice
    for label, where in (
        ("cold", f"NOT (({_NEW_ORIGIN_EXPR.replace('NEW.', '')}) IN ({_HOT_LIST}))"),
        ("hot", f"(({_NEW_ORIGIN_EXPR.replace('NEW.', '')}) IN ({_HOT_LIST}))"),
    ):
        row = conn.execute(
            f"SELECT rowid FROM rag_chunks WHERE embedding IS NULL AND {where} LIMIT 1"
        ).fetchone()
        if not row:
            res[f"selftest_{label}"] = "skip (aucun row NULL)"
            continue
        rid = row[0]
        conn.execute("BEGIN")
        conn.execute("UPDATE rag_chunks SET embedding=? WHERE rowid=?", (dummy, rid))
        got = conn.execute("SELECT embedding FROM rag_chunks WHERE rowid=?", (rid,)).fetchone()[0]
        conn.execute("ROLLBACK")
        if label == "cold":
            res["selftest_cold"] = "PASS (reste NULL)" if got is None else "FAIL (a pris l'embed!)"
        else:
            res["selftest_hot"] = "PASS (accepte)" if got is not None else "FAIL (bloque a tort!)"
    conn.close()
    return res


def main() -> int:
    import json
    r = install()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    ok = r.get("selftest_cold", "").startswith("PASS") and not r.get("selftest_hot", "PASS").startswith("FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
