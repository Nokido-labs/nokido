# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_commit_intel
#FORGE:[score:90|agent:claude-mcp|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: AST + commit + scope + impact + risque + apprentissage, sans CodeQL ni scan externe
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:claude-mcp|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"
"""
app/forge_commit_intel.py - Analyse AST + Impact + Risque pour chaque commit
==============================================================================

Pipeline :
  commit SHA -> parse AST des .py modifies (diff before/after)
             -> extract symbols touches (functions, classes, imports)
             -> scope = modules directement modifies
             -> impact = modules transitivement impactes via call graph (rag_graph_edges)
             -> risque = score base sur :
                 * symboles critiques touches (CRITICAL_SYMBOLS)
                 * patterns sensibles (subprocess, eval, os.system, sql)
                 * scope security/auth/firewall
                 * taille du diff
                 * historique de bugs sur ce fichier (apprentissage)
             -> persistance dans table commit_intel + rag_chunks

Apprentissage :
  - Chaque fix(xxx) commit incremente hist[file].bug_count
  - Lors du scoring futur, risque += hist[file].bug_count * 0.1
  - preflight_check peut maintenant repondre : "fichier X a eu N bugs, zone sensible"

Usage :
  from forge_commit_intel import analyze_commit, analyze_range, get_risk

  intel = analyze_commit("HEAD")
  print(f"Scope : {intel.modules_modified}")
  print(f"Impact : {intel.modules_impacted}")
  print(f"Risk : {intel.risk_score} ({intel.risk_level})")

  # Batch sur les 100 derniers commits
  for intel in analyze_range(since="HEAD~100"):
      store_intel(intel)

  # Pre-push hook : bloque si risk >= HIGH sur zone sensible
  risk = get_risk("HEAD")
  if risk["level"] == "CRITICAL":
      sys.exit(1)

Integration :
  - Appele par pre-push hook (bientot) pour bloquer les commits a risque
  - Appele par forge_git_historian en fin de pipeline pour enrichir commit_intel
  - Query-able via preflight_check : "modifier forge_xxx.py" -> alert si risk history
"""

import ast
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"


# =============================================================================
# CONFIGURATION - symboles critiques + patterns risque
# =============================================================================

# Symboles dont toute modification merite attention particuliere
CRITICAL_SYMBOLS = {
    # Securite
    "pre_flight",
    "post_flight",
    "redact_text",
    "restore_text",
    "wrap",
    "unwrap",
    "detect_injection",
    "generate_canary",
    "check_canary_leak",
    "sanitize",
    "anonymize",
    "is_pii_safe_for_cloud",
    "IntegrityRing",
    "get_firewall",
    "SovereignMembrane",
    "NoiseGuardian",
    # Auth
    "issue_token",
    "verify_token",
    "require_auth",
    "check_token",
    # Entree/sortie critiques
    "call_cascade",
    "route",
    "execute_cognitive_cycle",
    "evolve",
    "apply_smart_patch",
    "write",
    "apply_edit",
    # RAG coeur
    "search",
    "anchor_error",
    "anchor_solution",
    "preflight_check",
    "make_chunk_id",
    "rebuild_fts_index",
    # Init / bootstrap
    "bootstrap",
    "main",
    "rag_self_warmup",
    "get_rag_engine",
}

# Patterns dangereux : si ajoutes dans un diff, risk +2 chacun
DANGEROUS_PATTERNS = [
    (r"\bos\.system\s*\(", "os.system"),
    (r"\bsubprocess\.run\s*\([^,)]*shell\s*=\s*True", "subprocess shell=True"),
    (r"\beval\s*\(", "eval()"),
    (r"\bexec\s*\(", "exec()"),
    (r"\b__import__\s*\(", "__import__()"),
    (r"\bpickle\.loads?\s*\(", "pickle.load"),
    (r"\byaml\.load\s*\([^,)]*(?!Loader=)", "yaml.load sans Loader"),
    (r"verify\s*=\s*False", "SSL verify=False"),
    (r"check_hostname\s*=\s*False", "TLS check_hostname=False"),
    # SQL risque
    (r"(?i)\.execute\s*\(\s*['\"].*?%s.*?['\"]\s*%", "SQL format string (injection)"),
    (r"(?i)\.execute\s*\(\s*f['\"].*?\{", "SQL f-string (injection)"),
    # Credentials
    (r"(?i)password\s*=\s*['\"](?!\s*os\.environ)", "password= hardcoded"),
    (r"(?i)api[_-]?key\s*=\s*['\"](?!\s*os\.environ)", "api_key= hardcoded"),
    # Reseau ouvert
    (r"host\s*=\s*['\"]0\.0\.0\.0['\"]", "bind 0.0.0.0 (public)"),
]

