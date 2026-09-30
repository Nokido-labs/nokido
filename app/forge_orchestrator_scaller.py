# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_orchestrator_scaller
#FORGE:[score:90|agent:claude-mcp|temp:0.00|risk:0.15|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: auto-tuning Nokido base sur metriques mesurables, aucune application automatique
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:claude-mcp|temp:0.00|risk:0.15|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"
"""
app/forge_orchestrator_scaller.py - Auto-tuning Nokido
==========================================================

Module meta : Nokido analyse ses propres metriques pour generer des
recommandations de reglage. Aucune application automatique - humain valide.

SIGNAUX ANALYSES :
1. commit_intel (100 commits scores) -> distribution risk, seuils MIN_INTEL_SCORE
2. git_historian_state -> skipped/indexed ratio, throughput
3. agent_tasks (261 entrees, 81 executors) -> duree par domaine,
   success/fail rate par modele, patterns d echec
4. rag_chunks role_hint=rule -> rappel preflight (match vs miss)
5. rag_graph_edges -> couverture du graphe semantique

PATTERNS DETECTES (regles heuristiques) :
- SEUIL_PERMISSIF : si > 30 pourcents commits MINIMAL -> MIN_INTEL_SCORE +20
- SEUIL_INUTILE : si threshold X produit 0 effet sur 100 commits -> abaisser a P90
- MODELE_DEFAILLANT : executor qui echoue > 50 pourcents sur un domaine -> fallback
- RAPPEL_FAIBLE : preflight rappel < 20 pourcents -> assouplir query cleaner
- LECONS_OBSOLETES : leons non rappelees depuis > 7 jours -> archive/refresh

API :
  scan() -> list[Recommendation]
  scan_and_store() -> dict (stats + rec_ids)
  list_pending() -> list[dict]
  apply_one(rec_id) -> bool (patch le fichier cible via ast+str_replace)
  rollback_one(rec_id) -> bool

CLI :
  python app/forge_orchestrator_scaller.py scan
  python app/forge_orchestrator_scaller.py scan --store
  python app/forge_orchestrator_scaller.py list
  python app/forge_orchestrator_scaller.py apply 3
  python app/forge_orchestrator_scaller.py rollback 3
  python app/forge_orchestrator_scaller.py report  # resume visuel

IDEMPOTENCE : scan() deux fois sur donnees inchangees = memes recos.
SAFETY : confidence minimum 0.7 pour persister. apply utilise ast.parse
avant str_replace pour eviter les patches dangereux.
"""

import ast
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
# DATA STRUCTURE
# =============================================================================


@dataclass
class Recommendation:
    """Recommandation d auto-tuning produite par scan."""

    param: str  # "MIN_INTEL_SCORE" ou "MODEL_MAP.rag"
    current_value: str  # valeur actuelle lue depuis le source
    suggested_value: str  # valeur suggeree
    reason: str  # explication courte basee sur metriques
    confidence: float  # 0.0-1.0
    source_module: str  # app/forge_git_historian.py
    evidence: dict  # dict de metriques concretes justifiant
    pattern_code: str  # "SEUIL_PERMISSIF" etc. pour deduplication


# =============================================================================
# TABLE SETUP
# =============================================================================


def _ensure_table() -> None:
    """Cree orchestrator_recommendations si absente."""
    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orchestrator_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                param TEXT NOT NULL,
                current_value TEXT,
                suggested_value TEXT,
                reason TEXT,
                confidence REAL,
                source_module TEXT,
                evidence TEXT,
                pattern_code TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                applied_at TEXT,
                applied_by TEXT,
                rolled_back_at TEXT,
                UNIQUE(param, pattern_code, suggested_value)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_orec_pending "
            "ON orchestrator_recommendations(applied_at) WHERE applied_at IS NULL"
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# =============================================================================
# SIGNAL COLLECTORS
# =============================================================================


