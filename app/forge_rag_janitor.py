# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_rag_janitor
#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: RAG Cleaning & Noise Reduction
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import os
import sqlite3
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger("Nokido.RAG.Janitor")

# Patterns de pollution sémantique à ignorer
EXCLUDE_PATTERNS = [
    "*.bak",
    "*.tmp",
    "*.log",
    "__pycache__",
    ".git",
    ".versions",
    ".ruff_cache",
    ".ipynb_checkpoints",
    "node_modules",
    "venv",
    "env",
    "backups",
    "old_version",
    "copy",
]


class RAGJanitor:
    """Concierge du RAG : nettoie, filtre et optimise la base de connaissance."""

    def __init__(self, db_path: str = "rag/embeddings.db"):
        self.db_path = Path(db_path)

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def clean_orphans(self) -> int:
        """Supprime les chunks dont la source n'existe plus sur le disque."""
        conn = self._get_conn()
        cursor = conn.cursor()

        # On récupère toutes les sources de type 'file'
        # Forme GLOB **exactement** equivalente, et non un simple `GLOB 'file:*'` :
        # mesure 2026-09-04, `LIKE 'file:%'` rend 13 sources et elles sont TOUTES en
        # majuscules (`FILE: contrib/...`) -- aucune source `file:` minuscule
        # n'existe. Un GLOB minuscule seul aurait donc silencieusement vide cet
        # inventaire, et ce cursor alimente une suppression : on preserve le
        # perimetre a l'identique tout en rendant la requete indexable.
        cursor.execute(
            "SELECT DISTINCT source FROM rag_chunks "
            "WHERE source GLOB 'file:*' OR source GLOB 'FILE:*'"
        )
        sources = cursor.fetchall()

        removed = 0
        for (src_str,) in sources:
            file_path = src_str.replace("file:", "")
            if not Path(file_path).exists():
                logger.info(f"[Janitor] Source disparue détectée : {file_path}")
                # Anciens textes lus AVANT la suppression : purge FTS par MATCH
                # (forge_db_path.purger_fts). `DELETE FROM rag_fts WHERE source=?`
                # balayait tout l'index lexical (source UNINDEXED) sous verrou, une
                # fois par source disparue (2026-09-27).
                try:
                    from nokido_agent.app.forge_db_path import purger_fts
                except ImportError:  # lance par chemin : app/ est sys.path[0]
                    from forge_db_path import purger_fts
                anciens = cursor.execute(
                    "SELECT id, text FROM rag_chunks WHERE source = ?", (src_str,)).fetchall()
                n_fts, laissees = purger_fts(conn, anciens)
                if laissees:
                    logger.warning(f"[Janitor] {len(laissees)} ligne(s) FTS laissee(s) a "
                                   "purge_rag_fts_fantomes (texte sans mot exploitable)")
                cursor.execute("DELETE FROM rag_chunks WHERE source = ?", (src_str,))
                removed += n_fts

        conn.commit()
        conn.close()
        return removed

    def purge_old_logs(self, days: int = 7) -> int:
        """Purge les messages de session et logs plus vieux que N jours."""
        conn = self._get_conn()
        cursor = conn.cursor()

        limit_date = (datetime.now() - timedelta(days=days)).isoformat()

        # GLOB : verifie 2026-09-04, 827 sources des deux cotes, aucune perte.
        cursor.execute("DELETE FROM rag_chunks WHERE ingested_at < ? AND source GLOB 'session:*'", (limit_date,))
        removed = cursor.rowcount

        conn.commit()
        conn.close()
        return removed

    def purge_old_snapshots(self, keep: int = 50000) -> int:
        """Cap le journal d'undo rag_snapshots (incident V: 2026-07-06: 10.6M lignes
        = 90% du bloat DB). Garde les `keep` snapshots les plus recents (snap_id
        monotone), supprime le reste, puis checkpoint WAL TRUNCATE pour rendre
        l'espace disque. Idempotent, borne la croissance sans supprimer l'undo recent."""
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            # Garde les `keep` snapshots les plus recents PAR ORDRE (snap_id DESC),
            # robuste aux snap_id epars (le compteur autoincrement grimpe apres une
            # purge massive => 'max_id - keep' sur-supprimerait). NOT IN (top-keep).
            cur.execute(
                "DELETE FROM rag_snapshots WHERE snap_id NOT IN "
                "(SELECT snap_id FROM rag_snapshots ORDER BY snap_id DESC LIMIT ?)",
                (keep,),
            )
            removed = cur.rowcount
            conn.commit()
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            return removed
        finally:
            conn.close()

    def get_noise_report(self) -> dict:
        """Analyse le workspace pour identifier le volume de 'bruit'."""
        report = {"total_files": 0, "noise_files": 0, "noise_extensions": {}}
        root = Path(".")

        for p in root.rglob("*"):
            if p.is_file():
                report["total_files"] += 1
                if any(p.match(pat) for pat in EXCLUDE_PATTERNS) or p.suffix in (".bak", ".tmp"):
                    report["noise_files"] += 1
                    report["noise_extensions"][p.suffix] = report["noise_extensions"].get(p.suffix, 0) + 1

        return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    janitor = RAGJanitor()
    print("🧹 [Janitor] Démarrage du nettoyage...")

    orphans = janitor.clean_orphans()
    print(f"✅ Chunks orphelins supprimés : {orphans}")

    old_msgs = janitor.purge_old_logs(days=3)
    print(f"✅ Messages de session anciens purgés : {old_msgs}")

    noise = janitor.get_noise_report()
    print(f"📊 Rapport de bruit : {noise['noise_files']} fichiers polluants identifiés sur {noise['total_files']}.")
