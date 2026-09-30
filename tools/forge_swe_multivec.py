#!/usr/bin/env python3
"""
tools/forge_swe_multivec.py — Retrieval multi-vecteur Parent-Child pour code (SWE-bench).

Contourne la myopie des embeddings sur code BRUT (bruité par syntaxe). On indexe des
CHILDREN à entropie sémantique (résumé conceptuel LLM + docstring + signature + nom)
et on RETOURNE le PARENT = le bloc de code brut exact. Multi-vecteur = plusieurs
children par parent -> recherche chirurgicale, anti lost-in-the-middle (on ne dépose
sur le contexte de l'agent que les fonctions strictement nécessaires). Multi-hop :
les définitions sont indexées, les callers via forge_swebench_runner._callgraph_context.

embed_fn et summarize_fn INJECTABLES :
  - prod  : bge-m3 (brain_worker :5557) + un LLM léger (résumé concept).
  - test  : stubs déterministes (sans service).

CLI: python forge_swe_multivec.py --selftest
"""
from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


def _docstring(node) -> str:
    try:
        return ast.get_docstring(node) or ""
    except Exception:
        return ""


def _sig(node) -> str:
    try:
        args = [a.arg for a in node.args.args]
        return f"def {node.name}({', '.join(args)})"
    except Exception:
        return getattr(node, "name", "?")


def _deps_used(node) -> str:
    """Child VECTEUR DÉPENDANCES (point 2 multi-vec) : ce que la fonction appelle/utilise
    (calls + attributs). Indexé séparément -> requête multi-hop 'qui dépend de X'."""
    names: set = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute):
                names.add(f.attr)
        elif isinstance(n, ast.Attribute):
            names.add(n.attr)
    names.discard("self")
    return ("dépendances: " + ", ".join(sorted(names)[:24])) if names else ""


def _cos(a, b) -> float:
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return s / (na * nb)


class MultiVecIndex:
    """Parent-child multi-vecteur. children=[(vec, parent_id)], parents[id]={code,...}."""

    def __init__(self, embed_fn):
        self.embed_fn = embed_fn
        self.children: list = []
        self.parents: dict = {}

    def add_parent(self, pid, code, file, name, line, child_texts) -> None:
        self.parents[pid] = {"code": code, "file": file, "name": name, "line": line}
        for t in child_texts:
            if t and t.strip():
                try:
                    self.children.append((self.embed_fn(t), pid))
                except Exception:
                    pass

    def search(self, query, k: int = 5) -> list:
        """Match les children, RETOURNE les parents (dédupe), top-k par score."""
        qv = self.embed_fn(query)
        scored = sorted(((_cos(qv, cv), pid) for cv, pid in self.children), key=lambda x: x[0], reverse=True)
        seen, out = set(), []
        for sc, pid in scored:
            if pid in seen:
                continue
            seen.add(pid)
            out.append({"score": round(sc, 3), **self.parents[pid]})
            if len(out) >= k:
                break
        return out


def index_repo(repo_path, embed_fn, summarize_fn=None, cap_files: int = 400) -> MultiVecIndex:
    """Indexe fonctions/classes du repo en parent-child multi-vecteur."""
    repo_path = Path(repo_path)
    idx = MultiVecIndex(embed_fn)
    pid = 0
    for f in list(repo_path.rglob("*.py"))[:cap_files]:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
            lines = src.splitlines(keepends=True)
        except Exception:
            continue
        rel = str(f.relative_to(repo_path)).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                s = node.lineno - 1
                e = getattr(node, "end_lineno", node.lineno)
                code = "".join(lines[s:e])
                # CHILDREN multi-vecteur : nom + signature + docstring + DÉPENDANCES
                # (+ résumé conceptuel LLM CIBLÉ sur les fonctions SANS docstring, où le
                # signal naturel manque le plus -> borne le coût LLM. Une fonction
                # documentée a déjà son docstring comme child conceptuel.)
                doc = _docstring(node)
                children = [node.name, _sig(node), doc, _deps_used(node)]
                if summarize_fn and not doc:
                    try:
                        children.append(summarize_fn(code))
                    except Exception:
                        pass
                idx.add_parent(pid, code, rel, node.name, node.lineno, [c for c in children if c])
                pid += 1
    return idx


def _zmq_embed_batch(texts: list, addr: str = "tcp://localhost:5557", sub: int = 20, timeout_s: int = 120) -> list:
    """Embeddings bge-m3 RÉELS via brain_worker :5557 (protocole ZMQ §13, sub-batch 20)."""
    import time

    import msgpack  # type: ignore
    import zmq  # type: ignore

    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.connect(addr)
    out: list = []
    try:
        for i in range(0, len(texts), sub):
            chunk = texts[i : i + sub]
            sock.send(msgpack.packb({"cmd": "submit", "type": "embed", "texts": chunk}, use_bin_type=True))
            if not sock.poll(10_000):
                raise TimeoutError("submit")
            tid = msgpack.unpackb(sock.recv(), raw=False)["task_id"]
            vecs = None
            for _ in range(timeout_s):
                sock.send(msgpack.packb({"cmd": "check", "task_id": tid}, use_bin_type=True))
                if not sock.poll(5_000):
                    raise TimeoutError("check")
                res = msgpack.unpackb(sock.recv(), raw=False)
                st = res.get("status", "pending")
                if st == "completed":
                    d = res.get("data")
                    vecs = d.get("vecs", []) if isinstance(d, dict) else d
                    break
                if st == "error":
                    raise RuntimeError(res.get("error", "embed error"))
                time.sleep(1)
            out.extend(vecs or [[] for _ in chunk])
    finally:
        sock.close()
    return out


