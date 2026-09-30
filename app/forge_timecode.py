# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_060529_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: docstrings Args/Returns/Raises
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_timecode.py — Moteur Event Sourcing / Timecode pour Nokido
==================================================================
Implémente :
  1. Séquence monotone globale (résiliente aux collisions ms)
  2. Timecodes ISO8601+ms injectés dans chaque événement MCP
  3. Event Log (table event_log) — chronologie de toutes les actions
  4. Snapshots RAG (table rag_snapshots) — pour rollback temporel
  5. Vector Clock léger — détection de conflits multi-agents
  6. API rag_rollback — restaure l'état RAG à un instant T

USAGE :
    from forge_timecode import TimecodeEngine
    tc = TimecodeEngine()

    # Générer un timecode + enregistrer un événement
    seq, ts = tc.tick()
    tc.log_event(session_id="CLAUDE-01", agent_id="laforge",
                 event_type="write", target="app/Nokido.py",
                 payload={"lines": 6643}, session_state_hash="abc123")

    # Snapshot avant ingest RAG
    tc.snapshot_chunk(chunk_id="xxx", text="...", source="disco_k8s",
                      session_id="CLAUDE-01", op="insert")

    # Rollback : restaurer chunks avant un instant T
    restored = tc.rag_rollback(before="2026-03-14T04:00:00")

    # Timeline : événements d'une session
    events = tc.timeline(session_id="CLAUDE-01", limit=50)

    # Détection conflit : un chunk modifié par deux agents < delta_ms
    conflicts = tc.detect_conflicts(delta_ms=100)