def _get_commit_intel_stats() -> dict:
    """Distribution risk_level + scope dans commit_intel."""
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()

        cur.execute("SELECT risk_level, COUNT(*) FROM commit_intel GROUP BY risk_level")
        by_level = dict(cur.fetchall())

        cur.execute("SELECT COUNT(*) FROM commit_intel")
        total = cur.fetchone()[0]

        cur.execute("SELECT risk_score FROM commit_intel ORDER BY risk_score")
        scores = [r[0] for r in cur.fetchall()]

        # P90, P95 des scores (utile pour calibrer create_adr_if_score_gte)
        p50 = p90 = p95 = 0.0
        if scores:
            p50 = scores[len(scores) // 2]
            p90 = scores[int(len(scores) * 0.9)]
            p95 = scores[int(len(scores) * 0.95)]

        conn.close()
        return {
            "total": total,
            "by_level": by_level,
            "p50_score": p50,
            "p90_score": p90,
            "p95_score": p95,
            "scores_list": scores,
        }
    except Exception as e:
        return {"error": str(e)}


def _get_git_historian_stats() -> dict:
    """Stats d indexation historique + ADR."""
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()

        cur.execute("SELECT SUM(indexed_n), SUM(skipped_n), SUM(adr_created), COUNT(*) FROM git_historian_state")
        row = cur.fetchone()
        total_indexed, total_skipped, total_adr, n_runs = row or (0, 0, 0, 0)

        # Combien de git:% chunks indexes au total ?
        # GLOB : un motif de prefixe en LIKE est insensible a la casse, ce qui
        # interdit l'usage de l'index. Verifie 2026-09-04 : 170 sources des deux
        # cotes, aucune perte.
        cur.execute("SELECT COUNT(*) FROM rag_chunks WHERE source GLOB 'git:*'")
        git_chunks = cur.fetchone()[0]

        conn.close()
        return {
            "total_indexed": total_indexed or 0,
            "total_skipped": total_skipped or 0,
            "total_adr": total_adr or 0,
            "n_runs": n_runs or 0,
            "git_chunks": git_chunks,
        }
    except Exception as e:
        return {"error": str(e)}


def _get_agent_tasks_stats() -> dict:
    """Success/fail par executor + par domaine (si inferable)."""
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()

        # Distribution par status
        cur.execute("SELECT status, COUNT(*) FROM agent_tasks GROUP BY status")
        by_status = dict(cur.fetchall())

        # Executor -> success / total
        cur.execute("""
            SELECT executor,
                   SUM(CASE WHEN status IN ('done', 'approved') THEN 1 ELSE 0 END) AS ok,
                   SUM(CASE WHEN status IN ('failed', 'rejected', 'cancelled') THEN 1 ELSE 0 END) AS ko,
                   COUNT(*) AS total
            FROM agent_tasks
            WHERE executor IS NOT NULL AND executor != ''
            GROUP BY executor
            HAVING total >= 3
        """)
        executor_rates = []
        for exc, ok, ko, total in cur.fetchall():
            if total and (ok + ko) > 0:
                success = ok / (ok + ko) if (ok + ko) else 0
                executor_rates.append(
                    {
                        "executor": exc,
                        "ok": ok,
                        "ko": ko,
                        "total": total,
                        "success_rate": round(success, 2),
                    }
                )

        # Par task_type / scope (si present dans task_type)
        cur.execute("""
            SELECT task_type, COUNT(*), 
                   SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed
            FROM agent_tasks
            WHERE task_type IS NOT NULL AND task_type != 'generic'
            GROUP BY task_type HAVING COUNT(*) >= 3
        """)
        task_types = []
        for tt, n, failed in cur.fetchall():
            task_types.append(
                {
                    "task_type": tt,
                    "total": n,
                    "failed": failed,
                    "fail_rate": round(failed / n, 2) if n else 0,
                }
            )

        conn.close()
        return {
            "by_status": by_status,
            "executor_rates": executor_rates,
            "task_types": task_types,
        }
    except Exception as e:
        return {"error": str(e)}


def _get_lessons_stats() -> dict:
    """Volume + recence des lecons ancrees (role_hint=rule)."""
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(*) FROM rag_chunks 
            WHERE role_hint='rule' 
              AND source LIKE 'session:%'
        """)
        total_lessons = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM rag_chunks 
            WHERE role_hint='rule' 
              AND source LIKE 'session:%'
              AND ingested_at > datetime('now', '-7 days')
        """)
        recent_lessons = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM rag_chunks 
            WHERE role_hint='rule' 
              AND source LIKE 'session:%'
              AND ingested_at < datetime('now', '-30 days')
        """)
        old_lessons = cur.fetchone()[0]

        conn.close()
        return {
            "total_lessons": total_lessons,
            "recent_7d": recent_lessons,
            "old_30d": old_lessons,
        }
    except Exception as e:
        return {"error": str(e)}


def _read_constant_from_source(module_path: str, const_name: str) -> Optional[str]:
    """Lit une constante Python depuis un module source (ast.parse safe)."""
    fp = ROOT / module_path
    if not fp.exists():
        return None
    try:
        tree = ast.parse(fp.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == const_name:
                        try:
                            return ast.unparse(node.value)
                        except Exception:
                            return ast.dump(node.value)
        return None
    except SyntaxError:
        return None


# =============================================================================
# PATTERN DETECTORS - heuristiques qui generent les recommandations
# =============================================================================


def _detect_permissive_threshold(ci: dict) -> list:
    """SEUIL_PERMISSIF : > 30% MINIMAL indique seuil trop bas."""
    recs = []
    total = ci.get("total", 0)
    if total < 20:
        return recs  # pas assez de data

    minimal_n = ci.get("by_level", {}).get("MINIMAL", 0)
    pct_minimal = minimal_n / total if total else 0

    if pct_minimal > 0.30:
        current = _read_constant_from_source("app/forge_git_historian.py", "MIN_INTEL_SCORE")
        if current:
            try:
                current_val = float(current)
                suggested = round(current_val + 20.0, 1)
                recs.append(
                    Recommendation(
                        param="MIN_INTEL_SCORE",
                        current_value=str(current_val),
                        suggested_value=str(suggested),
                        reason=f"{pct_minimal:.0%} commits classes MINIMAL ({minimal_n}/{total}), "
                        f"seuil trop permissif - exclut trop de bruit",
                        confidence=min(0.95, 0.6 + pct_minimal),
                        source_module="app/forge_git_historian.py",
                        evidence={"pct_minimal": pct_minimal, "minimal_n": minimal_n, "total": total},
                        pattern_code="SEUIL_PERMISSIF",
                    )
                )
            except ValueError:
                pass
    return recs


def _detect_useless_threshold(ci: dict, hs: dict) -> list:
    """SEUIL_INUTILE : create_adr_if_score_gte qui produit 0 ADR sur beaucoup de commits."""
    recs = []
    total_adr = hs.get("total_adr", 0)
    total_commits = ci.get("total", 0)
    p90 = ci.get("p90_score", 0)

    if total_commits >= 50 and total_adr == 0 and p90 > 0:
        current = _read_constant_from_source("app/forge_git_historian.py", "MIN_INTEL_SCORE")
        # Le seuil ADR est hardcoded en parametre de index_commits.
        # Pattern : on recommande de passer de 120 a P90 pour generer des ADR
        suggested = round(p90 + 5.0, 1)
        recs.append(
            Recommendation(
                param="index_commits.create_adr_if_score_gte",
                current_value="120.0",
                suggested_value=str(suggested),
                reason=f"Aucun ADR cree sur {total_commits} commits. "
                f"P90 des scores observes = {p90:.1f}, abaisser le seuil permettrait "
                f"de generer automatiquement ~10 pourcents de commits en ADR.",
                confidence=0.85,
                source_module="app/forge_git_historian.py",
                evidence={"total_commits": total_commits, "total_adr": total_adr, "p90_score": p90},
                pattern_code="SEUIL_INUTILE",
            )
        )
    return recs


def _detect_failing_executor(ts: dict) -> list:
    """MODELE_DEFAILLANT : executor avec success_rate < 50% sur >= 5 tasks."""
    recs = []
    for er in ts.get("executor_rates", []):
        if er["total"] >= 5 and er["success_rate"] < 0.50:
            recs.append(
                Recommendation(
                    param=f"executor_blacklist.{er['executor'][:40]}",
                    current_value="None (active)",
                    suggested_value=f"blacklist OR fallback after success_rate < 50% on {er['total']} tasks",
                    reason=f"Executor '{er['executor']}' : {er['ok']} OK / {er['ko']} KO "
                    f"({er['success_rate']:.0%} success rate sur {er['total']} tasks)",
                    confidence=min(0.9, 0.6 + (0.5 - er["success_rate"])),
                    source_module="app/forge_silo_engine.py",  # lieu logique du routing
                    evidence=er,
                    pattern_code="MODELE_DEFAILLANT",
                )
            )
    return recs[:5]  # cap a 5 recos


def _detect_lesson_obsolescence(ls: dict) -> list:
    """LECONS_OBSOLETES : trop de vieilles lecons non refreshees."""
    recs = []
    old = ls.get("old_30d", 0)
    total = ls.get("total_lessons", 1)
    if old > 0 and (old / total) > 0.5:
        recs.append(
            Recommendation(
                param="lessons_retention_policy",
                current_value="infinite",
                suggested_value="archive lessons > 90d unless referenced by recent preflight",
                reason=f"{old} lecons ont plus de 30 jours sur {total} total ({old / total:.0%}). "
                f"Signal : rotation/archivage a ajouter pour eviter dilution retrieval.",
                confidence=0.75,
                source_module="app/forge_self_correction.py",
                evidence=ls,
                pattern_code="LECONS_OBSOLETES",
            )
        )
    return recs


def _detect_risk_distribution_imbalance(ci: dict) -> list:
    """DISTRIBUTION_DESEQUILIBREE : proportions anormales HIGH/CRITICAL."""
    recs = []
    total = ci.get("total", 0)
    if total < 30:
        return recs

    levels = ci.get("by_level", {})
    hc = levels.get("HIGH", 0) + levels.get("CRITICAL", 0)
    pct_hc = hc / total if total else 0

    if pct_hc > 0.15:
        recs.append(
            Recommendation(
                param="CRITICAL_SYMBOLS audit",
                current_value="30 symboles statiques",
                suggested_value="review + trim CRITICAL_SYMBOLS list (trop de matches)",
                reason=f"{pct_hc:.0%} commits sont HIGH ou CRITICAL ({hc}/{total}), "
                f"signal que les patterns de risque matchent trop largement. "
                f"Recommande audit CRITICAL_SYMBOLS et DANGEROUS_PATTERNS.",
                confidence=0.7,
                source_module="app/forge_commit_intel.py",
                evidence={
                    "pct_high_critical": pct_hc,
                    "high": levels.get("HIGH", 0),
                    "critical": levels.get("CRITICAL", 0),
                    "total": total,
                },
                pattern_code="DISTRIBUTION_DESEQUILIBREE",
            )
        )
    elif pct_hc < 0.02 and total >= 100:
        recs.append(
            Recommendation(
                param="CRITICAL_SYMBOLS coverage",
                current_value="30 symboles statiques",
                suggested_value="enrichir CRITICAL_SYMBOLS (couverture insuffisante)",
                reason=f"Seulement {pct_hc:.0%} commits HIGH/CRITICAL sur {total}. "
                f"Signal : la liste ne couvre peut-etre pas assez de fonctions sensibles. "
                f"Audit recommande.",
                confidence=0.7,
                source_module="app/forge_commit_intel.py",
                evidence={"pct_high_critical": pct_hc, "total": total},
                pattern_code="DISTRIBUTION_DESEQUILIBREE",
            )
        )
    return recs


# =============================================================================
# PUBLIC API
# =============================================================================


def scan() -> list:
    """
    Pipeline complet : collecte signaux + detecte patterns + retourne recos.
    Ne persiste rien (utiliser scan_and_store pour persistance).
    """
    ci = _get_commit_intel_stats()
    hs = _get_git_historian_stats()
    ts = _get_agent_tasks_stats()
    ls = _get_lessons_stats()

    all_recs = []
    all_recs.extend(_detect_permissive_threshold(ci))
    all_recs.extend(_detect_useless_threshold(ci, hs))
    all_recs.extend(_detect_failing_executor(ts))
    all_recs.extend(_detect_lesson_obsolescence(ls))
    all_recs.extend(_detect_risk_distribution_imbalance(ci))

    # Filtre confidence minimum
    filtered = [r for r in all_recs if r.confidence >= 0.7]
    return filtered


def scan_and_store() -> dict:
    """Scan + persiste les recos uniques dans orchestrator_recommendations."""
    _ensure_table()
    recs = scan()
    stored_ids = []
    duplicates = 0

    try:
        conn = sqlite3.connect(str(DB))
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.cursor()

        for r in recs:
            try:
                cur.execute(
                    "INSERT INTO orchestrator_recommendations "
                    "(param, current_value, suggested_value, reason, confidence, "
                    " source_module, evidence, pattern_code) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        r.param,
                        r.current_value,
                        r.suggested_value,
                        r.reason,
                        r.confidence,
                        r.source_module,
                        json.dumps(r.evidence),
                        r.pattern_code,
                    ),
                )
                stored_ids.append(cur.lastrowid)
            except sqlite3.IntegrityError:
                duplicates += 1

        conn.commit()
        conn.close()
    except Exception as e:
        return {"error": str(e), "scanned": len(recs)}

    return {
        "scanned": len(recs),
        "stored": len(stored_ids),
        "duplicates": duplicates,
        "ids": stored_ids,
    }


def list_pending(limit: int = 20) -> list:
    """Liste les recos non encore appliquees."""
    _ensure_table()
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, param, current_value, suggested_value, reason,
                   confidence, source_module, pattern_code, created_at
            FROM orchestrator_recommendations
            WHERE applied_at IS NULL
            ORDER BY confidence DESC, id DESC
            LIMIT ?
        """,
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "param": r[1],
                "current": r[2],
                "suggested": r[3],
                "reason": r[4],
                "confidence": r[5],
                "source_module": r[6],
                "pattern_code": r[7],
                "created_at": r[8],
            }
            for r in rows
        ]
    except Exception as e:
        return [{"error": str(e)}]


