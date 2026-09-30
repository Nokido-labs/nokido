# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = ssot/intention-journal
JOURNAL UNIFIE DES INTENTIONS — audit-trail infaillible (doc SSoT souverain, pilier A).

TOUTE intention d'agent (proposition d'action, ecriture d'etat partage, decision de gate)
est APPENDUE au timecode event-log (forge_timecode, event_type='intention:<type>'), une fois,
jamais modifiee. Replay deterministe -> n'importe quel agent reconstruit le contexte exact.

POURQUOI dedie (anti-dup, §3) : forge_timecode = le journal (event-log + hash-chain) ; ce
module est la COUCHE INTENTION au-dessus : un point d'entree unique que tous les chemins
(blackboard, gate, actions) appellent, pour que l'audit-trail soit UNIFORME (le gap = ~20%
des chemins ne journalisaient pas : faits blackboard, actions agent eparses).

Vision (raffinement GLM 2026-06-18) : a terme le event-log devient le CHEMIN D'ECRITURE
PRIMAIRE (agents append -> validateurs videur/gate consomment+appliquent), supprimant le
SPOF mono-writer. Ce module est le 1er maillon. 0 LLM, 0 cloud.
"""
from __future__ import annotations
import os, sys

APP = os.path.dirname(os.path.abspath(__file__))
if APP not in sys.path:
    sys.path.insert(0, APP)

try:
    from nokido_agent.app.forge_bounded_queue import EcrivainDiffere
except ImportError:  # lance par chemin : app/ est dans sys.path
    from forge_bounded_queue import EcrivainDiffere
# Fil d'ecriture unique du journal ; il ne demarre qu'a la premiere ecriture differee.
_ECRIVAIN = EcrivainDiffere("intention_journal")


def record(agent: str, intent_type: str, target: str = "", payload: dict | None = None,
           decision: str = "proposed", status: str = "ok", session_id: str = "") -> dict:
    """Appende une intention au journal immuable (timecode event-log).
    decision : proposed|validated|denied|executed. Retourne {ok, seq, ts}.

    Sur la boucle du hub (run, blackboard, gate), l'ecriture part dans UN fil dedie, en ordre
    FIFO (la hash-chain reste sequentielle) et rend {ok, differe: True} sans seq : elle
    attendait le verrou de embeddings.db jusqu'a 10 s EN BLOQUANT tout le hub (36 gels le
    27/09, dont le constructeur du moteur rejoue a chaque appel tant que son schema echouait).
    Aucun appelant n'utilise le seq. Hors boucle : ecriture sur place, comme avant."""
    try:
        pl = dict(payload or {})
        pl["decision"] = decision

        def _ecrire():
            from nokido_agent.app.forge_timecode import get_timecode_engine
            return get_timecode_engine().log_event(
                event_type=f"intention:{intent_type}", target=str(target)[:200], payload=pl,
                session_id=session_id, agent_id=agent, status=status)

        if _ECRIVAIN.sur_une_boucle():
            return {"ok": _ECRIVAIN.soumettre(_ecrire), "differe": True}
        seq, ts = _ecrire()
        return {"ok": True, "seq": seq, "ts": ts}
    except Exception as e:  # noqa: BLE001  (le journal ne doit JAMAIS casser l'action)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:90]}"}


def replay(session_id: str = "", limit: int = 50) -> list:
    """Rejoue les intentions (timeline du journal) — pour reconstruire le contexte."""
    try:
        from nokido_agent.app.forge_timecode import get_timecode_engine
        eng = get_timecode_engine()
        rows = eng.timeline(session_id=session_id, event_type=None, target="",
                            after="", before="", limit=limit)
        out = []
        for r in rows:
            et = (r.get("event_type") if isinstance(r, dict) else (r[4] if len(r) > 4 else "")) or ""
            if str(et).startswith("intention"):
                out.append(r if isinstance(r, dict) else {"event_type": et, "row": r})
        return out
    except Exception as e:  # noqa: BLE001
        return [{"error": f"{type(e).__name__}: {str(e)[:90]}"}]


def stats() -> dict:
    """Combien d'intentions journalisees (par decision)."""
    try:
        from nokido_agent.app.forge_timecode import get_timecode_engine
        eng = get_timecode_engine()
        con = eng._conn()
        rows = con.execute(
            "SELECT status, COUNT(*) FROM event_log WHERE event_type LIKE 'intention%' GROUP BY status"
        ).fetchall()
        con.close()
        return {"by_status": {r[0]: r[1] for r in rows},
                "total": sum(r[1] for r in rows)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:90]}"}


def propose(agent: str, action: dict, session_id: str = "") -> dict:
    """INVERSION log-as-write-path (raffinement GLM) : un agent N'ECRIT PAS l'etat
    directement, il APPEND sa proposition d'action au log (status='proposed'). Un
    validateur (forge_gate_consumer) la consomme, la passe au gate, applique le verdict.
    action = {kind, prompt|target, est_steps, est_tokens, task_type, ring, ...}.
    Retourne {ok, seq, ts} -> le seq est l'identite de la proposition dans le log."""
    return record(agent=agent, intent_type="action",
                  target=str(action.get("target") or action.get("prompt") or "")[:200],
                  payload=action, decision="proposed", status="proposed", session_id=session_id)


if __name__ == "__main__":
    import json
    print("=== INTENTION JOURNAL selftest ===")
    r1 = record("claude", "blackboard_write", target="tree_locks/test",
                payload={"fact": "selftest intention"}, decision="validated", session_id="selftest")
    r2 = record("gemini", "action", target="run:echo", decision="executed", session_id="selftest")
    print("record1:", r1)
    print("record2:", r2)
    rp = replay(session_id="selftest", limit=10)
    print(f"replay (selftest): {len(rp)} intentions")
    for e in rp[:3]:
        print("  ", {k: e.get(k) for k in ("event_type", "agent_id", "target", "status")} if isinstance(e, dict) else e)
    print("stats:", stats())