"""


import hashlib
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

_ROOT_DIR = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT_DIR / "RAG" / "embeddings.db"

# Verrou global pour la séquence monotone (thread-safe)
_SEQ_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# HORODATAGE PARTAGÉ — source unique de la FORME des dates dans Nokido
#
# Mandat owner 2026-07-26 : tout organe qui a besoin d'un horodatage doit s'y
# inscrire via un système fiable. Mesure du jour : 229 journaux actifs, dont 8
# append-only SANS date par ligne — `loop_lag.log` (22,6 Mo) et `organ_pulse.log`
# (3,8 Mo) en tête, c'est-à-dire exactement le dump de stack et le journal
# d'alarme sur lesquels repose un post-mortem. Et 109 modules définissent chacun
# leur propre format. Un fait temporel ne se réfute que par un LOG : un journal
# sans date ne réfute rien, et une alarme sans date ne se place pas dans une
# chronologie.
#
# On ÉTEND ce module au lieu d'en créer un : il est déjà l'autorité des timecodes
# (séquence monotone + ISO8601 ms + event_log). Aucun nouvel organe.
#
# CONVENTION UNIQUE : UTC, ISO-8601, millisecondes, suffixe Z — même forme que
# `forge_lifecycle_audit` et que la table `event_log`. Le mélange UTC/local a
# imposé une conversion manuelle en pleine enquête aujourd'hui : une seule
# horloge, et le lecteur convertit s'il veut de l'heure locale.

LOG_FORMAT = "%(asctime)s.%(msecs)03dZ [%(levelname)s] %(name)s — %(message)s"
LOG_DATEFMT = "%Y-%m-%dT%H:%M:%S"


def now_iso() -> str:
    """Horodatage canonique Nokido : UTC, ISO-8601, millisecondes, suffixe Z."""
    return datetime.now(tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stamp_line(msg: str) -> str:
    """Préfixe une ligne de journal TEXTE.

    Pour les écrivains qui n'utilisent PAS `logging` mais un append direct —
    c'est le cas de la majorité des journaux non datés mesurés (loop_lag,
    organ_pulse, coagulation, owner_daemons, videur_identity).
    """
    return "%s %s" % (now_iso(), msg)


def stamp_row(row: dict) -> dict:
    """Injecte `ts` dans une ligne JSONL si elle n'en porte pas.

    Ne REMPLACE jamais un `ts` existant : on date ce qui n'est pas daté, on ne
    réécrit pas l'horodatage de quelqu'un d'autre — ce serait falsifier une
    chronologie au lieu de la compléter.
    """
    if not isinstance(row, dict):
        return row
    if not row.get("ts"):
        row = dict(row)
        row["ts"] = now_iso()
    return row


def configure_logging(logger=None, level: int = logging.INFO) -> None:
    """Applique la convention à un logger (ou au root). Idempotent.

    `converter = time.gmtime` est OBLIGATOIRE : sans lui, `asctime` rendrait de
    l'heure locale sous un suffixe `Z`, soit un horodatage qui MENT de deux
    heures. Un capteur qui ment est pire qu'un capteur muet.
    """
    lg = logger or logging.getLogger()
    fmt = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
    fmt.converter = time.gmtime
    for h in lg.handlers:
        h.setFormatter(fmt)
    if not lg.handlers:
        h = logging.StreamHandler()
        h.setFormatter(fmt)
        lg.addHandler(h)
    lg.setLevel(level)


# ─────────────────────────────────────────────────────────────────────────────


# Bases dont le schema est deja pose DANS CE PROCESSUS. Sans ce memo, chaque construction
# rejouait un CREATE sur embeddings.db (verrou d'ecriture) -- et tant que ce CREATE echouait
# sur un verrou tenu par un tiers, le singleton restait vide et CHAQUE appel le retentait
# (mesure 27/09 : 29 gels de la boucle du hub dans ce constructeur).
_SCHEMAS_OK: set[str] = set()


class TimecodeEngine:
    """
    Moteur de timecoding et d'Event Sourcing pour Nokido.
    Thread-safe, WAL SQLite.
    """

    def __init__(self, db_path: Path | str = _DB_PATH) -> None:
        """Initialise."""
        self.db_path = Path(db_path)
        if str(self.db_path) not in _SCHEMAS_OK:
            self._ensure_schema()
            _SCHEMAS_OK.add(str(self.db_path))

    # ── Connexion ─────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """conn."""
        con = sqlite3.connect(str(self.db_path), timeout=10)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self) -> None:
        """Garantit que les tables event_log / global_sequence / rag_snapshots existent."""
        con = self._conn()
        con.executescript("""
        CREATE TABLE IF NOT EXISTS event_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timecode    TEXT    NOT NULL,
            sequence_id INTEGER NOT NULL,
            session_id  TEXT    NOT NULL DEFAULT '',
            agent_id    TEXT    NOT NULL DEFAULT 'laforge',
            event_type  TEXT    NOT NULL,
            target      TEXT    NOT NULL DEFAULT '',
            payload     TEXT    NOT NULL DEFAULT '{}',
            prev_hash   TEXT    NOT NULL DEFAULT '',
            new_hash    TEXT    NOT NULL DEFAULT '',
            status      TEXT    NOT NULL DEFAULT 'ok'
        );
        CREATE INDEX IF NOT EXISTS idx_evlog_timecode  ON event_log(timecode);
        CREATE INDEX IF NOT EXISTS idx_evlog_seq       ON event_log(sequence_id);
        CREATE INDEX IF NOT EXISTS idx_evlog_session   ON event_log(session_id);
        CREATE INDEX IF NOT EXISTS idx_evlog_type      ON event_log(event_type);
        CREATE INDEX IF NOT EXISTS idx_evlog_target    ON event_log(target);

        CREATE TABLE IF NOT EXISTS global_sequence (
            id       INTEGER PRIMARY KEY,
            last_seq INTEGER NOT NULL DEFAULT 0,
            last_tick TEXT   NOT NULL DEFAULT ''
        );
        INSERT OR IGNORE INTO global_sequence(id, last_seq, last_tick)
            VALUES(1, 0, '');

        CREATE TABLE IF NOT EXISTS rag_snapshots (
            snap_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            timecode    TEXT    NOT NULL,
            session_id  TEXT    NOT NULL DEFAULT '',
            agent_id    TEXT    NOT NULL DEFAULT 'laforge',
            chunk_id    TEXT    NOT NULL,
            text        TEXT    NOT NULL,
            source      TEXT    NOT NULL DEFAULT '',
            domain      TEXT    NOT NULL DEFAULT 'general',
            meta        TEXT    NOT NULL DEFAULT '{}',
            op          TEXT    NOT NULL DEFAULT 'insert',
            sequence_id INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snap_timecode ON rag_snapshots(timecode);
        CREATE INDEX IF NOT EXISTS idx_snap_chunk    ON rag_snapshots(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_snap_session  ON rag_snapshots(session_id);
        CREATE INDEX IF NOT EXISTS idx_snap_seq      ON rag_snapshots(sequence_id);
        """)
        con.commit()
        con.close()

    # ── Séquence monotone ─────────────────────────────────────────────────────

    def tick(self) -> Tuple[int, str]:
        """
        Retourne (sequence_id, timecode_iso).
        sequence_id est STRICTEMENT monotone même si deux appels arrivent
        dans la même milliseconde.
        Thread-safe via _SEQ_LOCK.
        """
        with _SEQ_LOCK:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            con = self._conn()
            cur = con.execute("UPDATE global_sequence SET last_seq = last_seq + 1, last_tick = ? WHERE id = 1", (ts,))
            seq = con.execute("SELECT last_seq FROM global_sequence WHERE id=1").fetchone()[0]
            con.commit()
            con.close()
            return seq, ts

    # ── Hash d'état (Vector Clock léger) ─────────────────────────────────────

    @staticmethod
    def state_hash(data: Any) -> str:
        """Hash SHA1 court (12 chars) d'un objet sérialisable."""
        raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    # ── Event Log ─────────────────────────────────────────────────────────────

    def log_event(
        self,
        event_type: str,
        target: str = "",
        payload: Dict | None = None,
        session_id: str = "",
        agent_id: str = "laforge",
        prev_hash: str = "",
        new_hash: str = "",
        status: str = "ok",
    ) -> Tuple[int, str]:
        """
        Enregistre un événement dans event_log.
        Retourne (sequence_id, timecode).
        """
        seq, ts = self.tick()
        con = self._conn()
        con.execute(
            """INSERT INTO event_log
               (timecode, sequence_id, session_id, agent_id, event_type,
                target, payload, prev_hash, new_hash, status)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                ts,
                seq,
                session_id,
                agent_id,
                event_type,
                target,
                json.dumps(payload or {}, ensure_ascii=False),
                prev_hash,
                new_hash,
                status,
            ),
        )
        con.commit()
        con.close()
        return seq, ts

    # ── Snapshot RAG ──────────────────────────────────────────────────────────

    def snapshot_chunk(
        self,
        chunk_id: str,
        text: str,
        source: str = "",
        domain: str = "general",
        meta: Dict | None = None,
        session_id: str = "",
        agent_id: str = "laforge",
        op: str = "insert",  # insert | update | delete
    ) -> Tuple[int, str]:
        """
        Sauvegarde une version d'un chunk RAG avant modification.
        Retourne (sequence_id, timecode).
        """
        seq, ts = self.tick()
        con = self._conn()
        con.execute(
            """INSERT INTO rag_snapshots
               (timecode, session_id, agent_id, chunk_id, text, source,
                domain, meta, op, sequence_id)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                ts,
                session_id,
                agent_id,
                chunk_id,
                text,
                source,
                domain,
                json.dumps(meta or {}, ensure_ascii=False),
                op,
                seq,
            ),
        )
        con.commit()
        con.close()
        return seq, ts

    # ── Timeline ──────────────────────────────────────────────────────────────

    def timeline(
        self,
        session_id: str = "",
        event_type: str = "",
        target: str = "",
        after: str = "",
        before: str = "",
        limit: int = 100,
    ) -> List[Dict]:
        """
        Retourne les événements triés par sequence_id ASC.
        Tous les filtres sont optionnels.
        """
        con = self._conn()
        clauses, params = [], []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if target:
            clauses.append("target LIKE ?")
            params.append(f"%{target}%")
        if after:
            clauses.append("timecode >= ?")
            params.append(after)
        if before:
            clauses.append("timecode <= ?")
            params.append(before)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = con.execute(
            f"SELECT * FROM event_log {where} ORDER BY sequence_id ASC LIMIT ?", params + [limit]
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]

    # ── Rollback RAG ──────────────────────────────────────────────────────────

    def rag_rollback(
        self,
        before: str,
        session_id: str = "",
        dry_run: bool = False,
    ) -> Dict:
        """
        Restaure les chunks RAG dans rag_chunks à leur état AVANT `before`.
        Stratégie :
          - Pour chaque chunk modifié après `before`, retrouve le snapshot
            précédant `before` et réécrit le chunk.
          - Les chunks insérés après `before` sont supprimés.
          - `dry_run=True` : retourne le plan sans modifier la DB.

        Retourne un dict { "restored": N, "deleted": N, "plan": [...] }
        """
        con = self._conn()

        # Chunks modifiés APRÈS before (via rag_snapshots)
        rows = con.execute(
            """
            SELECT DISTINCT chunk_id, op FROM rag_snapshots
            WHERE timecode > ?
            ORDER BY sequence_id DESC
        """,
            (before,),
        ).fetchall()

        plan = []
        restored = 0
        deleted = 0

        for row in rows:
            cid, op = row["chunk_id"], row["op"]

            # Trouver le snapshot précédant `before` pour ce chunk
            prev = con.execute(
                """
                SELECT * FROM rag_snapshots
                WHERE chunk_id = ? AND timecode <= ?
                ORDER BY sequence_id DESC LIMIT 1
            """,
                (cid, before),
            ).fetchone()

            if prev:
                action = "restore"
                plan.append({"chunk_id": cid, "action": action, "to_timecode": prev["timecode"]})
                if not dry_run:
                    con.execute(
                        """
                        UPDATE rag_chunks SET
                            text       = ?,
                            source     = ?,
                            domain     = ?,
                            meta       = ?,
                            updated_at = ?
                        WHERE id = ?
                    """,
                        (prev["text"], prev["source"], prev["domain"], prev["meta"], before, cid),
                    )
                    restored += 1
            else:
                # Pas de version antérieure → chunk créé après before → supprimer
                action = "delete"
                plan.append({"chunk_id": cid, "action": action})
                if not dry_run:
                    con.execute("DELETE FROM rag_chunks WHERE id = ?", (cid,))
                    deleted += 1

        if not dry_run:
            con.commit()
            # Logger le rollback
            self.log_event(
                event_type="rag_rollback",
                target=f"before={before}",
                payload={"restored": restored, "deleted": deleted, "session_id": session_id, "dry_run": False},
                session_id=session_id,
            )

        con.close()
        return {"restored": restored, "deleted": deleted, "plan": plan, "dry_run": dry_run}

    # ── Détection de conflits (Vector Clock) ──────────────────────────────────

    def detect_conflicts(self, delta_ms: int = 200) -> List[Dict]:
        """
        Détecte les événements sur la même cible par deux agents différents
        dans une fenêtre de `delta_ms` millisecondes.
        Retourne la liste des conflits potentiels.
        """
        con = self._conn()
        # Stratégie : pour chaque paire d'événements sur le même target,
        # par agents différents, dans delta_ms
        rows = con.execute("""
            SELECT a.id as id_a, b.id as id_b,
                   a.target, a.agent_id as agent_a, b.agent_id as agent_b,
                   a.timecode as tc_a, b.timecode as tc_b,
                   a.sequence_id as seq_a, b.sequence_id as seq_b
            FROM event_log a
            JOIN event_log b ON a.target = b.target
                             AND a.agent_id != b.agent_id
                             AND b.sequence_id > a.sequence_id
                             AND b.sequence_id - a.sequence_id <= 5
            WHERE a.target != ''
            ORDER BY a.sequence_id DESC
            LIMIT 50
        """).fetchall()
        con.close()

        conflicts = []
        for r in rows:
            conflicts.append(
                {
                    "target": r["target"],
                    "agent_a": r["agent_a"],
                    "agent_b": r["agent_b"],
                    "tc_a": r["tc_a"],
                    "tc_b": r["tc_b"],
                    "seq_a": r["seq_a"],
                    "seq_b": r["seq_b"],
                    "delta_seq": r["seq_b"] - r["seq_a"],
                }
            )
        return conflicts

    # ── Stats ─────────────────────────────────────────────────────────────────

    def stats(self) -> Dict:
        """Retourne les statistiques du système de timecoding."""
        con = self._conn()
        seq = con.execute("SELECT last_seq, last_tick FROM global_sequence WHERE id=1").fetchone()
        n_events = con.execute("SELECT COUNT(*) FROM event_log").fetchone()[0]
        n_snapshots = con.execute("SELECT COUNT(*) FROM rag_snapshots").fetchone()[0]
        n_sessions = con.execute("SELECT COUNT(DISTINCT session_id) FROM event_log WHERE session_id != ''").fetchone()[
            0
        ]
        oldest = con.execute("SELECT MIN(timecode) FROM event_log").fetchone()[0]
        con.close()
        return {
            "global_sequence": seq["last_seq"] if seq else 0,
            "last_tick": seq["last_tick"] if seq else "",
            "n_events": n_events,
            "n_snapshots": n_snapshots,
            "n_sessions": n_sessions,
            "oldest_event": oldest or "",
        }


# ─────────────────────────────────────────────────────────────────────────────
# Singleton global (partagé dans le process Nokido)
# ─────────────────────────────────────────────────────────────────────────────

_engine: TimecodeEngine | None = None


# Context:


def get_timecode_engine() -> "TimecodeEngine":
    """Get timecode engine singleton instance."""
    global _engine
    if _engine is None:
        _engine = TimecodeEngine()
    return _engine


# ───────────────────────────────────────────────────────────────────────────────
# Conversion UTC → heure locale pour affichage
# ───────────────────────────────────────────────────────────────────────────────


def _get_tz_offset() -> int:
    """
    Retourne l'offset UTC→local en heures.
    Priorité :
      1. TZ_OFFSET dans Nokido.env (configurable)
      2. Offset système détecté automatiquement (datetime.now - utcnow)
      3. Fallback NTP via pool.ntp.org si dérive > 60s (tente 3 serveurs)
    """

    # 1. Nokido.env
    try:
        env_path = _ROOT_DIR / "Nokido.env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("TZ_OFFSET") and "=" in line:
                    return int(line.split("=", 1)[1].strip())
    except Exception:
        pass

    # 2. Détection système (Windows met à jour l'heure via W32tm)
    try:
        from datetime import datetime as _dt

        local_h = _dt.now().hour
        utc_h = _dt.utcnow().hour
        # Gérer le passage minuit
        diff = (local_h - utc_h + 24) % 24
        if diff > 12:
            diff -= 24
        return diff
    except Exception:
        pass

    return 1  # UTC+1 fallback (France, heure d'été/hiver détecté par le système)


def to_local(utc_iso: str, fmt: str = "%H:%M:%S") -> str:
    """
    Convertit un timecode UTC stocké en DB vers l'heure locale pour affichage.

    Args:
        utc_iso : timecode UTC (ex: '2026-03-15T14:21:08.123Z')
        fmt     : format de sortie strftime (défaut: HH:MM:SS)

    Returns:
        Heure locale formatée (ex: '15:21:08')

    Exemples :
        to_local('2026-03-15T14:21:08Z')          → '15:21:08'  (UTC+1)
        to_local('2026-03-15T14:21:08Z', '%H:%M') → '15:21'
        to_local('2026-03-15T14:21:08Z',
                  '%Y-%m-%d %H:%M:%S')             → '2026-03-15 15:21:08'
    """
    from datetime import datetime, timedelta

    if not utc_iso:
        return ""
    try:
        # Normaliser : retirer le 'Z' final, tronquer les microsecondes
        s = utc_iso.rstrip("Z").replace("+00:00", "")
        # Essayer ISO avec ms, puis sans
        for pattern in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                dt_utc = datetime.strptime(s[: len(pattern) + 2], pattern)
                break
            except ValueError:
                continue
        else:
            return utc_iso  # fallback : retourner tel quel
        dt_local = dt_utc + timedelta(hours=_get_tz_offset())
        return dt_local.strftime(fmt)
    except Exception:
        return utc_iso  # jamais d'exception — afficher tel quel si erreur


def to_local_full(utc_iso: str) -> str:
    """Raccourci : retourne la date+heure locale complète."""
    return to_local(utc_iso, "%Y-%m-%d %H:%M:%S")


def timecode_inject(payload: Dict, session_id: str = "", agent_id: str = "laforge") -> Dict:
    """
    Injecte timecode + sequence_id dans un payload MCP avant envoi.
    Usage dans nokido_mcp_server.py :
        args = timecode_inject(args, session_id=agent_id)
    """
    tc = get_timecode_engine()
    seq, ts = tc.tick()
    payload["timecode"] = ts
    payload["sequence_id"] = seq
    payload["session_id"] = session_id or payload.get("session_id", "")
    payload["agent_id"] = agent_id
    return payload
