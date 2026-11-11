# -*- coding: utf-8 -*-
"""app.forge_formes — Exposition des formes qui marchent et règles d'exécution.

Construit dynamiquement la liste des formes autorisées, règles et contraintes
depuis les hooks et gardes (tools/hook_capability_gate.py, tools/bash_guard.py,
tools/hook_search_guard.py).
SÉCURITÉ : Ne charge/n'importe JAMAIS les scripts de hooks en tant que modules Python
(car certains s'exécutent au niveau module avec json.load(sys.stdin) et sys.exit).
La lecture est purement syntaxique (ast.parse + ast.literal_eval).
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/formes-servies"

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List

_ROOT = Path(__file__).resolve().parent.parent


def _extraire_constantes_ast(chemin: Path, noms: list[str]) -> dict[str, Any]:
    """Extrait des constantes d'un fichier source Python via AST sans rien exécuter.
    
    Si une constante est absente, non littérale, ou si le fichier est illisible,
    la valeur associée est {"etat": "ILLISIBLE", "nom": nom}.
    """
    res: dict[str, Any] = {}
    if not chemin.exists():
        for nom in noms:
            res[nom] = {"etat": "ILLISIBLE", "nom": nom, "raison": "fichier_introuvable"}
        return res

    try:
        source = chemin.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(chemin))
    except Exception as e:
        for nom in noms:
            res[nom] = {"etat": "ILLISIBLE", "nom": nom, "raison": f"parse_error: {type(e).__name__}"}
        return res

    for node in tree.body:
        # Recherche des affectations simples : NOM = <valeur>
        target_name = None
        val_node = None
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in noms:
                    target_name = t.id
                    val_node = node.value
                    break
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id in noms:
                target_name = node.target.id
                val_node = node.value

        if target_name and val_node is not None:
            try:
                # ast.literal_eval pour extraire structures constantes
                val = ast.literal_eval(val_node)
                res[target_name] = val
            except Exception:
                # Peut être un appel de fonction ou expression non constante
                # Dans bash_guard : _PASSTHROUGHS = ["curl vers :8766", ...] + list(ALLOWED_RECOVERY)
                # Si c'est un ast.BinOp (ex. list + list), on peut tenter une évaluation sûre
                try:
                    val = _eval_binop_liste(val_node, res)
                    res[target_name] = val
                except Exception:
                    res[target_name] = {"etat": "ILLISIBLE", "nom": target_name, "raison": "non_literal"}

    for nom in noms:
        if nom not in res:
            res[nom] = {"etat": "ILLISIBLE", "nom": nom, "raison": "absent"}

    return res


def _eval_binop_liste(node: ast.AST, known_consts: dict[str, Any]) -> Any:
    """Évalue récursivement et en sécurité des concaténations de listes/tuples constantes."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_binop_liste(node.left, known_consts)
        right = _eval_binop_liste(node.right, known_consts)
        if isinstance(left, list) and isinstance(right, list):
            return left + right
    elif isinstance(node, ast.Call):
        # Cas re.compile("motif", ...) : le motif est la donnee, rien n'est compile ni execute.
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "compile"
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" and node.args):
            return ast.literal_eval(node.args[0])
        # Cas list(...)
        if isinstance(node.func, ast.Name) and node.func.id == "list" and len(node.args) == 1:
            arg_val = _eval_binop_liste(node.args[0], known_consts)
            return list(arg_val)
    elif isinstance(node, ast.Name):
        if node.id in known_consts:
            return known_consts[node.id]
    return ast.literal_eval(node)


_MESSAGE_COMPACT = 160


def _compacter(regle: dict) -> dict:
    """Sans regex et message court : le détail se demande, il ne se paie pas à chaque appel."""
    r = {k: v for k, v in regle.items() if k != "regex"}
    r["message"] = str(r.get("message", ""))[:_MESSAGE_COMPACT]
    return r


