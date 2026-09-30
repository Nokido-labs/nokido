# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_git_historian
#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: reconstruire l historique technique depuis Git sans dupliquer le code existant
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:85|agent:claude-mcp|temp:0.00|risk:0.20|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"
"""
app/forge_git_historian.py - Historien Git semantique pour Nokido
====================================================================

Resout le probleme : la memoire technique s est perdue entre sessions car
le raisonnement derriere chaque changement n etait pas persiste. Git contient
pourtant TOUT l historique signe, horodate, auditable.

Ce module scanne git log et extrait la SUBSTANTIFIQUE MOELLE de chaque
commit significatif :
  - Intention (subject Conventional Commits parse)
  - Pourquoi (body, contraintes, alternatives ecartees)
  - Quoi (fichiers modifies groupes par module)
  - Consequences (tests, rollback, dette)

Filtre pragmatique : indexe seulement les commits qui contiennent une
decision technique (feat/fix/refactor avec body >= 80 chars). Skip les
chore/docs/merge/bump/version sans importance.

Strategies de stockage :
  1. ADR candidates -> adr_records (deja existant, 14 entrees au 2026-04-16)
  2. Commit snapshots -> rag_chunks avec source 'git:<sha>:<type>' pour
     preflight_check et FTS5
  3. Module co-change graph -> rag_graph_edges pour "si tu touches X,
     historique montre que Y est souvent co-modifie"

Idempotent : table git_historian_state garde last_sha traite. Relance
incrementale possible tous les jours / apres chaque push.

API :
  extract_commits(since_sha=None, limit=50) -> list[CommitIntel]
  index_commits(commits) -> {indexed, skipped, adr_created}
  run_full(limit=200) -> rapport complet
  get_last_processed() -> last_sha processe par run precedent

Usage CLI :
  python -m app.forge_git_historian --since v17.0.0
  python -m app.forge_git_historian --limit 50

Usage programmatique :
  from forge_git_historian import GitHistorian
  h = GitHistorian()
  report = h.run_full(limit=100)
  print(f"{report['indexed']} commits indexes, {report['adr_created']} ADR crees")
"""

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


# Types Conventional Commits avec poids "interet architectural"
# Plus le poids est haut, plus on veut indexer en detail
TYPE_WEIGHTS = {
    "feat": 1.0,  # nouvelle fonctionnalite - tres interessant
    "fix": 0.8,  # bug fix - interesse (raisonnement)
    "refactor": 1.0,  # refonte - tres interessant
    "refacto": 1.0,  # variante orthographique
    "perf": 0.9,  # optimisation - interessant
    "docs": 0.4,  # doc - peu d interet sauf gros corps
    "doc": 0.4,
    "test": 0.3,  # tests seuls - faible interet
    "chore": 0.1,  # bumps, deps - skip
    "ci": 0.2,
    "style": 0.1,  # cosmetic - skip
    "build": 0.2,
    "revert": 0.9,  # important a tracer
}

# Seuil minimal pour indexer un commit (body * type_weight)
MIN_INTEL_SCORE = 60.0  # body >=60 chars apres application du poids

# Nombre max de fichiers listes par commit (evite bruit sur les gros refactors)
MAX_FILES_IN_INTEL = 15


# ============================================================================
# DATA STRUCTURES
# ============================================================================


@dataclass
class CommitIntel:
    """Substantifique moelle d un commit."""

    sha: str
    short_sha: str
    author: str
    date_iso: str
    commit_type: str  # feat/fix/refactor/...
    scope: str  # router / rag / etc. (entre parentheses)
    subject: str  # apres le ":"
    body: str  # corps, tronque a 2000 chars max
    files: list  # fichiers touches (max 15)
    modules: list  # modules app/forge_*.py extraits
    breaking: bool  # "!" ou "BREAKING CHANGE"
    score: float  # interest score (type_weight * body_len)

    def to_rag_text(self) -> str:
        """Format compact pour indexation RAG."""
        parts = [
            f"COMMIT {self.short_sha} {self.commit_type}"
            + (f"({self.scope})" if self.scope else "")
            + ("!" if self.breaking else "")
            + f": {self.subject}",
            f"DATE: {self.date_iso}",
            f"AUTEUR: {self.author}",
        ]
        if self.body:
            parts.append(f"POURQUOI: {self.body[:1500]}")
        if self.modules:
            parts.append(f"MODULES TOUCHES: {', '.join(self.modules[:10])}")
        elif self.files:
            parts.append(f"FICHIERS: {', '.join(self.files[:10])}")
        return "\n".join(parts)


