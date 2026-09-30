"""
forge_jobid.py — Phase 2.2 JobID standardization
=================================================
"Hémoglobine" du Nokido. Chaque intention LLM = molécule de sang traçable
end-to-end via JobContext porté dans EventBus + agent_messages + tasks.

Format JobID : job_<8hex>_<unix_ts>_<agent_lower>
Exemple : job_a1b2c3d4_1777660000_claude

Author-Agent: CLAUDE
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:jobid|phase:2.2|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "RAG" / "embeddings.db"


def generate_job_id(agent: str, intent_type: str = "") -> str:
    """Génère un JobID unique : job_<8hex>_<ts>_<agent>.

    Args:
        agent: nom court agent (CLAUDE, GEMINI, EXEGOL, ...)
        intent_type: optionnel, ajouté en suffixe lisible (recon, refacto, ...)

    Returns:
        JobID string canonique
    """
    hex8 = secrets.token_hex(4)
    ts = int(time.time())
    agent_clean = (agent or "anon").lower().replace(" ", "_")[:16]
    job_id = f"job_{hex8}_{ts}_{agent_clean}"
    if intent_type:
        clean = intent_type.lower().replace(" ", "_")[:24]
        job_id = f"{job_id}_{clean}"
    return job_id


@dataclass
class JobContext:
    """Molécule de sang Nokido. Porte le contexte d'une intention end-to-end."""

    job_id: str
    agent: str
    intent_type: str = ""
    parent_id: Optional[str] = None
    trace_id: Optional[str] = None  # racine logique (= top-level job_id du flow)
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending|running|completed|failed|cancelled
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    error: Optional[str] = None
    result_summary: Optional[str] = None

    @classmethod
    def new(
        cls, agent: str, intent_type: str = "", payload: Optional[dict] = None, parent: Optional["JobContext"] = None
    ) -> "JobContext":
        """Crée un JobContext frais. Si parent fourni, propage trace_id."""
        jid = generate_job_id(agent, intent_type)
        trace_id = parent.trace_id if parent else jid
        return cls(
            job_id=jid,
            agent=agent,
            intent_type=intent_type,
            parent_id=parent.job_id if parent else None,
            trace_id=trace_id,
            payload=payload or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def mark_running(self) -> None:
        self.status = "running"
        self.updated_at = int(time.time())

    def mark_completed(self, result_summary: str = "") -> None:
        self.status = "completed"
        self.result_summary = result_summary[:500] if result_summary else None
        self.updated_at = int(time.time())

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = (error or "")[:500]
        self.updated_at = int(time.time())


def trace_link(parent_jobid: str, child_jobid: str, parent_trace_id: Optional[str] = None) -> Tuple[str, str]:
    """Établit le lien parent→enfant. Retourne (parent_id, trace_id).

    trace_id = racine logique du flow. Si pas fourni, parent_jobid devient la racine.
    """
    return (parent_jobid, parent_trace_id or parent_jobid)


def persist_job(ctx: JobContext, db_path: Optional[Path] = None) -> bool:
    """INSERT OR REPLACE dans table jobs_state. Crée la table si absente."""
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs_state (
                job_id TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                intent_type TEXT,
                parent_id TEXT,
                trace_id TEXT,
                payload_json TEXT,
                status TEXT NOT NULL,
                created_at INTEGER,
                updated_at INTEGER,
                error TEXT,
                result_summary TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_trace ON jobs_state(trace_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs_state(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_agent ON jobs_state(agent)")
        conn.execute(
            "INSERT OR REPLACE INTO jobs_state "
            "(job_id,agent,intent_type,parent_id,trace_id,payload_json,status,"
            "created_at,updated_at,error,result_summary) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                ctx.job_id,
                ctx.agent,
                ctx.intent_type,
                ctx.parent_id,
                ctx.trace_id,
                json.dumps(ctx.payload, ensure_ascii=False),
                ctx.status,
                ctx.created_at,
                ctx.updated_at,
                ctx.error,
                ctx.result_summary,
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def load_job(job_id: str, db_path: Optional[Path] = None) -> Optional[JobContext]:
    """Recharge un JobContext depuis SQLite."""
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT job_id,agent,intent_type,parent_id,trace_id,payload_json,status,"
            "created_at,updated_at,error,result_summary FROM jobs_state WHERE job_id=?",
            (job_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        return JobContext(
            job_id=row[0],
            agent=row[1],
            intent_type=row[2] or "",
            parent_id=row[3],
            trace_id=row[4],
            payload=json.loads(row[5]) if row[5] else {},
            status=row[6],
            created_at=row[7],
            updated_at=row[8],
            error=row[9],
            result_summary=row[10],
        )
    except Exception:
        return None


def get_trace(trace_id: str, db_path: Optional[Path] = None) -> list[JobContext]:
    """Retourne tous les JobContext partageant un trace_id (full flow)."""
    db = Path(db_path) if db_path else DEFAULT_DB
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT job_id,agent,intent_type,parent_id,trace_id,payload_json,status,"
            "created_at,updated_at,error,result_summary FROM jobs_state "
            "WHERE trace_id=? ORDER BY created_at",
            (trace_id,),
        ).fetchall()
        conn.close()
        return [
            JobContext(
                job_id=r[0],
                agent=r[1],
                intent_type=r[2] or "",
                parent_id=r[3],
                trace_id=r[4],
                payload=json.loads(r[5]) if r[5] else {},
                status=r[6],
                created_at=r[7],
                updated_at=r[8],
                error=r[9],
                result_summary=r[10],
            )
            for r in rows
        ]
    except Exception:
        return []
