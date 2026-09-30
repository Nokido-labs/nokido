"""hook_posttool_validate.py — PostToolUse hook (Write|Edit).

Auto-validates the AST of a Python file right after it is written/edited, so
the client (Claude) does NOT spend a separate tool call on the double-check.
Silent on success; on a syntax error it feeds the message back (exit 2) so the
client fixes it immediately.

Wired in .claude/settings.local.json -> hooks.PostToolUse (matcher Write|Edit).
"""

import ast
import json
import sys
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

# Fichiers dont une edition doit passer le garde HELD-OUT (invariants sur donnees de
# prod masquees). Scope STRICT : l'organe embedder, ou une regression de dimension /
# kernel casse silencieusement tout le RAG. Etendre au fil des profils held-out.
_HELDOUT_KIND = {
    "embedder": ("forge_embed_router", "forge_npu_embedder"),
}

# Une violation de FORME de sortie prouve que le CODE est casse -> on bloque.
# Une exception peut n'etre qu'un service momentanement absent (:8099) -> advisory,
# JAMAIS bloquer une edition legitime sur un alea transitoire (asymetrie des couts).
_REGRESSION_CODE = ("dim ", "NaN/Inf", "norme", "auto-cos", "compte sortie")


def _heldout_kind(path: str):
    low = path.replace("\\", "/").lower()
    for kind, markers in _HELDOUT_KIND.items():
        if any(m in low for m in markers):
            return kind
    return None


def _run_heldout(path: str, kind: str) -> int:
    """Le hook tourne en process FRAIS -> importe le module JUSTE edite et verifie ses
    invariants held-out. Bloque (exit 2) UNIQUEMENT sur une regression de forme prouvee.
    """
    try:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for p in (str(root / "tools"), str(root / "app")):
            if p not in sys.path:
                sys.path.insert(0, p)
        import importlib

        from nokido_agent.tools import forge_heldout_gate as hg
        for m in ("forge_embed_router",):
            if m in sys.modules:
                importlib.reload(sys.modules[m])
        r = hg.block_if_regressed(path, kind=kind)
    except Exception as e:  # noqa: BLE001 - un garde ne casse jamais l'edition
        print(f"[heldout] check indisponible ({type(e).__name__}) — edition non bloquee", file=sys.stderr)
        return 0
    if r.get("verdict") == "REGRESSION":
        reason = str(r.get("reason", ""))
        if any(marqueur in reason for marqueur in _REGRESSION_CODE):
            print(f"[heldout] REGRESSION de code sur {path}: {reason} — corriger avant de continuer", file=sys.stderr)
            return 2
        print(f"[heldout] signal non concluant ({reason}) — service embedder absent ? edition non bloquee", file=sys.stderr)
        return 0
    if r.get("verdict") == "held_out_OK":
        print(f"[heldout] invariants OK ({r.get('n')} chunks masques, dim {r.get('dim')})", file=sys.stderr)
    return 0


def _resolve_path(tool_input: dict) -> str:
    """Chemin edite, quelle que soit la ROUTE d'edition.

    Write/Edit natifs postent `file_path` (absolu) ; `governed_edit` poste `path`
    RELATIF au depot. Ne lire que `file_path` rendait ce garde INJOIGNABLE des que
    l'enforce thin-client est ON : forge_tool_gate deny alors Write/Edit sur Nokido,
    donc l'unique consommateur de forge_heldout_gate ne tournait plus sur AUCUNE
    edition du depot. Garde present, signal sans emetteur.
    """
    raw = tool_input.get("file_path") or tool_input.get("path") or ""
    if not raw:
        return ""
    p = Path(raw)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[1] / raw
    return str(p)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    path = _resolve_path(data.get("tool_input") or {})
    if not path or not path.endswith(".py"):
        return 0
    try:
        with open(path, encoding="utf-8") as fh:
            # `compile` et non `ast.parse` : celui-ci accepte des fichiers que
            # Python refuse d'executer (`from __future__` precede d'une autre
            # instruction, entre autres). Un validateur moins strict que
            # l'interpreteur ne valide rien -- mesure 2026-08-29, deux fois.
            compile(fh.read(), path, "exec")
    except SyntaxError as exc:
        print(
            f"[posttool-validate] SYNTAX ERROR in {path}: line {exc.lineno}: {exc.msg}",
            file=sys.stderr,
        )
        return 2
    except Exception:
        return 0
    kind = _heldout_kind(path)
    if kind:
        return _run_heldout(path, kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
