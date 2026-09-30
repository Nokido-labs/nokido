"""forge_seed_nokido_entity.py — 3b rebrand : ajoute l'entity RBAC wrk_nokido comme
MIROIR EXACT de wrk_laforge (ring 0, hub souverain) dans forge_entities (embeddings.db).

Additif + idempotent + réversible (DELETE FROM forge_entities WHERE entity_id='wrk_nokido').
Copie TOUTES les colonnes (dont token_hash/capabilities/ring_level/meta) -> comportement
STRICTEMENT identique. Ne change AUCUN comportement tant que les producteurs émettent
encore wrk_laforge : alias dormant jusqu'au switch producteur. Rejouable.
"""
import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
SRC = "wrk_laforge"
DST = "wrk_nokido"
DST_NAME = "Hub Nokido (MCP :8766)"


def main() -> int:
    c = sqlite3.connect(str(DB))
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(forge_entities)").fetchall()]
        src = c.execute("SELECT * FROM forge_entities WHERE entity_id=?", (SRC,)).fetchone()
        if not src:
            print("SRC MISSING:", SRC)
            return 2
        if c.execute("SELECT 1 FROM forge_entities WHERE entity_id=?", (DST,)).fetchone():
            print("ALREADY PRESENT:", DST)
            return 0
        d = dict(zip(cols, src))
        d["entity_id"] = DST
        d["display_name"] = DST_NAME
        placeholders = ",".join("?" * len(cols))
        c.execute(
            "INSERT INTO forge_entities (" + ",".join(cols) + ") VALUES (" + placeholders + ")",
            tuple(d[k] for k in cols),
        )
        c.commit()
        print("SEEDED", DST, "ring", d.get("ring_level"), "caps", d.get("capabilities"))
        return 0
    finally:
        c.close()


if __name__ == "__main__":
    raise SystemExit(main())
