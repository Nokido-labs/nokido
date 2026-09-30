"""
app/forge_clawhub_autoinstall.py — ClawHub Auto-Install on-demand
================================================================

Installe a la volee des skills ClawHub pertinents pour une intention donnee.
Utilise un scoring simple (mots-cles + TF-IDF naif) pour trouver les 3 meilleurs
matches dans le catalogue de 627 skills, puis telecharge et indexe dans le RAG.

Usage :
    from forge_clawhub_autoinstall import suggest_skills, install_skill

    # Proposer 3 skills pour une intention
    matches = suggest_skills("audit kubernetes RBAC", top_k=3)
    # matches = [("k8s-security-audit", 8.5, "..."), ...]

    # Installer un skill specifique
    install_skill("k8s-security-audit", audit=True, index_rag=True)

Le downloader utilise l'API ClawHub /skills/{slug} + SkillGuardian pour auditer
avant installation (patterns dangereux eval/exec/os.system -> quarantaine).
"""

from __future__ import annotations

import os
import json
import re
import hashlib
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills" / "clawhub"
CATALOG_PATH = ROOT / "sandbox" / "clawhub_catalog.json"
RAG_DB = ROOT / "RAG" / "embeddings.db"
CLAWHUB_API = "https://clawhub.ai/api/v1"


# ── Catalogue ────────────────────────────────────────────────────────────────


def load_catalog() -> dict:
    """Charge le catalogue local (627 skills). Re-collecte si absent/ancien."""
    if CATALOG_PATH.exists():
        age_days = (datetime.now().timestamp() - CATALOG_PATH.stat().st_mtime) / 86400
        if age_days < 7:
            return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return refresh_catalog()


def refresh_catalog() -> dict:
    """Re-enumere les skills distants via /search thematique."""
    queries = [
        "pentest",
        "recon",
        "web",
        "sql",
        "xss",
        "ssrf",
        "exploit",
        "crypto",
        "reverse",
        "malware",
        "forensic",
        "osint",
        "docker",
        "kubernetes",
        "cloud",
        "aws",
        "azure",
        "python",
        "bash",
        "javascript",
        "typescript",
        "go",
        "rust",
        "java",
        "ai",
        "llm",
        "rag",
        "code",
        "review",
        "test",
        "debug",
        "security",
        "audit",
        "api",
        "jwt",
        "auth",
        "password",
        "hash",
        "binary",
        "ctf",
        "redteam",
        "blueteam",
        "devops",
        "ci",
        "terraform",
        "ansible",
        "monitoring",
        "log",
        "analysis",
        "ml",
        "data",
        "mongodb",
        "postgres",
        "redis",
        "mobile",
        "android",
        "ios",
        "hardware",
        "iot",
        "embedded",
        "firmware",
        "report",
        "documentation",
        "writing",
        "translate",
        "refactor",
        "git",
        "github",
        "gitlab",
        "nmap",
        "burp",
        "metasploit",
        "wireshark",
        "ghidra",
        "ida",
        "radare",
        "frontend",
        "backend",
        "database",
        "xxe",
        "deserialize",
        "prototype",
        "sql-injection",
        "csrf",
    ]
    all_skills: dict[str, dict] = {}
    for q in queries:
        try:
            url = f"{CLAWHUB_API}/search?q={urllib.parse.quote(q)}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                j = json.loads(resp.read())
            for r in j.get("results", []):
                slug = r.get("slug")
                if slug and slug not in all_skills:
                    all_skills[slug] = {
                        "name": r.get("displayName", slug),
                        "summary": r.get("summary") or "",
                        "score": r.get("score", 0),
                    }
        except Exception:
            continue
    CATALOG_PATH.parent.mkdir(exist_ok=True)
    CATALOG_PATH.write_text(json.dumps(all_skills, indent=2, ensure_ascii=False), encoding="utf-8")
    return all_skills


# ── Scoring ──────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Tokenise naivement : alphanum minuscule, mots >= 3 chars."""
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) >= 3]


def _score_skill(slug: str, skill: dict, query_tokens: set[str]) -> float:
    """Score de pertinence skill vs tokens requete. TF-IDF naif."""
    doc_text = f"{slug} {skill.get('name', '')} {skill.get('summary', '')}".lower()
    doc_tokens = _tokenize(doc_text)
    if not doc_tokens:
        return 0.0
    matches = sum(1 for t in query_tokens if t in doc_tokens)
    if matches == 0:
        return 0.0
    # Bonus si slug contient directement un des tokens
    slug_bonus = sum(2 for t in query_tokens if t in slug.lower())
    # Bonus bigrams dans summary
    summary = skill.get("summary", "").lower()
    bigram_bonus = sum(1.5 for t in query_tokens for t2 in query_tokens if t != t2 and f"{t} {t2}" in summary)
    return matches + slug_bonus + bigram_bonus


