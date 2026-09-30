"""
forge_darwinian_arena.py — Quarantaine Ring 4 et Arène Évolutive Nokido.

POURQUOI
========
Lors de l'automutation (ex: `forge_guarded_mutation_loop`) ou la génération autonome 
d'outils par les boucles d'évolution, un risque "auto-immun" majeur existe :
du code invalide, hallucinant, ou malveillant pourrait empoisonner le Hub et 
corrompre les modules du Ring 0/1/2.

SOLUTION : L'ARÈNE DARWINIENNE (RING 4 QUARANTAINE)
===================================================
Tout code candidat (automutation, nouvel outil autogénéré) entre obligatoirement
dans un sas de quarantaine confiné au Ring 4 (UNTRUSTED / Lecture seule).

RÈGLES DE SÉLECTION NATURELLE :
1. Confinement : Le candidat tourne initialement en Ring 4 pendant une période 
   de probation (par défaut 24h = 86400s).
2. Épreuve synthétique : Le code est soumis à des tests synthétiques dans un bac 
   à sable d'exécution contrôlé (sans accès réseau, sans modification OS/DB).
3. Score de Confiance (`trust_score`) : Calculé selon le taux de réussite aux tests
   (`test_passes / max(1, test_runs)`).
4. Promotion : Si et seulement si `trust_score >= 0.85` (seuil de confiance) ET que
   la période de quarantaine est écoulée (ou validée par dérogation), le candidat 
   est promu en Ring 1 (DEV/TRUSTED). Sinon, si les échecs s'accumulent, il est rejeté.

USAGE :
=======
    from forge_darwinian_arena import submit_candidate, run_synthetic_test, evaluate_promotion

    # 1. Soumission d'une automutation par une boucle autonome
    cand = submit_candidate("mut_sort_algo", "def solve(x): return sorted(x)", author="loop_evo")
    cid = cand["candidate_id"]

    # 2. Exécution d'un test synthétique
    res = run_synthetic_test(cid, test_input=[3, 1, 2], expected_output=[1, 2, 3])

    # 3. Évaluation pour promotion (dépassement du seuil 0.85)
    promo = evaluate_promotion(cid, min_trust_score=0.85, ignore_time_lock=True)
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/guard : quarantaine ring 4 et arene evolutive des mutations"  # organe declare le 2026-09-06 (audit de raccordement)

import ast
import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("forge_darwinian_arena")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"

# Statuts possibles
STATUS_QUARANTINE = "quarantine"
STATUS_TESTING = "testing"
STATUS_PROMOTED = "promoted"
STATUS_REJECTED = "rejected"

# Seuil canonique pour la promotion d'un outil autogénéré
DEFAULT_MIN_TRUST_SCORE = 0.85
DEFAULT_QUARANTINE_HOURS = 24.0


@dataclass
class ArenaCandidate:
    candidate_id: str
    name: str
    code_content: str
    author: str
    ring: int
    status: str
    submitted_at: str
    quarantine_until: str
    trust_score: float
    test_runs: int
    test_passes: int
    logs: list[str]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "code_content": self.code_content,
            "author": self.author,
            "ring": self.ring,
            "status": self.status,
            "submitted_at": self.submitted_at,
            "quarantine_until": self.quarantine_until,
            "trust_score": self.trust_score,
            "test_runs": self.test_runs,
            "test_passes": self.test_passes,
            "logs": self.logs,
            "meta": self.meta,
        }


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB), timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS darwinian_candidates (
        candidate_id     TEXT PRIMARY KEY,
        name             TEXT NOT NULL,
        code_content     TEXT NOT NULL,
        author           TEXT NOT NULL,
        ring             INTEGER NOT NULL,
        status           TEXT NOT NULL,
        submitted_at     TEXT NOT NULL,
        quarantine_until TEXT NOT NULL,
        trust_score      REAL NOT NULL,
        test_runs        INTEGER NOT NULL,
        test_passes      INTEGER NOT NULL,
        logs             TEXT NOT NULL,
        meta             TEXT NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_darwinian_status ON darwinian_candidates(status)")
    conn.commit()


def _ast_safety_scan(code: str) -> tuple[bool, str]:
    """Scan AST statique pour interdire les imports dangereux et accès système
    dans le code en quarantaine Ring 4.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"

    forbidden_modules = {"os", "sys", "subprocess", "socket", "sqlite3", "shutil", "pathlib", "http", "urllib", "requests"}
    forbidden_calls = {"exec", "eval", "open", "__import__", "compile", "globals", "locals"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name.split(".")[0] for alias in node.names]
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
            for name in names:
                if name in forbidden_modules:
                    return False, f"Violation Ring 4: import interdit ({name})"
        elif isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            if func_name in forbidden_calls:
                return False, f"Violation Ring 4: appel interdit ({func_name})"

    return True, "AST clean"


