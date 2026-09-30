#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_trace_viz.py — IRM fonctionnelle : call-flow RUNTIME depuis un trace_id.

Le code STATIQUE (AST / mermaid_gen / atlas) ment sur l'ordre d'exécution, la
concurrence et les flux sous charge. Ce module lit les spans RÉELS du foie
d'audit (RAG/audit.db, table audit_log) via `forge_audit_log.query_recent` et
reconstruit, pour un `trace_id` donné :

  - SÉQUENCE Mermaid : qui appelle qui, dans l'ordre temporel réel, avec durée
    et statut — le flux async Hub→bus→workers tel qu'il s'est produit ;
  - DÉPENDANCES RUNTIME : graphe agent→target agrégé (compte + durée totale) —
    le « qui dépend de qui » observé, pas déclaré.

C'est la « visualisation plus complexe, moins de zones d'ombre » demandée
(roadmap observabilité, chantier #1). Réutilise le store d'audit existant — ne
ré-implémente RIEN. Voir [[trace_id_instrumentation_2026-05-30]],
[[roadmap_observability_no_blindspots_2026-06-02]].

Usage :
    forge_trace_viz.py list [--limit N]               # trace_ids récents
    forge_trace_viz.py <trace_id> [--seq|--deps|--json|--all] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import OrderedDict, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from nokido_agent.app.forge_audit_log import query_recent, init_db, _conn  # réutilise le store

MAX_SPANS = 1000
EXEC_DB = os.path.realpath(os.path.join(ROOT, "RAG", "execution_traces.db"))


# ── Store execution_traces.db (tool-calls RL, chaînés par session) ─────────
def _exec_ro():
    import sqlite3
    return sqlite3.connect(f"file:{EXEC_DB}?mode=ro", uri=True, timeout=10.0)


def _exec_to_span(row) -> dict:
    rid, ts, tid, ajson, ttype, success = row
    try:
        a = json.loads(ajson) if ajson else {}
    except Exception:
        a = {}
    if not isinstance(a, dict):
        a = {}
    return {
        "id": rid, "ts": ts, "trace_id": tid, "parent_id": None,
        "agent": a.get("agent") or a.get("role") or a.get("source"),
        "action": a.get("type") or a.get("tool") or ttype or "?",
        "target": a.get("tool") or a.get("target") or a.get("to"),
        "status": 0 if success else 1, "duration_ms": None,
    }


def exec_load_spans(trace_id: str, limit: int = MAX_SPANS) -> list[dict]:
    with _exec_ro() as c:
        rows = c.execute(
            "SELECT id,ts,trace_id,action_json,task_type,success FROM traces "
            "WHERE trace_id=? ORDER BY ts ASC LIMIT ?",
            (trace_id, min(max(limit, 1), MAX_SPANS)),
        ).fetchall()
    return [_exec_to_span(r) for r in rows]


def exec_list_traces(limit: int = 20, by: str = "recent") -> list[dict]:
    order = "n DESC, t1 DESC" if by == "count" else "t1 DESC"
    with _exec_ro() as c:
        rows = c.execute(
            "SELECT trace_id, COUNT(*) n, MIN(ts) t0, MAX(ts) t1, "
            "SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) errs "
            "FROM traces GROUP BY trace_id ORDER BY " + order + " LIMIT ?",
            (min(max(limit, 1), 200),),
        ).fetchall()
    return [
        {"trace_id": r[0], "spans": r[1], "t0": r[2], "t1": r[3],
         "wall_ms": int(((r[3] or 0) - (r[2] or 0)) * 1000), "dur_ms": 0,
         "errs": r[4]}
        for r in rows
    ]


def exec_diag() -> dict:
    with _exec_ro() as c:
        rows, traces = c.execute(
            "SELECT COUNT(*), COUNT(DISTINCT trace_id) FROM traces"
        ).fetchone()
        multi = c.execute(
            "SELECT COUNT(*) FROM (SELECT trace_id FROM traces "
            "GROUP BY trace_id HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        top_tt = c.execute(
            "SELECT task_type, COUNT(*) n FROM traces GROUP BY task_type "
            "ORDER BY n DESC LIMIT 8"
        ).fetchall()
    return {
        "store": EXEC_DB, "rows": rows, "distinct_traces": traces,
        "multi_span_traces": multi, "top_task_types": [
            {"task_type": t, "n": n} for t, n in top_tt],
    }


# ── Chargement ────────────────────────────────────────────────────────────
def load_spans(trace_id: str, limit: int = MAX_SPANS) -> list[dict]:
    """Spans d'un trace, ordre chronologique (query_recent renvoie id DESC)."""
    spans = query_recent(limit=limit, trace_id=trace_id)
    spans.sort(key=lambda s: (s.get("ts") or 0, s.get("id") or 0))
    return spans


def list_traces(limit: int = 20, by: str = "recent") -> list[dict]:
    """Trace_ids agrégés. by='recent' (t1 DESC) ou 'count' (spans DESC).

    query_recent ne groupe pas → SQL d'agrégat direct (réutilise _conn).
    """
    init_db()
    order = "n DESC, t1 DESC" if by == "count" else "t1 DESC"
    with _conn() as c:
        rows = c.execute(
            "SELECT trace_id, COUNT(*) n, MIN(ts) t0, MAX(ts) t1, "
            "SUM(COALESCE(duration_ms,0)) dur, "
            "SUM(CASE WHEN status>=400 THEN 1 ELSE 0 END) errs "
            "FROM audit_log GROUP BY trace_id ORDER BY " + order + " LIMIT ?",
            (min(max(limit, 1), 200),),
        ).fetchall()
    return [
        {"trace_id": r[0], "spans": r[1], "t0": r[2], "t1": r[3],
         "wall_ms": int(((r[3] or 0) - (r[2] or 0)) * 1000),
         "dur_ms": r[4], "errs": r[5]}
        for r in rows
    ]


def audit_diag() -> dict:
    """Santé de l'audit pour le call-flow : la propagation trace_id marche-t-elle ?

    Si multi_span_traces≈0 → trace_id régénéré par event (pas de flow à visualiser).
    parent_id_pct dit si le lien parent existe (fix=trace_id=root) ou non
    (fix=persister les child spans).
    """
    init_db()
    with _conn() as c:
        rows, traces, with_parent = c.execute(
            "SELECT COUNT(*), COUNT(DISTINCT trace_id), "
            "SUM(CASE WHEN parent_id IS NOT NULL AND parent_id!='' THEN 1 ELSE 0 END) "
            "FROM audit_log"
        ).fetchone()
        multi = c.execute(
            "SELECT COUNT(*) FROM (SELECT trace_id FROM audit_log "
            "GROUP BY trace_id HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        # parent_id pointe-t-il vers un trace_id existant ? (linkage cross-trace)
        linked = c.execute(
            "SELECT COUNT(*) FROM audit_log a WHERE a.parent_id IS NOT NULL "
            "AND a.parent_id!='' AND EXISTS "
            "(SELECT 1 FROM audit_log b WHERE b.trace_id=a.parent_id)"
        ).fetchone()[0]
        top_act = c.execute(
            "SELECT action, COUNT(*) n FROM audit_log GROUP BY action "
            "ORDER BY n DESC LIMIT 8"
        ).fetchall()
    return {
        "rows": rows, "distinct_traces": traces,
        "multi_span_traces": multi,
        "parent_id_pct": round(100 * (with_parent or 0) / rows, 1) if rows else 0,
        "parent_links_to_existing_trace": linked,
        "top_actions": [{"action": a, "n": n} for a, n in top_act],
    }


# ── Helpers rendu ─────────────────────────────────────────────────────────
def _node(v) -> str:
    return str(v) if v not in (None, "") else "(none)"


def _san(s: str, n: int = 44) -> str:
    return str(s).replace('"', "'").replace("\n", " ").replace(";", ",")[:n]


# ── SÉQUENCE Mermaid ──────────────────────────────────────────────────────
def to_sequence(spans: list[dict]) -> str:
    seen: list[str] = []
    for s in spans:
        for k in ("agent", "target"):
            v = _node(s.get(k))
            if v not in seen:
                seen.append(v)
    amap = OrderedDict((n, f"P{i}") for i, n in enumerate(seen))

    out = ["sequenceDiagram", "    autonumber"]
    for n, a in amap.items():
        out.append(f"    participant {a} as {_san(n, 40)}")
    for s in spans:
        src = amap[_node(s.get("agent"))]
        dst = amap[_node(s.get("target"))]
        meta = []
        if s.get("duration_ms") is not None:
            meta.append(f"{s['duration_ms']}ms")
        if s.get("status") is not None:
            meta.append(f"s={s['status']}")
        label = _san(s.get("action") or "?", 48)
        if meta:
            label += f" [{', '.join(meta)}]"
        out.append(f"    {src}->>{dst}: {label}")
        st = s.get("status")
        if isinstance(st, int) and st >= 400:
            out.append(f"    Note over {dst}: ! status {st}")
    return "\n".join(out)


# ── DÉPENDANCES RUNTIME ───────────────────────────────────────────────────
def to_deps(spans: list[dict]) -> str:
    edges: dict[tuple, dict] = defaultdict(lambda: {"n": 0, "dur": 0, "err": 0})
    for s in spans:
        key = (_node(s.get("agent")), _node(s.get("target")))
        e = edges[key]
        e["n"] += 1
        e["dur"] += s.get("duration_ms") or 0
        if isinstance(s.get("status"), int) and s["status"] >= 400:
            e["err"] += 1

    nodes: "OrderedDict[str,str]" = OrderedDict()
    for a, t in edges:
        for n in (a, t):
            if n not in nodes:
                nodes[n] = f"N{len(nodes)}"

    out = ["flowchart LR"]
    for n, nid in nodes.items():
        out.append(f'    {nid}["{_san(n, 40)}"]')
    for (a, t), e in edges.items():
        tag = f'{e["n"]}x {e["dur"]}ms'
        if e["err"]:
            tag += f' !{e["err"]}'
        out.append(f"    {nodes[a]} -->|{tag}| {nodes[t]}")
    return "\n".join(out)


# ── ARBRE D'APPELS (span_id -> parent_id) ─────────────────────────────────
def to_tree(spans: list[dict]) -> str:
    """Vrai arbre d'appels imbriqués : edge parent_span -> child_span via
    span_id/parent_id (modèle OTel, instrumenté par forge_span.span())."""
    by_id = {s.get("span_id"): s for s in spans if s.get("span_id")}
    out = ["flowchart TD"]
    for s in spans:
        sid = s.get("span_id")
        if not sid:
            continue
        d = s.get("duration_ms")
        meta = f" · {d}ms" if d is not None else ""
        nid = "S" + str(sid)[:8]
        out.append(f'    {nid}["{_san((s.get("action") or "?") + meta, 46)}"]')
        pid = s.get("parent_id")
        if pid and pid in by_id:
            out.append(f"    S{str(pid)[:8]} --> {nid}")
    return "\n".join(out)


# ── Résumé ────────────────────────────────────────────────────────────────
def summary(trace_id: str, spans: list[dict]) -> str:
    if not spans:
        return f"trace {trace_id}: aucun span (vérifie l'id via `list`)."
    t0 = spans[0].get("ts") or 0
    t1 = spans[-1].get("ts") or 0
    tot = sum(s.get("duration_ms") or 0 for s in spans)
    errs = sum(1 for s in spans if isinstance(s.get("status"), int) and s["status"] >= 400)
    agents = sorted({_node(s.get("agent")) for s in spans})
    return (
        f"trace {trace_id}\n"
        f"  spans={len(spans)} wall={int((t1 - t0) * 1000)}ms sum_dur={tot}ms "
        f"errs={errs}\n"
        f"  agents={', '.join(agents)}"
    )


# ── CLI ───────────────────────────────────────────────────────────────────
def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Call-flow runtime depuis un trace_id")
    ap.add_argument("target", help="'list' ou un trace_id")
    ap.add_argument("--limit", type=int, default=MAX_SPANS)
    ap.add_argument("--seq", action="store_true", help="diagramme de séquence")
    ap.add_argument("--deps", action="store_true", help="graphe deps runtime")
    ap.add_argument("--tree", action="store_true", help="arbre d'appels span_id/parent_id")
    ap.add_argument("--json", action="store_true", help="spans bruts JSON")
    ap.add_argument("--all", action="store_true", help="résumé + seq + deps")
    ap.add_argument("--exec", action="store_true",
                    help="store execution_traces.db (tool-calls) au lieu de audit.db")
    args = ap.parse_args()

    _list = exec_list_traces if args.exec else list_traces
    _load = exec_load_spans if args.exec else load_spans
    _diag = exec_diag if args.exec else audit_diag

    if args.target == "diag":
        print(json.dumps(_diag(), ensure_ascii=False, indent=2, default=str))
        return 0

    if args.target in ("list", "top"):
        by = "count" if args.target == "top" else "recent"
        traces = _list(args.limit if args.limit != MAX_SPANS else 20, by=by)
        if not traces:
            print("(aucune trace dans audit.db)")
            return 0
        print(f"{'trace_id':34} {'spans':>5} {'wall_ms':>8} {'dur_ms':>8} {'err':>4}")
        for t in traces:
            print(f"{(t['trace_id'] or '(null)'):34} {t['spans']:>5} "
                  f"{t['wall_ms']:>8} {t['dur_ms']:>8} {t['errs']:>4}")
        return 0

    spans = _load(args.target, args.limit)
    if args.json:
        print(json.dumps(spans, ensure_ascii=False, indent=2, default=str))
        return 0

    show_all = args.all or not (args.seq or args.deps)
    if show_all or args.seq or args.deps:
        print(summary(args.target, spans))
    if not spans:
        return 0
    if show_all or args.seq:
        print("\n```mermaid")
        print(to_sequence(spans))
        print("```")
    if show_all or args.deps:
        print("\n```mermaid")
        print(to_deps(spans))
        print("```")
    if show_all or args.tree:
        print("\n```mermaid")
        print(to_tree(spans))
        print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
