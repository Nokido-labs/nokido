#!/usr/bin/env python3
"""
forge_reflexion_cli.py — Visu CLI live du FLUX DE RÉFLEXION Nokido.

Tail le miroir JSONL de `forge_swarm_bus` (`sandbox/reflexion.jsonl`) en
temps-réel et affiche un ARBRE groupé par corr_id/trace_id : chaque "pensée"
(GOAP_INTUITION/ACTION, swarm steps, + futurs hooks actor/mpc/cascade) apparaît
sous sa corrélation.

Pourquoi ce JSONL : zéro auth, cross-process, append-only temps-réel (le miroir
est écrit par forge_swarm_bus.publish, actif après restart du hub). Schéma :
{ts, topic, kind, data, corr_id?, trace_id?}.

Phase 1.5 (gaps) : ajouter `swarm_bus.publish(...)` dans forge_actor (MCTS),
forge_mpc (plan_horizon), forge_llm_router (cascade) → ils apparaîtront ici.

Dépend : stdlib + `rich` (fallback texte si absent).

Usage :
  python tools/forge_reflexion_cli.py                      # tail le log
  python tools/forge_reflexion_cli.py --topics tool,silo,debate
  python tools/forge_reflexion_cli.py --log <path>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import OrderedDict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "sandbox" / "reflexion.jsonl"
MAX_GROUPS = 10
MAX_PER_GROUP = 14

_PREFIX_STYLE = {
    "tool": "red", "rpc": "blue", "silo": "green", "skill": "yellow",
    "debate": "magenta", "agent": "bright_yellow", "goap": "cyan",
    "system": "bright_black", "file": "white", "error": "bold red",
}


def _style(topic: str, kind: str) -> str:
    if kind in ("error", "critical"):
        return "bold red"
    return _PREFIX_STYLE.get((topic or "").split(".")[0], "white")


def _summary(kind: str, data) -> str:
    if not isinstance(data, dict):
        return str(data)[:90]
    bits = []
    for k, v in list(data.items())[:5]:
        sv = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        bits.append(f"{k}={sv[:48]}")
    return " ".join(bits)[:170]


def _tail(path: Path, backlog: int = 30, follow: bool = True):
    """Générateur : backlog (dernières lignes) puis suit le live. JSON parsé.
    follow=False : ne yield QUE le backlog puis stoppe (mode --once/snapshot)."""
    waited = 0
    while not path.exists():
        if not follow and waited:
            return
        print(f"[reflexion] attente du log {path} … (actif après restart hub)", flush=True)
        time.sleep(2 if follow else 0.1)
        waited += 1
        if not follow:
            return
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        # contexte immédiat : dernières lignes déjà présentes
        for bl in f.read().splitlines()[-backlog:]:
            bl = bl.strip()
            if bl:
                try:
                    yield json.loads(bl)
                except Exception:
                    pass
        if not follow:
            return
        # f est en fin de fichier après read() -> suit les nouveaux events
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.3)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def _run_rich(log: Path, topics) -> int:
    from rich.console import Console
    from rich.live import Live
    from rich.tree import Tree

    groups: "OrderedDict[str, deque]" = OrderedDict()
    console = Console()

    def render() -> Tree:
        root = Tree(f"[bold]🧠 Nokido — flux de réflexion[/]  [dim]{log.name}[/]")
        for gid, evs in list(groups.items())[-MAX_GROUPS:]:
            label = gid[:16] if gid != "—" else "(sans corr_id)"
            br = root.add(f"[bold white]{label}[/] [dim]{len(evs)} ét.[/]")
            for e in list(evs)[-MAX_PER_GROUP:]:
                ts = str(e["ts"])[-12:-4] if isinstance(e["ts"], str) else time.strftime("%H:%M:%S", time.localtime(e["ts"]))
                br.add(f"[dim]{ts}[/] [{e['style']}]{e['topic']}/{e['kind']}[/] {e['summary']}")
        return root

    console.print(f"[dim]Tail {log} … (Ctrl+C pour quitter)[/]")
    with Live(render(), console=console, refresh_per_second=4, screen=False) as live:
        for ev in _tail(log):
            topic = str(ev.get("topic", "?"))
            if topics and (topic.split(".")[0] not in topics):
                continue
            kind = str(ev.get("kind", "?"))
            gid = str(ev.get("corr_id") or ev.get("trace_id") or ev.get("agent") or "—")
            groups.setdefault(gid, deque(maxlen=64)).append({
                "ts": ev.get("ts", time.time()), "topic": topic, "kind": kind,
                "style": _style(topic, kind), "summary": _summary(kind, ev.get("data", {})),
            })
            while len(groups) > MAX_GROUPS * 3:
                groups.popitem(last=False)
            live.update(render())
    return 0


def _run_plain(log: Path, topics) -> int:
    print(f"[reflexion] tail {log} (texte brut, rich absent)")
    for ev in _tail(log):
        topic = str(ev.get("topic", "?"))
        if topics and (topic.split(".")[0] not in topics):
            continue
        kind = str(ev.get("kind", "?"))
        gid = str(ev.get("corr_id") or ev.get("trace_id") or ev.get("agent") or "—")[:16]
        print(f"  [{gid}] {topic}/{kind} {_summary(kind, ev.get('data', {}))}", flush=True)
    return 0


def _snapshot(log: Path, topics) -> int:
    """Rend le backlog une fois puis sort (--once / test)."""
    n = 0
    for ev in _tail(log, follow=False):
        topic = str(ev.get("topic", "?"))
        if topics and (topic.split(".")[0] not in topics):
            continue
        kind = str(ev.get("kind", "?"))
        gid = str(ev.get("corr_id") or ev.get("trace_id") or ev.get("agent") or "—")[:16]
        print(f"  [{gid}] {topic}/{kind} {_summary(kind, ev.get('data', {}))}", flush=True)
        n += 1
    print(f"[reflexion] {n} events (snapshot). {log}", flush=True)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Visu CLI live du flux de réflexion (tail miroir swarm_bus).")
    p.add_argument("--log", default=str(DEFAULT_LOG))
    p.add_argument("--topics", default="", help="CSV prefixes à garder (tool,silo,debate,goap…)")
    p.add_argument("--once", action="store_true", help="Snapshot backlog puis sortir (pas de suivi live)")
    args = p.parse_args(argv)
    topics = {t.strip() for t in args.topics.split(",") if t.strip()} or None
    log = Path(args.log)

    try:
        if args.once:
            return _snapshot(log, topics)
        try:
            import rich  # noqa
            return _run_rich(log, topics)
        except ImportError:
            return _run_plain(log, topics)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