def suggest_skills(intention: str, top_k: int = 3, exclude_installed: bool = True) -> list[tuple[str, float, str]]:
    """Retourne les top_k skills les plus pertinents pour l'intention.

    Returns:
        [(slug, score, summary_short), ...]
    """
    catalog = load_catalog()

    # Exclure deja installes
    if exclude_installed and SKILLS_DIR.exists():
        installed = {d.name for d in SKILLS_DIR.iterdir() if d.is_dir()}
        catalog = {k: v for k, v in catalog.items() if k not in installed}

    query_tokens = set(_tokenize(intention))
    # Ajouter des synonymes courants
    synonyms = {
        "k8s": ["kubernetes"],
        "aws": ["cloud"],
        "db": ["database"],
        "auth": ["authentication"],
        "perf": ["performance"],
        "wifi": ["wireless", "network"],
        "sec": ["security"],
    }
    for t in list(query_tokens):
        query_tokens.update(synonyms.get(t, []))

    scored = []
    for slug, skill in catalog.items():
        score = _score_skill(slug, skill, query_tokens)
        if score > 0:
            scored.append((slug, score, skill.get("summary", "")[:120]))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ── Installation ─────────────────────────────────────────────────────────────


def _sanity_check_skill(content: dict) -> tuple[bool, str]:
    """SkillGuardian leger : detecte patterns dangereux dans le contenu brut."""
    dangerous_patterns = [
        (r"\beval\s*\(", "eval() direct"),
        (r"\bexec\s*\(", "exec() direct"),
        (r"os\.system\s*\(", "os.system"),
        (r"subprocess\.call\s*\(\s*[\"']rm\s+-rf", "rm -rf"),
        (r"requests\.post.*password", "POST password exfil"),
    ]
    full_text = json.dumps(content, ensure_ascii=False).lower()
    for pat, desc in dangerous_patterns:
        if re.search(pat, full_text):
            return False, f"Pattern dangereux: {desc}"
    return True, "clean"


