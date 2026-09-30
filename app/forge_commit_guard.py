import ast
import re
import logging
from pathlib import Path

logger = logging.getLogger("Nokido.CommitGuard")


class CommitGuard:
    def __init__(self):
        self.warnings = []
        self.blocks = []

    def check(self, files: list[str]) -> "GuardResult":
        """Vérifie la qualité des fichiers avant commit."""
        self.warnings = []
        self.blocks = []

        for file in files:
            path = Path(file)
            if not path.exists():
                continue
            if path.suffix != ".py":
                continue

            content = path.read_text(encoding="utf-8", errors="replace")

            # 1. Vérification AST (Imports valides)
            try:
                tree = ast.parse(content)
            except SyntaxError as e:
                self.blocks.append(f"SyntaxError dans {file}: {e}")
                continue

            # 2. Vérification Coherence (Graph impacts)
            self._check_coherence(file)

            # 3. Vérification TODO/FIXME
            self._check_todos(content, file)

        return GuardResult(len(self.blocks) == 0, self.warnings, self.blocks)

    def _check_coherence(self, file_path):
        try:
            from nokido_agent.app.forge_graph_linker import GraphLinker

            linker = GraphLinker()
            impacted_files = linker.get_impacted_by_change(file_path)
            if len(impacted_files) > 10:
                self.warnings.append(f"{file_path}: >10 fichiers impactés ({len(impacted_files)})")
        except Exception as e:
            logger.debug(f"Coherence check failed: {e}")

    def _check_todos(self, content, file_path):
        # Chercher TODO/FIXME suivis de CRITICAL ou BLOCK
        todo_pattern = re.compile(r"(TODO|FIXME|HACK)[:\s]+(CRITICAL|BLOCK)", re.IGNORECASE)
        matches = todo_pattern.findall(content)
        if matches:
            for m in matches:
                self.blocks.append(f"{file_path}: {m[0]} {m[1]} détecté")

        # Warnings pour TODO simples
        simple_todo = re.compile(r"TODO|FIXME|HACK", re.IGNORECASE)
        if simple_todo.search(content) and not matches:
            self.warnings.append(f"{file_path}: TODO/FIXME trouvés")


class GuardResult:
    def __init__(self, ok, warnings, blocks):
        self.ok = ok
        self.warnings = warnings
        self.blocks = blocks

    def __repr__(self):
        return f"<GuardResult ok={self.ok} warnings={len(self.warnings)} blocks={len(self.blocks)}>"
