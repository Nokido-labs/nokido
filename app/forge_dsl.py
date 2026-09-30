"""forge_dsl.py — DSL compact Nokido (économie tokens 80-90% vs prompt naturel).

Grammar (mini, parsable sans regex complexe)
============================================
    DSL    := OP[':' ARGS] [' > ' OP[':' ARGS]]*
    ARGS   := KEY '=' VAL [',' KEY '=' VAL]*
    VAL    := str (mots joints par '+', refs DB en @id, listes en val1|val2)

Exemples (vs équivalent texte)
==============================
    "Recherche dans le RAG les chunks sur le protocole MCP, top 10"
        ~16 tokens cloud
    →   RAG:q=protocole+MCP,k=10
        ~7 tokens

    "Ingère l'URL https://gumloop.com dans le RAG, domain=ai_tools, role=tooling"
        ~22 tokens
    →   INGEST:url=https://gumloop.com,d=ai_tools,r=tooling
        ~10 tokens

    "Lance un cycle hebbian linker, puis ancre la solution dans le domaine neuro"
        ~16 tokens
    →   HEBBIAN > ANCHOR:d=neuro
        ~5 tokens

CATALOGUE OPS (alias courts)
============================
    RAG       : RAG search       args: q, k, domain
    INGEST    : URL → RAG         args: url, d, r (domain, role)
    BIBLIO    : insert biblio     args: q, idea (triggered_by)
    WATCH     : add WATCH_URL     args: url, label, d
    ANCHOR    : anchor_solution   args: prob, sol, d, ex
    HEBBIAN   : run hebbian       args: (none)
    HORMONE   : release/read      args: name, level (release if level), src
    IMMUNE    : check_request     args: text=ref:rag_chunk:<id> | inline
    RENAL     : purge table       args: table, days, apply (1/0)
    CHAT      : LLM call          args: uc (use_case), max=NN, p=ref:prompt_id
    T         : template          args: template_id

REFS EXTERNALISÉES (CRITIQUE — pas de doc/log inline)
=====================================================
    @rag_chunk:<id>            → SELECT text FROM rag_chunks WHERE id=...
    @blr:<id>                  → biblio_raw entry
    @lesson:<id>               → rag_chunks lesson_sol_*
    @prompt:<id>               → shared_prompt_log
    @file:<sandbox/path>       → fichier sandbox

TEMPLATES (lookup hash → DSL pré-stocké)
========================================
    Table dsl_templates(template_id, dsl, expansion_json, usage_count, last_used)
    T:wf_email_summary_telegram    → resolve depuis DB
    Auto-apprentissage : DSL exécuté > 5 fois devient template avec hash sha8.

USAGE
=====
    from forge_dsl import compile_dsl, expand_dsl, execute_dsl

    # Compiler humain → DSL
    compact = compile_dsl("Lance hebbian puis ancre dans neuro")
    # → "HEBBIAN > ANCHOR:d=neuro"

    # Exécuter (LLM local ou direct selon op)
    result = execute_dsl(compact)
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


# ============================================================================
# PARSER
# ============================================================================


@dataclass
class DSLOp:
    op: str
    args: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        a = ",".join(f"{k}={v}" for k, v in self.args.items())
        return f"{self.op}:{a}" if a else self.op


def parse_dsl(dsl: str) -> list[DSLOp]:
    """Parse une string DSL en liste d'ops. Lève ValueError sur mal-formé."""
    if not dsl or not dsl.strip():
        return []
    out = []
    for chunk in re.split(r"\s*>\s*", dsl.strip()):
        if not chunk:
            continue
        if ":" in chunk:
            op_name, raw_args = chunk.split(":", 1)
            args = {}
            for kv in raw_args.split(","):
                kv = kv.strip()
                if not kv:
                    continue
                if "=" not in kv:
                    raise ValueError(f"DSL arg malformé: '{kv}' dans '{chunk}'")
                k, v = kv.split("=", 1)
                args[k.strip()] = v.strip().replace("+", " ")  # + → espace
            out.append(DSLOp(op=op_name.strip().upper(), args=args))
        else:
            out.append(DSLOp(op=chunk.strip().upper()))
    return out


# ============================================================================
# REF RESOLVER (externalisation contexte)
# ============================================================================