def apply_one(rec_id: int, applied_by: str = "manual") -> dict:
    """
    Applique une reco : patch le fichier cible via ast.parse + str_replace safe.
    Limite aux params numeriques pour cette premiere version.
    """
    _ensure_table()
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()
        cur.execute(
            "SELECT param, current_value, suggested_value, source_module, pattern_code, applied_at "
            "FROM orchestrator_recommendations WHERE id = ?",
            (rec_id,),
        )
        row = cur.fetchone()
        conn.close()

        if not row:
            return {"ok": False, "error": "reco not found"}
        param, current, suggested, source, pattern, applied_at = row

        if applied_at:
            return {"ok": False, "error": "already applied", "applied_at": applied_at}

        # Pour cette version : supporter uniquement param constant Python simple
        # dans app/forge_git_historian.py ou app/forge_commit_intel.py
        if not source.startswith("app/forge_"):
            return {
                "ok": False,
                "error": "source module not in scope",
                "hint": "only app/forge_*.py supported for auto-apply",
            }

        fp = ROOT / source
        if not fp.exists():
            return {"ok": False, "error": f"source file not found: {source}"}

        content = fp.read_text(encoding="utf-8", errors="replace")

        # Strategy : si param est un identifier Python simple, on fait str_replace du literal
        if re.match(r"^[A-Z_][A-Z0-9_]*$", param):
            # Chercher "PARAM = <current>" et remplacer par "PARAM = <suggested>"
            pattern_re = rf"({re.escape(param)}\s*=\s*){re.escape(current)}\b"
            new_content, n = re.subn(pattern_re, rf"\g<1>{suggested}", content)
            if n == 0:
                return {"ok": False, "error": f"pattern '{param} = {current}' not found in {source}"}
            if n > 1:
                return {"ok": False, "error": f"ambiguous: {n} matches for {param} in {source}"}

            # Validate AST parse after patch
            try:
                ast.parse(new_content)
            except SyntaxError as e:
                return {"ok": False, "error": f"patched file has syntax error: {e}"}

            # Write
            fp.write_text(new_content, encoding="utf-8")
        else:
            # Params complexes : pas d auto-apply, retourne hint
            return {
                "ok": False,
                "error": "param not a simple constant (manual patch required)",
                "hint": f"Edit {source} manually for param '{param}'",
            }

        # Mark as applied
        conn = sqlite3.connect(str(DB))
        conn.execute(
            "UPDATE orchestrator_recommendations SET applied_at = datetime('now'), applied_by = ? WHERE id = ?",
            (applied_by, rec_id),
        )
        conn.commit()
        conn.close()

        return {
            "ok": True,
            "rec_id": rec_id,
            "param": param,
            "from": current,
            "to": suggested,
            "file": source,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def rollback_one(rec_id: int) -> dict:
    """Restaure current_value dans le fichier source."""
    _ensure_table()
    try:
        conn = sqlite3.connect(str(DB))
        cur = conn.cursor()
        cur.execute(
            "SELECT param, current_value, suggested_value, source_module, applied_at "
            "FROM orchestrator_recommendations WHERE id = ?",
            (rec_id,),
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return {"ok": False, "error": "reco not found"}
        param, current, suggested, source, applied_at = row
        if not applied_at:
            return {"ok": False, "error": "not applied - nothing to rollback"}

        fp = ROOT / source
        if not fp.exists():
            return {"ok": False, "error": f"source file not found: {source}"}
        content = fp.read_text(encoding="utf-8", errors="replace")

        pattern_re = rf"({re.escape(param)}\s*=\s*){re.escape(suggested)}\b"
        new_content, n = re.subn(pattern_re, rf"\g<1>{current}", content)
        if n != 1:
            return {"ok": False, "error": f"{n} matches for rollback (expected 1)"}

        ast.parse(new_content)
        fp.write_text(new_content, encoding="utf-8")

        conn = sqlite3.connect(str(DB))
        conn.execute("UPDATE orchestrator_recommendations SET rolled_back_at = datetime('now') WHERE id = ?", (rec_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "rec_id": rec_id, "param": param, "restored_to": current, "file": source}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def report() -> str:
    """Retourne un resume visuel des metriques + recos."""
    ci = _get_commit_intel_stats()
    hs = _get_git_historian_stats()
    ts = _get_agent_tasks_stats()
    ls = _get_lessons_stats()

    lines = ["=== Nokido Orchestrator Scaller Report ===\n"]

    # commit_intel
    total = ci.get("total", 0)
    lines.append(f"commit_intel : {total} commits analyses")
    if total:
        for level in ("MINIMAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"):
            n = ci.get("by_level", {}).get(level, 0)
            pct = n / total * 100 if total else 0
            bar = "#" * int(pct / 3)
            lines.append(f"  {level:<9} {n:>3} ({pct:>4.1f}%) {bar}")
        lines.append(f"  P50 score: {ci.get('p50_score', 0):.1f}")
        lines.append(f"  P90 score: {ci.get('p90_score', 0):.1f}")
        lines.append(f"  P95 score: {ci.get('p95_score', 0):.1f}")

    # git_historian
    lines.append(f"\ngit_historian : {hs.get('git_chunks', 0)} git:* chunks indexes")
    lines.append(f"  runs total  : {hs.get('n_runs', 0)}")
    lines.append(f"  indexed     : {hs.get('total_indexed', 0)}")
    lines.append(f"  ADR crees   : {hs.get('total_adr', 0)}")

    # agent_tasks
    lines.append(f"\nagent_tasks : {sum(ts.get('by_status', {}).values())} tasks")
    for status, n in sorted(ts.get("by_status", {}).items(), key=lambda x: -x[1]):
        lines.append(f"  {status:<12} {n}")

    failing = [e for e in ts.get("executor_rates", []) if e["success_rate"] < 0.50 and e["total"] >= 5]
    if failing:
        lines.append("\nExecutors defaillants (success < 50%) :")
        for e in failing:
            lines.append(f"  {e['executor'][:40]:<42} {e['success_rate']:.0%} ({e['ok']}/{e['total']})")

    # lessons
    lines.append(
        f"\nlecons : total={ls.get('total_lessons', 0)} "
        f"recent_7d={ls.get('recent_7d', 0)} old_30d={ls.get('old_30d', 0)}"
    )

    return "\n".join(lines)


# =============================================================================
# CLI
# =============================================================================


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp_scan = sub.add_parser("scan", help="Scanne les metriques et affiche les recos")
    sp_scan.add_argument("--store", action="store_true", help="Persiste dans orchestrator_recommendations")

    sub.add_parser("list", help="Liste les recos pending")

    sp_apply = sub.add_parser("apply", help="Applique une reco par id")
    sp_apply.add_argument("rec_id", type=int)

    sp_rb = sub.add_parser("rollback", help="Annule une reco appliquee")
    sp_rb.add_argument("rec_id", type=int)

    sub.add_parser("report", help="Rapport visuel des metriques")

    args = parser.parse_args()

    if args.cmd == "scan":
        recs = scan()
        if not recs:
            print("Aucune recommandation (tous seuils respectes ou pas assez de data).")
            return 0
        print(f"=== {len(recs)} recommandation(s) ===\n")
        for i, r in enumerate(recs, 1):
            print(f"[{i}] {r.pattern_code} - confidence={r.confidence:.2f}")
            print(f"    param     : {r.param}")
            print(f"    current   : {r.current_value}")
            print(f"    suggested : {r.suggested_value}")
            print(f"    reason    : {r.reason}")
            print(f"    source    : {r.source_module}")
            print()

        if args.store:
            result = scan_and_store()
            print(f"\nPersistance : {result}")
        return 0

    if args.cmd == "list":
        recs = list_pending()
        if not recs or (recs and recs[0].get("error")):
            print("Aucune reco pending" if not recs else f"Erreur : {recs[0]['error']}")
            return 0
        print(f"=== {len(recs)} reco(s) pending ===\n")
        for r in recs:
            print(f"#{r['id']} [{r.get('pattern_code')}] conf={r.get('confidence'):.2f}")
            print(f"  {r['param']} : {r['current']} -> {r['suggested']}")
            print(f"  {r['reason']}")
            print()
        return 0

    if args.cmd == "apply":
        result = apply_one(args.rec_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if args.cmd == "rollback":
        result = rollback_one(args.rec_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("ok") else 1

    if args.cmd == "report":
        print(report())
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(_cli())
