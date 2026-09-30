"""forge_migrate_metadata.py — Colonnes generees ext/folder/lang + index.

Socle du Self-Querying (pre-filtre metadonnees). Derive deterministiquement
de `source` : extension, dossier racine, langage. Colonnes VIRTUAL (calculees
a la lecture, zero stockage) + index B-tree -> pre-filtre WHERE ext='py' ultra
rapide, plus de LIKE sauvage. Idempotent.

Run : run action=trusted_script path=tools/forge_migrate_metadata.py
"""

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"

# Extension : match precis (fin de source, ou suivi de #suffixe de chunk).
_EXT_CASES = [
    ("py", "py"),
    ("ts", "ts"),
    ("js", "js"),
    ("md", "md"),
    ("rs", "rs"),
    ("toml", "toml"),
    ("json", "json"),
    ("yaml", "yaml"),
    ("yml", "yaml"),
    ("sh", "sh"),
    ("bat", "bat"),
    ("ps1", "ps1"),
    ("sql", "sql"),
    ("html", "html"),
    ("css", "css"),
    ("pdf", "pdf"),
    ("txt", "txt"),
]
EXT_EXPR = (
    "CASE\n"
    + "\n".join(
        f"  WHEN source LIKE '%.{e}' OR source LIKE '%.{e}#%' THEN '{v}'" for e, v in _EXT_CASES
    )
    + "\n  ELSE '' END"
)

FOLDER_EXPR = (
    "CASE WHEN instr(source, '/') > 0 THEN substr(source, 1, instr(source, '/') - 1) ELSE '' END"
)

LANG_EXPR = (
    "CASE ext WHEN 'py' THEN 'python' WHEN 'ts' THEN 'typescript' "
    "WHEN 'js' THEN 'javascript' WHEN 'rs' THEN 'rust' "
    "WHEN 'sh' THEN 'shell' WHEN 'ps1' THEN 'powershell' "
    "WHEN 'md' THEN 'markdown' WHEN 'sql' THEN 'sql' ELSE '' END"
)

COLS = [("ext", EXT_EXPR), ("folder", FOLDER_EXPR), ("lang", LANG_EXPR)]


def main() -> None:
    con = sqlite3.connect(str(DB), timeout=60)
    con.execute("PRAGMA busy_timeout=30000")
    for name, expr in COLS:
        try:
            con.execute(f"SELECT {name} FROM rag_chunks LIMIT 1")
            print(f"[meta] colonne {name} deja presente")
        except sqlite3.OperationalError:
            con.execute(
                f"ALTER TABLE rag_chunks ADD COLUMN {name} TEXT "
                f"GENERATED ALWAYS AS ({expr}) VIRTUAL"
            )
            con.commit()
            print(f"[meta] colonne {name} ajoutee")
    for idx, cols in [
        ("idx_ext", "ext"),
        ("idx_folder", "folder"),
        ("idx_lang", "lang"),
        ("idx_domain_ext", "domain, ext"),
    ]:
        con.execute(f"CREATE INDEX IF NOT EXISTS {idx} ON rag_chunks({cols})")
    con.commit()
    print("[meta] index B-tree OK")

    print("[meta] repartition par ext (tier chaud) :")
    for ext, n in con.execute(
        "SELECT ext, COUNT(*) c FROM rag_chunks WHERE embedding IS NOT NULL "
        "GROUP BY ext ORDER BY c DESC LIMIT 10"
    ):
        print(f"  {ext or '(aucune)':<10} {n}")
    con.close()


if __name__ == "__main__":
    main()
