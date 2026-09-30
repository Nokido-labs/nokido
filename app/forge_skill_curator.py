"""
forge_skill_curator.py — Curation autonome de skills depuis execution_traces
=============================================================================

Carve-out hermes-agent (cf [[research-hermes-agent]]) : extraction
auto de skills depuis trajectoires self-play réussies + boucle
grader/pruner/consolidator. Complète forge_skill_enricher
(qui couvre rag_chunks lesson_* humain) en ouvrant le canal
machine = execution_traces.db (13k+ transitions MPC self-play).

PIPELINE
========
1. Extractor     : scan traces success=1, cluster par (task_type, action.type)
2. Grader        : score = success_rate · log(uses+1)/log_norm · ema_recency
3. Pruner        : drop si score<MIN_SCORE OU uses<MIN_USES OU rate<MIN_RATE
4. Consolidator  : upsert rag_chunks id='skill_<sha8>' domain='curated_skills'

OUTPUT
======
rag_chunks domain='curated_skills' (relisible par MPC/Actor planification).
ancrage anchor_solution() audit trail.

USAGE
=====
    LAFORGE_PYTHON app/forge_skill_curator.py --once
    LAFORGE_PYTHON app/forge_skill_curator.py --daemon --interval 21600

NSSM : service NokidoSkillCurator (cf services.toml wave 4).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import signal
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[role:skill_curator|phase:6|color:GREEN]"

ROOT = Path(__file__).resolve().parent.parent
TRACES_DB = ROOT / "RAG" / "execution_traces.db"
RAG_DB = ROOT / "RAG" / "embeddings.db"
SANDBOX = ROOT / "sandbox"
STATE_FILE = SANDBOX / "skill_curator_state.json"
HEARTBEAT = SANDBOX / "skill_curator.heartbeat"
PIDFILE = SANDBOX / "skill_curator.pid"

DEFAULT_INTERVAL_S = int(os.environ.get("LAFORGE_SKILL_CURATOR_INTERVAL_S", "21600"))  # 6h

# Le pouls vient du COEUR (`forge_cardiac_node`) via l'organe du battement. Sans lui,
# cet organe ne battait qu'une fois par cycle de 6 h pour un seuil de 3600 s : il
# etait relance CHAQUE HEURE et n'achevait jamais une attente (13 relances
# « heartbeat stale » au journal du superviseur).
from nokido_agent.app.forge_heartbeat import Cadence
MIN_USES = int(os.environ.get("LAFORGE_SKILL_CURATOR_MIN_USES", "3"))
MIN_RATE = float(os.environ.get("LAFORGE_SKILL_CURATOR_MIN_RATE", "0.60"))
MIN_SCORE = float(os.environ.get("LAFORGE_SKILL_CURATOR_MIN_SCORE", "0.10"))
RECENCY_TAU_S = float(os.environ.get("LAFORGE_SKILL_CURATOR_TAU_S", str(7 * 86400)))  # 7j

_SHUTDOWN = False


# ── Dataclass skill ─────────────────────────────────────────────────────────


@dataclass
class CuratedSkill:
    skill_id: str
    task_type: str
    action_type: str
    uses: int
    successes: int
    success_rate: float
    avg_cost_delta: float
    last_ts: float
    score: float = 0.0
    description: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        return f"skill_{self.skill_id}"


# ── Extractor ───────────────────────────────────────────────────────────────


def extract_skills(traces_db: Optional[Path] = None) -> list[CuratedSkill]:
    """Scan traces, cluster par (task_type, action.type)."""
    traces_db = traces_db if traces_db is not None else TRACES_DB
    if not traces_db.exists():
        return []
    conn = sqlite3.connect(str(traces_db), timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT ts, action_json, task_type, cost_before, cost_after, success FROM traces WHERE action_json IS NOT NULL"
    ).fetchall()
    conn.close()

    buckets: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "uses": 0,
            "successes": 0,
            "sum_delta": 0.0,
            "last_ts": 0.0,
            "state_samples": [],
        }
    )

    for r in rows:
        try:
            action = json.loads(r["action_json"])
        except Exception:
            continue
        atype = str(action.get("type", "unknown"))[:80]
        ttype = str(r["task_type"] or "unknown")[:80]
        key = (ttype, atype)
        b = buckets[key]
        b["uses"] += 1
        if r["success"]:
            b["successes"] += 1
        if r["cost_before"] is not None and r["cost_after"] is not None:
            b["sum_delta"] += r["cost_after"] - r["cost_before"]
        if r["ts"] and r["ts"] > b["last_ts"]:
            b["last_ts"] = r["ts"]
        if len(b["state_samples"]) < 3:
            st = action.get("state_text") or action.get("desc") or ""
            if st:
                b["state_samples"].append(str(st)[:100])

    skills: list[CuratedSkill] = []
    for (ttype, atype), b in buckets.items():
        if b["uses"] == 0:
            continue
        rate = b["successes"] / b["uses"]
        avg_delta = b["sum_delta"] / b["uses"]
        sid = hashlib.sha256(f"{ttype}|{atype}".encode()).hexdigest()[:8]
        desc = (
            f"When task={ttype} and action.type={atype}: succeeds {rate:.0%} "
            f"over {b['uses']} attempts, avg cost delta {avg_delta:+.4f}."
        )
        if b["state_samples"]:
            desc += " States: " + " | ".join(b["state_samples"])
        skills.append(
            CuratedSkill(
                skill_id=sid,
                task_type=ttype,
                action_type=atype,
                uses=b["uses"],
                successes=b["successes"],
                success_rate=rate,
                avg_cost_delta=avg_delta,
                last_ts=b["last_ts"],
                description=desc,
            )
        )
    return skills


# ── Grader ──────────────────────────────────────────────────────────────────


def grade(skills: list[CuratedSkill], now: float | None = None, tau: float = RECENCY_TAU_S) -> None:
    """Pose `score` in-place. Score = rate · log(uses+1)/log_norm · ema_recency."""
    if not skills:
        return
    now = now or time.time()
    max_uses = max(s.uses for s in skills)
    log_norm = math.log(max_uses + 1) if max_uses > 0 else 1.0
    for s in skills:
        freq = math.log(s.uses + 1) / log_norm if log_norm > 0 else 0.0
        elapsed = max(0.0, now - s.last_ts) if s.last_ts > 0 else tau
        recency = math.exp(-elapsed / tau)
        cost_bonus = 0.1 if s.avg_cost_delta < 0 else 0.0  # action ameliorante
        s.score = round(s.success_rate * freq * recency + cost_bonus, 4)


# ── Pruner ──────────────────────────────────────────────────────────────────


def prune(
    skills: list[CuratedSkill], min_uses: int = MIN_USES, min_rate: float = MIN_RATE, min_score: float = MIN_SCORE
) -> tuple[list[CuratedSkill], list[CuratedSkill]]:
    """Sépare keep vs drop."""
    # skill_promotion_review (p53) : succes statistiquement significatif (Wilson lower),
    # pas le raw success_rate gameable (2/2=100% sur trivial -> rejete). Fail-open.
    try:
        from nokido_agent.tools.forge_oncoguard import review_skill as _review
    except Exception:
        _review = None
    keep, drop = [], []
    for s in skills:
        _sig_ko = False
        if _review is not None:
            _sig_ko = not _review(s.uses, round(s.uses * s.success_rate))["promote"]
        if s.uses < min_uses or s.success_rate < min_rate or s.score < min_score or _sig_ko:
            if _sig_ko:
                try:
                    from nokido_agent.tools.forge_alignment_trace import emit as _atrace
                    _atrace("skill_curator", "skill_promotion_review", "drop", "skill",
                            f"{s.success_rate:.0%}@{s.uses} non significatif (Wilson)")
                except Exception:
                    pass
            drop.append(s)
        else:
            keep.append(s)
    return keep, drop


# ── Consolidator ────────────────────────────────────────────────────────────

_CHUNK_SCHEMA_CHECKED = False


def _ensure_rag_schema(conn: sqlite3.Connection) -> None:
    global _CHUNK_SCHEMA_CHECKED
    if _CHUNK_SCHEMA_CHECKED:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)").fetchall()}
    if "id" not in cols or "text" not in cols:
        raise RuntimeError("rag_chunks schema unexpected (id, text required)")
    _CHUNK_SCHEMA_CHECKED = True


def consolidate(skills: list[CuratedSkill], rag_db: Optional[Path] = None) -> int:
    """Upsert skills dans rag_chunks domain='curated_skills'. Retourne n écrits."""
    if not skills:
        return 0
    rag_db = rag_db if rag_db is not None else RAG_DB
    if not rag_db.exists():
        return 0
    conn = sqlite3.connect(str(rag_db), timeout=15)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        _ensure_rag_schema(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)").fetchall()}
        # Colonnes minimales communes vues dans le code Nokido :
        #   id TEXT PK, source TEXT, text TEXT, domain TEXT, meta TEXT, ingested_at TEXT
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
        n = 0
        for s in skills:
            meta = json.dumps(
                {
                    "skill_id": s.skill_id,
                    "task_type": s.task_type,
                    "action_type": s.action_type,
                    "uses": s.uses,
                    "successes": s.successes,
                    "success_rate": round(s.success_rate, 4),
                    "avg_cost_delta": round(s.avg_cost_delta, 4),
                    "score": s.score,
                    "last_ts": s.last_ts,
                    "curator_version": 1,
                },
                ensure_ascii=False,
            )
            payload = {
                "id": s.chunk_id,
                "source": "skill_curator",
                "text": s.description,
                "domain": "curated_skills",
                "meta": meta,
                "ingested_at": now_iso,
            }
            keys = [k for k in payload if k in cols]
            placeholders = ",".join("?" for _ in keys)
            assigns = ",".join(f"{k}=excluded.{k}" for k in keys if k != "id")
            sql = (
                f"INSERT INTO rag_chunks ({','.join(keys)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {assigns}"
            )
            conn.execute(sql, [payload[k] for k in keys])
            n += 1
        conn.commit()
        # FTS sync (best-effort, table optionnelle)
        try:
            for s in skills:
                conn.execute(
                    # `chunk_id` manquait : cle NULL, ligne inatteignable par jointure.
                    "INSERT OR REPLACE INTO rag_fts(rowid, chunk_id, source, text, domain) "
                    "SELECT rowid, id, source, text, domain FROM rag_chunks WHERE id=?",
                    (s.chunk_id,),
                )
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()
    return n


# ── Audit ───────────────────────────────────────────────────────────────────


def _anchor(stats: dict) -> None:
    try:
        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_self_correction import anchor_solution  # type: ignore

        anchor_solution(
            problem="Curation skills depuis execution_traces",
            solution=(
                f"Curator cycle: extracted={stats.get('extracted')} "
                f"kept={stats.get('kept')} pruned={stats.get('pruned')} "
                f"persisted={stats.get('persisted')}"
            ),
            example="LAFORGE_PYTHON app/forge_skill_curator.py --once",
            domain="ami",
        )
    except Exception:
        pass


# ── Cycle ───────────────────────────────────────────────────────────────────


def run_cycle() -> dict:
    """1 cycle complet : extract → grade → prune → consolidate."""
    t0 = time.time()
    skills = extract_skills()
    grade(skills)
    keep, drop = prune(skills)
    keep.sort(key=lambda s: -s.score)
    persisted = consolidate(keep)
    stats = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(time.time() - t0, 2),
        "extracted": len(skills),
        "kept": len(keep),
        "pruned": len(drop),
        "persisted": persisted,
        "top": [
            {
                "skill_id": s.skill_id,
                "task": s.task_type,
                "action": s.action_type,
                "uses": s.uses,
                "rate": round(s.success_rate, 3),
                "score": s.score,
            }
            for s in keep[:10]
        ],
    }
    _anchor(stats)
    return stats


# ── Daemon plumbing ─────────────────────────────────────────────────────────


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"last_run_ts": 0, "cycles": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_run_ts": 0, "cycles": 0}


def _save_state(state: dict) -> None:
    SANDBOX.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _pid_alive_win(pid: int) -> bool:
    if os.name != "nt":
        return False
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        exit_code = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and exit_code.value == 259
    except Exception:
        return False


def _acquire_pidfile() -> bool:
    pid = os.getpid()
    if PIDFILE.exists():
        try:
            old = int(PIDFILE.read_text().strip())
            if old != pid and _pid_alive_win(old):
                return False
        except Exception:
            pass
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(pid))
    return True


def _on_signal(signum, frame):
    global _SHUTDOWN
    _SHUTDOWN = True
    try:
        if PIDFILE.exists() and int(PIDFILE.read_text().strip()) == os.getpid():
            PIDFILE.unlink()
    except Exception:
        pass


def main() -> int:
    global MIN_USES, MIN_RATE, MIN_SCORE
    ap = argparse.ArgumentParser(description="Nokido skill curator daemon")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    ap.add_argument("--min-uses", type=int, default=MIN_USES)
    ap.add_argument("--min-rate", type=float, default=MIN_RATE)
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    ap.add_argument("--dry-run", action="store_true", help="extract+grade+prune sans écrire rag_chunks")
    args = ap.parse_args()

    if not args.once and not args.daemon:
        ap.error("--once ou --daemon requis")

    MIN_USES = args.min_uses
    MIN_RATE = args.min_rate
    MIN_SCORE = args.min_score

    if args.daemon and not _acquire_pidfile():
        print("[skill_curator] another instance running, exit", flush=True)
        return 0

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    state = _load_state()

    # PAS de battement de demarrage : la doctrine de `beat_daemon` (2026-07-28) l'interdit
    # explicitement — « jamais au demarrage : le pouls doit attester du TRAVAIL, pas de la
    # simple existence ». Celui que j'avais ajoute ce matin la violait pour contourner un
    # cycle trop long ; le rythme du coeur rend le contournement inutile, puisque le pouls
    # arrive maintenant toutes les ~30 s sans attendre la fin d'un cycle de 6 h.
    cad = Cadence("skill_curator", cycle_s=args.interval)

    def cycle():
        if args.dry_run:
            sk = extract_skills()
            grade(sk)
            keep, drop = prune(sk)
            stats = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "extracted": len(sk),
                "kept": len(keep),
                "pruned": len(drop),
                "persisted": 0,
                "top": [],
            }
            return stats
        return run_cycle()

    while True:
        try:
            stats = cycle()
        except Exception as e:
            stats = {"error": f"{type(e).__name__}: {str(e)[:200]}", "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        print(
            f"[skill_curator] {stats.get('ts')} "
            f"extracted={stats.get('extracted')} kept={stats.get('kept')} "
            f"pruned={stats.get('pruned')} persisted={stats.get('persisted')} "
            f"err={stats.get('error', '')}",
            flush=True,
        )
        for top in stats.get("top", [])[:5]:
            print(
                f"   • [{top['score']}] {top['task']}/{top['action']} uses={top['uses']} rate={top['rate']}", flush=True
            )

        state["last_run_ts"] = time.time()
        state["cycles"] = state.get("cycles", 0) + 1
        _save_state(state)
        cad.cycle_termine(ok="error" not in stats, extracted=stats.get("extracted"),
                          kept=stats.get("kept"), pruned=stats.get("pruned"))

        if args.once or _SHUTDOWN:
            break
        # On attend en battant au rythme du coeur. `stop` preserve la reactivite a
        # l'arret : sans lui, un SIGTERM attendrait la fin du battement en cours.
        while not _SHUTDOWN and not cad.tour():
            cad.dormir(stop=lambda: _SHUTDOWN)

    try:
        if PIDFILE.exists() and int(PIDFILE.read_text().strip()) == os.getpid():
            PIDFILE.unlink()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
