"""
forge_snapshot_janitor.py — Nokido v18.5
==========================================
Maintenance automatique de rag_snapshots.
Fusionne les recommandations Gemini (task_890595) avec les fixes Nokido.

Règles appliquées :
  R1 : max 3 UPDATE par chunk (les plus récents)
  R2 : purge DELETE orphelins (chunk absent de rag_chunks) — batch snap_id
  R3 : purge snapshot/update > 90j hors anchors
  R4 : VACUUM hors transaction (récupération espace disque)

Intégration : agent_tasks type=maintenance | forge_bell hebdo | DIContainer worker

SÉCURITÉ : DROP TRIGGER avant purge massive pour éviter cascade snapshot-de-snapshot.
SÉCURITÉ : Jamais de DELETE brut depuis un agent LLM — passer par cette fonction.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_db_path() -> Path:
    """Résout le chemin réel de embeddings.db depuis __file__."""
    return Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"


def drop_rag_triggers(conn: sqlite3.Connection) -> list[str]:
    """Désactive les triggers BEFORE DELETE/UPDATE sur rag_chunks.
    Nécessaire avant purge massive pour éviter la cascade de snapshots.
    Retourne les DDL pour les recréer."""
    triggers = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name='rag_chunks'"
    ).fetchall()
    for name, _ in triggers:
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")
    conn.commit()
    return [(name, sql) for name, sql in triggers if sql]


def recreate_triggers(conn: sqlite3.Connection, trigger_ddls: list[tuple]) -> None:
    """Recrée les triggers après purge."""
    for name, sql in trigger_ddls:
        conn.execute(sql)
    conn.commit()
    logger.info(f"Triggers recréés : {[t[0] for t in trigger_ddls]}")


def run_janitor(
    db_path: str | Path | None = None,
    dry_run: bool = False,
    max_update_per_chunk: int = 3,
    retention_days: int = 90,
    batch_size: int = 10_000,
) -> dict:
    """
    Applique les règles de rotation sur rag_snapshots.

    Args:
        db_path       : chemin DB. None = auto-détection.
        dry_run       : si True, compte sans supprimer.
        max_update_per_chunk : nb d'UPDATE à conserver par chunk.
        retention_days : seuil ancienneté (jours).
        batch_size     : taille des batches DELETE (évite timeout).

    Returns:
        dict avec les compteurs de chaque règle.
    """
    path = Path(db_path) if db_path else _get_db_path()
    if not path.exists():
        raise FileNotFoundError(f"DB introuvable : {path}")

    results = {
        "r1_update_old": 0,
        "r2_delete_orphan": 0,
        "r3_old_snapshots": 0,
        "vacuum_done": False,
        "dry_run": dry_run,
    }

    conn = sqlite3.connect(str(path), timeout=600)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-256000")  # 256MB Gemini recommandation

    try:
        before = conn.execute("SELECT COUNT(*) FROM rag_snapshots").fetchone()[0]
        logger.info(f"Janitor start — {before} snapshots")

        # ── DÉSACTIVER TRIGGERS (évite cascade) ──────────────────────────────
        trigger_ddls = []
        if not dry_run:
            trigger_ddls = drop_rag_triggers(conn)
            logger.info(f"Triggers suspendus : {[t[0] for t in trigger_ddls]}")

        # ── R1 : max N UPDATE par chunk ──────────────────────────────────────
        logger.info(f"R1 — max {max_update_per_chunk} UPDATE/chunk...")
        if dry_run:
            n = conn.execute(f"""
                SELECT COUNT(*) FROM rag_snapshots
                WHERE op = 'update'
                AND snap_id NOT IN (
                    SELECT snap_id FROM (
                        SELECT snap_id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY chunk_id ORDER BY snap_id DESC
                               ) as rn
                        FROM rag_snapshots WHERE op = 'update'
                    ) x WHERE rn <= {max_update_per_chunk}
                )
            """).fetchone()[0]
            results["r1_update_old"] = n
        else:
            conn.execute(f"""
                DELETE FROM rag_snapshots
                WHERE op = 'update'
                AND snap_id NOT IN (
                    SELECT snap_id FROM (
                        SELECT snap_id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY chunk_id ORDER BY snap_id DESC
                               ) as rn
                        FROM rag_snapshots WHERE op = 'update'
                    ) x WHERE rn <= {max_update_per_chunk}
                )
            """)
            results["r1_update_old"] = conn.total_changes
            conn.commit()
        logger.info(f"  -> R1 : {results['r1_update_old']} supprimés")

        # ── R2 : DELETE orphelins par batch snap_id ───────────────────────────
        # NOTE : LIMIT dans DELETE...NOT IN est invalide en SQLite.
        # On récupère les snap_id explicitement (batch 10K) — correctif Nokido.
        logger.info("R2 — DELETE orphelins par batch snap_id...")
        total_orphans = 0
        while True:
            orphan_ids = conn.execute(f"""
                SELECT s.snap_id FROM rag_snapshots s
                WHERE s.op = 'delete'
                AND NOT EXISTS (
                    SELECT 1 FROM rag_chunks r WHERE r.id = s.chunk_id
                )
                LIMIT {batch_size}
            """).fetchall()

            if not orphan_ids:
                break

            ids = [r[0] for r in orphan_ids]
            ph = ",".join("?" * len(ids))

            if not dry_run:
                conn.execute(f"DELETE FROM rag_snapshots WHERE snap_id IN ({ph})", ids)
                conn.commit()

            total_orphans += len(ids)
            logger.info(f"  -> batch {total_orphans} orphelins...")

            if dry_run:
                break  # en dry_run, compter une estimation partielle

        results["r2_delete_orphan"] = total_orphans
        logger.info(f"  -> R2 total : {total_orphans}")

        # ── R3 : > retention_days jours hors anchors ──────────────────────────
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)).strftime(
            "%Y-%m-%d"
        )
        logger.info(f"R3 — snapshots > {retention_days}j (cutoff={cutoff})...")
        if dry_run:
            n = conn.execute(f"""
                SELECT COUNT(*) FROM rag_snapshots
                WHERE op NOT IN ('knowledge_anchor', 'disco_anchor')
                AND SUBSTR(timecode,1,10) < '{cutoff}'
            """).fetchone()[0]
            results["r3_old_snapshots"] = n
        else:
            conn.execute(f"""
                DELETE FROM rag_snapshots
                WHERE op NOT IN ('knowledge_anchor', 'disco_anchor')
                AND SUBSTR(timecode,1,10) < '{cutoff}'
            """)
            results["r3_old_snapshots"] = conn.total_changes
            conn.commit()
        logger.info(f"  -> R3 : {results['r3_old_snapshots']} supprimés")

    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur janitor : {e}")
        raise
    finally:
        # ── TOUJOURS recréer les triggers ────────────────────────────────────
        if trigger_ddls and not dry_run:
            recreate_triggers(conn, trigger_ddls)
        after = conn.execute("SELECT COUNT(*) FROM rag_snapshots").fetchone()[0]
        conn.execute("PRAGMA synchronous=FULL")
        conn.commit()
        conn.close()
        logger.info(f"Janitor end — {after} snapshots restants")

    # ── R4 : VACUUM hors transaction ─────────────────────────────────────────
    if not dry_run:
        logger.info("R4 — VACUUM (hors transaction)...")
        conn2 = sqlite3.connect(str(path), timeout=1200)
        try:
            conn2.execute("VACUUM")
            results["vacuum_done"] = True
            size_mb = path.stat().st_size // 1024 // 1024
            logger.info(f"  -> VACUUM OK — DB : {size_mb}MB")
        except Exception as e:
            logger.error(f"VACUUM erreur : {e}")
        finally:
            conn2.close()

    return results


# ── Intégration agent_tasks / DIContainer ───────────────────────────────────


def trigger_db_maintenance(
    task_payload: dict | None = None,
    db_path: str | None = None,
) -> dict:
    """
    Point d'entrée sécurisé pour agents LLM (ring 0, SysAdmin_Operator).
    Valide les arguments JSON avant exécution.

    Payload attendu :
      {"dry_run": false, "retention_days": 90, "max_update_per_chunk": 3}
    """
    payload = task_payload or {}
    dry_run = bool(payload.get("dry_run", False))
    retention_days = int(payload.get("retention_days", 90))
    max_update_per_chunk = int(payload.get("max_update_per_chunk", 3))

    # Garde-fous : valeurs raisonnables
    assert 7 <= retention_days <= 365, "retention_days hors plage [7,365]"
    assert 1 <= max_update_per_chunk <= 10, "max_update_per_chunk hors plage [1,10]"

    return run_janitor(
        db_path=db_path,
        dry_run=dry_run,
        retention_days=retention_days,
        max_update_per_chunk=max_update_per_chunk,
    )


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    dry = "--dry-run" in sys.argv
    path = None
    for arg in sys.argv[1:]:
        if not arg.startswith("--"):
            path = arg
    result = run_janitor(db_path=path, dry_run=dry)
    print("\nRésultat :", result)
