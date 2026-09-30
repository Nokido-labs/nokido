"""app/forge_repo_map_tools.py - outils deterministes view/edit pour agents.

Couple le forge_repo_map (carte topographique) avec des operations atomiques
sur fichiers. Conception Aider/OpenHands : l'agent navigue librement via la
map, ouvre les fichiers a la demande, edite par bloc EXACT (anti-hallucination).

Tools exposes :
  - view_file_content(path, start_line, end_line) -> str
    Lit le fichier dans la fenetre [start, end]. Pas de limit par defaut.
  - edit_file_block(path, old_block, new_block, expect_unique=True) -> dict
    Remplace old_block par new_block IFF old_block apparait exactement N fois.
    expect_unique=True (defaut) : echec si old_block n est pas unique - force
    l agent a contextualiser son edit (anti-collision).

Aucun LLM dans ce module. Operations pure I/O + assertions. Permet a un
juge symbolique (forge_scorecard.evaluate_symbolic) d arbitrer le rendu.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path


# === view_file_content =======================================================


def view_file_content(
    path: str | Path, start_line: int = 1, end_line: int | None = None, max_chars: int = 50000
) -> dict:
    """Lit le fichier path dans la fenetre lignes [start, end].
    Lignes 1-indexed, end_line inclusif. None = jusqu a fin.
    Retourne {ok, content, lines, truncated, error}."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"file not found: {p}", "content": "", "lines": 0, "truncated": False}
    if not p.is_file():
        return {"ok": False, "error": f"not a file: {p}", "content": "", "lines": 0, "truncated": False}
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": f"read error: {e}", "content": "", "lines": 0, "truncated": False}
    all_lines = raw.splitlines()
    total = len(all_lines)
    start_idx = max(0, start_line - 1)
    end_idx = total if end_line is None else min(total, end_line)
    window = all_lines[start_idx:end_idx]
    out = "\n".join(window)
    truncated = False
    if len(out) > max_chars:
        out = out[:max_chars]
        truncated = True
    return {
        "ok": True,
        "content": out,
        "lines": len(window),
        "total_lines": total,
        "start_line": start_line,
        "end_line": start_idx + len(window),
        "truncated": truncated,
    }


# === edit_file_block =========================================================


def edit_file_block(
    path: str | Path, old_block: str, new_block: str, expect_unique: bool = True, backup: bool = True
) -> dict:
    """Remplace old_block par new_block dans le fichier.

    Anti-hallucination : si old_block n est pas trouve OU pas unique (quand
    expect_unique=True), echec. L agent doit alors lire le contexte plus
    large pour produire un old_block discriminant.

    backup=True : copie path -> path.bak.<ts> avant edit (restore facile).
    Retourne {ok, matches, replaced, backup_path, error}."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": f"file not found: {p}", "matches": 0, "replaced": False, "backup_path": None}
    if not p.is_file():
        return {"ok": False, "error": f"not a file: {p}", "matches": 0, "replaced": False, "backup_path": None}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": f"read error: {e}", "matches": 0, "replaced": False, "backup_path": None}

    # Normalisation : preserve l'encodage source, mais normalise les line endings
    # pour la recherche (\r\n -> \n). Re-encode apres edit avec le ending d origine.
    src_lineend = "\r\n" if "\r\n" in text else "\n"
    if src_lineend == "\r\n":
        text_norm = text.replace("\r\n", "\n")
        old_norm = old_block.replace("\r\n", "\n")
        new_norm = new_block.replace("\r\n", "\n")
    else:
        text_norm = text
        old_norm = old_block
        new_norm = new_block

    n = text_norm.count(old_norm)
    if n == 0:
        return {"ok": False, "error": "old_block not found", "matches": 0, "replaced": False, "backup_path": None}
    if expect_unique and n > 1:
        return {
            "ok": False,
            "error": f"old_block not unique ({n} matches) - elargis le contexte pour discriminer",
            "matches": n,
            "replaced": False,
            "backup_path": None,
        }

    backup_path: str | None = None
    if backup:
        ts = int(time.time())
        bk = p.with_suffix(p.suffix + f".bak.{ts}")
        try:
            shutil.copy2(str(p), str(bk))
            backup_path = str(bk)
        except OSError:
            pass  # backup soft-fail, l edit continue

    # Edit : remplace seulement la PREMIERE occurrence (deterministe).
    new_text = text_norm.replace(old_norm, new_norm, 1)
    if src_lineend == "\r\n":
        new_text = new_text.replace("\n", "\r\n")
    try:
        p.write_text(new_text, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"write error: {e}", "matches": n, "replaced": False, "backup_path": backup_path}
    return {
        "ok": True,
        "matches": n,
        "replaced": True,
        "backup_path": backup_path,
        "old_bytes": len(old_norm),
        "new_bytes": len(new_norm),
    }


# === insert_at_line ==========================================================


def insert_at_line(path: str | Path, line: int, content: str, backup: bool = True) -> dict:
    """Insere content APRES la ligne `line` (1-indexed). line=0 = debut fichier.
    Pour ajout d imports en tete ou d une nouvelle fonction en fin."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": f"not a file: {p}"}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": f"read error: {e}"}
    lines = text.splitlines(keepends=True)
    if line < 0 or line > len(lines):
        return {"ok": False, "error": f"line {line} out of range [0, {len(lines)}]"}
    # Ensure content ends with newline
    if content and not content.endswith("\n"):
        content += "\n"
    lines.insert(line, content)
    backup_path: str | None = None
    if backup:
        ts = int(time.time())
        bk = p.with_suffix(p.suffix + f".bak.{ts}")
        try:
            shutil.copy2(str(p), str(bk))
            backup_path = str(bk)
        except OSError:
            pass
    try:
        p.write_text("".join(lines), encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"write error: {e}", "backup_path": backup_path}
    return {"ok": True, "inserted_at": line, "bytes_added": len(content), "backup_path": backup_path}


# === restore_backup ==========================================================


def restore_backup(backup_path: str | Path) -> dict:
    """Restore : backup_path -> path.bak.<ts> remis a path. Idempotent."""
    bk = Path(backup_path)
    if not bk.exists():
        return {"ok": False, "error": f"backup not found: {bk}"}
    # Reconstruct original path : strip .bak.<ts>
    parts = bk.name.rsplit(".bak.", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return {"ok": False, "error": f"invalid backup name format: {bk.name}"}
    orig = bk.with_name(parts[0])
    try:
        shutil.copy2(str(bk), str(orig))
    except OSError as e:
        return {"ok": False, "error": f"restore error: {e}"}
    return {"ok": True, "restored": str(orig)}
