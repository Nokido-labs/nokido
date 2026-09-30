"""
app/forge_sandbox_guard.py — Nokido v18.5
===========================================
Règles d'économie tokens pour exécution sandbox/externe.

Règle 1 — Pré-validation locale (Tier 0) avant d'envoyer à sandbox
Règle 2 — Résumé Hub : extraire seulement l'essentiel des logs
Règle 3 — Méta-outil run_analysis_pipeline (mot-clé → Hub gère tout)
Règle 4 — Quota tokens : couper un agent externe après N itérations
"""

from __future__ import annotations
import ast, re, sqlite3, time, json
from pathlib import Path
from typing import Optional

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

# ── Règle 1 : Pré-validation locale ─────────────────────────────────────────


def prevalidate_code(code: str, lang: str = "python") -> dict:
    """
    Valide le code localement (AST + lint statique) avant envoi sandbox.
    Coût : 0 token. Évite un aller-retour Tier 2 pour une virgule oubliée.
    Returns: {"valid": bool, "errors": list[str], "warnings": list[str]}
    """
    errors, warnings = [], []

    if lang == "python":
        # 1. AST parse
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            errors.append(f"SyntaxError L{e.lineno}: {e.msg}")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # 2. Checks statiques rapides
        code_lower = code.lower()
        DANGER = ["os.system(", "subprocess.call(", "shutil.rmtree(", "rm -rf", "__import__('os').system"]
        for d in DANGER:
            if d in code_lower:
                errors.append(f"DANGER: pattern interdit détecté: {d!r}")

        # 3. Imports inconnus
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("pickle", "marshal", "ctypes"):
                        warnings.append(f"Import sensible: {alias.name}")

        # 4. Complexité basique
        lines = [l for l in code.split("\n") if l.strip()]
        if len(lines) > 200:
            warnings.append(f"Code long: {len(lines)} lignes — vérifier nécessité")

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


# ── Règle 2 : Résumé logs ────────────────────────────────────────────────────


def summarize_output(raw: str, max_lines: int = 20) -> str:
    """
    Extrait l'essentiel d'un stdout/stderr long.
    Priorise : erreurs > warnings > dernières lignes.
    Évite de renvoyer 2000 lignes à un LLM externe.
    """
    lines = raw.strip().split("\n")
    if len(lines) <= max_lines:
        return raw

    # Priorité 1 : lignes d'erreur
    errors = [l for l in lines if any(k in l.lower() for k in ("error", "exception", "traceback", "fatal", "critical"))]

    # Priorité 2 : dernières lignes (résultat final)
    tail = lines[-10:]

    # Assemblage
    summary_lines = []
    if errors:
        summary_lines.append(f"[{len(errors)} erreurs détectées]")
        summary_lines.extend(errors[:8])
        summary_lines.append("...")
    summary_lines.append(f"[Dernières {len(tail)} lignes sur {len(lines)}]")
    summary_lines.extend(tail)

    return "\n".join(summary_lines)


# ── Règle 3 : Méta-outil run_analysis_pipeline ───────────────────────────────

PIPELINES = {
    "security_audit": {
        "steps": ["read_env", "run_bandit", "check_secrets", "summarize"],
        "description": "Audit sécurité complet du repo",
    },
    "code_quality": {
        "steps": ["py_compile_all", "count_todos", "check_complexity"],
        "description": "Qualité code statique",
    },
    "rag_status": {
        "steps": ["count_chunks", "check_embeddings", "stale_tasks"],
        "description": "État de la base RAG",
    },
    "git_summary": {
        "steps": ["recent_commits", "diff_stat", "branch_status"],
        "description": "Résumé activité git",
    },
    "agent_status": {
        "steps": ["list_agents", "read_messages", "task_summary"],
        "description": "État de tous les agents actifs",
    },
}