# ============================================================================
# STATE - idempotence via table dediee
# ============================================================================


def _ensure_state_table() -> None:
    """Cree git_historian_state si absente. Idempotent."""
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS git_historian_state (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                last_sha    TEXT,
                last_run_at TEXT DEFAULT (datetime('now')),
                indexed_n   INTEGER DEFAULT 0,
                skipped_n   INTEGER DEFAULT 0,
                adr_created INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_last_processed() -> Optional[str]:
    """Retourne le last_sha de la derniere execution, ou None si premiere fois."""
    _ensure_state_table()
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.execute("SELECT last_sha FROM git_historian_state ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def _save_state(last_sha: str, indexed: int, skipped: int, adr_created: int) -> None:
    """Persiste l etat de la derniere run."""
    _ensure_state_table()
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute(
            "INSERT INTO git_historian_state (last_sha, indexed_n, skipped_n, adr_created) VALUES (?,?,?,?)",
            (last_sha, indexed, skipped, adr_created),
        )
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).error(
            "[historien] etat NON sauvegarde (%s: %s) — dernier sha %s | consequence: "
            "la prochaine passe repartira d'un point PERIME et re-indexera ou sautera "
            "des commits sans que le compte ne le montre",
            type(e).__name__, str(e)[:80], str(last_sha)[:12])


# ============================================================================
# EXTRACTION
# ============================================================================


_SUBJECT_RE = re.compile(r"^(?P<type>\w+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<subj>.+)$")


def _parse_subject(subject: str) -> tuple[str, str, bool, str]:
    """Parse Conventional Commit header. Retourne (type, scope, breaking, subject_clean)."""
    m = _SUBJECT_RE.match(subject)
    if not m:
        return ("", "", False, subject)
    return (
        m.group("type").lower(),
        (m.group("scope") or "").lower(),
        bool(m.group("bang")) or "BREAKING CHANGE" in subject,
        m.group("subj").strip(),
    )


def _extract_modules(files: list) -> list:
    """Extrait les noms de modules app/forge_*.py depuis une liste de fichiers."""
    modules = []
    for f in files:
        if not f:
            continue
        m = re.match(r"app/(forge_[\w_]+)\.py", f)
        if m and m.group(1) not in modules:
            modules.append(m.group(1))
    return modules


def extract_commits(since_sha: Optional[str] = None, limit: int = 200) -> list[CommitIntel]:
    """
    Appelle git log et parse les commits en CommitIntel.

    since_sha : si fourni, extrait depuis ce sha (exclu). None = depuis HEAD~limit.
    limit : max de commits a extraire.
    """
    fmt = "%H%x09%an%x09%ai%x09%s%x09%b"
    sep = "\x1e"

    cmd = ["git", "log", "--pretty=format:" + fmt + sep, "--name-only"]
    if since_sha:
        cmd.append(f"{since_sha}..HEAD")
    else:
        cmd.append(f"-{limit}")

    try:
        r = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as e:
        print(f"[historian] git log failed: {e}")
        return []

    if r.returncode != 0:
        print(f"[historian] git log rc={r.returncode}: {r.stderr[:200]}")
        return []

    commits = []
    raw_chunks = [x for x in r.stdout.split(sep) if x.strip()]

    for chunk in raw_chunks:
        import re as _re

        m = _re.search(r"([0-9a-f]{40})\t", chunk)
        if not m:
            continue
        sha = m.group(1)
        rest = chunk[m.end() :]
        tab_split = rest.split("\t", 3)  # author, date, subject, body+files
        if len(tab_split) < 3:
            continue
        author = tab_split[0].strip()
        date_iso = tab_split[1].strip()
        subject = tab_split[2].strip()
        body_and_files = tab_split[3] if len(tab_split) > 3 else ""

        # Separer body et fichiers : git log --name-only termine par une liste de paths
        # precedee d une ligne vide. On scan depuis la fin pour identifier la section files.
        # C est fiable : les paths ont une extension dans le basename OU commencent par un dossier connu.
        text_bf = body_and_files.rstrip()
        file_lines = []
        body = ""
        if text_bf:
            _lines_bf = text_bf.split("\n")
            _body_end = len(_lines_bf)
            for _i in range(len(_lines_bf) - 1, -1, -1):
                _s = _lines_bf[_i].strip()
                if not _s:
                    if file_lines:
                        _body_end = _i
                        break
                    continue
                _is_path = (
                    ("/" in _s or "\\" in _s)
                    and " " not in _s
                    and not _s.startswith(("-", "*", "#", ">", "|"))
                    and (
                        "." in _s.split("/")[-1].split("\\")[-1]
                        or _s.startswith(
                            (
                                "app/",
                                "tools/",
                                "docs/",
                                "tests/",
                                "sandbox/",
                                "recon_silo/",
                                "scripts/",
                                "app\\",
                                "tools\\",
                            )
                        )
                    )
                )
                if _is_path:
                    file_lines.insert(0, _s)
                else:
                    _body_end = _i + 1
                    break
            body = "\n".join(_lines_bf[:_body_end]).strip()

        commit_type, scope, breaking, subject_clean = _parse_subject(subject)

        # Filtrage : skip si type non liste ou non identifiable
        weight = TYPE_WEIGHTS.get(commit_type, 0.0)
        if weight == 0.0 and commit_type not in ("initial", ""):
            continue

        # Score d interet : weight * min(body_len, 500) / 5
        body_factor = min(len(body), 500) / 5.0
        score = weight * max(10.0, body_factor)

        if score < MIN_INTEL_SCORE:
            continue

        # Filtrer fichiers significatifs (app/, tools/, docs/, *.md)
        meaningful = [
            f
            for f in file_lines
            if f.startswith(("app/", "tools/", "docs/", "tests/"))
            or f.endswith((".md", ".py", ".yml", ".yaml", ".json", ".env"))
        ]
        meaningful = meaningful[:MAX_FILES_IN_INTEL]

        modules = _extract_modules(meaningful)

        commits.append(
            CommitIntel(
                sha=sha,
                short_sha=sha[:8],
                author=author,
                date_iso=date_iso[:10],
                commit_type=commit_type,
                scope=scope,
                subject=subject_clean[:200],
                body=body[:2000],
                files=meaningful,
                modules=modules,
                breaking=breaking,
                score=round(score, 1),
            )
        )

    return commits


# ============================================================================
# INDEXATION
# ============================================================================


def _make_chunk_id(sha: str, commit_type: str) -> str:
    """ID deterministe pour un commit indexe (reutilisable inter-run)."""
    return f"git_{commit_type}_{sha[:12]}"


def index_commits(commits: list[CommitIntel], create_adr_if_score_gte: float = 120.0) -> dict:
    """
    Insere les commits dans rag_chunks (+ rag_fts) et cree des ADR
    pour les commits les plus significatifs (score >= threshold).

    Idempotent : INSERT OR IGNORE sur chunk_id.
    """
    if not commits:
        return {"indexed": 0, "skipped": 0, "adr_created": 0}

    indexed = 0
    skipped = 0
    adr_created = 0

    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.cursor()

        for c in commits:
            chunk_id = _make_chunk_id(c.sha, c.commit_type)
            text = c.to_rag_text()
            source = f"git:{c.short_sha}:{c.commit_type}"
            domain = _guess_domain(c)
            meta = json.dumps(
                {
                    "sha": c.sha,
                    "author": c.author,
                    "date": c.date_iso,
                    "type": c.commit_type,
                    "scope": c.scope,
                    "breaking": c.breaking,
                    "score": c.score,
                    "modules": c.modules[:10],
                    "ring": 1,
                    "trust_score": 0.90,
                    "tags": ["git_history", c.commit_type] + ([c.scope] if c.scope else []),
                }
            )

            # 1. rag_chunks
            cur.execute(
                "INSERT OR IGNORE INTO rag_chunks "
                "(id, text, source, domain, role_hint, meta, author) "
                "VALUES (?, ?, ?, ?, 'rule', ?, ?)",
                (chunk_id, text, source, domain, meta, c.author),
            )
            if cur.rowcount > 0:
                indexed += 1
                # 2. rag_fts sync
                try:
                    cur.execute(
                        "INSERT INTO rag_fts (chunk_id, text, source, domain) VALUES (?,?,?,?)",
                        (chunk_id, text, source, domain),
                    )
                except Exception as e:  # noqa: BLE001
                    import logging as _lg

                    # Le chunk existe alors dans rag_chunks mais PAS dans l'index
                    # lexical : il est stocke et introuvable. C'est la forme la plus
                    # trompeuse d'une ingestion « reussie ».
                    _lg.getLogger(__name__).warning(
                        "[historien] chunk %s NON indexe en lexical (%s: %s) | "
                        "consequence: ce contenu est en base mais INTROUVABLE par "
                        "recherche", str(chunk_id)[:24], type(e).__name__, str(e)[:70])
            else:
                skipped += 1

            # 3. ADR si score eleve (decision architecturale majeure)
            if c.score >= create_adr_if_score_gte and c.commit_type in ("feat", "refactor", "refacto"):
                if _maybe_create_adr(cur, c, chunk_id):
                    adr_created += 1

            # 4. module co-change graph (edges entre modules co-modifies)
            if len(c.modules) >= 2:
                _insert_cochange_edges(cur, c.modules, c.sha)

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"[historian] index_commits error: {e}")

    return {
        "indexed": indexed,
        "skipped": skipped,
        "adr_created": adr_created,
    }


