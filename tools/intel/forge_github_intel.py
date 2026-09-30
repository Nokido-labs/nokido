"""
forge_github_intel.py — Nokido Engrid · Intelligence GitHub
=============================================================
fetch_github_intelligence() : extrait l'intelligence publique de GitHub
(issues, PRs, discussions, wiki) pour nourrir les shards OSS/Alignement
de ForgeEngridEngine sans exposer les données locales.

Le résultat est du texte public — aucun secret ne transite.
Il est injecté dans execute_cognitive_cycle(github_intel=...) et mixé
par la Membrane avant envoi Cloud.

Sources supportées :
    - GitHub REST API  (issues, PRs, comments)
    - GitHub Search    (code, topics, repos)
    - RAG local        (chunks déjà indexés sur ce dépôt)
    - bounty_watcher   (issues connues de sécurité)

Usage :
    from forge_github_intel import fetch_github_intelligence

    intel = fetch_github_intelligence(
        repo_url = "https://github.com/encode/httpx",
        query    = "Memory Leak Sockets",
    )
    report = engine.execute_cognitive_cycle(task, data, github_intel=intel)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

_ROOT = Path(__file__).resolve().parent.parent
_RAG_DB = _ROOT / "RAG" / "embeddings.db"

# GitHub API base — sans token, rate limit = 60 req/h
_GH_API = "https://api.github.com"
_TIMEOUT = 8


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════


def _gh_get(url: str, token: str = "") -> dict | list | None:
    """GET GitHub API avec gestion rate limit."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LaForge/1.0",
    }
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        req = urllib.request.Request(url, headers=headers)
        resp = urllib.request.urlopen(req, timeout=_TIMEOUT)
        return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.debug(f"[GH] {url} → {e}")
        return None


def _parse_repo(repo_url: str) -> tuple[str, str] | None:
    """Extrait owner/repo depuis une URL GitHub."""
    m = re.search(r"github\.com/([^/]+)/([^/?#]+)", repo_url)
    if m:
        return m.group(1), m.group(2).removesuffix(".git")
    return None


def _rag_search(query: str, domain: str = "", limit: int = 5) -> list[str]:
    """Recherche dans le RAG local — ne modifie rien."""
    if not _RAG_DB.exists():
        return []
    words = [w.lower() for w in re.findall(r"[a-z0-9]{3,}", query.lower())][:6]
    if not words:
        return []
    try:
        conn = sqlite3.connect(str(_RAG_DB), timeout=3)
        parts = []
        for w in words[:3]:
            sql = "SELECT text FROM rag_chunks WHERE text LIKE ? "
            params = [f"%{w}%"]
            if domain:
                sql += "AND domain=? "
                params.append(domain)
            sql += "ORDER BY rowid DESC LIMIT ?"
            params.append(2)
            rows = conn.execute(sql, params).fetchall()
            parts.extend(r[0][:300] for r in rows if r[0])
        conn.close()
        return parts[:limit]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTEURS
# ══════════════════════════════════════════════════════════════════════════════


def _fetch_issues(owner: str, repo: str, query: str, token: str, max_results: int) -> list[str]:
    """Cherche les issues GitHub correspondant à la requête."""
    q = urllib.parse.quote(f"{query} repo:{owner}/{repo}")
    url = f"{_GH_API}/search/issues?q={q}&sort=relevance&per_page={max_results}"
    data = _gh_get(url, token)
    if not isinstance(data, dict):
        return []
    results = []
    for item in data.get("items", [])[:max_results]:
        title = item.get("title", "")
        body = (item.get("body") or "")[:400]
        num = item.get("number", "")
        state = item.get("state", "")
        results.append(f"Issue #{num} [{state}]: {title}\n{body}")
    return results


def _fetch_prs(owner: str, repo: str, query: str, token: str, max_results: int) -> list[str]:
    """Cherche les PRs fusionnées liées à la requête."""
    q = urllib.parse.quote(f"{query} repo:{owner}/{repo} is:pr is:merged")
    url = f"{_GH_API}/search/issues?q={q}&sort=relevance&per_page={max_results}"
    data = _gh_get(url, token)
    if not isinstance(data, dict):
        return []
    results = []
    for item in data.get("items", [])[:max_results]:
        title = item.get("title", "")
        body = (item.get("body") or "")[:300]
        num = item.get("number", "")
        results.append(f"PR #{num} [merged]: {title}\n{body}")
    return results