def submit_candidate(
    name: str,
    code_content: str,
    *,
    author: str = "autonomous_loop",
    quarantine_hours: float = DEFAULT_QUARANTINE_HOURS,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Soumet un code autogénéré dans la quarantaine Ring 4 de l'Arène Darwinienne."""
    # Vérification AST préliminaire
    is_safe, scan_msg = _ast_safety_scan(code_content)
    if not is_safe:
        raise SecurityError(f"[DARWINIAN ARENA] Refus de soumission Ring 4 — {scan_msg}")

    now_dt = datetime.now(timezone.utc)
    now_iso = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    quar_s = int(max(0.0, float(quarantine_hours)) * 3600)
    until_iso = datetime.fromtimestamp(now_dt.timestamp() + quar_s, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    # ID unique basé sur timestamp et hash du code
    code_hash = hashlib.sha256(code_content.encode("utf-8")).hexdigest()[:8]
    cid = f"cand_{int(now_dt.timestamp())}_{code_hash}"

    conn = _conn()
    _ensure_schema(conn)
    conn.execute(
        "INSERT INTO darwinian_candidates "
        "(candidate_id, name, code_content, author, ring, status, submitted_at, quarantine_until, "
        "trust_score, test_runs, test_passes, logs, meta) "
        "VALUES (?, ?, ?, ?, 4, ?, ?, ?, 0.0, 0, 0, '[]', ?)",
        (
            cid,
            name,
            code_content,
            author,
            STATUS_QUARANTINE,
            now_iso,
            until_iso,
            json.dumps(meta or {}, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()

    logger.info("[DARWINIAN ARENA] Candidat soumis en quarantaine Ring 4: %s (name=%s)", cid, name)
    cand = get_candidate(cid)
    return cand.to_dict() if cand else {}


def get_candidate(candidate_id: str) -> Optional[ArenaCandidate]:
    """Récupère un candidat depuis l'arène."""
    conn = _conn()
    _ensure_schema(conn)
    row = conn.execute(
        "SELECT candidate_id, name, code_content, author, ring, status, submitted_at, "
        "quarantine_until, trust_score, test_runs, test_passes, logs, meta "
        "FROM darwinian_candidates WHERE candidate_id = ?",
        (candidate_id,),
    ).fetchone()
    conn.close()

    if not row:
        return None

    try:
        logs = json.loads(row[11])
    except Exception:
        logs = []
    try:
        meta = json.loads(row[12])
    except Exception:
        meta = {}

    return ArenaCandidate(
        candidate_id=row[0],
        name=row[1],
        code_content=row[2],
        author=row[3],
        ring=int(row[4]),
        status=row[5],
        submitted_at=row[6],
        quarantine_until=row[7],
        trust_score=float(row[8]),
        test_runs=int(row[9]),
        test_passes=int(row[10]),
        logs=logs,
        meta=meta,
    )


def run_synthetic_test(
    candidate_id: str,
    test_input: Any = None,
    expected_output: Any = None,
    func_name: str = "solve",
) -> dict[str, Any]:
    """Exécute un test synthétique en bac à sable Ring 4 sur le code du candidat.

    Le code candidat est compilé et exécuté dans un namespace confiné (sans builtins
    dangereux). Si la fonction func_name(test_input) == expected_output, le test passe.
    """
    cand = get_candidate(candidate_id)
    if not cand:
        raise ValueError(f"Candidat introuvable: {candidate_id}")

    if cand.status in (STATUS_PROMOTED, STATUS_REJECTED):
        return {"error": f"Le candidat {candidate_id} est déjà clôturé ({cand.status})."}

    # Revérification de sécurité par acquit de conscience
    is_safe, scan_msg = _ast_safety_scan(cand.code_content)
    if not is_safe:
        return _record_test_result(cand, passed=False, log_msg=f"Échec sécurité AST: {scan_msg}")

    # Exécution confinée Ring 4
    safe_globals = {
        "__builtins__": {
            "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
            "enumerate": enumerate, "filter": filter, "float": float, "int": int,
            "len": len, "list": list, "map": map, "max": max, "min": min,
            "pow": pow, "range": range, "reversed": reversed, "round": round,
            "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
            "zip": zip, "isinstance": isinstance, "print": lambda *a, **kw: None,
        }
    }
    safe_locals: dict[str, Any] = {}

    t0 = time.perf_counter()
    try:
        exec(cand.code_content, safe_globals, safe_locals)
        if func_name not in safe_locals:
            return _record_test_result(
                cand, passed=False, log_msg=f"Fonction cible '{func_name}' non définie dans le code candidat."
            )

        target_func = safe_locals[func_name]
        if test_input is not None:
            if isinstance(test_input, (tuple, list)):
                result = target_func(*test_input)
            elif isinstance(test_input, dict):
                result = target_func(**test_input)
            else:
                result = target_func(test_input)
        else:
            result = target_func()

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)

        if expected_output is not None:
            if result == expected_output:
                return _record_test_result(cand, passed=True, log_msg=f"Test PASS ({elapsed_ms}ms) -> {result}")
            else:
                return _record_test_result(
                    cand, passed=False, log_msg=f"Test FAIL ({elapsed_ms}ms) -> attendu {expected_output}, obtenu {result}"
                )
        else:
            return _record_test_result(cand, passed=True, log_msg=f"Test PASS sans assertion ({elapsed_ms}ms)")

    except Exception as e:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return _record_test_result(cand, passed=False, log_msg=f"RuntimeError pendant le test ({elapsed_ms}ms): {e}")


def _record_test_result(cand: ArenaCandidate, passed: bool, log_msg: str) -> dict[str, Any]:
    new_runs = cand.test_runs + 1
    new_passes = cand.test_passes + (1 if passed else 0)
    new_score = round(new_passes / max(1, new_runs), 2)
    new_status = STATUS_TESTING if cand.status == STATUS_QUARANTINE else cand.status

    # Limite à 20 logs dans le storage pour éviter la saturation
    logs = cand.logs + [f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {log_msg}"]
    if len(logs) > 20:
        logs = logs[-20:]

    conn = _conn()
    conn.execute(
        "UPDATE darwinian_candidates "
        "SET test_runs = ?, test_passes = ?, trust_score = ?, status = ?, logs = ? "
        "WHERE candidate_id = ?",
        (new_runs, new_passes, new_score, new_status, json.dumps(logs, ensure_ascii=False), cand.candidate_id),
    )
    conn.commit()
    conn.close()

    return {
        "candidate_id": cand.candidate_id,
        "test_passed": passed,
        "test_runs": new_runs,
        "test_passes": new_passes,
        "trust_score": new_score,
        "status": new_status,
        "log": log_msg,
    }


def evaluate_promotion(
    candidate_id: str,
    *,
    min_trust_score: float = DEFAULT_MIN_TRUST_SCORE,
    min_test_runs: int = 3,
    ignore_time_lock: bool = False,
) -> dict[str, Any]:
    """Évalue si un candidat en quarantaine peut être promu en Ring 1 (DEV/TRUSTED).

    Conditions cumulatives pour la promotion :
    1. test_runs >= min_test_runs
    2. trust_score >= min_trust_score (défaut 0.85)
    3. Heure actuelle >= quarantine_until (sauf si ignore_time_lock=True pour dérogation/tests)
    """
    cand = get_candidate(candidate_id)
    if not cand:
        raise ValueError(f"Candidat introuvable: {candidate_id}")

    if cand.status == STATUS_PROMOTED:
        return {"candidate_id": candidate_id, "promoted": True, "status": STATUS_PROMOTED, "ring": cand.ring, "reason": "Déjà promu"}
    if cand.status == STATUS_REJECTED:
        return {"candidate_id": candidate_id, "promoted": False, "status": STATUS_REJECTED, "reason": "Déjà rejeté"}

    # Vérification du nombre de tests
    if cand.test_runs < min_test_runs:
        return {
            "candidate_id": candidate_id,
            "promoted": False,
            "status": cand.status,
            "reason": f"Nombre de tests insuffisant ({cand.test_runs}/{min_test_runs})",
        }

    # Vérification du score de confiance
    if cand.trust_score < min_trust_score:
        # Rejet automatique si beaucoup d'échecs et score faible
        if cand.test_runs >= 5 and cand.trust_score < 0.5:
            _set_status_ring(cand.candidate_id, STATUS_REJECTED, 4)
            return {
                "candidate_id": candidate_id,
                "promoted": False,
                "status": STATUS_REJECTED,
                "reason": f"Rejeté : trust_score insuffisant ({cand.trust_score} < {min_trust_score}) après {cand.test_runs} tests",
            }
        return {
            "candidate_id": candidate_id,
            "promoted": False,
            "status": cand.status,
            "reason": f"Score de confiance insuffisant ({cand.trust_score} < {min_trust_score})",
        }

    # Vérification de la durée de quarantaine
    if not ignore_time_lock:
        try:
            until_dt = datetime.fromisoformat(cand.quarantine_until.replace(" ", "T"))
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            if now_utc < until_dt:
                rem_s = int((until_dt - now_utc).total_seconds())
                return {
                    "candidate_id": candidate_id,
                    "promoted": False,
                    "status": cand.status,
                    "reason": f"En quarantaine Ring 4 pour encore {rem_s}s (jusqu'à {cand.quarantine_until})",
                }
        except Exception:
            pass

    # PROMOTION AU RING 1 !
    _set_status_ring(cand.candidate_id, STATUS_PROMOTED, 1)
    logger.info("[DARWINIAN ARENA] CANDIDAT PROMU EN RING 1 ! id=%s, score=%f", candidate_id, cand.trust_score)

    return {
        "candidate_id": candidate_id,
        "promoted": True,
        "status": STATUS_PROMOTED,
        "ring": 1,
        "trust_score": cand.trust_score,
        "reason": f"Promotion réussie : {cand.test_passes}/{cand.test_runs} tests (score {cand.trust_score})",
    }


def _set_status_ring(candidate_id: str, status: str, ring: int) -> None:
    conn = _conn()
    conn.execute("UPDATE darwinian_candidates SET status = ?, ring = ? WHERE candidate_id = ?", (status, ring, candidate_id))
    conn.commit()
    conn.close()


def list_candidates(status: Optional[str] = None) -> list[dict[str, Any]]:
    """Liste les candidats présents dans l'arène."""
    conn = _conn()
    _ensure_schema(conn)
    if status:
        rows = conn.execute("SELECT candidate_id FROM darwinian_candidates WHERE status = ? ORDER BY submitted_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT candidate_id FROM darwinian_candidates ORDER BY submitted_at DESC").fetchall()
    conn.close()

    out = []
    for (cid,) in rows:
        c = get_candidate(cid)
        if c:
            out.append(c.to_dict())
    return out


class SecurityError(Exception):
    """Exception levée en cas de violation des règles Ring 4."""
    pass


# ============================================================================
# CLI INTERACTIF
# ============================================================================

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Nokido Darwinian Arena (Quarantaine Ring 4 & Évolution)")
    subparsers = parser.add_subparsers(dest="command", help="Commande à exécuter")

    list_p = subparsers.add_parser("list", help="Lister les candidats")
    list_p.add_argument("--status", choices=[STATUS_QUARANTINE, STATUS_TESTING, STATUS_PROMOTED, STATUS_REJECTED])

    test_p = subparsers.add_parser("test", help="Exécuter un test synthétique")
    test_p.add_argument("candidate_id")
    test_p.add_argument("--input", default="[]", help="Input JSON")
    test_p.add_argument("--expected", default="null", help="Output attendu JSON")
    test_p.add_argument("--func", default="solve", help="Nom de la fonction")

    promo_p = subparsers.add_parser("promote", help="Évaluer la promotion d'un candidat")
    promo_p.add_argument("candidate_id")
    promo_p.add_argument("--ignore-lock", action="store_true", help="Ignorer le verrou temporel de 24h")

    args = parser.parse_args()
    if args.command == "list" or not args.command:
        print(json.dumps(list_candidates(args.status), indent=2, ensure_ascii=False))
    elif args.command == "test":
        inp = json.loads(args.input)
        exp = json.loads(args.expected) if args.expected != "null" else None
        res = run_synthetic_test(args.candidate_id, test_input=inp, expected_output=exp, func_name=args.func)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    elif args.command == "promote":
        res = evaluate_promotion(args.candidate_id, ignore_time_lock=args.ignore_lock)
        print(json.dumps(res, indent=2, ensure_ascii=False))
    sys.exit(0)