def _guess_domain(c: CommitIntel) -> str:
    """Infere le domaine RAG depuis le scope et les modules touches."""
    blob = (c.scope + " " + " ".join(c.modules)).lower()
    if any(k in blob for k in ("rag", "embed", "vector", "search", "retriev")):
        return "rag"
    if any(k in blob for k in ("security", "firewall", "membrane", "guard", "auth", "pii")):
        return "security"
    if any(k in blob for k in ("router", "llm", "ollama", "llamacpp", "cascade")):
        return "llm"
    if any(k in blob for k in ("mcp", "hub", "handler", "tool")):
        return "mcp"
    if any(k in blob for k in ("ui", "tui", "web")):
        return "ui"
    if c.commit_type == "docs" or c.commit_type == "doc":
        return "docs"
    return "systeme"


def _maybe_create_adr(cur: sqlite3.Cursor, c: CommitIntel, chunk_id: str) -> bool:
    """Cree un ADR candidate si le commit merite d en etre un (score eleve)."""
    # Verifier si un ADR existe deja pour ce sha
    try:
        cur.execute("SELECT adr_id FROM adr_records WHERE adr_id = ?", (f"ADR-git-{c.short_sha}",))
        if cur.fetchone():
            return False

        # Recuperer le prochain numero ADR disponible
        cur.execute("SELECT COUNT(*) FROM adr_records")
        n_existing = cur.fetchone()[0]
        adr_id = f"ADR-git-{c.short_sha}"

        # Construire le context depuis le body (premieres lignes = contexte)
        body_lines = [line.strip() for line in c.body.split("\n") if line.strip()]
        context = " ".join(body_lines[:3])[:800]
        decision = c.subject[:500]

        # Consequences positives : patterns "valide", "test", "7/7"
        pos_signals = [
            line
            for line in body_lines
            if any(kw in line.lower() for kw in ("test", "valide", "ok", "passe", "confirme"))
        ]
        neg_signals = [
            line
            for line in body_lines
            if any(kw in line.lower() for kw in ("dette", "todo", "pending", "breaking", "risk"))
        ]

        tags = json.dumps([c.commit_type, c.scope or "global"] + c.modules[:3])

        cur.execute(
            "INSERT INTO adr_records (adr_id, title, status, context, decision, "
            "consequences_pos, consequences_neg, tags, ring, author, embedding_id) "
            "VALUES (?, ?, 'Accepté', ?, ?, ?, ?, ?, 1, ?, 0)",
            (
                adr_id,
                f"[{c.commit_type}] {c.subject[:120]}",
                context,
                decision,
                " | ".join(pos_signals[:3])[:500],
                " | ".join(neg_signals[:3])[:500],
                tags,
                c.author,
            ),
        )
        return cur.rowcount > 0
    except Exception as e:
        print(f"[historian] ADR creation skip: {e}")
        return False