def run_analysis_pipeline(pipeline_key: str, agent_id: str = "external") -> dict:
    """
    Méta-outil : l'agent externe envoie UN mot-clé.
    Le Hub exécute toute la pipeline localement et retourne un résumé.
    Zéro token de dialogue pour la complexité interne.
    """
    if pipeline_key not in PIPELINES:
        return {"error": f"Pipeline inconnue: {pipeline_key!r}", "available": list(PIPELINES.keys())}

    pipe = PIPELINES[pipeline_key]
    results = {}
    import subprocess

    for step in pipe["steps"]:
        try:
            if step == "count_chunks":
                conn = sqlite3.connect(str(DB), timeout=3)
                n = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
                conn.close()
                results[step] = f"{n} chunks"

            elif step == "stale_tasks":
                conn = sqlite3.connect(str(DB), timeout=3)
                n = conn.execute("SELECT COUNT(*) FROM agent_tasks WHERE status='stale'").fetchone()[0]
                conn.close()
                results[step] = f"{n} tâches stale"

            elif step == "recent_commits":
                r = subprocess.run(
                    ["git", "log", "--oneline", "-5"],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=5,
                )
                results[step] = r.stdout.strip()

            elif step == "diff_stat":
                r = subprocess.run(
                    ["git", "diff", "--stat", "HEAD~1"],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=5,
                )
                results[step] = summarize_output(r.stdout, 10)

            elif step == "list_agents":
                from nokido_agent.app.forge_db_path import m2m_path as _m2m_path   # scission M2M
                conn = sqlite3.connect(_m2m_path(), timeout=3)
                agents = conn.execute(
                    "SELECT DISTINCT from_agent FROM agent_messages UNION SELECT DISTINCT to_agent FROM agent_messages"
                ).fetchall()
                conn.close()
                results[step] = [a[0] for a in agents]

            elif step == "read_messages":
                from nokido_agent.app.forge_db_path import m2m_path as _m2m_path   # scission M2M
                conn = sqlite3.connect(_m2m_path(), timeout=3)
                msgs = conn.execute(
                    "SELECT from_agent, to_agent, method, status FROM agent_messages ORDER BY created_at DESC LIMIT 5"
                ).fetchall()
                conn.close()
                results[step] = [{"from": m[0], "to": m[1], "method": m[2], "status": m[3]} for m in msgs]

            elif step == "task_summary":
                conn = sqlite3.connect(str(DB), timeout=3)
                summary = dict(conn.execute("SELECT status, COUNT(*) FROM agent_tasks GROUP BY status").fetchall())
                conn.close()
                results[step] = summary

            else:
                results[step] = "not_implemented"

        except Exception as e:
            results[step] = f"ERR: {e}"

    return {"pipeline": pipeline_key, "description": pipe["description"], "results": results, "agent": agent_id}


# ── Règle 4 : Quota tokens / itérations ─────────────────────────────────────