def build_formes_liste(limit: int | None = None, detail: bool = True) -> str:
    """Construit le JSON des formes et règles. `limit` borne les TROIS listes, ce qui est coupé se compte ; `detail=False` rend sans regex et messages courts."""
    out: Dict[str, Any] = {
        "ok": True,
        "formes": [],
        "regles_capability_gate": [],
        "ecartees": [],
        "gardes": {},
    }

    # 1. hook_capability_gate.py : REGLES
    path_cap = _ROOT / "tools" / "hook_capability_gate.py"
    consts_cap = _extraire_constantes_ast(path_cap, ["REGLES"])
    regles_raw = consts_cap.get("REGLES")

    if isinstance(regles_raw, list):
        for idx, item in enumerate(regles_raw):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                rx, msg = item[0], item[1]
                m = re.search(r"motif\s+[`'\"]?([A-Za-z0-9_-]+)[`'\"]?", msg)
                if m:
                    nom_motif = m.group(1)
                    out["regles_capability_gate"].append({
                        "motif": nom_motif,
                        "regex": rx,
                        "message": msg,
                    })
                else:
                    out["ecartees"].append({
                        "index": idx,
                        "regex": rx,
                        "message": msg,
                        "raison": "sans_motif",
                    })
            else:
                out["ecartees"].append({
                    "index": idx,
                    "valeur": str(item),
                    "raison": "format_invalide",
                })
    else:
        out["gardes"]["hook_capability_gate"] = regles_raw if isinstance(regles_raw, dict) else {
            "etat": "ILLISIBLE",
            "nom": "REGLES",
            "valeur": str(regles_raw),
        }

    # 2. bash_guard.py : _PASSTHROUGHS, ALLOWED_RECOVERY, _MONITOR_OK
    path_bash = _ROOT / "tools" / "bash_guard.py"
    consts_bash = _extraire_constantes_ast(path_bash, ["ALLOWED_RECOVERY", "_PASSTHROUGHS", "_MONITOR_OK"])

    passthroughs = consts_bash.get("_PASSTHROUGHS")
    allowed_recovery = consts_bash.get("ALLOWED_RECOVERY")
    monitor_ok = consts_bash.get("_MONITOR_OK")

    if isinstance(passthroughs, (list, tuple)):
        for p in passthroughs:
            out["formes"].append({"type": "passthrough_bash", "valeur": p})
    elif isinstance(passthroughs, dict) and passthroughs.get("etat") == "ILLISIBLE":
        out["gardes"]["bash_guard_passthroughs"] = passthroughs
    else:
        out["gardes"]["bash_guard_passthroughs"] = {
            "etat": "ILLISIBLE",
            "nom": "_PASSTHROUGHS",
            "valeur": str(passthroughs),
        }

    if isinstance(allowed_recovery, (list, tuple)):
        for r in allowed_recovery:
            out["formes"].append({"type": "allowed_recovery", "valeur": r})
    elif isinstance(allowed_recovery, dict) and allowed_recovery.get("etat") == "ILLISIBLE":
        out["gardes"]["bash_guard_allowed_recovery"] = allowed_recovery
    else:
        out["gardes"]["bash_guard_allowed_recovery"] = {
            "etat": "ILLISIBLE",
            "nom": "ALLOWED_RECOVERY",
            "valeur": str(allowed_recovery),
        }

    if isinstance(monitor_ok, dict) and monitor_ok.get("etat") == "ILLISIBLE":
        out["gardes"]["bash_guard_monitor_ok"] = monitor_ok
    else:
        out["gardes"]["bash_guard_monitor_ok"] = monitor_ok

    # 3. hook_search_guard.py : SIZE_LIMIT
    path_search = _ROOT / "tools" / "hook_search_guard.py"
    consts_search = _extraire_constantes_ast(path_search, ["SIZE_LIMIT"])
    size_limit = consts_search.get("SIZE_LIMIT")

    if isinstance(size_limit, (int, float)):
        out["formes"].append({"type": "search_guard_size_limit", "valeur": size_limit})
    elif isinstance(size_limit, dict) and size_limit.get("etat") == "ILLISIBLE":
        out["gardes"]["hook_search_guard_size_limit"] = size_limit
    else:
        out["gardes"]["hook_search_guard_size_limit"] = {
            "etat": "ILLISIBLE",
            "nom": "SIZE_LIMIT",
            "valeur": str(size_limit),
        }

    out["ok"] = not any(isinstance(g, dict) and g.get("etat") == "ILLISIBLE" for g in out["gardes"].values())
    out["detail"] = bool(detail)
    out["total_formes"] = len(out["formes"])
    out["total_regles"] = len(out["regles_capability_gate"])
    out["total_ecartees"] = len(out["ecartees"])
    if limit is not None:
        borne = max(0, int(limit))
        out["formes"] = out["formes"][:borne]
        out["regles_capability_gate"] = out["regles_capability_gate"][:borne]
        out["ecartees"] = out["ecartees"][:borne]
    out["coupees"] = (out["total_formes"] - len(out["formes"])
                      + out["total_regles"] - len(out["regles_capability_gate"])
                      + out["total_ecartees"] - len(out["ecartees"]))
    if not detail:
        out["regles_capability_gate"] = [_compacter(r) for r in out["regles_capability_gate"]]
        out["ecartees"] = [_compacter(r) for r in out["ecartees"]]
        out["pour_le_detail"] = "hub action=formes mode=detail limit=<N>"
    return json.dumps(out, ensure_ascii=False, indent=2)
