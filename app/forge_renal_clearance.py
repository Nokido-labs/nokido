"""Purge les fichiers .bak de plus de 7 jours, mesure les chunks RAG en double et
compacte RAG/embeddings.db par VACUUM (forcé, ou si WAL > 50 Mo ou base > 500 Mo).

Entrées : run_cycle (dry_run, do_vacuum, dedup_chunks), filter_table avec
FiltrationRule / FiltrationResult (DELETE des lignes plus vieilles qu'un âge), et
les classes RenalClearance (purge_obsolete_bak, deduplicate_rag) et CognitiveServing.
Utilisé par forge_homeostasis_orchestrator.py (run_cycle) et
forge_pluripotent_workers.py (filter_table, FiltrationRule, _conn).
Effets : unlink des *.bak sous la racine du dépôt ; deduplicate_rag lit rag_chunks en
lecture seule sans rien supprimer ; exécuté en script, applique purge et VACUUM.
"""
import sqlite3
import os
import time
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
_HUB_DB = _ROOT / "RAG" / "embeddings.db"


def _conn(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or _HUB_DB
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class FiltrationRule:
    table: str
    age_column: str
    max_age_days: int
    protect_where: str = ""


@dataclass
class FiltrationResult:
    table: str
    deleted: int
    dry_run: bool


def filter_table(conn: sqlite3.Connection, rule: FiltrationRule, dry_run: bool = True) -> FiltrationResult:
    cutoff = (datetime.now() - timedelta(days=rule.max_age_days)).isoformat()
    protect = f"AND NOT ({rule.protect_where})" if rule.protect_where else ""
    sql = f"DELETE FROM {rule.table} WHERE {rule.age_column} < ? {protect}"
    count = 0
    if not dry_run:
        try:
            cur = conn.execute(sql, (cutoff,))
            count = cur.rowcount
            conn.commit()
        except sqlite3.Error as exc:
            # Sans ce message, un DELETE qui echoue rend `deleted=0`, soit
            # exactement ce que rend « rien a supprimer ». Le rollback evite en
            # plus de laisser la transaction ouverte sur le verrou.
            try:
                conn.rollback()
            except sqlite3.Error:  # muet-ok : rollback d'une connexion deja morte
                pass
            print(f"[renal] filtration {rule.table} ECHOUEE : {exc}")
            count = 0
    return FiltrationResult(table=rule.table, deleted=count, dry_run=dry_run)


def run_cycle(dry_run: bool = True, do_vacuum: bool = False, dedup_chunks: bool = False) -> dict:
    """
    Point d'entrée pour l'orchestrateur homéostatique.
    Auto-compact trigger : Si la taille du WAL dépasse 100MB ou si la DB est très fragmentée, force un VACUUM.
    """
    renal = RenalClearance()
    # `chunks_redondants_mesures` et non `chunks_deduped` : rien n'est supprimé
    # ici. -1 signale une mesure ILLISIBLE, à ne pas confondre avec 0.
    res = {
        "bak_purged": 0,
        "chunks_redondants_mesures": 0,
        "vacuumed": False,
        "dry_run": dry_run,
    }

    # Purge des .bak
    if not dry_run:
        res["bak_purged"] = renal.purge_obsolete_bak()

    # Mesure de redondance (la suppression est un acte séparé et gouverné :
    # tools/forge_rag_dedup_hash.py). Lecture seule, donc plus conditionnée à
    # `dry_run` — mesurer ne modifie rien.
    if dedup_chunks:
        res["chunks_redondants_mesures"] = renal.deduplicate_rag()

    # Auto-compact trigger (VACUUM)
    db_path = renal.db_path
    wal_path = db_path.with_suffix(".db-wal")

    should_vacuum = do_vacuum
    if not should_vacuum and not dry_run and db_path.exists():
        # Heuristique d'auto-compact: WAL > 50MB ou DB > 500MB
        try:
            wal_size_mb = wal_path.stat().st_size / (1024 * 1024) if wal_path.exists() else 0
            db_size_mb = db_path.stat().st_size / (1024 * 1024)
            if wal_size_mb > 50 or db_size_mb > 500:
                should_vacuum = True
        except OSError as exc:
            # Silencieux, ce chemin desarme l'auto-compact : `should_vacuum`
            # reste False et un WAL demesure passe inapercu. On le DIT, et on
            # le trace dans le resultat pour que l'appelant sache que le seuil
            # n'a pas pu etre evalue -- pas qu'il n'a pas ete atteint.
            res["auto_compact_indecidable"] = str(exc)
            print(f"[renal] taille DB/WAL illisible, auto-compact non evalue : {exc}")

    if should_vacuum and not dry_run:
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("VACUUM;")
            conn.commit()
            conn.close()
            res["vacuumed"] = True
            print(f"🗜️ Auto-compact trigger : Base SQLite {db_path.name} compactée.")
        except Exception as e:
            res["vacuum_error"] = str(e)

    return res


class RenalClearance:
    """
    Système de nettoyage et de purification des données (Lutte contre l'entropie).
    """

    def __init__(self, db_path=None):
        if db_path is None:
            root = Path(__file__).resolve().parent.parent
            db_path = root / "RAG" / "embeddings.db"
        self.db_path = Path(db_path)

    def purge_obsolete_bak(self, workspace_root=None):
        """Supprime les fichiers .bak de plus de 7 jours."""
        if workspace_root is None:
            workspace_root = Path(__file__).resolve().parent.parent
        root = Path(workspace_root)
        count = 0
        echecs: list[str] = []
        now = time.time()
        for bak_file in root.rglob("*.bak"):
            try:
                age = now - bak_file.stat().st_mtime
            except OSError as exc:
                # Le fichier a disparu ou reste illisible entre le parcours et
                # le stat : non lu n'est pas non concerne.
                echecs.append(f"{bak_file.name} (stat: {exc.__class__.__name__})")
                continue
            if age > 7 * 86400:
                try:
                    bak_file.unlink()
                    count += 1
                except OSError as exc:
                    # Un .bak verrouille non compte fait surestimer la proprete
                    # du disque : on nomme le fichier qui resiste.
                    echecs.append(f"{bak_file.name} ({exc.__class__.__name__})")
        if count > 0:
            print(f"🧹 Clairance : {count} fichiers .bak obsolètes supprimés.")
        if echecs:
            print(
                f"🧹 Clairance : {len(echecs)} .bak NON supprimés "
                f"(retenus/vus = {count}/{count + len(echecs)}) : {echecs[:5]}"
            )
        return count

    def deduplicate_rag(self):
        """MESURE les chunks RAG redondants. NE SUPPRIME RIEN.

        La suppression appartient au seul chemin gouverné,
        `tools/forge_rag_dedup_hash.py` : il ARCHIVE dans
        `rag_chunks_dedup_archive` avant de supprimer, nettoie les DEUX tables
        FTS, agrège les `access_count` du groupe sur l'exemplaire gardé, et sait
        restaurer. Il tourne en dry-run par défaut.

        L'ancien corps faisait ici un `DELETE ... GROUP BY text` nu, appelé par
        la boucle d'homéostasie. Quatre défauts, chacun mesuré le 2026-08-30 :
          1. aucune archive — contre la doctrine « rien n'est supprimé en base » ;
          2. `rag_fts` / `rag_chunks_fts` laissées intactes, donc des lignes FTS
             orphelines servant le texte d'un chunk disparu. Le lexical PRIME
             dans ce système : il ne doit jamais devenir un cache périmé ;
          3. `sqlite3.connect()` nu pour écrire = transaction implicite tenant le
             verrou pendant tout le DELETE (`database is locked` chez le voisin),
             là où `forge_db_path.open_writer()` existe pour ça ;
          4. `except Exception: return 0` — un verrou pris rendait le même 0 que
             « rien à dédoublonner ». Un chemin d'erreur muet.

        Rend le nombre de chunks en trop, ou **-1 si la mesure est ILLISIBLE**
        (base absente, verrou) : trois états, jamais deux. La lecture se fait en
        `mode=ro`, donc sans prendre le moindre verrou d'écriture.
        """
        if not self.db_path.exists():
            return -1

        try:
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro", uri=True, timeout=10.0
            )
            try:
                row = conn.execute(
                    "SELECT COUNT(*) - COUNT(DISTINCT text) FROM rag_chunks"
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            print(f"🧬 Clairance RAG : mesure ILLISIBLE ({exc}) — aucun verdict.")
            return -1

        en_trop = int(row[0]) if row and row[0] is not None else 0
        if en_trop > 0:
            print(
                f"🧬 Clairance RAG : {en_trop} chunks redondants MESURÉS "
                "(suppression = tools/forge_rag_dedup_hash.py --apply)"
            )
        return en_trop

    def score_relevance(self):
        """
        Baisse le poids des connaissances qui n'ont pas été activées depuis longtemps.
        (Concept de 'Fading Memory').
        """
        # À implémenter avec une colonne 'last_accessed' dans la DB
        pass


class CognitiveServing:
    """
    Optimise la livraison de la connaissance au modèle.
    """

    def filter_context(self, context_chunks, persona_name):
        """
        Filtre le contexte pour qu'il soit 'Digestible' et pertinent pour le Persona.
        """
        # Ne garde que ce qui est cohérent avec le rôle du persona
        # (Ex: Supprimer le code si on est en mode 'Report')
        filtered = [c for c in context_chunks if len(c) < 1000]  # Évite les pavés indigestes
        return filtered[:5]  # Top 5 ultra-pertinent uniquement


if __name__ == "__main__":
    res = run_cycle(dry_run=False, do_vacuum=True, dedup_chunks=True)
    print(f"✨ Le système est purifié : {res}")
