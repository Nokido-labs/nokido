#!/usr/bin/env python3
"""tools/forge_warpgrep.py — recherche de code hybride pour la LOCALISATION.

Donné un repo + une description de bug -> les fichiers à éditer. Conçu pour
la localisation SWE-bench (remplacer le TF-IDF brut de `_find_relevant_files`).

v1 = repomap (signatures AST condensées) + BM25 sparse sur tokens de code.
PAS de RAG dense (vetting 6-LLM : le dense relie mal une stacktrace abstraite
à une méthode précise — pour du code, BM25 + topologie > vectoriel).
v2 prévu : call-graph cross-fichier ≤2 sauts (résolution des imports).

Réutilise : rank_bm25 (déjà au lockfile, zéro dép neuve). Tokeniseur enrichi
code (split snake_case / CamelCase) — un identifiant `parse_header` matche
"parse" ET "header".

API :
    warpgrep_locate(repo_root, problem_statement, k=8, keywords=None)
        -> [(score, rel_path, [symboles matchés]), ...]
CLI :
    forge_warpgrep.py <repo_root> "<description du bug>"
"""

from __future__ import annotations

import ast
import math
import re
import sys
from collections import Counter
from pathlib import Path

_STOP = {
    "the",
    "and",
    "for",
    "this",
    "that",
    "with",
    "from",
    "when",
    "should",
    "would",
    "have",
    "not",
    "but",
    "are",
    "was",
    "use",
    "using",
    "code",
    "test",
    "tests",
    "bug",
    "issue",
    "error",
    "expected",
    "actual",
    "following",
    "example",
    "return",
    "returns",
    "value",
    "values",
}
_SKIP = (
    "/test",
    "test_",
    "tests/",
    "/.git/",
    "build/",
    "/docs/",
    "/examples/",
    "/__pycache__/",
    "/.tox/",
    "/venv/",
    "/site-packages/",
)


def _split_ident(name: str) -> list[str]:
    """`parseHTTPHeader` / `parse_http_header` -> [parse, http, header].
    Un identifiant de code éclaté en mots-racines minuscules."""
    out: list[str] = []
    for part in re.split(r"[_\W]+", str(name)):
        if not part:
            continue
        # CamelCase + ACRONYMCase + chiffres
        pieces = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z][a-z]+|[A-Z]+|[a-z]+|\d+", part) or [part]
        out += [p.lower() for p in pieces]
    return [w for w in out if len(w) > 1]


def build_repomap(repo_root) -> dict:
    """{rel_path: {"symbols": [...], "tokens": [...]}} — signatures AST
    condensées + sac de tokens (chemin + symboles éclatés + mots docstrings)."""
    root = Path(repo_root)
    out: dict = {}
    for p in root.rglob("*.py"):
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if any(x in ("/" + rel.lower()) for x in _SKIP):
            continue
        try:
            src = p.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src)
        except Exception:
            continue
        symbols: list[str] = []
        toks: list[str] = list(_split_ident(rel))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.append(node.name)
                toks += _split_ident(node.name)
                doc = ast.get_docstring(node)
                if doc:
                    toks += [w.lower() for w in re.findall(r"[A-Za-z_]{3,}", doc[:240])]
        if toks:
            out[rel] = {"symbols": symbols, "tokens": toks}
    return out


def _bm25_scores(corpus: list, query: list, k1: float = 1.5, b: float = 0.75) -> list:
    """BM25 Okapi — pur stdlib (pas de dépendance rank_bm25, ACL-fragile).
    corpus = liste de sacs de tokens ; renvoie un score par document."""
    n = len(corpus)
    if not n:
        return []
    dl = [len(d) for d in corpus]
    avgdl = (sum(dl) / n) or 1.0
    tfs = [Counter(d) for d in corpus]
    df: Counter = Counter()
    for c in tfs:
        for t in c:
            df[t] += 1
    qset = set(query)
    idf = {t: math.log(1.0 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in qset if t in df}
    scores = []
    for i, c in enumerate(tfs):
        norm = k1 * (1 - b + b * dl[i] / avgdl)
        s = 0.0
        for t in qset:
            f = c.get(t, 0)
            if f and t in idf:
                s += idf[t] * (f * (k1 + 1)) / (f + norm)
        scores.append(s)
    return scores


def warpgrep_locate(
    repo_root, problem_statement: str, k: int = 8, keywords: list | None = None
) -> list:
    """Top-k fichiers candidats. keywords = termes distillés (Stage 0) ;
    sinon extraits du problem_statement. -> [(score, rel, [symboles])]."""
    rm = build_repomap(repo_root)
    if not rm:
        return []
    rels = list(rm.keys())

    q: list[str] = []
    if keywords:
        for w in keywords:
            q += _split_ident(w)
    if not q:
        q = [
            w.lower()
            for w in re.findall(r"[A-Za-z_]{3,}", problem_statement or "")
            if w.lower() not in _STOP
        ]
    if not q:
        return []

    scores = _bm25_scores([rm[r]["tokens"] for r in rels], q)
    qset = set(q)
    ranked = sorted(zip(scores, rels), key=lambda x: -x[0])[:k]
    out = []
    for sc, rel in ranked:
        if sc <= 0:
            continue
        matched = [s for s in rm[rel]["symbols"] if qset & set(_split_ident(s))]
        out.append((round(float(sc), 2), rel, matched[:6]))
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('usage: forge_warpgrep.py <repo_root> "<bug description>"')
        sys.exit(1)
    hits = warpgrep_locate(sys.argv[1], sys.argv[2])
    for sc, rel, syms in hits:
        print(f"{sc:8.2f}  {rel}")
        if syms:
            print(f"          symboles: {', '.join(syms)}")