def _insert_cochange_edges(cur: sqlite3.Cursor, modules: list, sha: str) -> None:
    """
    Enregistre les paires de modules co-modifies dans un commit pour analyse
    ulterieure ('quels modules bougent ensemble ?'). Utilise rag_graph_edges
    si la table existe.
    """
    try:
        # Check table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rag_graph_edges'")
        if not cur.fetchone():
            return

        # Check schema : on tente un insert simple
        for i in range(len(modules)):
            for j in range(i + 1, len(modules)):
                src_node = modules[i]
                dst_node = modules[j]
                try:
                    cur.execute(
                        "INSERT OR IGNORE INTO rag_graph_edges "
                        "(src_node, dst_node, edge_type, weight, meta) "
                        "VALUES (?, ?, 'cochange', 1, ?)",
                        (src_node, dst_node, json.dumps({"last_sha": sha[:12]})),
                    )
                except sqlite3.OperationalError as e:
                    import logging as _lg

                    # « skip silencieusement » etait le comportement voulu ; le taire
                    # ne l'etait pas. Un graphe de co-changement sans aretes se lit
                    # comme un depot sans couplage entre fichiers.
                    _lg.getLogger(__name__).warning(
                        "[historien] aretes de co-changement NON ecrites, schema "
                        "different (%s) | consequence: le graphe parait sans couplage "
                        "entre fichiers alors qu'il n'a simplement pas ete alimente",
                        str(e)[:90])
                    return
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[historien] co-changement interrompu (%s: %s) | consequence: le graphe "
            "de couplage est incomplet pour cette passe",
            type(e).__name__, str(e)[:80])