def make_ollama_summarize(model: str = "laforge-qwen:latest", addr: str = "http://127.0.0.1:11434"):
    """summarize_fn prod : résumé conceptuel 1-phrase via LLM local (gratuit)."""
    import json as _j
    import urllib.request

    def _sum(code: str) -> str:
        body = _j.dumps(
            {
                "model": model,
                "prompt": f"Résume en UNE phrase ce que FAIT cette fonction (concept métier, pas la syntaxe):\n{code[:1500]}",
                "stream": False,
                "options": {"num_predict": 40},
            }
        ).encode()
        req = urllib.request.Request(addr + "/api/generate", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return _j.loads(r.read()).get("response", "").strip()

    return _sum


def make_hub_summarize(provider: str = "gemini_cli", addr: str = "http://127.0.0.1:8766"):
    """summarize_fn via LLM PUISSANT (claude_cli/gemini_cli) à travers le hub (raw,
    task_type=code), PAS ollama local. Pour le résumé conceptuel (fonctions sans docstring)."""
    import json as _j
    import urllib.request

    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        tok = get_secret("FORGE_MCP_TOKEN") or ""
    except Exception:
        tok = ""

    def _sum(code: str) -> str:
        body = _j.dumps({"method": "tools/call", "params": {"name": "ask", "arguments": {
            "provider": provider, "message": f"Résume en UNE phrase ce que FAIT cette fonction (concept):\n{code[:1400]}",
            "max_tokens": 40, "task_type": "code"}}}).encode()
        req = urllib.request.Request(addr + "/mcp", body,
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=40) as r:
            d = _j.loads(r.read())
            txt = d.get("result", {}).get("content", [{}])[0].get("text", "")
        try:
            return _j.loads(txt).get("text", "") or ""
        except Exception:
            return txt

    return _sum


def build_index_bge(repo_path, summarize_fn=None, cap_files: int = 400, files=None) -> MultiVecIndex:
    """Prod path : index multi-vec avec embeddings bge-m3 RÉELS (batch §13). Children =
    nom + signature + docstring + DÉPENDANCES (+ résumé LLM ciblé no-docstring).

    files : liste de chemins (candidats de localisation) -> SCOPE l'indexation à ces
    fichiers SEULEMENT. SANS ça (rglob de TOUT le repo) = des milliers de fonctions =
    catastrophe sur gros repo (astropy). Fallback rglob si files=None (petits repos)."""
    repo_path = Path(repo_path)
    if files:
        paths = [(Path(f) if Path(f).is_absolute() else repo_path / f) for f in files]
    else:
        paths = list(repo_path.rglob("*.py"))[:cap_files]
    specs: list = []
    pid = 0
    for f in paths:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
            lines = src.splitlines(keepends=True)
        except Exception:
            continue
        rel = str(f.relative_to(repo_path)).replace("\\", "/")
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                s = node.lineno - 1
                e = getattr(node, "end_lineno", node.lineno)
                code = "".join(lines[s:e])
                doc = _docstring(node)
                ch = [node.name, _sig(node), doc, _deps_used(node)]
                if summarize_fn and not doc:
                    try:
                        ch.append(summarize_fn(code))
                    except Exception:
                        pass
                ch = [c for c in ch if c and c.strip()]
                specs.append(({"pid": pid, "code": code, "file": rel, "name": node.name, "line": node.lineno}, ch))
                pid += 1
    flat = [t for _, ch in specs for t in ch]
    vecs = _zmq_embed_batch(flat) if flat else []
    idx = MultiVecIndex(lambda q: (_zmq_embed_batch([q]) or [[]])[0])
    it = iter(vecs)
    for meta, ch in specs:
        idx.parents[meta["pid"]] = {"code": meta["code"], "file": meta["file"], "name": meta["name"], "line": meta["line"]}
        for _t in ch:
            v = next(it, None)
            if v:
                idx.children.append((v, meta["pid"]))
    return idx


def _selftest() -> int:
    import json

    # stub embed déterministe : vecteur de comptage sur un petit vocab
    vocab = "database reconnect timeout json parse user auth token".split()

    def embed(t):
        tl = (t or "").lower()
        return [float(tl.count(w)) for w in vocab]

    repo = Path("mvtest_repo")
    (repo / "db").mkdir(parents=True, exist_ok=True)
    (repo / "db" / "conn.py").write_text(
        'def reconnect(host):\n    """Reconnect to the database after a timeout."""\n    return host\n',
        encoding="utf-8",
    )
    (repo / "db" / "io.py").write_text(
        'def load(s):\n    """Parse a json payload from a user request."""\n    return s\n',
        encoding="utf-8",
    )
    idx = index_repo(repo, embed)
    hits = idx.search("database reconnection after timeout", k=2)
    import shutil

    shutil.rmtree(repo, ignore_errors=True)
    top = hits[0] if hits else {}
    ok = bool(hits) and top.get("name") == "reconnect" and "Reconnect" in top.get("code", "")
    print("SELFTEST", "OK" if ok else "FAIL",
          json.dumps({"top_name": top.get("name"), "top_score": top.get("score"),
                      "returns_parent_code": "Reconnect" in top.get("code", ""),
                      "n_children": len(idx.children), "n_parents": len(idx.parents)}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
