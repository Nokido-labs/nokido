"""forge_swarm_validator.py — Gatekeeper pré-vol déterministe (ForgeSwarm M0).

S'insère ENTRE la sortie GOAP (le LLM qui produit le DAG) et le DAGRunner. 100%
déterministe, ~ms CPU. Neutralise le SPOF du sommet : un plan faux (collision,
fichier fantôme, cycle, consommateur orphelin) est REFUSÉ avant de brûler de
l'APU, et l'erreur est renvoyée au GOAP pour re-plan. (cf roadmap_forge_swarm §12.)

    ok, errors = validate_swarm_plan(plan, root=".", import_graph=None)

Schéma tâche attendu :
  {"task_id": "T1", "targets": ["auth.py"], "deps": ["T0"],
   "op": "edit_sr|create|delete|rename|noop", "affects_exports": false}
  (`context_files` accepté comme alias de `targets`.)

`import_graph` (règle 4) = {fichier: set(fichiers qui l'importent)}, INJECTÉ
(découplé de forge_repo_map → testable seul). Si None, la règle 4 est sautée.
"""

from __future__ import annotations

from pathlib import Path

OPS = {"edit_sr", "create", "delete", "rename", "noop"}
_NEEDS_EXISTING = {"edit_sr", "delete", "rename", "noop"}  # la cible doit préexister


def _targets(task: dict) -> list[str]:
    return list(task.get("targets") or task.get("context_files") or [])


def _rounds(plan: list[dict]) -> tuple[list[list[dict]], list[str]]:
    """Tri topologique en ROUNDS (couches Kahn). (rounds, erreurs)."""
    by_id = {t["task_id"]: t for t in plan}
    errs: list[str] = []
    deps_of: dict[str, list[str]] = {}
    for t in plan:
        ds = list(t.get("deps") or [])
        for d in ds:
            if d not in by_id:
                errs.append(f"R3: dépendance inconnue '{d}' (tâche {t['task_id']})")
        deps_of[t["task_id"]] = [d for d in ds if d in by_id]

    done: set[str] = set()
    remaining = set(by_id)
    rounds: list[list[dict]] = []
    while remaining:
        ready = [tid for tid in remaining if all(d in done for d in deps_of[tid])]
        if not ready:
            errs.append(f"R3: dépendance circulaire entre {sorted(remaining)}")
            break
        rounds.append([by_id[tid] for tid in sorted(ready)])
        done.update(ready)
        remaining -= set(ready)
    return rounds, errs


def validate_swarm_plan(
    plan: list[dict],
    root: str | Path = ".",
    import_graph: dict[str, set[str]] | None = None,
) -> tuple[bool, list[str]]:
    """Valide un DAG d'essaim. Retourne (ok, liste d'erreurs lisibles par le GOAP)."""
    root = Path(root)
    if not isinstance(plan, list):
        return False, ["plan doit être une liste de tâches"]
    if not plan:
        return True, []  # plan vide = no-op valide

    errors: list[str] = []

    # ── Structurel (bloque tout le reste si cassé) ───────────────────────────
    ids = [t.get("task_id") for t in plan]
    if any(i is None for i in ids):
        errors.append("tâche sans task_id")
    dup = sorted({i for i in ids if i and ids.count(i) > 1})
    if dup:
        errors.append(f"task_id dupliqué: {dup}")
    for t in plan:
        op = t.get("op", "edit_sr")
        if op not in OPS:
            errors.append(f"op invalide '{op}' (tâche {t.get('task_id')})")
    if errors:
        return False, errors

    rounds, cyc = _rounds(plan)
    errors += cyc

    # ── Règle 1 : collision de round (2 workers // sur le même fichier) ──────
    for ri, rnd in enumerate(rounds):
        seen: dict[str, str] = {}
        for t in rnd:
            for f in _targets(t):
                if f in seen:
                    errors.append(
                        f"R1: fichier '{f}' ciblé par {seen[f]} ET {t['task_id']} dans le round {ri} "
                        f"(éditions parallèles sur un même fichier interdites)"
                    )
                else:
                    seen[f] = t["task_id"]

    # ── Règle 2 : intégrité FS (la cible existe ou est créée en amont) ──────
    created_upstream: set[str] = set()
    for rnd in rounds:
        for t in rnd:
            op = t.get("op", "edit_sr")
            for f in _targets(t):
                exists = (root / f).resolve().is_file() or f in created_upstream
                if op in _NEEDS_EXISTING and not exists:
                    errors.append(
                        f"R2: tâche {t['task_id']} ({op}) cible '{f}' qui n'existe pas "
                        f"(ni sur disque ni créé par une tâche amont)"
                    )
        for t in rnd:  # créations enregistrées APRÈS le round
            if t.get("op") == "create":
                created_upstream.update(_targets(t))

    # ── Règle 3 : acyclique → déjà couvert par _rounds (cyc) ────────────────

    # ── Règle 4 : couverture bipartite (pas de consommateur orphelin) ───────
    if import_graph is not None:
        all_targets = {f for t in plan for f in _targets(t)}
        orphans: set[tuple[str, str]] = set()
        for t in plan:
            if t.get("op") == "rename" or t.get("affects_exports"):
                for f in _targets(t):
                    for consumer in import_graph.get(f, set()):
                        if consumer not in all_targets:
                            orphans.add((f, consumer))
        for f, consumer in sorted(orphans):
            errors.append(
                f"R4: '{f}' modifie une API publique mais le consommateur '{consumer}' "
                f"(qui l'importe) n'est couvert par aucune tâche — complète le plan"
            )

    return (len(errors) == 0), errors
