# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_code_surgery
#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: Unification CodeSurgeon + AST Helpers (shredded from core_agents/versioning/handlers)
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:95|agent:gemini-cli|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import ast as _ast_module
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("Nokido.Code.Surgery")


@dataclass
class SurgeryResult:
    """Résultat d'une opération chirurgicale AST."""

    success: bool
    node_name: str  # ancre cible (ex: "record_success")
    node_type: str  # "function" | "class" | "method"
    lines_before: int = 0  # taille avant patch
    lines_after: int = 0  # taille après patch
    error: str = ""  # message d'erreur si success=False
    backup_node: str = ""  # code original sérialisé (pour rollback unitaire)


class _NodeLocator(_ast_module.NodeVisitor):
    """Trouve un nœud par son nom dans un AST."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.results: list = []  # [(nœud, parent_class|None)]
        self._current_class: str = ""

    def visit_ClassDef(self, node: _ast_module.ClassDef) -> None:
        prev = self._current_class
        self._current_class = node.name
        if node.name == self.target:
            self.results.append((node, None))
        self.generic_visit(node)
        self._current_class = prev

    def visit_FunctionDef(self, node: _ast_module.FunctionDef) -> None:
        if node.name == self.target:
            self.results.append((node, self._current_class or None))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef


class _NodeReplacer(_ast_module.NodeTransformer):
    """Remplace le premier nœud correspondant au target par new_node."""

    def __init__(self, target: str, new_node: _ast_module.AST, class_scope: str = "") -> None:
        self.target = target
        self.new_node = new_node
        self.class_scope = class_scope
        self.replaced = False

    def _match(self, node: _ast_module.AST) -> bool:
        if self.replaced:
            return False
        name = getattr(node, "name", None)
        return name == self.target

    def visit_FunctionDef(self, node: _ast_module.FunctionDef) -> _ast_module.AST:
        if self._match(node):
            self.replaced = True
            logger.debug(f"[Surgeon] Remplacement : {node.name} (l.{node.lineno})")
            return _ast_module.copy_location(self.new_node, node)
        return self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: _ast_module.ClassDef) -> _ast_module.AST:
        if self._match(node):
            self.replaced = True
            logger.debug(f"[Surgeon] Remplacement classe : {node.name}")
            return _ast_module.copy_location(self.new_node, node)
        return self.generic_visit(node)


def ts_surgery(source: str, target: str, new_code: str) -> dict:
    """Mock ou bridge vers tree-sitter sidecar (si disponible)."""
    # Pour l'instant on retourne une erreur pour forcer le fallback AST natif
    # à moins qu'un sidecar ne soit détecté.
    return {"success": False, "message": "sidecar tree-sitter non détecté"}


class CodeSurgeon:
    """Moteur de patch chirurgical AST unifié."""

    def __init__(self, source_path: Path | str) -> None:
        self.source_path = Path(source_path)
        self._source = self.source_path.read_text(encoding="utf-8")
        self._tree = _ast_module.parse(self._source)
        self._pending: str = ""
        self._ops: list = []

    def locate(self, target: str) -> list:
        locator = _NodeLocator(target)
        locator.visit(self._tree)
        results = []
        for node, parent_cls in locator.results:
            results.append(
                {
                    "name": node.name,
                    "type": "class"
                    if isinstance(node, _ast_module.ClassDef)
                    else ("async_function" if isinstance(node, _ast_module.AsyncFunctionDef) else "function"),
                    "line": node.lineno,
                    "class": parent_cls or "",
                    "code": _ast_module.unparse(node),
                }
            )
        return results

    def locate_all(self) -> Dict[str, list]:
        result: Dict[str, list] = {}
        for node in _ast_module.walk(self._tree):
            if isinstance(node, _ast_module.ClassDef):
                methods = []
                for child in node.body:
                    if isinstance(child, (_ast_module.FunctionDef, _ast_module.AsyncFunctionDef)):
                        methods.append(
                            {
                                "name": child.name,
                                "line": child.lineno,
                                "async": isinstance(child, _ast_module.AsyncFunctionDef),
                            }
                        )
                result[node.name] = methods
        return result

    def apply_patch(self, target: str, new_code: str) -> SurgeryResult:
        ts_result = ts_surgery(self._source, target, new_code)
        if ts_result.get("success"):
            result_code = ts_result["result"]
            backup_code = ts_result["backup"]
            lines_before = backup_code.count("\n") + 1
            lines_after = new_code.count("\n") + 1
            self._pending = result_code
            self._ops.append(
                {
                    "ts": datetime.now().isoformat(),
                    "target": target,
                    "before": lines_before,
                    "after": lines_after,
                    "engine": "tree-sitter",
                }
            )
            return SurgeryResult(True, target, "function", lines_before, lines_after, "", backup_code)
        return self._apply_patch_ast(target, new_code)

    def _apply_patch_ast(self, target: str, new_code: str) -> SurgeryResult:
        try:
            new_tree = _ast_module.parse(new_code)
        except SyntaxError as e:
            return SurgeryResult(False, target, "?", error=f"SyntaxError: {e}")

        hits = self.locate(target)
        if not hits:
            return SurgeryResult(False, target, "?", error=f"Ancre '{target}' introuvable")
        hit = hits[0]
        node_type = hit["type"]

        candidates = [
            n
            for n in new_tree.body
            if isinstance(n, (_ast_module.FunctionDef, _ast_module.AsyncFunctionDef, _ast_module.ClassDef))
        ]
        if not candidates:
            return SurgeryResult(False, target, node_type, error="new_code vide")
        new_node = candidates[0]
        backup = hit["code"]

        replacer = _NodeReplacer(target, new_node)
        new_tree_full = replacer.visit(_ast_module.parse(self._source))
        if not replacer.replaced:
            return SurgeryResult(False, target, node_type, error="Replacement failed")

        try:
            _ast_module.fix_missing_locations(new_tree_full)
            result_code = _ast_module.unparse(new_tree_full)
            _ast_module.parse(result_code)
        except Exception as e:
            return SurgeryResult(False, target, node_type, error=f"Codegen failed: {e}")

        lines_before = len(backup.splitlines())
        lines_after = len(new_code.splitlines())
        self._pending = result_code
        self._ops.append(
            {
                "ts": datetime.now().isoformat(),
                "target": target,
                "before": lines_before,
                "after": lines_after,
                "engine": "ast-fallback",
            }
        )
        return SurgeryResult(True, target, node_type, lines_before, lines_after, "", backup)

    def apply_patch_batch(self, patches: List[Dict[str, str]]) -> List[SurgeryResult]:
        results = []
        for p in patches:
            r = self.apply_patch(p["target"], p["new_code"])
            results.append(r)
            if not r.success:
                break
            self._source = self._pending
            self._tree = _ast_module.parse(self._source)
        return results

    def write(self, target_path: Path | str = None) -> Path:
        if not self._pending:
            raise RuntimeError("write() sans patch")
        out = Path(target_path) if target_path else self.source_path
        out.write_text(self._pending, encoding="utf-8")
        self._source = self._pending
        self._tree = _ast_module.parse(self._source)
        self._pending = ""
        return out

    def get_pending(self) -> str:
        return self._pending

    def surgery_report(self) -> str:
        if not self._ops:
            return "  [dim]Aucune opération.[/dim]"
        lines = ["  [bold]🔬 Rapport chirurgie AST[/bold]"]
        for op in self._ops:
            delta = op["after"] - op["before"]
            sign = "+" if delta >= 0 else ""
            lines.append(
                f"  • [cyan]{op['target']}[/cyan] ({op['before']}→{op['after']} lignes, {sign}{delta}) [dim]{op['ts'][:19]}[/dim]"
            )
        return "\n".join(lines)