def resolve_ref(ref: str) -> str:
    """Résout une ref @kind:id depuis la DB. Renvoie le contenu ou ''."""
    if not ref or not ref.startswith("@"):
        return ref
    spec = ref[1:]  # strip @
    if ":" not in spec:
        return ref
    kind, rid = spec.split(":", 1)
    conn = sqlite3.connect(str(DB), timeout=5)
    try:
        if kind == "rag_chunk":
            r = conn.execute("SELECT text FROM rag_chunks WHERE id=? LIMIT 1", (rid,)).fetchone()
            return r[0] if r else ""
        elif kind == "blr":
            r = conn.execute(
                "SELECT title || chr(10) || COALESCE(description,'') FROM biblio_raw WHERE id=? LIMIT 1", (rid,)
            ).fetchone()
            return r[0] if r else ""
        elif kind == "lesson":
            r = conn.execute(
                # GLOB sur le prefixe : '_' y est litteral, alors qu'en LIKE c'est un
                # joker. Verifie 2026-09-04 : aucun id ne commence par 'lesson' + un
                # autre caractere, donc aucune perte. Le plan reste un SCAN ici -- il
                # est impose par le `LIKE ?` en '%rid%' de la ligne, pas par ce motif.
                "SELECT text FROM rag_chunks WHERE id LIKE ? AND id GLOB 'lesson_*' LIMIT 1", (f"%{rid}%",)
            ).fetchone()
            return r[0] if r else ""
        elif kind == "file":
            p = ROOT / rid
            if p.exists():
                return p.read_text(encoding="utf-8", errors="replace")[:8000]
        return ""
    finally:
        conn.close()


# ============================================================================
# OP HANDLERS (registry — extensible)
# ============================================================================

OpHandler = Callable[[dict, dict], dict]
_HANDLERS: dict[str, OpHandler] = {}


def register(op_name: str):
    def deco(fn: OpHandler) -> OpHandler:
        _HANDLERS[op_name.upper()] = fn
        return fn

    return deco


# ── RAG search ──────────────────────────────────────────────────────────────
@register("RAG")
def _h_rag(args: dict, ctx: dict) -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    q = args.get("q", "")
    k = int(args.get("k", "5"))
    domain = args.get("domain")
    try:
        from nokido_agent.app.forge_self_correction import preflight_check_verbose

        v = preflight_check_verbose(q, "")
        rows = v.get("results", [])[:k]
        if domain:
            rows = [r for r in rows if r.get("domain") == domain]
        return {
            "op": "RAG",
            "ok": True,
            "n": len(rows),
            "results": [
                {"id": r.get("id"), "score": r.get("score"), "preview": (r.get("preview") or "")[:200]} for r in rows
            ],
        }
    except Exception as e:
        return {"op": "RAG", "ok": False, "err": str(e)}


# ── INGEST URL ──────────────────────────────────────────────────────────────
def _entetes_hub(agent: str) -> dict:
    """En-tetes d'organe vers le hub (jeton propre ou SERVICES, jamais le maitre) -- 2026-09-24."""
    try:
        from nokido_agent.app.forge_hub_client import entetes_organe

        return entetes_organe(agent)
    except Exception:  # noqa: BLE001 -- sans porteur, le hub rend 401 : l'echec reste visible
        return {"Content-Type": "application/json"}


@register("INGEST")
def _h_ingest(args: dict, ctx: dict) -> dict:
    import urllib.request

    body = json.dumps(
        {
            "header": "LF1.S.H.1.5.ING",
            "source": args.get("src", "dsl_ingest"),
            "data": {"url": args.get("url"), "title": args.get("title", args.get("url", ""))},
        }
    ).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8766/api/ingest", data=body, headers=_entetes_hub("DSL"), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return {"op": "INGEST", "ok": True, "result": json.loads(r.read())}
    except Exception as e:
        return {"op": "INGEST", "ok": False, "err": str(e)[:160]}


# ── BIBLIO insert ───────────────────────────────────────────────────────────
@register("BIBLIO")
def _h_biblio(args: dict, ctx: dict) -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_biblio_core import insert_biblio_raw

        entry = {
            "type": args.get("type", "concept"),
            "title": (args.get("q") or "DSL biblio")[:120],
            "authors": ["dsl_runtime"],
            "year": int(args.get("year", "2026")),
            "url": args.get("url"),
            "description": args.get("desc", args.get("q", "")),
            "triggered_by_idea_id": args.get("idea", "dsl_default"),
            "source_kind": "agent_research",
        }
        r = insert_biblio_raw(entry)
        return {"op": "BIBLIO", "ok": r.get("ok"), "id": r.get("id"), "status": r.get("status")}
    except Exception as e:
        return {"op": "BIBLIO", "ok": False, "err": str(e)[:160]}


# ── ANCHOR ──────────────────────────────────────────────────────────────────
@register("ANCHOR")
def _h_anchor(args: dict, ctx: dict) -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_self_correction import anchor_solution

        # Prev op result peut servir de contexte
        prev_summary = ""
        if ctx.get("_prev"):
            prev_summary = json.dumps(ctx["_prev"], ensure_ascii=False)[:500]
        r = anchor_solution(
            problem=args.get("prob", "DSL anchor — pas de problème explicite"),
            solution=args.get("sol", prev_summary or "DSL execution result"),
            example=args.get("ex", ""),
            domain=args.get("d", "dsl"),
        )
        return {"op": "ANCHOR", "ok": r.get("ok"), "chunk_id": r.get("chunk_id")}
    except Exception as e:
        return {"op": "ANCHOR", "ok": False, "err": str(e)[:160]}


