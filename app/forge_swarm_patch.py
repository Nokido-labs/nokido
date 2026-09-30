"""forge_swarm_patch.py — Search/Replace applier + VFS overlay (ForgeSwarm).

Cœur de correction DÉTERMINISTE (0 LLM), partagé par le worker (M2, qui valide
son propre patch) et le reducer (M5, qui applique en cascade). Voir roadmap §11.

- Format S/R (style Aider) — ancrage sur le CONTENU (insensible aux décalages
  de lignes, contrairement à un unified-diff) :

      <<<<<<< SEARCH
      <texte exact à trouver>
      =======
      <remplacement>
      >>>>>>> REPLACE

  Ancre non trouvée → `PatchError` (JAMAIS d'application floue silencieuse :
  le worker retentera avec le contenu réel ré-injecté).

- `VFSOverlay` — staging EN MÉMOIRE. `read()` lit l'overlay sinon le disque ;
  les ops (create/edit_sr/delete/rename/noop) mutent l'overlay ; `commit()` écrit
  tout d'un coup (atomicité all-or-nothing) ; `discard()` jette (rollback gratuit).
  Check AST LAZY : seul le fichier `.py` modifié est re-parsé (syntaxe brute, ~ms).
"""

from __future__ import annotations

import ast
from pathlib import Path


class PatchError(Exception):
    """Patch invalide : ancre absente, bloc malformé, op inconnue, syntaxe cassée."""


def parse_sr_blocks(text: str) -> list[tuple[str, str]]:
    """Extrait les couples (search, replace) d'une sortie worker. `PatchError` si malformé."""
    lines = text.splitlines()
    blocks: list[tuple[str, str]] = []
    i, n = 0, len(lines)
    while i < n:
        if lines[i].strip().startswith("<<<<<<<"):
            i += 1
            search: list[str] = []
            while i < n and not lines[i].strip().startswith("======="):
                if lines[i].strip().startswith(("<<<<<<<", ">>>>>>>")):
                    raise PatchError("bloc S/R malformé (divider ======= manquant)")
                search.append(lines[i])
                i += 1
            if i >= n:
                raise PatchError("bloc S/R sans divider =======")
            i += 1  # saute =======
            replace: list[str] = []
            while i < n and not lines[i].strip().startswith(">>>>>>>"):
                if lines[i].strip().startswith(("<<<<<<<", "=======")):
                    raise PatchError("bloc S/R malformé (marqueur >>>>>>> REPLACE manquant)")
                replace.append(lines[i])
                i += 1
            if i >= n:
                raise PatchError("bloc S/R sans marqueur >>>>>>> REPLACE")
            i += 1  # saute >>>>>>> REPLACE
            blocks.append(("\n".join(search), "\n".join(replace)))
        else:
            i += 1
    if not blocks:
        raise PatchError("aucun bloc SEARCH/REPLACE trouvé")
    return blocks


def apply_sr(content: str, blocks: list[tuple[str, str]]) -> str:
    """Applique les blocs S/R à `content`. Ancre exacte requise, sinon `PatchError`."""
    out = content
    for search, replace in blocks:
        if search == "":
            raise PatchError("bloc SEARCH vide (interdit)")
        if search not in out:
            raise PatchError(f"ancre SEARCH non trouvée: {search[:60]!r}")
        out = out.replace(search, replace, 1)  # 1re occurrence (l'ancre doit être unique)
    return out


class VFSOverlay:
    """Système de fichiers virtuel en mémoire — staging avant commit atomique."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._files: dict[str, str] = {}
        self._deleted: set[str] = set()

    def exists(self, path: str) -> bool:
        if path in self._deleted:
            return False
        return path in self._files or (self.root / path).is_file()

    def read(self, path: str) -> str:
        if path in self._deleted:
            raise PatchError(f"fichier supprimé dans l'overlay: {path}")
        if path in self._files:
            return self._files[path]
        p = self.root / path
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
        raise PatchError(f"fichier absent: {path}")

    def _set(self, path: str, content: str) -> None:
        if not path:
            raise PatchError("op sans target")
        if str(path).endswith(".py"):
            try:
                ast.parse(content)
            except SyntaxError as e:
                raise PatchError(f"syntaxe Python cassée dans {path}: {e}")
        self._deleted.discard(path)
        self._files[path] = content

    def apply(self, op: dict) -> None:
        """Applique une op worker (create/edit_sr/delete/rename/noop) à l'overlay."""
        kind = op.get("op", "edit_sr")
        target = op.get("target") or op.get("path")
        if kind == "noop":
            return
        if kind == "create":
            self._set(target, op.get("content", ""))
        elif kind == "edit_sr":
            blocks = op.get("blocks") or parse_sr_blocks(op.get("text", ""))
            self._set(target, apply_sr(self.read(target), blocks))
        elif kind == "delete":
            if not target:
                raise PatchError("delete sans target")
            self._files.pop(target, None)
            self._deleted.add(target)
        elif kind == "rename":
            new = op.get("new_path")
            if not new:
                raise PatchError("rename sans new_path")
            content = self.read(target)
            self._files.pop(target, None)
            self._deleted.add(target)
            self._set(new, content)
        else:
            raise PatchError(f"op inconnue: {kind}")

    def commit(self, dry_run: bool = False) -> list[str]:
        """Écrit l'overlay sur disque. Retourne les fichiers touchés (préfixe ~ modif, - suppr)."""
        touched: list[str] = []
        for path in sorted(self._deleted):
            p = self.root / path
            if not dry_run and p.is_file():
                p.unlink()
            touched.append(f"-{path}")
        for path in sorted(self._files):
            p = self.root / path
            if not dry_run:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(self._files[path], encoding="utf-8")
            touched.append(f"~{path}")
        return touched

    def discard(self) -> None:
        self._files.clear()
        self._deleted.clear()
