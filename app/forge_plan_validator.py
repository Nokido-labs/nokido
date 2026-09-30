"""
forge_plan_validator.py — Nokido v18.5
========================================
Validation stricte des plans agent_tasks.
Implémente la règle system_rules ring=10 :
  "task(action=result) DOIT fournir un plan structuré non vide (LENGTH>50)"

SECURITY BY DESIGN :
  - Validation déterministe (pas de LLM)
  - Appelé par le Hub AVANT d écriture en DB
  - Rejet explicite avec message d erreur précis
  - Pas de side-effects (lecture seule du plan)

MODULARITÉ :
  - Importable indépendamment du Hub
  - Testable en isolation (self-test intégré)
  - Extensible : ajouter des règles sans toucher au Hub
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# SCHÉMA ATTENDU (security by design — déclaratif)
# ═══════════════════════════════════════════════════════════════

PLAN_REQUIRED_FIELDS = {"step", "action", "tool", "ok"}
PLAN_MIN_LENGTH = 50  # chars JSON minimum
PLAN_MIN_STEPS = 1  # au moins 1 step
PLAN_MAX_STEPS = 50  # sanity cap
PLAN_STEP_MAX_SIZE = 4096  # bytes par step (évite les BLOB accidentels)

# Types de tâches exemptés de validation stricte (legacy tests)
EXEMPT_TASK_TYPES = set()  # vide = personne n est exempté

# Exécutants dont on accepte le plan partiel (ring 0 uniquement)
TRUSTED_EXECUTORS = {"usr_naarob", "wrk_laforge", "wrk_nokido", "agt_claude"}


@dataclass
class PlanValidationResult:
    valid: bool
    reason: str
    steps_count: int = 0
    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class PlanValidator:
    """
    Valide la structure d un plan agent_tasks.
    Instancier une fois, appeler .validate() à chaque task(result).
    """

    def validate(
        self,
        plan: str | list | None,
        task_type: str = "generic",
        executor: str = "",
        task_id: str = "",
    ) -> PlanValidationResult:
        """
        Valide un plan. Retourne PlanValidationResult.

        Args:
            plan      : JSON string ou list de steps
            task_type : type de la tâche (generic/research/devops...)
            executor  : entité exécutante (pour trusted bypass)
            task_id   : pour les messages d erreur

        RÈGLES (ring=10) :
          1. plan non vide et non null
          2. JSON valide (list de dicts)
          3. LENGTH(JSON) > PLAN_MIN_LENGTH
          4. Au moins PLAN_MIN_STEPS step(s)
          5. Chaque step a les champs requis
          6. Aucun step ne dépasse PLAN_STEP_MAX_SIZE
        """
        ctx = f"[task={task_id[:12] if task_id else '?'}]"

        # Exemption legacy (aucune actuellement)
        if task_type in EXEMPT_TASK_TYPES:
            return PlanValidationResult(True, "task_type exempté", warnings=["EXEMPT"])

        # 1. Non vide
        if not plan:
            return PlanValidationResult(False, f"{ctx} plan vide ou null — obligation ring=10")

        # 2. Parser JSON
        if isinstance(plan, str):
            if len(plan) <= 2:
                return PlanValidationResult(False, f"{ctx} plan trop court ({len(plan)} chars, min={PLAN_MIN_LENGTH})")
            try:
                steps = json.loads(plan)
            except json.JSONDecodeError as e:
                return PlanValidationResult(False, f"{ctx} plan JSON invalide: {e}")
        elif isinstance(plan, list):
            steps = plan
            plan = json.dumps(steps, ensure_ascii=False)
        else:
            return PlanValidationResult(False, f"{ctx} plan type inconnu: {type(plan)}")

        # 3. Length
        if len(plan) < PLAN_MIN_LENGTH:
            return PlanValidationResult(False, f"{ctx} plan trop court ({len(plan)} chars < {PLAN_MIN_LENGTH} min)")

        # 4. List de dicts
        if not isinstance(steps, list):
            return PlanValidationResult(False, f"{ctx} plan doit être une liste de steps (reçu {type(steps).__name__})")

        if len(steps) < PLAN_MIN_STEPS:
            return PlanValidationResult(
                False, f"{ctx} plan doit avoir au moins {PLAN_MIN_STEPS} step(s) (reçu {len(steps)})"
            )

        if len(steps) > PLAN_MAX_STEPS:
            return PlanValidationResult(
                False, f"{ctx} plan trop long ({len(steps)} steps > {PLAN_MAX_STEPS} max) — découper"
            )

        # 5. Champs requis + taille par step
        warnings = []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                return PlanValidationResult(False, f"{ctx} step[{i}] n est pas un dict")

            missing = PLAN_REQUIRED_FIELDS - step.keys()
            if missing:
                # Exécutant de confiance → warning, pas erreur
                if executor in TRUSTED_EXECUTORS:
                    warnings.append(f"step[{i}] champs manquants: {missing} (trusted executor)")
                else:
                    return PlanValidationResult(
                        False, f"{ctx} step[{i}] champs manquants: {missing} (requis: {PLAN_REQUIRED_FIELDS})"
                    )

            # 6. Taille step
            step_size = len(json.dumps(step, ensure_ascii=False).encode())
            if step_size > PLAN_STEP_MAX_SIZE:
                return PlanValidationResult(
                    False,
                    f"{ctx} step[{i}] trop volumineux ({step_size} bytes > {PLAN_STEP_MAX_SIZE}) "
                    "— ne pas stocker de contenu binaire dans le plan",
                )

            # Warning si output vide
            if not step.get("output") and not step.get("code"):
                warnings.append(f"step[{i}] output vide — plan moins rejouable")

        return PlanValidationResult(valid=True, reason="OK", steps_count=len(steps), warnings=warnings)

    def enforce(
        self,
        plan: str | list | None,
        task_type: str = "generic",
        executor: str = "",
        task_id: str = "",
    ) -> str:
        """
        Comme validate() mais lève ValueError si invalide.
        Usage dans le Hub : appeler avant écriture DB.
        """
        result = self.validate(plan, task_type, executor, task_id)
        if not result.valid:
            raise ValueError(f"PlanValidator REJECT: {result.reason} (ring=10 rule: plan obligatoire)")
        return result.reason


# Singleton
_validator: PlanValidator | None = None


def get_plan_validator() -> PlanValidator:
    global _validator
    if _validator is None:
        _validator = PlanValidator()
    return _validator


# ═══════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    v = PlanValidator()
    print("=== PlanValidator self-test ===\n")

    # Cas OK
    good_plan = json.dumps(
        [
            {
                "step": 1,
                "action": "Analyser logs nginx",
                "tool": "run_ssh",
                "args": {"cmd": "tail -1000 /var/log/nginx/error.log"},
                "output": "[200ms] 142 lignes 5xx trouvées",
                "ok": True,
                "duration_ms": 200,
            },
            {
                "step": 2,
                "action": "Filtrer erreurs 5xx",
                "tool": "python",
                "code": "lines = [l for l in logs if ' 5' in l]",
                "output": "42 erreurs 502",
                "ok": True,
                "duration_ms": 50,
            },
        ]
    )
    r = v.validate(good_plan, "devops", "agt_claude", "test_001")
    assert r.valid, f"FAIL good_plan: {r.reason}"
    print(f"  [OK] plan valide: {r.steps_count} steps")

    # Cas rejet : plan vide
    r2 = v.validate("", "generic", "agt_gemini", "test_002")
    assert not r2.valid
    print(f"  [OK] plan vide rejeté: {r2.reason}")

    # Cas rejet : JSON invalide
    r3 = v.validate("{not json}", "generic", "agt_gemini", "test_003")
    assert not r3.valid
    print(f"  [OK] JSON invalide rejeté: {r3.reason[:50]}")

    # Cas rejet : champ manquant (executor non trusted)
    bad_plan_short = json.dumps([{"step": 1, "action": "do thing"}])
    r4 = v.validate(bad_plan_short, "generic", "agt_gemini", "test_004")
    assert not r4.valid
    print(f"  [OK] plan court rejeté: {r4.reason[:60]}")

    # Cas warning : champ manquant mais trusted executor (plan assez long)
    bad_plan_long = json.dumps(
        [{"step": 1, "action": "action suffisamment longue pour passer le seuil de taille minimum requis", "args": {}}]
    )
    r5 = v.validate(bad_plan_long, "generic", "agt_claude", "test_005")
    assert r5.valid, f"trusted should pass: {r5.reason}"  # trusted = warning pas erreur
    print(f"  [OK] trusted executor warning: {r5.warnings}")

    # Cas rejet : plan string trop court (pas JSON valide et court)
    r6 = v.validate("[]", "generic", "agt_gemini", "test_006")
    assert not r6.valid, "empty list should fail"
    print(f"  [OK] plan liste vide rejeté: {r6.reason}")

    # Cas OK : step complet et assez long
    ok_step = json.dumps(
        [
            {
                "step": 1,
                "action": "Analyser configuration nginx et appliquer correctif",
                "tool": "run_python",
                "ok": True,
                "output": "OK",
                "args": {},
            }
        ]
    )
    r6b = v.validate(ok_step, "devops", "agt_gemini", "test_006b")
    assert r6b.valid, f"should pass: {r6b.reason}"
    print(f"  [OK] plan complet+long valide: {r6b.steps_count} step")

    # enforce() lève ValueError
    try:
        v.enforce(None, "generic", "agt_gemini", "test_007")
        raise AssertionError("devrait lever")
    except ValueError as e:
        print(f"  [OK] enforce() lève ValueError: {str(e)[:60]}")

    print("\nSelf-test PASS")
