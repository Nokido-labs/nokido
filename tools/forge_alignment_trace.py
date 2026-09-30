"""forge_alignment_trace — P1 du homeostat axiologique : observabilite des flux
internes auto-generes (service mesh d'alignement, le CAPTEUR).

emit() trace les DECLENCHEMENTS d'invariants (qui tente quoi sur quel juge,
accepte/refuse, par quel invariant) -> le regulateur (P3) y detecte
collusion/tampering/confabulation. Reutilise la DB RAG/execution_traces.db
(table dediee alignment_events). 0 dep externe. Fail-open (jamais bloquant).

Selftest : LAFORGE_PYTHON tools/forge_alignment_trace.py
"""
from __future__ import annotations
import time
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DB = _ROOT / "RAG" / "execution_traces.db"

_DDL = (
    "CREATE TABLE IF NOT EXISTS alignment_events ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor TEXT, invariant TEXT, "
    "verdict TEXT, target TEXT, reason TEXT)"
)


def _conn():
    c = sqlite3.connect(str(_DB), timeout=5)
    c.execute(_DDL)
    try:
        c.execute("ALTER TABLE alignment_events ADD COLUMN meta TEXT")
        c.commit()
    except sqlite3.OperationalError:
        pass
    return c


_MAX_ROWS = 50000
_emit_count = 0
_emit_fail = 0  # F6 : compteur d'echecs d'emit (capteur fail-open -> angle mort si >0)


def _purge(max_rows: int = _MAX_ROWS) -> None:
    """Borne la table (anti-croissance illimitee, warn gate). Garde les max_rows derniers."""
    try:
        c = _conn()
        c.execute("DELETE FROM alignment_events WHERE id NOT IN "
                  "(SELECT id FROM alignment_events ORDER BY id DESC LIMIT ?)", (max_rows,))
        c.commit()
        c.close()
    except Exception:
        pass


def emit(actor: str, invariant: str, verdict: str, target: str = "", reason: str = "") -> bool:
    """Trace un declenchement d'invariant. Fail-open : ne leve jamais."""
    try:
        c = _conn()
        c.execute(
            "INSERT INTO alignment_events (ts, actor, invariant, verdict, target, reason) VALUES (?,?,?,?,?,?)",
            (time.time(), str(actor)[:40], str(invariant)[:40], str(verdict)[:16], str(target)[:200], str(reason)[:200]),
        )
        c.commit()
        c.close()
        global _emit_count
        _emit_count += 1
        if _emit_count % 500 == 0:
            _purge()
        return True
    except Exception:
        global _emit_fail
        _emit_fail += 1
        return False


def emit_introspection(
    actor: str,
    action: str,
    target_module: str,
    ring: int | None = None,
    execution_tier: str | None = None,
    is_self_judging: bool | None = None,
    diversity: float | None = None,
    tokens: dict | None = None,
    cost_usd: float | None = None,
    free_energy: float | None = None,
    surprise: float | None = None,
    goodhart_score: float | None = None,
    reason: str = ""
) -> bool:
    """Trace un evenement d'introspection riche dans alignment_events. Fail-open."""
    try:
        import json
        meta_dict = {
            "ring": ring,
            "execution_tier": execution_tier,
            "is_self_judging": is_self_judging,
            "diversity": diversity,
            "tokens": tokens,
            "cost_usd": cost_usd,
            "free_energy": free_energy,
            "surprise": surprise,
            "goodhart_score": goodhart_score,
        }
        meta_dict = {k: v for k, v in meta_dict.items() if v is not None}
        meta_str = json.dumps(meta_dict) if meta_dict else None

        c = _conn()
        c.execute(
            "INSERT INTO alignment_events (ts, actor, invariant, verdict, target, reason, meta) VALUES (?,?,?,?,?,?,?)",
            (
                time.time(),
                str(actor)[:40],
                "introspection",
                str(action)[:16],
                str(target_module)[:200],
                str(reason)[:200],
                meta_str,
            ),
        )
        c.commit()
        c.close()
        global _emit_count
        _emit_count += 1
        if _emit_count % 500 == 0:
            _purge()
        return True
    except Exception:
        global _emit_fail
        _emit_fail += 1
        return False


def recent(limit: int = 50, invariant: str | None = None) -> list[dict]:
    try:
        import json
        c = _conn()
        try:
            if invariant:
                rows = c.execute(
                    "SELECT ts,actor,invariant,verdict,target,reason,meta FROM alignment_events "
                    "WHERE invariant=? ORDER BY id DESC LIMIT ?", (invariant, limit)).fetchall()
            else:
                rows = c.execute(
                    "SELECT ts,actor,invariant,verdict,target,reason,meta FROM alignment_events "
                    "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            c.close()
            return [{"ts": r[0], "actor": r[1], "invariant": r[2], "verdict": r[3],
                     "target": r[4], "reason": r[5], "meta": json.loads(r[6]) if r[6] else None} for r in rows]
        except sqlite3.OperationalError:
            if invariant:
                rows = c.execute(
                    "SELECT ts,actor,invariant,verdict,target,reason FROM alignment_events "
                    "WHERE invariant=? ORDER BY id DESC LIMIT ?", (invariant, limit)).fetchall()
            else:
                rows = c.execute(
                    "SELECT ts,actor,invariant,verdict,target,reason FROM alignment_events "
                    "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            c.close()
            return [{"ts": r[0], "actor": r[1], "invariant": r[2], "verdict": r[3],
                     "target": r[4], "reason": r[5], "meta": None} for r in rows]
    except Exception:
        return []


def emit_fail_count() -> int:
    """F6 : nb d'echecs d'ecriture du capteur depuis le demarrage (angle mort si >0)."""
    return _emit_fail


def summary() -> dict:
    """Tableau de bord : declenchements par (invariant, verdict)."""
    from collections import Counter
    ev = recent(1000)
    c = Counter((e["invariant"], e["verdict"]) for e in ev)
    return {"total": len(ev), "emit_fail": _emit_fail,
            "by_invariant_verdict": {f"{k[0]}:{k[1]}": v for k, v in c.items()}}


def selftest() -> bool:
    ok_emit = emit("CLAUDE", "no_self_score_edit", "deny", "forge_trust_score.py", "selftest")
    emit("ANTIGRAVITY", "memory_quality_gate", "reject", "anchor", "selftest noise")
    ev = recent(5)
    print("emit ok:", ok_emit, "| recent:", [(e["invariant"], e["verdict"]) for e in ev[:3]])
    print("summary:", summary())
    ok = ok_emit and any(e["invariant"] == "no_self_score_edit" for e in ev)
    print("P1 ALIGNMENT TRACE:", "PASS" if ok else "FAIL (DB non-inscriptible en sandbox ? marche dans le hub)")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if selftest() else 1)
