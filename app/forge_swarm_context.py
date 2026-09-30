"""forge_swarm_context.py — contexte STÉRILE par worker (ForgeSwarm, M1).

Confine un sous-agent (worker) à son périmètre, contre la "pollution de contexte"
et l'hallucination d'API. Contexte à 3 niveaux (cf. docs/roadmap_forge_swarm.md §11) :

  1. CIBLE (éditable)   : contenu COMPLET des `context_files` — seuls fichiers
                          que le worker a le droit d'ÉCRIRE.
  2. RÉFÉRENCE (RO)      : SKELETON (signatures via forge_repo_map.file_skeleton)
                          des fichiers importés — le worker VOIT l'API sans le
                          corps (frugal en n_ctx, pas de fuite, pas de mod).
  3. PROJET RO complet  : HORS de ce module — c'est le mount Docker du Quality
                          Gate (pylint/mypy résolvent les imports). Ici on ne
                          gère QUE ce que le LLM voit + ce qu'il peut écrire.

`sterile_read` et `assert_writable` lèvent `ScopeViolation` hors périmètre →
testable seul (`test_forge_swarm_context.py`). Anti-traversal inclus.
"""

from __future__ import annotations

import sys
from pathlib import Path


class ScopeViolation(Exception):
    """Tentative de lecture/écriture hors du périmètre stérile du worker."""


def _resolve(path: str | Path, root: Path) -> Path:
    """Résout `path` sous `root`. Refuse toute sortie de racine (path traversal)."""
    root = Path(root).resolve()
    p = Path(path)
    p = (root / p) if not p.is_absolute() else p
    p = p.resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise ScopeViolation(f"hors-racine (traversal): {path}")
    return p


def _norm_set(files, root: Path) -> set[str]:
    return {str(_resolve(f, root)) for f in (files or [])}


def sterile_read(requested: str, allowed: list[str], root: str | Path) -> str:
    """Lit `requested` UNIQUEMENT s'il est dans la whitelist `allowed`.

    Hors whitelist → ScopeViolation (le worker ne peut pas fuir vers un autre
    fichier). Fichier absent → ScopeViolation.
    """
    root = Path(root)
    rp = _resolve(requested, root)
    if str(rp) not in _norm_set(allowed, root):
        raise ScopeViolation(f"lecture hors périmètre: {requested}")
    if not rp.is_file():
        raise ScopeViolation(f"fichier absent: {requested}")
    return rp.read_text(encoding="utf-8", errors="replace")


def assert_writable(path: str, writable: list[str], root: str | Path) -> None:
    """Lève ScopeViolation si `path` n'est pas une cible éditable du worker."""
    root = Path(root)
    if str(_resolve(path, root)) not in _norm_set(writable, root):
        raise ScopeViolation(f"écriture hors cible autorisée: {path}")


def _skeletons(files: list[str], root: Path, max_chars: int) -> str:
    """Interfaces (signatures) des fichiers référence via forge_repo_map.

    Fallback stérile (juste le nom) si le module/skeleton est indisponible —
    jamais le corps complet d'une référence.
    """
    out: list[str] = []
    file_skeleton = None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nokido_agent.app.forge_repo_map import file_skeleton as _fs  # type: ignore

        file_skeleton = _fs
    except Exception:
        file_skeleton = None
    for f in files:
        sk = ""
        if file_skeleton is not None:
            try:
                sk = file_skeleton(f, root)
            except Exception:
                sk = ""
        out.append(f"\n### {f} (interface)\n{sk or '(skeleton indisponible)'}")
    return "\n".join(out)[:max_chars]


def build_worker_context(
    target_files: list[str],
    reference_files: list[str] | None = None,
    root: str | Path = ".",
    *,
    read_fn=None,
    ref_max_chars: int = 6000,
) -> str:
    """Assemble le contexte stérile à 3 niveaux à injecter dans le prompt worker.

    - CIBLE : contenu complet de `target_files` (un fichier absent = `create`).
    - RÉFÉRENCE : skeletons compacts de `reference_files` (signatures only).
    """
    root = Path(root)
    parts: list[str] = ["## CIBLE — fichiers que tu peux ÉDITER (contenu complet)"]
    for f in target_files or []:
        if read_fn is not None:  # overlay-aware : voit les patchs des rounds amont (anti état-fantôme)
            try:
                body = read_fn(f)
            except Exception:
                body = "(nouveau fichier — vide)"
        else:
            rp = _resolve(f, root)
            body = rp.read_text(encoding="utf-8", errors="replace") if rp.is_file() else "(nouveau fichier — vide)"
        parts.append(f"\n### {f}\n```\n{body}\n```")
    if reference_files:
        parts.append("\n## RÉFÉRENCE — lecture seule (INTERFACES, NE PAS modifier)")
        parts.append(_skeletons(reference_files, root, ref_max_chars))
    return "\n".join(parts)
