# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_batch_forge_git_worker
#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:80|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_git_worker.py — Agent Git controle pour Nokido
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)
_ROOT = Path(__file__).resolve().parent.parent

_ALLOWED_ACTIONS = {
    "status",
    "log",
    "diff",
    "branch",
    "add",
    "commit",
    "push",
    "pull",
    "stash",
    "show",
}
_MAX_COMMIT_MSG = 200


class GitWorker:
    def __init__(self, root_path: Path | None = None) -> None:
        """Init.

        Args:
            root_path: Description.
        """
        self.root = Path(root_path) if root_path else _ROOT

    def _exec(self, args: list[str]) -> dict:
        """Exec.

        Args:
            args: Description.
        """
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            ok = result.returncode == 0
            logger.info(f"[GitWorker] git {' '.join(args[:3])} -> {'OK' if ok else 'FAIL'}")
            return {
                "ok": ok,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
                "code": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "stderr": "timeout 30s", "stdout": "", "code": -1}
        except FileNotFoundError:
            return {"ok": False, "stderr": "git introuvable", "stdout": "", "code": -1}
        except Exception as e:
            return {"ok": False, "stderr": str(e), "stdout": "", "code": -1}

    def run_safe(
        self,
        action: str,
        files: list[str] | None = None,
        message: str = "",
        limit: int = 10,
        branch: str = "alpha",
        remote: str = "origin",
    ) -> dict:
        """Run safe.

        Args:
            action: Description.
            files: Description.
            message: Description.
            limit: Description.
            branch: Description.
            remote: Description.
        """
        action = action.lower().strip()
        if action not in _ALLOWED_ACTIONS:
            return {
                "ok": False,
                "stdout": "",
                "stderr": f"Action '{action}' non autorisee. Autorisees: {sorted(_ALLOWED_ACTIONS)}",
                "code": -1,
            }

        if action == "status":
            return self._exec(["status", "--short"])
        if action == "log":
            return self._exec(["log", "--oneline", f"-{min(max(1, limit), 50)}"])
        if action == "diff":
            args = ["diff", "--stat"]
            if files:
                args += ["--"] + files
            return self._exec(args)
        if action == "branch":
            return self._exec(["branch", "-v"])
        if action == "show":
            return self._exec(["show", "--stat", "HEAD"])
        if action == "add":
            targets = files if files else ["."]
            for f in targets:
                p = (self.root / f).resolve()
                if not str(p).startswith(str(self.root)):
                    return {
                        "ok": False,
                        "stderr": f"Chemin hors projet: {f}",
                        "stdout": "",
                        "code": -1,
                    }
            return self._exec(["add"] + targets)
        if action == "commit":
            if not message:
                return {
                    "ok": False,
                    "stderr": "Message de commit requis.",
                    "stdout": "",
                    "code": -1,
                }
            return self._exec(["commit", "-m", message[:_MAX_COMMIT_MSG]])
        if action == "push":
            return self._exec(["push", remote or "origin", branch or "alpha"])
        if action == "pull":
            return self._exec(["pull", remote or "origin", branch or "alpha"])
        if action == "stash":
            return self._exec(["stash"])
        return {
            "ok": False,
            "stderr": f"Action '{action}' non implementee.",
            "stdout": "",
            "code": -1,
        }


worker = GitWorker()