# ── HEBBIAN ─────────────────────────────────────────────────────────────────
@register("HEBBIAN")
def _h_hebbian(args: dict, ctx: dict) -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_hebbian_linker import run_cycle

        return {"op": "HEBBIAN", "ok": True, "result": run_cycle()}
    except Exception as e:
        return {"op": "HEBBIAN", "ok": False, "err": str(e)[:160]}


# ── HORMONE ─────────────────────────────────────────────────────────────────
@register("HORMONE")
def _h_hormone(args: dict, ctx: dict) -> dict:
    import sys

    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_endocrine import release, read

        name = args.get("name", "")
        if not name:
            return {"op": "HORMONE", "ok": False, "err": "name required"}
        if "level" in args:
            r = release(name, level=float(args["level"]), source=args.get("src", "dsl"), reason=args.get("reason", ""))
            return {"op": "HORMONE", "ok": True, "released": r}
        else:
            level = read(name)
            return {"op": "HORMONE", "ok": True, "name": name, "level": level}
    except Exception as e:
        return {"op": "HORMONE", "ok": False, "err": str(e)[:160]}


# ── CHAT ────────────────────────────────────────────────────────────────────
@register("CHAT")
def _h_chat(args: dict, ctx: dict) -> dict:
    """Prompt courte vers LLM local via direct llamacpp / ollama."""
    import urllib.request

    prompt = args.get("p", "")
    if prompt.startswith("@"):
        prompt = resolve_ref(prompt)
    if not prompt and ctx.get("_prev"):
        prompt = json.dumps(ctx["_prev"], ensure_ascii=False)[:1500]
    if not prompt:
        return {"op": "CHAT", "ok": False, "err": "no prompt"}
    body = json.dumps(
        {
            "model": args.get("model", "qwen"),
            "messages": [{"role": "user", "content": prompt[:4000]}],
            "max_tokens": int(args.get("max", "200")),
            "temperature": float(args.get("temp", "0.2")),
        }
    ).encode()
    port = args.get("port", "8091")  # llama.cpp natif par défaut
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
        text = d["choices"][0]["message"]["content"]
        usage = d.get("usage", {})
        return {"op": "CHAT", "ok": True, "text": text[:2000], "usage": usage, "model": d.get("model")}
    except Exception as e:
        return {"op": "CHAT", "ok": False, "err": str(e)[:160]}


# ── T (template) ────────────────────────────────────────────────────────────
@register("T")
def _h_template(args: dict, ctx: dict) -> dict:
    """Lookup template hash → DSL → execute."""
    tid = args.get("id") or list(args.keys())[0] if args else ""
    conn = sqlite3.connect(str(DB), timeout=5)
    _ensure_templates_schema(conn)
    row = conn.execute("SELECT dsl FROM dsl_templates WHERE template_id=?", (tid,)).fetchone()
    if not row:
        conn.close()
        return {"op": "T", "ok": False, "err": f"template '{tid}' not found"}
    conn.execute(
        "UPDATE dsl_templates SET usage_count = usage_count + 1, last_used=datetime('now') WHERE template_id=?", (tid,)
    )
    conn.commit()
    conn.close()
    # Re-exécute la chaîne
    return execute_dsl(row[0], _depth=ctx.get("_depth", 0) + 1)


# ============================================================================
# TEMPLATES (auto-apprentissage)
# ============================================================================


