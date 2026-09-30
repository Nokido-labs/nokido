#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_build_repair.py — Boucle build-repair CAPABILITY-ADAPTIVE pour code généré.

Idées portées de Jeidoban/Ironsmith (ContentViewBuildRepairLoop) — cf mémoire
ironsmith-ideas-2026-06-15 + blackboard architecture_rules:ironsmith_build_repair_loop.
Comble le GAP Nokido : la génération (forge_tool_forger / forge_skill_forge / workers
forge_spawn_swarm) est aujourd'hui ONE-SHOT = fragile (le 7b rend du code cassé sans recours).

Principe (pourquoi ça rend le local-faible utile) :
  1. DÉTERMINISTE d'abord  : fixers purs (testés) bouclés jusqu'à stable — gratuit, sans LLM.
  2. MODEL-repair ensuite  : seulement si déterministe insuffisant. ROLLBACK si le candidat
     AUGMENTE les erreurs. BEST-CANDIDATE tracking (on garde/restaure le meilleur).
  3. CAPABILITY-ADAPTIVE   : modèle FORT (OAuth Opus/Gemini) -> repair itératif ;
     modèle FAIBLE (7b local) -> déterministe + 1 réécriture complète max (pas de diff fin).
  4. REGEN borné           : si bloqué, regénère depuis zéro (regen_fn), borné par la policy.

Anti-dup : `validate` réutilise forge_quality_gate si présent (sinon compile/AST). Les fixers
sont PLUGGABLES (ruff/black à brancher en privilégié). `infer_fn`/`regen_fn` injectés = testable
sans LLM. Compose forge_wip_rescue (best-candidate) + forge_llm_router (capability) côté appelant.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Callable

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)


@dataclass
class RepairPolicy:
    """Seuils CENTRALISÉS (pas de magie éparpillée) — discipline Ironsmith."""
    max_det_passes: int = 6      # boucles déterministes par cycle
    max_model_passes: int = 4    # tentatives model-repair par cycle (fort)
    max_regen: int = 2           # régénérations complètes max
    weak_rewrites: int = 1       # réécritures complètes max (faible)


# ---- VALIDATION (déterministe) ----
def validate(code: str, extra: list[Callable[[str], list[str]]] | None = None) -> list[str]:
    """Diagnostics déterministes. Syntaxe (compile) d'abord ; puis validateurs pluggables
    (quality_gate / ruff / checks custom). Retourne la liste d'erreurs (vide = OK)."""
    diags: list[str] = []
    try:
        compile(code, "<gen>", "exec")
    except SyntaxError as e:
        diags.append(f"SyntaxError:L{e.lineno}:{e.msg}")
    # CORE = syntaxe seulement. quality_gate/ruff = validateurs PLUGGABLES via `extra`
    # (trop stricts pour des snippets ; voir quality_gate_validator).
    for v in (extra or []):
        try:
            diags.extend(v(code) or [])
        except Exception:
            pass
    return diags


def quality_gate_validator(code: str) -> list[str]:
    """Validateur PLUGGABLE (à passer en `extra_validators`) : forge_quality_gate (pylint/coverage).
    Hors du core (trop strict pour des snippets) ; à brancher pour du code de prod."""
    try:
        from nokido_agent.app.forge_quality_gate import block_if_failing  # type: ignore
        block_if_failing(code)
    except ImportError:
        return []
    except Exception as e:  # noqa: BLE001
        return [f"quality_gate:{type(e).__name__}:{str(e)[:80]}"]
    return []


# ---- FIXERS DÉTERMINISTES (purs, sûrs, testés). Brancher ruff/black en privilégié. ----
def _fix_trailing_ws(code: str) -> str:
    return "\n".join(line.rstrip() for line in code.splitlines())


def _fix_final_newline(code: str) -> str:
    return code if code.endswith("\n") else code + "\n"


def _fix_tabs_to_spaces(code: str) -> str:
    return code.replace("\t", "    ")


DETERMINISTIC_FIXERS: list[tuple[str, Callable[[str], str]]] = [
    ("trailing_ws", _fix_trailing_ws),
    ("tabs", _fix_tabs_to_spaces),
    ("final_newline", _fix_final_newline),
]


def deterministic_fix(code: str) -> str:
    for _name, fn in DETERMINISTIC_FIXERS:
        try:
            code = fn(code)
        except Exception:
            pass
    return code


def _strip_fences(txt: str) -> str:
    t = (txt or "").strip()
    if t.startswith("```"):
        t = t[3:]
        if t[:6].lower().startswith("python"):
            t = t[6:]
        elif t[:3].lower() == "py\n":
            t = t[3:]
        t = t.strip()
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def model_repair(code: str, diags: list[str], infer_fn: Callable[[str], str]) -> str:
    """Demande au modèle le code CORRIGÉ. Le caller valide + rollback-si-pire. (Le mode diff
    unifié borné est le raffinement prod ; ici full-source validé = même discipline rollback.)"""
    prompt = ("Corrige ce code Python. Erreurs:\n- " + "\n- ".join(diags) +
              "\n\nCode:\n" + code + "\n\nRenvoie UNIQUEMENT le code Python corrigé complet, "
              "sans explication, sans markdown.")
    return _strip_fences(infer_fn(prompt))


