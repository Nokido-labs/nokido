"""
forge_dispatchers.py — Branchage des organes réels sur forge_trajectory dispatch.

Chaque méthode de forge_trajectory.ALLOWED_METHODS est wired ici à son organe
réel (cervelet NPU, RAG, SearXNG, Crawl4AI, Exegol container, etc.).

Import side-effect : `import forge_dispatchers` enregistre tous les handlers.

Author-Agent: CLAUDE | Phase 6 — Symbiose
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent

from nokido_agent.app.forge_trajectory import register_dispatcher, ALLOWED_METHODS

# Ajout vector_feedback à la whitelist
ALLOWED_METHODS["vector_feedback"] = {
    "params": {"chunk_id": "str", "helpful": "bool", "context": "str?"},
    "ring": 2,
    "organ": "memoire",
}
ALLOWED_METHODS["search_memory"] = {
    "params": {"query": "str", "limit": "int?"},
    "ring": 2,
    "organ": "memoire",
}
ALLOWED_METHODS["synaptic_metrics"] = {
    "params": {},
    "ring": 2,
    "organ": "memoire",
}
# Bridge GENERIQUE : 1 seul method whitelist (ring 2) pour TOUS les outils forges
# par forge_tool_forger (registre dynamique separe). Le ring gouverne l'ACCES ;
# l'EXEC passe par SecretGuard (cf. forge_call_dynamic).
ALLOWED_METHODS["forge_call_dynamic"] = {
    "params": {"name": "str", "kwargs": "dict?"},
    "ring": 2,
    "organ": "meta",
}


# ============================================================
# Memory / RAG dispatchers
# ============================================================
async def _embed(params: Dict[str, Any]) -> Dict[str, Any]:
    """Embed via cervelet NPU (preferé) ou Cervelet WASM fallback."""
    texts = params.get("texts", [])
    if not texts:
        return {"vecs": [], "error": "no texts"}
    if isinstance(texts, str):
        texts = [texts]
    # Tente cervelet NPU via subprocess (env ryzen-ai dédié)
    try:
        npu_python = os.environ.get(
            "LAFORGE_NPU_PYTHON",
            str(Path.home() / "miniforge3" / "envs" / "ryzen-ai-final" / "python.exe"),
        )
        npu_script = ROOT / "app" / "forge_npu_direct.py"
        if Path(npu_python).exists() and npu_script.exists():
            proc = await asyncio.create_subprocess_exec(
                npu_python,
                str(npu_script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            stdout, _ = await proc.communicate(input=json.dumps({"texts": texts}).encode())
            if proc.returncode == 0:
                d = json.loads(stdout.decode("utf-8", errors="replace"))
                return {"vecs": d.get("embeddings", []), "dim": d.get("dim"), "backend": "npu"}
    except Exception as e:
        pass
    # Fallback : cervelet WASM via WSL
    try:
        from nokido_agent.app.forge_wasm_cervelet import embed as wasm_embed

        vecs = wasm_embed(texts, prefer="docker")
        return {"vecs": vecs, "dim": len(vecs[0]) if vecs and vecs[0] else 0, "backend": "wasm"}
    except Exception as e:
        return {"vecs": [], "error": str(e)}


async def _rag_search(params: Dict[str, Any]) -> Dict[str, Any]:
    """Search RAG via FAISS+BM25+RRF + apply synaptic plasticity."""
    query = params.get("query", "")
    limit = int(params.get("limit", 5))
    if not query:
        return {"hits": [], "error": "query required"}
    try:
        import sys

        sys.path.insert(0, str(ROOT))
        from nokido_agent.app.forge_rag_engine import get_rag
        from nokido_agent.app.forge_synaptic_plasticity import synaptic_score, filter_by_dynamic_threshold, record_query

        # get_rag() = singleton verrouille : sans lui, CHAQUE dispatch reconstruisait
        # un moteur complet (decode ~691k chunks) — residuel du cold-wedge 2026-07-07.
        engine = get_rag()
        # RAGEngine.search peut être async ou sync selon version
        search_result = engine.search(query, k=limit * 2)
        if asyncio.iscoroutine(search_result):
            results = await search_result
        else:
            results = search_result
        # Apply synaptic weighting
        weighted = []
        for r in results:
            base = r.get("score", 0)
            meta = r.get("meta")
            w_score = synaptic_score(base, json.dumps(meta) if isinstance(meta, dict) else meta)
            weighted.append({**r, "score": w_score})
        weighted.sort(key=lambda x: -x["score"])
        filtered, thr = filter_by_dynamic_threshold(weighted)
        record_query(matched=bool(filtered))
        return {
            "hits": filtered[:limit],
            "threshold_used": thr,
            "total_candidates": len(weighted),
            "passed_threshold": len(filtered),
        }
    except Exception as e:
        return {"hits": [], "error": f"{type(e).__name__}: {e}"}


async def _search_memory(params: Dict[str, Any]) -> Dict[str, Any]:
    """Alias rag_search avec retour adapté pour LLM (best match + match_id)."""
    r = await _rag_search(params)
    hits = r.get("hits", [])
    if not hits:
        return {
            "success": False,
            "match_id": None,
            "score": 0,
            "metrics": {"max_score": 0, "threshold": r.get("threshold_used")},
        }
    top = hits[0]
    return {
        "success": True,
        "match_id": top.get("id") or top.get("chunk_id"),
        "match_text": (top.get("text") or "")[:1000],
        "score": top.get("score"),
        "metrics": {
            "threshold": r.get("threshold_used"),
            "candidates": r.get("total_candidates"),
            "filtered": r.get("passed_threshold"),
        },
    }


async def _vector_feedback(params: Dict[str, Any]) -> Dict[str, Any]:
    """Boucle de feedback : renforce/affaiblit un souvenir."""
    chunk_id = params.get("chunk_id") or params.get("match_id")
    helpful = bool(params.get("helpful", False))
    context = params.get("context", "")
    if not chunk_id:
        return {"ok": False, "error": "chunk_id required"}
    try:
        from nokido_agent.app.forge_synaptic_plasticity import feedback_loop

        return feedback_loop(chunk_id, helpful, agent="trajectory_dispatch", context=context)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _synaptic_metrics(_params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from nokido_agent.app.forge_synaptic_plasticity import get_global_metrics

        return get_global_metrics()
    except Exception as e:
        return {"error": str(e)}


async def _rag_ingest(params: Dict[str, Any]) -> Dict[str, Any]:
    """Ingest chunks via cervelet embeddings → store rag_chunks."""
    chunks = params.get("chunks", [])
    domain = params.get("domain", "trajectory_ingest")
    if not chunks:
        return {"ok": False, "error": "chunks required"}
    try:
        emb = await _embed({"texts": chunks})
        vecs = emb.get("vecs", [])
        if not vecs:
            return {"ok": False, "error": f"embed failed: {emb.get('error')}"}
        import sqlite3, struct, hashlib, time as _t

        conn = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"))
        n = 0
        for ch, v in zip(chunks, vecs):
            cid = "traj_" + hashlib.sha256(ch.encode()).hexdigest()[:16]
            blob = struct.pack(f"<{len(v)}f", *v) if v else None
            try:
                # Forme sans existant (2026-10-01) : n'arme pas le trigger rag_chunks_fts_bi.
                conn.execute(
                    "INSERT OR IGNORE INTO rag_chunks (id, text, source, domain, embedding, ingested_at, author) "
                    "SELECT ?,?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
                    (cid, ch, "trajectory_dispatch", domain, blob, int(_t.time()), "TRAJ", cid),
                )
                conn.execute(
                    # `id` n'est PAS une colonne de rag_fts (chunk_id, text, source,
                    # domain) : chaque insertion levait "no such column: id", et le
                    # `except Exception` en dessous l'avalait. Ce chemin n'a donc JAMAIS
                    # rien indexe depuis son ecriture, sans que rien ne le signale.
                    "INSERT OR IGNORE INTO rag_fts(chunk_id, source, text) VALUES (?,?,?)",
                    (cid, "trajectory_dispatch", ch),
                )
                n += 1
            except Exception:
                pass
        conn.commit()
        conn.close()
        return {"ok": True, "ingested": n, "backend": emb.get("backend")}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ============================================================
# Web / Sens dispatchers
# ============================================================
async def _web_search(params: Dict[str, Any]) -> Dict[str, Any]:
    """SearXNG :8080 query."""
    q = params.get("query", "")
    if not q:
        return {"results": [], "error": "query required"}
    try:
        url = f"http://127.0.0.1:8080/search?q={urllib.parse.quote(q)}&format=json"
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: urllib.request.urlopen(url, timeout=15).read())
        d = json.loads(r.decode())
        return {"results": d.get("results", [])[:10], "query": q}
    except Exception as e:
        return {"results": [], "error": f"{type(e).__name__}: {e}"}


async def _crawl(params: Dict[str, Any]) -> Dict[str, Any]:
    """Crawl4AI :11235 fetch URL."""
    url = params.get("url", "")
    if not url:
        return {"content": "", "error": "url required"}
    try:
        body = json.dumps({"urls": [url]}).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:11235/crawl",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=30).read())
        d = json.loads(r.decode())
        results = d.get("results", [])
        if results:
            return {
                "url": url,
                "html": (results[0].get("html") or "")[:50000],
                "markdown": (results[0].get("markdown") or "")[:50000],
            }
        return {"content": "", "error": "no result"}
    except Exception as e:
        return {"content": "", "error": f"{type(e).__name__}: {e}"}


# ============================================================
# Network / Recon dispatchers (Exegol container)
# ============================================================
async def _exegol_run(cmd: list) -> Dict[str, Any]:
    """Exécute commande dans container Exegol via wsl docker exec."""
    try:
        full = ["wsl", "-d", "Debian", "--", "docker", "exec", "exegol-recon"] + cmd
        proc = await asyncio.create_subprocess_exec(
            *full,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        return {
            "ok": proc.returncode == 0,
            "rc": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:50000],
            "stderr": stderr.decode("utf-8", errors="replace")[:5000],
            "cmd": " ".join(cmd),
        }
    except asyncio.TimeoutError:
        return {"ok": False, "rc": -1, "error": "timeout 300s", "cmd": " ".join(cmd)}
    except Exception as e:
        return {"ok": False, "rc": -2, "error": str(e), "cmd": " ".join(cmd)}


async def _nmap(params: Dict[str, Any]) -> Dict[str, Any]:
    target = params.get("target", "")
    ports = params.get("ports", "")
    if not target:
        return {"ok": False, "error": "target required"}
    cmd = ["nmap", "-sV", "-T4", "--open", target]
    if ports:
        cmd.extend(["-p", str(ports)])
    return await _exegol_run(cmd)


async def _exegol_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    ip = params.get("ip", "")
    if not ip:
        return {"ok": False, "error": "ip required"}
    return await _exegol_run(["nmap", "-A", "-T4", "--top-ports", "1000", ip])


async def _bruteforce_ssh(_params: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": False, "error": "bruteforce_ssh disabled by policy (ring 4 require explicit approval)"}


# ============================================================
# Locomoteur dispatchers
# ============================================================
async def _run_python(params: Dict[str, Any]) -> Dict[str, Any]:
    """Exec Python via SecretGuard'd pool."""
    code = params.get("code", "")
    if not code:
        return {"ok": False, "error": "code required"}
    try:
        from nokido_agent.app.forge_secret_guard import sanitize_python_code

        violation = sanitize_python_code(code, "TRAJECTORY", 2)
        if violation:
            return {"ok": False, "error": f"SecretGuard: {violation}"}
        from nokido_agent.app.forge_python_runner import get_runner

        loop = asyncio.get_event_loop()
        t_out = min(float(params.get("timeout", 30)), 300.0)
        result = await loop.run_in_executor(None, lambda: get_runner().run_code(code, t_out))
        return {"ok": True, "stdout": result.get("stdout", "")[:50000], "stderr": result.get("stderr", "")[:5000]}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _run_shell(params: Dict[str, Any]) -> Dict[str, Any]:
    """Exec shell via SecretGuard sanitize."""
    code = params.get("code", "")
    if not code:
        return {"ok": False, "error": "code required"}
    try:
        from nokido_agent.app.forge_secret_guard import sanitize_shell_command

        violation = sanitize_shell_command(code, "TRAJECTORY", 2)
        if violation:
            return {"ok": False, "error": violation}
        proc = await asyncio.create_subprocess_shell(
            code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        return {
            "ok": proc.returncode == 0,
            "rc": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:30000],
            "stderr": stderr.decode("utf-8", errors="replace")[:5000],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================================================
# Comm dispatchers
# ============================================================
async def _notify(params: Dict[str, Any]) -> Dict[str, Any]:
    """Hub action=notify pour message inter-agent."""
    to = params.get("to", "").upper()
    msg = params.get("message", "")
    if not to or not msg:
        return {"ok": False, "error": "to + message required"}
    try:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "hub", "arguments": {"action": "notify", "message": f"[{to}] {msg}"}},
            }
        ).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8766/mcp",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10).read())
        return {"ok": True, "result": json.loads(r.decode()).get("result", {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _event_publish(params: Dict[str, Any]) -> Dict[str, Any]:
    """Hub action=event publish."""
    topic = params.get("topic", "")
    data = params.get("data", {})
    if not topic:
        return {"ok": False, "error": "topic required"}
    try:
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "event",
                    "arguments": {"action": "publish", "topic": topic, "kind": "info", "data": data},
                },
            }
        ).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:8766/mcp", data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10).read())
        return {"ok": True, "result": json.loads(r.decode()).get("result", {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================================================
# Cervelet swarm
# ============================================================
async def _swarm_vectorize(params: Dict[str, Any]) -> Dict[str, Any]:
    """Vectorise un repo entier en parallèle (chunks → NPU embed → store)."""
    target = params.get("target_repo", "")
    depth = params.get("depth", "shallow")
    if not target:
        return {"ok": False, "error": "target_repo required"}
    target_path = Path(target)
    if not target_path.exists():
        return {"ok": False, "error": f"path not found: {target}"}
    # Collect files (.py .md .ts .js .go)
    exts = {".py", ".md", ".ts", ".js", ".go", ".rs", ".java", ".c", ".cpp", ".h"}
    files = [f for f in target_path.rglob("*") if f.suffix in exts and f.is_file() and f.stat().st_size < 100_000]
    if depth == "shallow":
        files = files[:50]
    else:
        files = files[:500]
    chunks = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")[:5000]
            chunks.append(f"# {f.relative_to(target_path)}\n\n{text}")
        except Exception:
            pass
    if not chunks:
        return {"ok": False, "error": "no readable chunks"}
    return await _rag_ingest({"chunks": chunks, "domain": f"swarm:{target_path.name}"})


# ============================================================
# OPSEC Rules of Engagement
# ============================================================
async def _set_opsec_level(params: Dict[str, Any]) -> Dict[str, Any]:
    """Switch niveau OPSEC à chaud (CTF | STANDARD | PARANOID).

    Set_by 'trajectory_dispatch' = AI actor → respecte human_locked.
    """
    level = params.get("level", "")
    reason = params.get("reason", "")
    if not level:
        return {"ok": False, "error": "level required (CTF|STANDARD|PARANOID)"}
    try:
        from nokido_agent.app.forge_opsec import set_opsec_level as _set

        # AI actor → respect human lock
        return _set(level, set_by="ai_trajectory", reason=reason)
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _detect_lab(params: Dict[str, Any]) -> Dict[str, Any]:
    """Scan text pour signatures CTF/lab. AI peut s'en servir pour décider OPSEC."""
    text = params.get("text", "")
    try:
        from nokido_agent.app.forge_opsec import detect_lab_environment

        return detect_lab_environment(text)
    except Exception as e:
        return {"error": str(e)}


async def _opsec_status(_params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from nokido_agent.app.forge_opsec import status

        return status()
    except Exception as e:
        return {"error": str(e)}


async def _sanitize_text(params: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize selon niveau courant ou explicite."""
    text = params.get("text", "")
    level_str = params.get("level")
    if not text:
        return {"ok": False, "error": "text required"}
    try:
        from nokido_agent.app.forge_opsec import sanitize_for_archive, OpsecLevel

        explicit = OpsecLevel[level_str.upper()] if level_str else None
        return sanitize_for_archive(text, agent="trajectory", explicit_level=explicit)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ============================================================
# Result/Error passthrough
# ============================================================
async def _result(params: Dict[str, Any]) -> Dict[str, Any]:
    return {"received": True, "job_id": params.get("job_id"), "data": params.get("data")}


async def _error(params: Dict[str, Any]) -> Dict[str, Any]:
    return {"received": True, "job_id": params.get("job_id"), "reason": params.get("reason")}


# ============================================================
# LLM cascade
# ============================================================
async def _llm_call(params: Dict[str, Any]) -> Dict[str, Any]:
    """Délègue à forge_llm_router cascade."""
    provider = params.get("provider", "auto")
    message = params.get("message", "")
    if not message:
        return {"ok": False, "error": "message required"}
    try:
        from nokido_agent.app.forge_llm_router import LLMRouter

        loop = asyncio.get_event_loop()
        rt = LLMRouter()
        r = await loop.run_in_executor(
            None,
            lambda: rt.call_cascade(
                prompt=message,
                use_case=provider if provider != "auto" else "general",
                max_tokens=int(params.get("max_tokens", 500)),
            ),
        )
        return r
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _llm_route(params: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-route une tâche par task_type."""
    task_type = params.get("task_type", "general")
    payload = params.get("payload", {})
    return await _llm_call({"provider": task_type, "message": json.dumps(payload), "max_tokens": 800})


# ============================================================
# Capteurs code (pagination sémantique) + blackboard (mémoire d'essaim)
# ============================================================
async def _get_file_skeleton(params: Dict[str, Any]) -> Dict[str, Any]:
    """Squelette AST (imports+signatures) via forge_repo_map.file_skeleton."""
    path = params.get("file_path", "")
    if not path:
        return {"ok": False, "error": "file_path required"}
    try:
        import os
        from nokido_agent.app.forge_repo_map import file_skeleton

        root = os.path.dirname(os.path.dirname(__file__))
        sk = await asyncio.to_thread(file_skeleton, path, root)
        return {"ok": bool(sk), "skeleton": sk}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _read_function_body(params: Dict[str, Any]) -> Dict[str, Any]:
    """Corps exact d'une fonction/classe via AST."""
    fp = params.get("file_path", "")
    func = params.get("function_name", "")
    if not fp or not func:
        return {"ok": False, "error": "file_path + function_name required"}
    try:
        import ast as _ast
        import os as _os

        root = _os.path.dirname(_os.path.dirname(__file__))
        ap = fp if _os.path.isabs(fp) else _os.path.join(root, fp)
        src = open(ap, encoding="utf-8", errors="replace").read()
        tree = _ast.parse(src)
        lines = src.splitlines(keepends=True)
        for n in _ast.walk(tree):
            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)) and n.name == func:
                s = n.lineno - 1
                e = getattr(n, "end_lineno", n.lineno)
                return {"ok": True, "body": "".join(lines[s:e])}
        return {"ok": False, "error": f"'{func}' introuvable dans {fp}"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _get_function_dependencies(params: Dict[str, Any]) -> Dict[str, Any]:
    """Callers+callees fonction-level via forge_callgraph_jit."""
    func = params.get("function_name", "")
    if not func:
        return {"ok": False, "error": "function_name required"}
    try:
        from nokido_agent.app.forge_callgraph_jit import get_function_dependencies

        res = await asyncio.to_thread(get_function_dependencies, func, params.get("file_path", ""))
        return {"ok": True, **res}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _blackboard_read_zone(params: Dict[str, Any]) -> Dict[str, Any]:
    zone = params.get("zone_name", "")
    if not zone:
        return {"ok": False, "error": "zone_name required"}
    try:
        from nokido_agent.app.forge_swarm_blackboard import read_zone

        rows = await asyncio.to_thread(read_zone, zone)
        return {"ok": True, "zone": zone, "facts": rows}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


async def _blackboard_propose_fact(params: Dict[str, Any]) -> Dict[str, Any]:
    zone = params.get("zone_name", "")
    fact = params.get("fact", "")
    if not zone or not fact:
        return {"ok": False, "error": "zone_name and fact required"}
    try:
        from nokido_agent.app.forge_swarm_blackboard import apply_fact

        res = await apply_fact(zone, fact, category=params.get("category", ""),
                               trust=float(params.get("trust", 0.5)),
                               source=params.get("source", "planner"),
                               ring=int(params.get("ring", 2)))
        return {"ok": not res.get("error"), **res}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ============================================================
# Bridge outils dynamiques forges (forge_tool_forger)
# ============================================================
async def _forge_call_dynamic(params: Dict[str, Any]) -> Dict[str, Any]:
    """Invoque un outil forge par forge_tool_forger. UN seul point whitelist (ring 2)
    pour TOUS les outils forges ; l'exec est gardee par SecretGuard dans forge_call_dynamic."""
    name = params.get("name", "")
    if not name:
        return {"ok": False, "error": "name required"}
    kwargs = params.get("kwargs", {}) or {}
    if not isinstance(kwargs, dict):
        return {"ok": False, "error": "kwargs must be an object"}
    try:
        from nokido_agent.app.forge_tool_forger import forge_call_dynamic as _fcd

        res = await asyncio.to_thread(lambda: _fcd(name, **kwargs))
        if isinstance(res, dict) and res.get("error"):
            return {"ok": False, "error": res["error"], "tool": name}
        return {"ok": True, "result": res.get("result", res) if isinstance(res, dict) else res, "tool": name}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ============================================================
# Register all
# ============================================================
def register_all() -> None:
    register_dispatcher("embed", _embed)
    register_dispatcher("rag_search", _rag_search)
    register_dispatcher("rag_ingest", _rag_ingest)
    register_dispatcher("search_memory", _search_memory)
    register_dispatcher("vector_feedback", _vector_feedback)
    register_dispatcher("synaptic_metrics", _synaptic_metrics)
    register_dispatcher("web_search", _web_search)
    register_dispatcher("crawl", _crawl)
    # Handlers offensifs (ring>=3) SORTIS du registre du coeur (owner 2026-09-26/27, symetrie avec
    # forge_trajectory._charger_intents_offensifs_optionnels, 82e03a1d9). Cablage SEULEMENT si la charge
    # redteam a inscrit la methode dans ALLOWED_METHODS ; coeur defensif => registre sans surface offensive.
    for _m, _fn in (("nmap", _nmap), ("exegol_scan", _exegol_scan), ("bruteforce_ssh", _bruteforce_ssh)):
        if _m in ALLOWED_METHODS:
            register_dispatcher(_m, _fn)
    register_dispatcher("run_python", _run_python)
    register_dispatcher("run_shell", _run_shell)
    register_dispatcher("notify", _notify)
    register_dispatcher("event_publish", _event_publish)
    register_dispatcher("swarm_vectorize", _swarm_vectorize)
    register_dispatcher("llm_call", _llm_call)
    register_dispatcher("llm_route", _llm_route)
    register_dispatcher("result", _result)
    register_dispatcher("error", _error)
    register_dispatcher("set_opsec_level", _set_opsec_level)
    register_dispatcher("opsec_status", _opsec_status)
    register_dispatcher("sanitize_text", _sanitize_text)
    register_dispatcher("detect_lab", _detect_lab)
    register_dispatcher("get_file_skeleton", _get_file_skeleton)
    register_dispatcher("read_function_body", _read_function_body)
    register_dispatcher("get_function_dependencies", _get_function_dependencies)
    register_dispatcher("blackboard_read_zone", _blackboard_read_zone)
    register_dispatcher("blackboard_propose_fact", _blackboard_propose_fact)
    register_dispatcher("forge_call_dynamic", _forge_call_dynamic)


# Side effect : enregistre tous les dispatchers à l'import
register_all()