# ============================================================================
# RUNNER
# ============================================================================


class GitHistorian:
    """Wrapper qui orchestre extraction + indexation + state."""

    def run_full(self, limit: int = 200, since: Optional[str] = None) -> dict:
        """Pipeline complet : extract + index + save state."""
        since_sha = since or get_last_processed()
        commits = extract_commits(since_sha=since_sha, limit=limit)

        if not commits:
            return {
                "indexed": 0,
                "skipped": 0,
                "adr_created": 0,
                "commits_raw": 0,
                "last_sha": since_sha,
                "status": "nothing_new" if since_sha else "no_commits_found",
            }

        result = index_commits(commits)
        result["commits_raw"] = len(commits)
        result["last_sha"] = commits[0].sha  # HEAD du batch (git log est newest-first)
        result["status"] = "ok"

        _save_state(
            last_sha=result["last_sha"],
            indexed=result["indexed"],
            skipped=result["skipped"],
            adr_created=result["adr_created"],
        )

        return result


# ============================================================================
# CLI
# ============================================================================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since", default=None, help="SHA depuis lequel extraire (ex: v17.0.0 ou un sha). Defaut: last_sha traite."
    )
    parser.add_argument("--limit", type=int, default=200, help="Max commits a extraire si since absent.")
    parser.add_argument("--dry-run", action="store_true", help="Extrait mais n indexe pas.")
    parser.add_argument("--report", action="store_true", help="Affiche uniquement le rapport du dernier run.")
    args = parser.parse_args()

    if args.report:
        last = get_last_processed()
        print(f"Last SHA processed : {last or '(never)'}")
        try:
            conn = sqlite3.connect(str(DB))
            cur = conn.execute(
                "SELECT last_run_at, indexed_n, skipped_n, adr_created "
                "FROM git_historian_state ORDER BY id DESC LIMIT 5"
            )
            print("\nDernieres executions :")
            for row in cur.fetchall():
                print(f"  {row[0]} : indexed={row[1]} skipped={row[2]} adr={row[3]}")
            conn.close()
        except Exception as e:
            print(f"Erreur lecture state : {e}")
        sys.exit(0)

    if args.dry_run:
        commits = extract_commits(since_sha=args.since, limit=args.limit)
        print(f"=== DRY RUN : {len(commits)} commits extraits ===\n")
        for c in commits[:10]:
            print(
                f"[{c.score:5.1f}] {c.short_sha} {c.commit_type}"
                + (f"({c.scope})" if c.scope else "")
                + ("!" if c.breaking else "")
                + f" : {c.subject[:80]}"
            )
            if c.modules:
                print(f"         modules: {', '.join(c.modules[:5])}")
        if len(commits) > 10:
            print(f"\n... et {len(commits) - 10} de plus")
        sys.exit(0)

    h = GitHistorian()
    print("=== forge_git_historian ===")
    since = args.since or get_last_processed()
    print(f"Since : {since or '(first run, limit=' + str(args.limit) + ')'}")

    t0 = time.time()
    report = h.run_full(limit=args.limit, since=args.since)
    dt = time.time() - t0

    print(f"\nStatus        : {report['status']}")
    print(f"Commits parses: {report.get('commits_raw', 0)}")
    print(f"Indexes       : {report['indexed']}")
    print(f"Skipped (dup) : {report['skipped']}")
    print(f"ADR crees     : {report['adr_created']}")
    print(f"Dernier SHA   : {(report.get('last_sha') or '')[:12]}")
    print(f"Duree         : {dt:.2f}s")
