# -*- coding: utf-8 -*-
"""
__FORGE_COLOR__ = immunitaire/guard qui consomme le journal d'intentions (gate SSoT)
GATE-CONSUME-LOG — le validateur CONSOMME le journal d'intentions (raffinement GLM 2026-06-18).

Vision SSoT souveraine inversee : les agents APPENDENT leurs propositions au timecode
event-log (forge_intention_journal), et des VALIDATEURS (ce module) consomment le log,
passent chaque intention par le GATE deterministe (forge_orchestration_gate.classify) et
RE-POSTENT le verdict (lane/target) dans le log. Supprime le SPOF mono-writer : l'ecriture
primaire = append au log ; la validation = consommation parallele idempotente.

POURQUOI dedie (anti-dup, §3) : forge_intention_journal = append ; forge_orchestration_gate
= la regle deterministe ; ce module = le CONSUMER qui les relie (read log -> gate -> verdict).

0 LLM, 0 cloud (le gate est deterministe ~ms).
  LAFORGE_PYTHON app/forge_gate_consumer.py            # selftest : propose -> consume -> verdict
  LAFORGE_PYTHON app/forge_gate_consumer.py --daemon   # boucle (validateur continu)
"""
from __future__ import annotations
import os, sys, json, dataclasses

APP = os.path.dirname(os.path.abspath(__file__))
if APP not in sys.path:
    sys.path.insert(0, APP)
# RACINE aussi (2026-09-24, mesure) : `nokido_agent` est un dossier de la RACINE ; n'ajouter
# que app/ laissait le service mourir en ModuleNotFoundError a chaque demarrage.
_RACINE_AMORCE = os.path.dirname(APP)
if _RACINE_AMORCE not in sys.path:
    sys.path.insert(0, _RACINE_AMORCE)


def _build_action(intent: dict):
    """Construit un Action (gate) depuis une intention, defensif sur le schema."""
    from nokido_agent.app.forge_orchestration_gate import Action
    known = {
        "kind": intent.get("kind") or "llm",
        "prompt": str(intent.get("prompt") or intent.get("target") or "")[:400],
        "est_tokens": int(intent.get("est_tokens", 500) or 500),
        "est_steps": int(intent.get("est_steps", 1) or 1),
        "task_type": intent.get("task_type") or "general",
        "quality_need": intent.get("quality_need") or "normal",
        "ring": int(intent.get("ring", 4) or 4),
        "nlu_conf": float(intent.get("nlu_conf", 0.5) or 0.5),
    }
    kwargs = {}
    for f in dataclasses.fields(Action):
        if f.name in known:
            kwargs[f.name] = known[f.name]
        elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            kwargs[f.name] = "" if f.type in (str, "str") else 0
    return Action(**kwargs)


def _verdicted_seqs(con) -> set:
    """src_seq deja routees. Event-sourcing : on N'EFFACE pas la proposition (immuable),
    on relit les verdicts pour dedup -> idempotence sans muter le log."""
    done = set()
    for (pj,) in con.execute(
            "SELECT payload FROM event_log WHERE event_type='intention:gate_verdict'").fetchall():
        try:
            s = json.loads(pj or "{}").get("src_seq")
            if s is not None:
                done.add(int(s))
        except Exception:
            pass
    return done


def consume(limit: int = 20) -> list:
    """Consomme les intentions PROPOSEES NON ENCORE routees -> gate -> verdict.
    IDEMPOTENT : une proposition deja verdictee n'est jamais re-routee (le daemon
    boucle sans dupliquer). C'est l'inversion : agents append, validateur consomme."""
    from nokido_agent.app.forge_timecode import get_timecode_engine
    from nokido_agent.app.forge_orchestration_gate import classify
    from nokido_agent.app import forge_intention_journal as ij
    eng = get_timecode_engine()
    con = eng._conn()
    try:
        rows = con.execute(
            "SELECT sequence_id, agent_id, target, payload FROM event_log "
            "WHERE event_type LIKE 'intention:%' AND status='proposed' "
            "ORDER BY sequence_id DESC LIMIT ?", (limit * 6,)).fetchall()
        done = _verdicted_seqs(con)
    finally:
        con.close()
    verdicts = []
    for seq, agent, target, payload_json in rows:
        if int(seq) in done or len(verdicts) >= limit:
            continue
        try:
            intent = json.loads(payload_json or "{}")
        except Exception:
            intent = {}
        try:
            d = classify(_build_action({**intent, "target": target}))
            dd = d.to_dict() if hasattr(d, "to_dict") else {"lane": getattr(d, "lane", None)}
            ij.record(agent=agent or "unknown", intent_type="gate_verdict", target=str(target),
                      payload={"src_seq": seq, "lane": dd.get("lane"), "route": dd.get("target"),
                               "reason": dd.get("reason"), "quality_floor": dd.get("quality_floor")},
                      decision="routed")
            verdicts.append({"seq": seq, "agent": agent, "lane": dd.get("lane"), "route": dd.get("target")})
        except Exception as e:  # noqa: BLE001
            verdicts.append({"seq": seq, "error": f"{type(e).__name__}: {str(e)[:70]}"})
    return verdicts


def serve(interval: int = 30, rounds: int = 0):
    """Validateur continu : consomme le log en boucle (daemon)."""
    import time
    i = 0
    while rounds == 0 or i < rounds:
        v = consume()
        if v:
            print(f"[gate-consumer {i}] {len(v)} intentions routees")
        # Pouls APRES un round reussi (SUPERVISE sans port au recensement 2026-07-28).
        try:
            from nokido_agent.app.forge_heartbeat import beat_daemon

            beat_daemon("gate_consumer", intentions=len(v or []), interval_s=interval)
        except Exception:  # noqa: BLE001
            pass
        i += 1
        if rounds and i >= rounds:
            break
        time.sleep(interval)


def _selftest():
    from nokido_agent.app import forge_intention_journal as ij
    print("=== GATE-CONSUME-LOG selftest (inversion log-as-write-path) ===")
    # 1. des agents APPENDENT leurs propositions au log (status=proposed) via propose()
    p1 = ij.propose("claude", {"kind": "refactor_multi", "target": "refactor 12 fichiers auth",
                               "est_steps": 12, "est_tokens": 8000, "task_type": "code", "ring": 4})
    p2 = ij.propose("gemini", {"kind": "list", "target": "lister un repertoire",
                               "est_steps": 1, "est_tokens": 50, "ring": 4})
    print("propose1:", p1, "\npropose2:", p2)
    # 2. le validateur CONSOMME + route
    v = consume(limit=10)
    routed = sum(1 for x in v if x.get("lane"))
    print(f"\nverdicts round1 ({routed} routees):")
    for x in v[:6]:
        print("  ", x)
    # 3. IDEMPOTENCE : re-consommer ne re-route RIEN (daemon-safe)
    v2 = consume(limit=10)
    idemp = len(v2) == 0
    print(f"\nround2 (idempotence) : {len(v2)} re-routees (attendu 0)")
    ok = routed > 0 and idemp
    print(f"-> gate-consume-log {'OK' if ok else 'KO'} : {routed} routees, idempotent={idemp}")
    return 0 if ok else 1


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=30)
    args = ap.parse_args(argv)
    if args.daemon:
        serve(args.interval, 0)
        return 0
    return _selftest()


if __name__ == "__main__":
    sys.exit(main())