def _ensure_templates_schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS dsl_templates (
        template_id TEXT PRIMARY KEY,
        dsl         TEXT NOT NULL,
        expansion_json TEXT,
        usage_count INTEGER DEFAULT 1,
        created_at  TEXT DEFAULT (datetime('now')),
        last_used   TEXT
    )""")
    conn.commit()


def register_template(template_id: str, dsl: str) -> dict:
    """Enregistre un template manuel."""
    conn = sqlite3.connect(str(DB), timeout=5)
    _ensure_templates_schema(conn)
    conn.execute(
        "INSERT OR REPLACE INTO dsl_templates(template_id, dsl, usage_count) "
        "VALUES (?, ?, COALESCE((SELECT usage_count FROM dsl_templates "
        "WHERE template_id=?), 0))",
        (template_id, dsl, template_id),
    )
    conn.commit()
    conn.close()
    return {"template_id": template_id, "dsl": dsl, "ok": True}


def auto_promote_to_template(dsl: str, threshold: int = 5) -> str | None:
    """Si un DSL est exécuté >= threshold fois, devient template auto avec hash."""
    h = hashlib.sha256(dsl.encode("utf-8")).hexdigest()[:8]
    tid = f"auto_{h}"
    conn = sqlite3.connect(str(DB), timeout=5)
    _ensure_templates_schema(conn)
    row = conn.execute("SELECT usage_count FROM dsl_templates WHERE template_id=?", (tid,)).fetchone()
    if not row:
        conn.execute("INSERT INTO dsl_templates(template_id, dsl, usage_count) VALUES (?, ?, 1)", (tid, dsl))
    else:
        conn.execute(
            "UPDATE dsl_templates SET usage_count=usage_count+1, last_used=datetime('now') WHERE template_id=?", (tid,)
        )
    conn.commit()
    new_count = conn.execute("SELECT usage_count FROM dsl_templates WHERE template_id=?", (tid,)).fetchone()[0]
    conn.close()
    if new_count >= threshold:
        return tid
    return None


# ============================================================================
# EXEC + COMPILE
# ============================================================================


def execute_dsl(dsl: str, *, _depth: int = 0) -> dict:
    """Exécute une chaîne DSL. Renvoie un dict de résultats."""
    if _depth > 5:
        return {"ok": False, "err": "depth limit (template recursion)"}
    ops = parse_dsl(dsl)
    if not ops:
        return {"ok": False, "err": "empty dsl"}
    ctx: dict = {"_depth": _depth}
    pipeline = []
    for op in ops:
        handler = _HANDLERS.get(op.op)
        if not handler:
            pipeline.append({"op": op.op, "ok": False, "err": "unknown op"})
            continue
        try:
            res = handler(op.args, ctx)
        except Exception as e:
            res = {"op": op.op, "ok": False, "err": f"{type(e).__name__}: {e}"}
        pipeline.append(res)
        ctx["_prev"] = res

    # Auto-promote si fréquent
    auto_promote_to_template(dsl)

    return {"ok": all(r.get("ok") for r in pipeline), "dsl": dsl, "ops_count": len(ops), "pipeline": pipeline}


def compile_intent(text: str) -> str:
    """Heuristique LIGHT pour compiler un texte en DSL.

    Pour les cas simples : lookup mots-clés. Pour les cas complexes : passer
    par un LLM local (CHAT op) qui compile lui-même.
    """
    t = text.lower().strip()
    # Patterns directs
    if t.startswith("hebbian") or "hebbian" in t and "linker" in t:
        return "HEBBIAN"
    if t.startswith("anchor") or t.startswith("ancre"):
        return "ANCHOR:d=dsl,sol=" + text.replace(" ", "+")[:80]
    if t.startswith("rag") or t.startswith("recherche"):
        m = re.search(r"['\"]([^'\"]+)['\"]", text)
        if m:
            return f"RAG:q={m.group(1).replace(' ', '+')},k=10"
    if t.startswith("ingest") or t.startswith("ingère"):
        m = re.search(r"https?://\S+", text)
        if m:
            return f"INGEST:url={m.group(0).rstrip('.')}"
    # Fallback : bypass DSL, retourner le texte brut (pas optimisé)
    return f"# RAW:{text[:200]}"


# ============================================================================
# CLI
# ============================================================================


def _cli() -> int:
    import argparse, sys

    ap = argparse.ArgumentParser(description="Nokido DSL compiler/runtime")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_exec = sub.add_parser("exec", help="Exécute un DSL")
    p_exec.add_argument("dsl")

    p_comp = sub.add_parser("compile", help="Compile un texte en DSL")
    p_comp.add_argument("text")

    p_reg = sub.add_parser("register", help="Enregistre un template")
    p_reg.add_argument("template_id")
    p_reg.add_argument("dsl")

    sub.add_parser("templates", help="Liste les templates")

    p_parse = sub.add_parser("parse", help="Parse un DSL (debug)")
    p_parse.add_argument("dsl")

    args = ap.parse_args()
    if args.cmd == "exec":
        out = execute_dsl(args.dsl)
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    elif args.cmd == "compile":
        print(compile_intent(args.text))
    elif args.cmd == "register":
        out = register_template(args.template_id, args.dsl)
        print(json.dumps(out, indent=2, ensure_ascii=False))
    elif args.cmd == "templates":
        conn = sqlite3.connect(str(DB))
        _ensure_templates_schema(conn)
        rows = conn.execute(
            "SELECT template_id, dsl, usage_count, last_used FROM dsl_templates ORDER BY usage_count DESC LIMIT 30"
        ).fetchall()
        for tid, dsl, n, lu in rows:
            print(f"  {tid:30s} ×{n:>4}  → {dsl[:80]}")
    elif args.cmd == "parse":
        for op in parse_dsl(args.dsl):
            print(repr(op))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_cli())