# Scopes qui augmentent le risque intrinseque
SENSITIVE_SCOPES = {
    "security",
    "firewall",
    "membrane",
    "auth",
    "guard",
    "integrity",
    "sentinel",
    "precommit",
    "pre_commit",
    "llm_router",
    "cascade",
    "ring",
}

# Niveaux de risque
RISK_LEVELS = [
    (0, "MINIMAL"),
    (3, "LOW"),
    (7, "MEDIUM"),
    (12, "HIGH"),
    (20, "CRITICAL"),
]


def risk_level(score: float) -> str:
    """Convertit un score numerique en label textuel."""
    level = "MINIMAL"
    for threshold, name in RISK_LEVELS:
        if score >= threshold:
            level = name
    return level


# =============================================================================
# DATA STRUCTURE
# =============================================================================


@dataclass
class CommitIntel:
    """Intel d un commit : ce qu il touche, impact, risque."""

    sha: str
    short_sha: str
    subject: str
    commit_type: str
    scope: str
    date: str
    # Analyse AST
    files_modified: list  # chemins
    modules_modified: list  # app/forge_xxx
    symbols_added: list  # functions/classes ajoutees
    symbols_removed: list
    symbols_modified: list  # functions/classes dont le corps change
    imports_added: list
    imports_removed: list
    critical_symbols_touched: list  # intersection avec CRITICAL_SYMBOLS
    # Impact
    modules_impacted: list  # transitivement via call graph
    # Risque
    danger_patterns_hits: list  # [(pattern_label, count)]
    risk_score: float
    risk_level: str
    # Apprentissage
    file_bug_counts: dict  # {file: n_bugs_historique}
    # Meta
    stats: dict  # {lines_added, lines_removed, files_count}


# =============================================================================
# AST ANALYSIS
# =============================================================================


def _get_file_content_at(sha: str, path: str) -> Optional[str]:
    """Retourne le contenu d un fichier a un commit donne. None si absent."""
    try:
        r = subprocess.run(
            ["git", "show", f"{sha}:{path}"],
            cwd=str(ROOT),
            capture_output=True,
            timeout=10,
        )
        if r.returncode != 0:
            return None
        return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


def _extract_symbols(source: str) -> dict:
    """Parse AST, extrait {functions: set, classes: set, imports: set}."""
    result = {"functions": set(), "classes": set(), "imports": set()}
    if not source:
        return result
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return result
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result["functions"].add(node.name)
        elif isinstance(node, ast.ClassDef):
            result["classes"].add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                result["imports"].add(node.module)
    return result


def _extract_function_bodies(source: str) -> dict:
    """Retourne {qualified_name: source_text} pour tracking modifications internes."""
    bodies = {}
    if not source:
        return bodies
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return bodies
    lines = source.split("\n")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = node.lineno - 1
            end = getattr(node, "end_lineno", start + 1)
            body = "\n".join(lines[start:end])
            bodies[node.name] = body
    return bodies


# =============================================================================
# DIFF ANALYSIS
# =============================================================================