def install_skill(slug: str, index_rag: bool = True, audit: bool = True) -> dict:
    """Download + audit + install d'un skill ClawHub.

    Returns:
        {ok: bool, slug, files_count, chunks_indexed, message}
    """
    result = {"ok": False, "slug": slug, "files_count": 0, "chunks_indexed": 0, "message": ""}

    # 1. Fetch skill content depuis l'API
    try:
        url = f"{CLAWHUB_API}/skills/{slug}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            skill_data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result["message"] = f"Skill '{slug}' introuvable (API 404)"
            return result
        result["message"] = f"HTTP {e.code}: {e.read().decode()[:100]}"
        return result
    except Exception as e:
        result["message"] = f"Fetch err: {type(e).__name__}: {e}"
        return result

    # 2. Audit
    if audit:
        ok, reason = _sanity_check_skill(skill_data)
        if not ok:
            result["message"] = f"REJET audit : {reason}"
            return result

    # 3. Creer dossier skill
    skill_dir = SKILLS_DIR / slug
    skill_dir.mkdir(parents=True, exist_ok=True)

    # 4. Sauver metadata + content
    meta = {
        "name": skill_data.get("displayName", slug),
        "description": skill_data.get("summary", ""),
        "version": skill_data.get("version", "1.0.0"),
        "author": skill_data.get("author", "clawhub"),
        "installed_at": datetime.now().isoformat(),
    }
    (skill_dir / "_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Le contenu peut etre dans "content", "files", "skill", "instructions"
    files_written = 0
    content = skill_data.get("content") or skill_data.get("skill") or skill_data.get("instructions") or ""
    if isinstance(content, str) and content:
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
        files_written = 1
    elif isinstance(content, list):
        for i, entry in enumerate(content):
            if isinstance(entry, dict):
                fname = entry.get("filename", f"part_{i}.md")
                text = entry.get("content", "") or entry.get("text", "")
                (skill_dir / fname).write_text(text, encoding="utf-8")
                files_written += 1
    elif isinstance(content, dict):
        for fname, text in content.items():
            safe_fname = re.sub(r"[^a-zA-Z0-9_.-]", "_", fname)
            if not safe_fname.endswith(".md"):
                safe_fname += ".md"
            (skill_dir / safe_fname).write_text(str(text), encoding="utf-8")
            files_written += 1

    result["files_count"] = files_written

    # 5. Mettre a jour index.json
    idx_path = SKILLS_DIR / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    idx[slug] = {**meta, "rag_indexed": index_rag, "local_status": "clean"}
    idx_path.write_text(json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8")

    # 6. Indexer dans RAG (chunks par fichier .md)
    if index_rag and RAG_DB.exists():
        chunks_added = _index_skill_in_rag(slug, skill_dir)
        result["chunks_indexed"] = chunks_added

    result["ok"] = True
    result["message"] = f"✅ Skill '{slug}' installe ({files_written} fichiers)"
    return result


def _index_skill_in_rag(slug: str, skill_dir: Path) -> int:
    """Indexe les fichiers .md d'un skill dans rag_chunks. Retourne count."""
    conn = sqlite3.connect(str(RAG_DB), timeout=10)
    cur = conn.cursor()

    # Domain mapping heuristique
    domain = "security"
    if any(k in slug for k in ("pwn", "exploit", "payload")):
        domain = "exploit"
    elif any(k in slug for k in ("recon", "nmap", "osint")):
        domain = "recon"
    elif any(k in slug for k in ("code", "review", "refactor", "python")):
        domain = "code"
    elif any(k in slug for k in ("doc", "write", "report")):
        domain = "doc"

    inserted = 0
    for md in skill_dir.glob("*.md"):
        content = md.read_text(encoding="utf-8", errors="replace")
        if len(content.strip()) < 100:
            continue
        source_base = f"skills/clawhub/{slug}/{md.name}"
        # Check if already indexed
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE source LIKE ?", (f"{source_base}#%",))
        if cur.fetchone()[0] > 0:
            continue
        # Chunks ~800 chars
        chunks = []
        curbuf, curlen = [], 0
        for para in content.split("\n\n"):
            if curlen + len(para) > 800 and curbuf:
                chunks.append("\n\n".join(curbuf))
                curbuf, curlen = [para], len(para)
            else:
                curbuf.append(para)
                curlen += len(para) + 2
        if curbuf:
            chunks.append("\n\n".join(curbuf))
        ts = datetime.now().isoformat()
        for i, ch_text in enumerate(chunks):
            chunk_id = f"skill_{slug}_{md.stem}_{i}"
            ch_hash = hashlib.sha256(ch_text.encode()).hexdigest()[:16]
            try:
                cur.execute(
                    """
                    INSERT INTO rag_chunks 
                    (id, text, source, domain, role_hint, embedding, meta,
                     ingested_at, author, hash, indexed_at)
                    VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                    (
                        chunk_id,
                        ch_text,
                        f"{source_base}#chunk{i}",
                        domain,
                        "skill",
                        json.dumps({"skill": slug, "file": md.name}),
                        ts,
                        "clawhub",
                        ch_hash,
                        ts,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                continue
    conn.commit()
    conn.close()
    return inserted


# ── Import helper ────────────────────────────────────────────────────────────


def autoinstall_from_intention(
    intention: str, top_k: int = 3, auto_install: bool = False, min_score: float = 1.5
) -> dict:
    """Workflow complet : suggest + (optionnel) install.

    Args:
        intention: L'intention textuelle
        top_k: Nombre de suggestions
        auto_install: Si True, installe automatiquement les matches
        min_score: Score minimum pour proposer un skill

    Returns:
        {suggestions: [...], installed: [...]}
    """
    matches = suggest_skills(intention, top_k=top_k)
    matches = [(s, sc, sm) for s, sc, sm in matches if sc >= min_score]

    result = {
        "intention": intention,
        "suggestions": [{"slug": s, "score": round(sc, 2), "summary": sm} for s, sc, sm in matches],
        "installed": [],
    }

    if auto_install and matches:
        for slug, _, _ in matches:
            install_result = install_skill(slug)
            result["installed"].append(install_result)

    return result


# ── CLI rapide ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python forge_clawhub_autoinstall.py '<intention>' [--install]")
        sys.exit(1)
    intention = sys.argv[1]
    do_install = "--install" in sys.argv
    r = autoinstall_from_intention(intention, auto_install=do_install)
    print(json.dumps(r, indent=2, ensure_ascii=False))
