#!/usr/bin/env python3
"""forge_secretary.py — SECRÉTAIRE PROACTIF par agent : sur le tick heartbeat, RELÈVE le courrier
postal (digest intelligent) et INTERPELLE l'agent — au lieu que l'agent doive poller lui-même.

Passe le swarm de RÉACTIF (l'agent pense à poll, ou user le demande) à PROACTIF/asynchrone.
Problème d'un agent CLI : il est BLOQUANT (attend le prochain prompt). Pour qu'un secrétaire
réveille un CLI, 3 méthodes (analyse Gemini 2026-06-11) :
  A. INJECTION CONTEXTE (Nokido-native, ACTIVE ici) : écrit le digest dans sandbox/inbox/<agent>.md
     que le HOOK d'amorce (hub_lifecycle_hooks [HOOK:INBOX]) injecte au PROCHAIN tour de l'agent.
     -> au prochain prompt (même "ok"), l'agent voit "tu as N courriers, urgent: ...".
  B. PUSH MCP (notifications/message poussé dans la socket stdio) = + élégant, évolution bridge.
  C. SendKeys/stdin (YOLO) = intrusif, écarté.

Tick = heartbeat (10s). Pour chaque agent : forge_postal.digest(agent) -> si courrier en attente,
écrit l'interpellation (priorisée) + event + heartbeat. Le secrétaire NE consomme PAS (l'agent
ack en lisant via poll/secretaire). Un par canal = AGENTS configurable.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT))

INTERVAL = int(os.environ.get("SECRETARY_INTERVAL", "10"))
AGENTS = [a.strip().upper() for a in os.environ.get("SECRETARY_AGENTS", "CLAUDE,GEMINI,COPILOT").split(",") if a.strip()]
INBOX_DIR = ROOT / "sandbox" / "inbox"
_HB = ROOT / "sandbox" / "secretary.heartbeat"


def _interpeller(agent: str, d: dict) -> None:
    """Écrit l'interpellation (digest priorisé) là où le hook d'amorce la surface au prochain tour."""
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 📬 SECRÉTAIRE — {d['n_pending']} courrier(s) en attente pour {agent}",
        f"**Reco :** {d['recommend']}  ·  {d['n_threads']} fil(s)  ·  plus vieux : {d['oldest_pending_age_s']}s",
    ]
    if d.get("urgent"):
        lines.append("\n## ⚠️ URGENT (traiter d'abord)")
        for u in d["urgent"]:
            lines.append(f"- `#{u['id']}` de **{u['from']}** (prio {u['prio']}) : {u['body']}")
    lines.append("\n_Relève via `poll` (hub) ou forge_postal.secretaire(agent, ack=True) = accusé réception._")
    (INBOX_DIR / f"{agent.lower()}.md").write_text("\n".join(lines), encoding="utf-8")


def _clear(agent: str) -> None:
    f = INBOX_DIR / f"{agent.lower()}.md"
    if f.exists():
        try:
            f.unlink()
        except Exception:
            pass


def tick() -> list:
    """Un battement : (P0-5) le FACTEUR draine les canaux queued -> delivered, puis le SECRÉTAIRE
    relève le postal de chaque agent + interpelle. Sort la livraison du hot-path notify."""
    from nokido_agent.app.forge_postal import channels_with_pending, digest, facteur

    out = []
    # P0-5 FACTEUR DAEMON : draine channels_with_pending() (existait, appelé par PERSONNE) -> facteur(ch).
    # Achemine les courriers postés HORS notify (réponses inter-daemons, futurs CFP Contract Net).
    try:
        for _ch in channels_with_pending():
            _f = facteur(_ch)
            if _f.get("delivered"):
                out.append({"facteur": _ch, "delivered": len(_f["delivered"])})
    except Exception as _fe:  # noqa: BLE001
        out.append({"facteur_err": str(_fe)[:80]})
    for agent in AGENTS:
        try:
            # AUTO-TRIAGE (synchro) : clôt le courrier déjà traité (répondu-en-thread + routine)
            # AVANT le digest -> le pending ne compte que l'actionnable réellement non traité.
            from nokido_agent.app.forge_postal import auto_ack_replied

            _at = auto_ack_replied(agent)
            if _at.get("replied") or _at.get("routine"):
                out.append({"auto_ack": agent,
                            "replied": len(_at["replied"]), "routine": len(_at["routine"])})
            d = digest(agent)
            if d["n_pending"] > 0:
                _interpeller(agent, d)
                out.append({"agent": agent, "pending": d["n_pending"], "urgent": len(d.get("urgent", []))})
            else:
                _clear(agent)
        except Exception as e:  # noqa: BLE001
            out.append({"agent": agent, "error": str(e)[:90]})
    return out


def main() -> int:
    if "--once" in sys.argv:
        print(json.dumps(tick(), ensure_ascii=False, indent=2))
        return 0
    print(f"[secretary] PROACTIF start — agents={AGENTS} interval={INTERVAL}s", flush=True)
    while True:
        try:
            s = tick()
            # CHEMIN CANONIQUE UNIQUE (`forge_heartbeat.beat_daemon`) : ajoute le pid.
            from nokido_agent.app.forge_heartbeat import beat_daemon

            beat_daemon("secretary", health="ok", interpellations=s)
            if any("pending" in x for x in s):
                print(f"[secretary] {json.dumps(s, ensure_ascii=False)}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[secretary] err {e}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