def _get_diff_stats(sha: str) -> dict:
    """Retourne {files: n, insertions: n, deletions: n}."""
    try:
        r = subprocess.run(
            ["git", "show", "--stat", "--format=", sha],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        # Parse "X files changed, Y insertions(+), Z deletions(-)"
        text = r.stdout
        m = re.search(r"(\d+) files? changed(?:, (\d+) insertions?.+)?(?:, (\d+) deletions?.+)?", text)
        if m:
            return {
                "files": int(m.group(1)),
                "insertions": int(m.group(2) or 0),
                "deletions": int(m.group(3) or 0),
            }
    except Exception:
        pass
    return {"files": 0, "insertions": 0, "deletions": 0}


def _get_diff_content(sha: str) -> str:
    """Retourne le diff brut pour regex-scan des patterns dangereux."""
    try:
        r = subprocess.run(
            ["git", "show", "--no-color", sha],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
        )
        return r.stdout
    except Exception:
        return ""


def _get_changed_files(sha: str) -> list:
    """Liste des fichiers modifies par un commit."""
    try:
        r = subprocess.run(
            ["git", "show", "--name-only", "--format=", sha],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        return [f.strip() for f in r.stdout.split("\n") if f.strip() and f.endswith((".py", ".md", ".yml", ".json"))]
    except Exception:
        return []


# =============================================================================
# IMPACT ANALYSIS
# =============================================================================


def _get_impacted_modules(modules_modified: list, max_depth: int = 2) -> list:
    """
    Utilise rag_graph_edges pour trouver les modules transitivement impactes.

    Strategie : pour chaque module modifie, chercher les edges SEMANTIC ou
    CO_SOURCE inverses (dst = ce module) pour trouver qui en depend.
    """
    if not modules_modified:
        return []
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()
        impacted = set()
        to_visit = set(modules_modified)
        visited = set()
        for _depth in range(max_depth):
            next_batch = set()
            for mod in to_visit:
                if mod in visited:
                    continue
                visited.add(mod)
                # Chercher qui reference ce module (dst = mod, donc src est dependant)
                cur.execute(
                    "SELECT src FROM rag_graph_edges "
                    "WHERE dst LIKE ? AND rel_type IN ('SEMANTIC', 'CO_SOURCE') "
                    "LIMIT 30",
                    (f"%{mod}%",),
                )
                for row in cur.fetchall():
                    candidate = row[0]
                    # Extraire nom module depuis chemin source
                    m = re.search(r"(forge_[\w_]+)", candidate)
                    if m:
                        modname = m.group(1)
                        if modname not in modules_modified and modname not in impacted:
                            impacted.add(modname)
                            next_batch.add(modname)
            to_visit = next_batch
            if not to_visit:
                break
        conn.close()
        return sorted(impacted)[:20]  # cap
    except Exception:
        return []


# =============================================================================
# RISK SCORING
# =============================================================================


def _score_risk(intel: CommitIntel) -> float:
    """Calcule le risk_score d un commit deja analyse."""
    score = 0.0

    # +2 par symbole critique touche
    score += 2.0 * len(intel.critical_symbols_touched)

    # +N selon patterns dangereux
    for _label, count in intel.danger_patterns_hits:
        score += 2.0 * count

    # +3 si scope sensible
    if intel.scope and any(s in intel.scope for s in SENSITIVE_SCOPES):
        score += 3.0

    # +1 par 100 lignes modifiees (cap a +5)
    total_changes = intel.stats.get("insertions", 0) + intel.stats.get("deletions", 0)
    score += min(5.0, total_changes / 100.0)

    # +0.5 par module impacte (cap a +5)
    score += min(5.0, len(intel.modules_impacted) * 0.5)

    # Apprentissage : +0.1 par bug historique dans les fichiers touches
    for _file, n_bugs in intel.file_bug_counts.items():
        score += n_bugs * 0.1

    # Breaking change marker ajoute +4
    # (detection via subject scanne dans analyze_commit)

    return round(score, 1)


# =============================================================================
# LEARNING - historique des bugs par fichier
# =============================================================================


def _build_bug_history() -> dict:
    """
    Parcourt les commits fix() pour compter combien de fois chaque fichier
    a ete touche par un bug fix. Utile pour identifier les zones sensibles.

    Retourne {filepath: bug_count}.
    """
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()
        cur.execute("""
            SELECT meta FROM rag_chunks
            WHERE source LIKE 'git:%:fix'
        """)
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return {}

    bug_count = {}
    for (meta_json,) in rows:
        try:
            meta = json.loads(meta_json)
            # Les modules sont dans meta.modules
            for mod in meta.get("modules", []):
                path = f"app/{mod}.py"
                bug_count[path] = bug_count.get(path, 0) + 1
        except Exception:
            continue
    return bug_count


_BUG_HISTORY_CACHE = None


def get_bug_history(force_refresh: bool = False) -> dict:
    """Cache pour eviter recalcul a chaque commit."""
    global _BUG_HISTORY_CACHE
    if _BUG_HISTORY_CACHE is None or force_refresh:
        _BUG_HISTORY_CACHE = _build_bug_history()
    return _BUG_HISTORY_CACHE


# =============================================================================
# MAIN API : analyze_commit
# =============================================================================


_SUBJECT_RE = re.compile(r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<subj>.+)$")


def analyze_commit(sha: str = "HEAD") -> Optional[CommitIntel]:
    """
    Analyse complete d un commit : AST + scope + impact + risque.

    sha : SHA ou ref (HEAD, HEAD~1, tag, branch).
    """
    # Resoudre sha court en sha complet + metadata
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%H|%ai|%s", sha],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
        if r.returncode != 0 or "|" not in r.stdout:
            return None
        full_sha, date_iso, subject = r.stdout.split("|", 2)
    except Exception:
        return None

    # Parse subject
    m = _SUBJECT_RE.match(subject)
    if m:
        commit_type = m.group("type").lower()
        scope = (m.group("scope") or "").lower()
        breaking = bool(m.group("bang"))
    else:
        commit_type = ""
        scope = ""
        breaking = False

    # Diff stats + fichiers
    stats = _get_diff_stats(full_sha)
    files_changed = _get_changed_files(full_sha)
    py_files = [f for f in files_changed if f.endswith(".py")]

    # Modules modifies
    modules_modified = []
    for f in py_files:
        mm = re.match(r"app/(forge_[\w_]+)\.py", f)
        if mm:
            modules_modified.append(mm.group(1))

    # Analyse AST before/after pour chaque .py modifie
    symbols_added = []
    symbols_removed = []
    symbols_modified = []
    imports_added = set()
    imports_removed = set()
    critical_touched = set()

    parent_sha = full_sha + "~1"
    for path in py_files:
        before_src = _get_file_content_at(parent_sha, path) or ""
        after_src = _get_file_content_at(full_sha, path) or ""

        before_sym = _extract_symbols(before_src)
        after_sym = _extract_symbols(after_src)

        # Symbols ajoutes / retires
        added_fns = after_sym["functions"] - before_sym["functions"]
        removed_fns = before_sym["functions"] - after_sym["functions"]
        added_cls = after_sym["classes"] - before_sym["classes"]
        removed_cls = before_sym["classes"] - after_sym["classes"]

        symbols_added.extend(list(added_fns) + list(added_cls))
        symbols_removed.extend(list(removed_fns) + list(removed_cls))

        # Symbols dont le body a change (present dans les deux mais body different)
        before_bodies = _extract_function_bodies(before_src)
        after_bodies = _extract_function_bodies(after_src)
        common = set(before_bodies) & set(after_bodies)
        for name in common:
            if before_bodies[name] != after_bodies[name]:
                symbols_modified.append(name)

        # Imports
        imports_added.update(after_sym["imports"] - before_sym["imports"])
        imports_removed.update(before_sym["imports"] - after_sym["imports"])

        # Critical symbols
        all_touched = added_fns | removed_fns | added_cls | removed_cls | set(symbols_modified)
        critical_touched.update(all_touched & CRITICAL_SYMBOLS)

    # Patterns dangereux dans le diff
    diff_content = _get_diff_content(full_sha)
    # Ne regarder que les lignes AJOUTEES (+) pour eviter faux positifs sur suppression
    added_lines = "\n".join(
        line for line in diff_content.split("\n") if line.startswith("+") and not line.startswith("+++")
    )
    danger_hits = []
    for pattern, label in DANGEROUS_PATTERNS:
        matches = re.findall(pattern, added_lines)
        if matches:
            danger_hits.append((label, len(matches)))

    # Impact via graph
    impacted = _get_impacted_modules(modules_modified, max_depth=2)

    # Apprentissage : bug history sur les fichiers touches
    bug_hist = get_bug_history()
    file_bugs = {f: bug_hist.get(f, 0) for f in py_files if bug_hist.get(f, 0) > 0}

    # Construire intel
    intel = CommitIntel(
        sha=full_sha,
        short_sha=full_sha[:8],
        subject=subject[:200],
        commit_type=commit_type,
        scope=scope,
        date=date_iso[:10],
        files_modified=files_changed[:20],
        modules_modified=modules_modified,
        symbols_added=list(set(symbols_added))[:20],
        symbols_removed=list(set(symbols_removed))[:20],
        symbols_modified=list(set(symbols_modified))[:20],
        imports_added=sorted(imports_added)[:15],
        imports_removed=sorted(imports_removed)[:15],
        critical_symbols_touched=sorted(critical_touched),
        modules_impacted=impacted,
        danger_patterns_hits=danger_hits,
        risk_score=0.0,  # calcule apres
        risk_level="MINIMAL",
        file_bug_counts=file_bugs,
        stats=stats,
    )

    # Breaking change si marque
    if breaking:
        intel.risk_score += 4.0

    # Scoring final
    intel.risk_score = _score_risk(intel) + (4.0 if breaking else 0.0)
    intel.risk_level = risk_level(intel.risk_score)

    return intel


# =============================================================================
# PERSISTENCE
# =============================================================================


def _ensure_commit_intel_table() -> None:
    """Cree la table commit_intel si absente."""
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS commit_intel (
                sha TEXT PRIMARY KEY,
                short_sha TEXT,
                subject TEXT,
                commit_type TEXT,
                scope TEXT,
                date TEXT,
                modules_modified TEXT,       -- JSON
                symbols_added TEXT,           -- JSON
                symbols_modified TEXT,        -- JSON
                critical_symbols TEXT,        -- JSON
                modules_impacted TEXT,        -- JSON
                danger_patterns TEXT,         -- JSON
                risk_score REAL,
                risk_level TEXT,
                stats TEXT,                   -- JSON
                analyzed_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ci_risk ON commit_intel(risk_level)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ci_scope ON commit_intel(scope)")
        conn.commit()
        conn.close()
    except Exception:
        pass


def store_intel(intel: CommitIntel) -> bool:
    """Persiste un CommitIntel dans la table commit_intel (idempotent)."""
    _ensure_commit_intel_table()
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "INSERT OR REPLACE INTO commit_intel "
            "(sha, short_sha, subject, commit_type, scope, date, "
            " modules_modified, symbols_added, symbols_modified, critical_symbols, "
            " modules_impacted, danger_patterns, risk_score, risk_level, stats) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                intel.sha,
                intel.short_sha,
                intel.subject,
                intel.commit_type,
                intel.scope,
                intel.date,
                json.dumps(intel.modules_modified),
                json.dumps(intel.symbols_added),
                json.dumps(intel.symbols_modified),
                json.dumps(intel.critical_symbols_touched),
                json.dumps(intel.modules_impacted),
                json.dumps(intel.danger_patterns_hits),
                intel.risk_score,
                intel.risk_level,
                json.dumps(intel.stats),
            ),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[commit_intel] store failed: {e}")
        return False


# =============================================================================
# BATCH API
# =============================================================================


def analyze_range(since: str = "HEAD~20", limit: int = 100) -> list:
    """Analyse plusieurs commits en batch. Idempotent."""
    try:
        r = subprocess.run(
            ["git", "log", f"{since}..HEAD", "--pretty=format:%H", f"-{limit}"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        shas = [s.strip() for s in r.stdout.split("\n") if s.strip()]
    except Exception:
        return []

    results = []
    for sha in shas:
        intel = analyze_commit(sha)
        if intel:
            results.append(intel)
    return results


def analyze_last_n(n: int = 20) -> list:
    """Les N derniers commits."""
    try:
        r = subprocess.run(
            ["git", "log", "--pretty=format:%H", f"-{n}"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        shas = [s.strip() for s in r.stdout.split("\n") if s.strip()]
    except Exception:
        return []
    return [analyze_commit(sha) for sha in shas if analyze_commit(sha)]


# =============================================================================
# QUERY API - pour preflight et pre-push
# =============================================================================


def get_risk(sha: str = "HEAD") -> dict:
    """Retourne {sha, risk_score, risk_level, critical, reasons} pour une decision rapide."""
    intel = analyze_commit(sha)
    if not intel:
        return {"sha": sha, "risk_score": 0, "risk_level": "UNKNOWN", "error": "could not analyze"}

    reasons = []
    if intel.critical_symbols_touched:
        reasons.append(f"critical symbols : {', '.join(intel.critical_symbols_touched[:5])}")
    if intel.danger_patterns_hits:
        patterns = [f"{label}({n})" for label, n in intel.danger_patterns_hits]
        reasons.append(f"danger patterns : {', '.join(patterns)}")
    if intel.scope and any(s in intel.scope for s in SENSITIVE_SCOPES):
        reasons.append(f"scope sensible : {intel.scope}")
    if intel.file_bug_counts:
        top = sorted(intel.file_bug_counts.items(), key=lambda x: -x[1])[:3]
        reasons.append(f"zones sensibles : {', '.join(f'{f}({n})' for f, n in top)}")
    if intel.modules_impacted:
        reasons.append(f"impact transitif : {len(intel.modules_impacted)} modules")

    return {
        "sha": intel.short_sha,
        "subject": intel.subject[:80],
        "risk_score": intel.risk_score,
        "risk_level": intel.risk_level,
        "reasons": reasons,
        "critical_symbols": intel.critical_symbols_touched,
        "modules_modified": intel.modules_modified,
        "modules_impacted": intel.modules_impacted,
        "stats": intel.stats,
    }


# =============================================================================
# CLI
# =============================================================================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", default="HEAD", help="SHA a analyser")
    parser.add_argument("--last", type=int, default=0, help="Analyse les N derniers commits")
    parser.add_argument("--store", action="store_true", help="Persiste dans commit_intel table")
    parser.add_argument("--json", action="store_true", help="Sortie JSON")
    parser.add_argument(
        "--filter-risk",
        type=str,
        default=None,
        help="Ne montre que les commits de ce niveau (MINIMAL, LOW, MEDIUM, HIGH, CRITICAL)",
    )
    args = parser.parse_args()

    intels = []
    if args.last > 0:
        intels = analyze_last_n(args.last)
    else:
        intel = analyze_commit(args.sha)
        if intel:
            intels = [intel]

    if not intels:
        print(f"Aucun intel a analyser pour '{args.sha}'")
        sys.exit(1)

    # Filtre risque
    if args.filter_risk:
        intels = [i for i in intels if i.risk_level == args.filter_risk.upper()]

    if args.json:
        out = []
        for i in intels:
            out.append(
                {
                    "sha": i.short_sha,
                    "subject": i.subject,
                    "scope": i.scope,
                    "risk_score": i.risk_score,
                    "risk_level": i.risk_level,
                    "modules_modified": i.modules_modified,
                    "modules_impacted": i.modules_impacted,
                    "critical_symbols": i.critical_symbols_touched,
                    "danger_patterns": i.danger_patterns_hits,
                    "stats": i.stats,
                }
            )
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"\n=== Analyse de {len(intels)} commit(s) ===\n")
        for i in intels:
            marker = {"MINIMAL": ".", "LOW": "-", "MEDIUM": "*", "HIGH": "!", "CRITICAL": "!!"}.get(i.risk_level, "?")
            print(
                f"{marker} [{i.risk_level:<8} score={i.risk_score:>5.1f}] {i.short_sha} {i.commit_type}"
                + (f"({i.scope})" if i.scope else "")
                + f" : {i.subject[:70]}"
            )
            if i.modules_modified:
                print(f"    modules modified : {', '.join(i.modules_modified[:5])}")
            if i.modules_impacted:
                print(f"    impact transitif : {', '.join(i.modules_impacted[:5])}")
            if i.critical_symbols_touched:
                print(f"    CRITICAL symbols : {', '.join(i.critical_symbols_touched[:5])}")
            if i.danger_patterns_hits:
                print(f"    danger patterns  : {', '.join(f'{l}({n})' for l, n in i.danger_patterns_hits)}")
            if i.file_bug_counts:
                top = sorted(i.file_bug_counts.items(), key=lambda x: -x[1])[:3]
                print(f"    zones sensibles  : {', '.join(f'{f}(bugs={n})' for f, n in top)}")

    if args.store:
        stored = sum(1 for i in intels if store_intel(i))
        print(f"\n{stored}/{len(intels)} intels persistes dans commit_intel")