class AgentQuota:
    """
    Coupe un agent externe après N itérations sandbox.
    Persisté en SQLite pour survivre aux redémarrages.
    """

    MAX_ITER = 10  # itérations sandbox max par session
    MAX_CALLS = 50  # appels MCP max par heure

    def __init__(self):
        self._ensure_table()

    def _ensure_table(self):
        conn = sqlite3.connect(str(DB), timeout=3)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_quota (
                agent_id   TEXT PRIMARY KEY,
                iter_count INTEGER DEFAULT 0,
                call_count INTEGER DEFAULT 0,
                priority   TEXT DEFAULT 'NORMAL',
                last_reset TEXT DEFAULT (datetime('now')),
                blocked    INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def check(self, agent_id: str) -> dict:
        """Vérifier si l'agent peut encore exécuter. Retourne {"allowed": bool, "reason": str}"""
        conn = sqlite3.connect(str(DB), timeout=3)
        row = conn.execute(
            "SELECT iter_count, call_count, priority, blocked, last_reset FROM agent_quota WHERE agent_id=?",
            (agent_id,),
        ).fetchone()
        conn.close()

        if not row:
            return {"allowed": True, "reason": "new_agent", "iter": 0, "calls": 0}

        iter_n = row[0]
        call_n = row[1]
        blocked = row[3] if len(row) > 3 else row[2]
        last_reset = row[4] if len(row) > 4 else row[3]

        if blocked:
            return {"allowed": False, "reason": "quota_blocked", "iter": iter_n, "calls": call_n}
        priority = row[2] if len(row) > 2 else "NORMAL"
        limits = self.PRIORITY_LIMITS.get(priority, self.PRIORITY_LIMITS["NORMAL"])
        if iter_n >= limits["iter"]:
            self._block(agent_id, "max_iterations")
            return {
                "allowed": False,
                "reason": f"max_iter={limits['iter']} [{priority}]",
                "iter": iter_n,
                "calls": call_n,
                "priority": priority,
            }
        if call_n >= limits["calls"]:
            self._block(agent_id, "max_calls_per_hour")
            return {
                "allowed": False,
                "reason": f"max_calls={limits['calls']} [{priority}]",
                "iter": iter_n,
                "calls": call_n,
                "priority": priority,
            }

        return {"allowed": True, "reason": "ok", "iter": iter_n, "calls": call_n}

    def increment(self, agent_id: str, sandbox: bool = False):
        """Incrémenter les compteurs après une exécution."""
        conn = sqlite3.connect(str(DB), timeout=3)
        conn.execute(
            """
            INSERT INTO agent_quota (agent_id, iter_count, call_count)
            VALUES (?, ?, 1)
            ON CONFLICT(agent_id) DO UPDATE SET
                iter_count = iter_count + ?,
                call_count = call_count + 1
        """,
            (agent_id, 1 if sandbox else 0, 1 if sandbox else 0),
        )
        conn.commit()
        conn.close()

    def reset(self, agent_id: str):
        """Reset manuel (après validation humaine)."""
        conn = sqlite3.connect(str(DB), timeout=3)
        conn.execute(
            """
            UPDATE agent_quota SET iter_count=0, call_count=0, blocked=0,
            last_reset=datetime('now') WHERE agent_id=?
        """,
            (agent_id,),
        )
        conn.commit()
        conn.close()

    PRIORITY_LIMITS = {
        "HIGH": {"iter": 50, "calls": 200},  # agents critiques (audit sécurité)
        "NORMAL": {"iter": 10, "calls": 50},
        "LOW": {"iter": 3, "calls": 20},  # agents veille passive
    }

    def set_priority(self, agent_id: str, priority: str = "NORMAL"):
        """Définir la priorité d'un agent → ajuste ses limites."""
        assert priority in self.PRIORITY_LIMITS
        conn = sqlite3.connect(str(DB), timeout=3)
        conn.execute(
            "INSERT INTO agent_quota (agent_id, priority) VALUES (?,?) ON CONFLICT(agent_id) DO UPDATE SET priority=?",
            (agent_id, priority, priority),
        )
        conn.commit()
        conn.close()

    def _block(self, agent_id: str, reason: str):
        conn = sqlite3.connect(str(DB), timeout=3)
        conn.execute(
            "INSERT INTO agent_quota (agent_id, blocked) VALUES (?,1) ON CONFLICT(agent_id) DO UPDATE SET blocked=1",
            (agent_id,),
        )
        conn.commit()
        conn.close()

    def status_all(self) -> list:
        conn = sqlite3.connect(str(DB), timeout=3)
        rows = conn.execute("SELECT agent_id, iter_count, call_count, blocked, last_reset FROM agent_quota").fetchall()
        conn.close()
        return [{"agent": r[0], "iter": r[1], "calls": r[2], "blocked": bool(r[3]), "last_reset": r[4]} for r in rows]


# Singleton
_quota = None


def get_quota() -> AgentQuota:
    global _quota
    if _quota is None:
        _quota = AgentQuota()
    return _quota


if __name__ == "__main__":
    # Test rapide
    print("=== TEST forge_sandbox_guard ===")

    # Règle 1
    good_code = "x = 1 + 1\nprint(x)"
    bad_code = "import os\nos.system('rm -rf /')"
    print("Règle 1 — pré-validation:")
    print(f"  good: {prevalidate_code(good_code)}")
    print(f"  bad:  {prevalidate_code(bad_code)}")

    # Règle 2
    long_log = "\n".join([f"ligne {i}" for i in range(100)] + ["ERROR: crash final"])
    print(f"\nRègle 2 — résumé logs: {summarize_output(long_log, 20)[:150]}...")

    # Règle 3
    print("\nRègle 3 — pipeline agent_status:")
    result = run_analysis_pipeline("agent_status", "test")
    print(f"  {result}")

    # Règle 4
    q = get_quota()
    print(f"\nRègle 4 — quota test_agent: {q.check('test_agent')}")
    q.increment("test_agent", sandbox=True)
    print(f"  après 1 iter: {q.check('test_agent')}")