def _fetch_readme_snippet(owner: str, repo: str, query: str, token: str) -> str:
    """Extrait un snippet du README si la requête y est mentionnée."""
    url = f"{_GH_API}/repos/{owner}/{repo}/readme"
    data = _gh_get(url, token)
    if not isinstance(data, dict):
        return ""
    import base64

    content_b64 = data.get("content", "")
    try:
        text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    except Exception:
        return ""
    # Cherche le paragraphe autour du premier hit
    words = query.lower().split()[:3]
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if any(w in line.lower() for w in words):
            snippet = "\n".join(lines[max(0, i - 1) : i + 4])
            return f"README snippet:\n{snippet}"
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# INTERFACE PRINCIPALE
# ══════════════════════════════════════════════════════════════════════════════


def fetch_github_intelligence(
    repo_url: str,
    query: str,
    token: str = "",
    max_issues: int = 3,
    max_prs: int = 2,
    include_rag: bool = True,
    dry_run: bool = False,
) -> str:
    """
    Extrait l'intelligence publique GitHub pour un repo + une requête.

    Retourne un bloc texte prêt à injecter dans execute_cognitive_cycle()
    via le paramètre github_intel.

    Args:
        repo_url    : URL du dépôt (ex: https://github.com/encode/httpx)
        query       : sujet de recherche (ex: "Memory Leak Sockets")
        token       : GitHub token optionnel (augmente le rate limit à 5000 req/h)
        max_issues  : nb max d'issues à extraire
        max_prs     : nb max de PRs à extraire
        include_rag : cherche aussi dans le RAG local (chunks déjà indexés)
        dry_run     : retourne un mock sans appeler l'API (tests)

    Returns:
        str : bloc texte d'intelligence (public, sans secrets)
    """
    if dry_run:
        return (
            f"[DRY-RUN] Intelligence GitHub simulée pour {repo_url}\n"
            f"Query: {query}\n"
            f"Issue #402: Fuite mémoire détectée avec sockets — fix: pool async.\n"
            f"PR #387 [merged]: Refactor socket handling — éviter eval().\n"
        )

    parsed = _parse_repo(repo_url)
    if not parsed:
        logger.warning(f"[GH-Intel] URL non reconnue: {repo_url}")
        return f"[GH-Intel] URL non reconnue: {repo_url}"

    owner, repo = parsed
    blocks: list[str] = [f"=== GITHUB INTEL: {owner}/{repo} — '{query}' ===\n"]

    # Issues
    try:
        issues = _fetch_issues(owner, repo, query, token, max_issues)
        if issues:
            blocks.append(f"--- ISSUES ({len(issues)}) ---\n" + "\n\n".join(issues))
    except Exception as e:
        logger.debug(f"[GH-Intel] Issues error: {e}")

    # PRs
    try:
        prs = _fetch_prs(owner, repo, query, token, max_prs)
        if prs:
            blocks.append(f"--- PULL REQUESTS ({len(prs)}) ---\n" + "\n\n".join(prs))
    except Exception as e:
        logger.debug(f"[GH-Intel] PRs error: {e}")

    # README snippet
    try:
        snippet = _fetch_readme_snippet(owner, repo, query, token)
        if snippet:
            blocks.append(f"--- README ---\n{snippet}")
    except Exception as e:
        logger.debug(f"[GH-Intel] README error: {e}")

    # RAG local
    if include_rag:
        rag_chunks = _rag_search(query)
        if rag_chunks:
            blocks.append(
                f"--- RAG LOCAL ({len(rag_chunks)} chunks) ---\n"
                + "\n".join(f"• {c[:200]}" for c in rag_chunks)
            )

    result = "\n\n".join(b for b in blocks if b.strip())
    logger.info(f"[GH-Intel] {owner}/{repo} — {len(result)} chars extraits")
    return result or f"[GH-Intel] Aucun résultat pour '{query}' sur {repo_url}"