def build_repair(initial_code: str, infer_fn: Callable[[str], str], *, capability: str = "strong",
                 policy: RepairPolicy | None = None,
                 extra_validators: list[Callable[[str], list[str]]] | None = None,
                 regen_fn: Callable[[], str] | None = None) -> dict:
    """Boucle build-repair. capability in {strong, weak}. Retourne {ok, code, errors, best_errors,
    cycles, history}. Garantit de rendre le MEILLEUR candidat même en échec."""
    pol = policy or RepairPolicy()
    code = initial_code
    best_code, best_err = code, len(validate(code, extra_validators))
    history: list[dict] = []

    def _track(c: str) -> int:
        nonlocal best_code, best_err
        n = len(validate(c, extra_validators))
        if n < best_err:
            best_code, best_err = c, n
        return n

    for cycle in range(pol.max_regen + 1):
        # 1) déterministe jusqu'à stable
        for _ in range(pol.max_det_passes):
            diags = validate(code, extra_validators)
            if not diags:
                break
            nxt = deterministic_fix(code)
            if nxt == code:
                break  # plus de progrès déterministe
            code = nxt
            _track(code)
        diags = validate(code, extra_validators)
        if not diags:
            _track(code)
            return {"ok": True, "code": code, "errors": 0, "best_errors": 0,
                    "cycles": cycle, "history": history}

        # 2) model-repair (capability-adaptive)
        if capability == "strong":
            for _ in range(pol.max_model_passes):
                cand = model_repair(code, diags, infer_fn)
                cn = len(validate(cand, extra_validators))
                history.append({"cycle": cycle, "mode": "model", "before": len(diags), "after": cn})
                _track(cand)
                if cn < len(diags):           # mieux -> on accepte
                    code, diags = cand, validate(cand, extra_validators)
                    if not diags:
                        return {"ok": True, "code": code, "errors": 0, "best_errors": 0,
                                "cycles": cycle, "history": history}
                else:                          # ROLLBACK : pas mieux -> on garde code, on arrête
                    break
        else:  # weak : pas de diff fin. Déterministe + 1 réécriture complète max.
            for _ in range(pol.weak_rewrites):
                cand = model_repair(code, diags, infer_fn)
                cn = _track(cand)
                history.append({"cycle": cycle, "mode": "weak_rewrite", "before": len(diags), "after": cn})
                if cn == 0:
                    return {"ok": True, "code": cand, "errors": 0, "best_errors": 0,
                            "cycles": cycle, "history": history}
                if cn < len(diags):
                    code = cand
                break

        # 3) regen borné si bloqué
        if regen_fn and cycle < pol.max_regen:
            try:
                code = regen_fn()
                _track(code)
            except Exception:
                break
        else:
            break

    return {"ok": best_err == 0, "code": best_code, "errors": len(validate(best_code, extra_validators)),
            "best_errors": best_err, "cycles": pol.max_regen, "history": history}


def _selftest() -> bool:
    # 1) FORT : code cassé, infer_fn répare -> ok
    broken = "def f(:\n    return 1\n"
    fixed = "def f():\n    return 1\n"
    r = build_repair(broken, lambda p: fixed, capability="strong")
    assert r["ok"] and r["errors"] == 0, r

    # 2) ROLLBACK : infer_fn rend du PIRE -> garde le meilleur (l'original), ok=False
    worse = "def f(:\n  def g(:\n"  # 2 erreurs > 1
    r2 = build_repair(broken, lambda p: worse, capability="strong")
    assert r2["ok"] is False and r2["best_errors"] == 1, r2  # n'a pas dégradé

    # 3) FAIBLE : déterministe + 1 réécriture -> ok
    r3 = build_repair(broken, lambda p: fixed, capability="weak")
    assert r3["ok"] and r3["errors"] == 0, r3

    # 4) DÉTERMINISTE seul : code valide mais tabs/trailing -> nettoyé, ok sans LLM
    msg = []
    r4 = build_repair("def h():\n\treturn 2  \n", lambda p: msg.append(1) or "X", capability="strong")
    assert r4["ok"] and not msg, ("le LLM ne devait pas être appelé", r4)

    # 5) REGEN : 1er code cassé, infer ne répare pas, regen_fn donne du bon
    r5 = build_repair(broken, lambda p: broken, capability="strong",
                      regen_fn=lambda: fixed, policy=RepairPolicy(max_model_passes=1))
    assert r5["ok"], r5
    print("forge_build_repair selftest OK (strong/rollback/weak/deterministic/regen)")
    return True


if __name__ == "__main__":
    _selftest()
