"""nokido_phase0_derive_paths.py -- phase 0 du renommage: deriver la racine.

POURQUOI. Le depot est cite par son propre nom de dossier dans du code ACTIF, sous
deux formes: le chemin litteral (C:\\Users\\<owner>\\Script python IA\\LaForge\\...) et
la forme expanduser("~/Script python IA/LaForge/..."). La seconde retire le nom de
l'UTILISATEUR mais garde le nom du DOSSIER: elle casse donc au renommage, et elle est
DEJA fausse sous un compte de service dont HOME vaut C:\\Users\\Default. Tant que ces
sites existent, renommer le dossier est une chirurgie.

CE QUE FAIT L'OUTIL. Il remplace ces chemins par une derivation depuis __file__, qui
suit le dossier quel que soit son nom:

    __import__("os").path.expanduser(r"~\\Script python IA\\LaForge\\RAG\\x.db")
    -> str(__import__("pathlib").Path(__file__).resolve().parents[1] / "RAG" / "x.db")

CE QU'IL NE FAIT PAS, ET POURQUOI. Il ne touche NI les commentaires NI les docstrings
(le nom du dossier y est de la prose, elle releve de l'autre passe), NI les chaines
multi-lignes destinees a un shell externe (commande de hook avec %USERPROFILE%, tache
planifiee): la derivation par __file__ ne s'y applique pas, elles demandent une
interpolation a l'execution et sont listees comme MANUEL. Il ignore aussi les scripts
jetables (tmp_*, _*), bench_fixtures et _attic: du code mort reecrit est du bruit dans
la revue.

GARDE. Chaque fichier reecrit est re-parse (ast.parse) AVANT ecriture: un fichier qui
ne parse plus n'est pas ecrit, il est signale. Dry-run par defaut.

CLI :
    LAFORGE_PYTHON tools/nokido_phase0_derive_paths.py            # dry-run + rapport
    LAFORGE_PYTHON tools/nokido_phase0_derive_paths.py --apply
    LAFORGE_PYTHON tools/nokido_phase0_derive_paths.py --json
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/rename : phase 0 du renommage, deriver la racine"

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SKIP_PARTS = ("_attic", "bench_fixtures", "node_modules", ".venv")

# Racine du depot citee en dur: soit ~, soit un profil utilisateur absolu.
_HOME = r"(?:~|[A-Za-z]:[\\/]+Users[\\/]+[^\\/]+)"
_ROOT_RE = re.compile(rf"^{_HOME}[\\/]+Script python IA[\\/]+LaForge(?P<tail>(?:[\\/]+[^\\/]+)*)[\\/]*$")
# Le dossier PARENT (depots freres: netcfg-agent-mcp, ...). Meme defaut: ces chemins
# sont deja faux sous un compte dont HOME vaut C:\Users\Default, la derivation corrige
# les deux maux d'un coup. On le derive de parents[depth + 1].
_SUPER_RE = re.compile(rf"^{_HOME}[\\/]+Script python IA(?P<tail>(?:[\\/]+[^\\/]+)*)[\\/]*$")

# Chaine qui NOMME le dossier sans etre convertible ici (shell externe, %VAR%).
_MENTION_RE = re.compile(r"Script python IA[\\/]+LaForge")


def _in_scope(p: Path) -> bool:
    rel = p.relative_to(ROOT)
    if any(part in SKIP_PARTS for part in rel.parts):
        return False
    name = p.name
    if name.startswith("tmp_") or name.startswith("_"):
        return False
    return True


def _depth(p: Path) -> int:
    """Nombre de parents entre le fichier et la racine du depot."""
    return len(p.relative_to(ROOT).parts) - 1


def _expr(depth: int, tail: str) -> str:
    base = f'__import__("pathlib").Path(__file__).resolve().parents[{depth}]'
    parts = [seg for seg in re.split(r"[\\/]+", tail) if seg]
    for seg in parts:
        base += f' / "{seg}"'
    return f"str({base})"


def _line_offsets(src: str) -> list[int]:
    off, acc = [0], 0
    for line in src.splitlines(keepends=True):
        acc += len(line)
        off.append(acc)
    return off


def _abs(off: list[int], lineno: int, col: int) -> int:
    return off[lineno - 1] + col


def _annotate(tree: ast.AST) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent  # type: ignore[attr-defined]


def _is_expanduser_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "expanduser"
        and len(node.args) == 1
        and not node.keywords
    )


def _scan_file(p: Path) -> tuple[str | None, list[dict], list[dict]]:
    """Rend (nouvelle source ou None, conversions, sites laisses en manuel)."""
    src = p.read_text(encoding="utf-8", errors="replace")
    if "Script python IA" not in src:
        return None, [], []
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return None, [], [{"ligne": exc.lineno or 0, "motif": f"fichier non parsable: {exc.msg}"}]
    _annotate(tree)

    depth = _depth(p)
    offs = _line_offsets(src)
    edits: list[tuple[int, int, str]] = []
    faits: list[dict] = []
    manuels: list[dict] = []
    couverts: list[tuple[int, int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        val = node.value
        if "Script python IA" not in val:
            continue
        parent = getattr(node, "parent", None)
        if isinstance(parent, ast.Expr):
            continue  # docstring / prose: passe de prose, pas celle-ci
        if "\n" in val:
            manuels.append({"ligne": node.lineno, "motif": "chaine multi-lignes (commande externe)"})
            continue
        m = _ROOT_RE.match(val)
        niveau = depth
        if not m:
            m = _SUPER_RE.match(val)
            if m and (m.group("tail") or "").lstrip("\\/").split("\\")[0].split("/")[0] == "LaForge":
                m = None  # deja couvert par _ROOT_RE, ne pas doubler
            niveau = depth + 1
        if not m:
            if _MENTION_RE.search(val):
                manuels.append({"ligne": node.lineno, "motif": "chemin non litteral (%VAR%, fragment, commande)"})
            continue
        target: ast.AST = node
        if _is_expanduser_call(parent) and parent.args[0] is node:  # type: ignore[union-attr]
            target = parent
        start = _abs(offs, target.lineno, target.col_offset)
        end = _abs(offs, target.end_lineno or target.lineno, target.end_col_offset or 0)
        edits.append((start, end, _expr(niveau, m.group("tail"))))
        couverts.append((start, end))
        faits.append({"ligne": node.lineno, "avant": val})

    if not edits:
        return None, [], manuels

    out = src
    for start, end, new in sorted(edits, key=lambda e: e[0], reverse=True):
        out = out[:start] + new + out[end:]
    try:
        ast.parse(out)
    except SyntaxError as exc:
        return None, [], manuels + [{"ligne": exc.lineno or 0, "motif": f"REECRITURE REJETEE (ne parse plus): {exc.msg}"}]
    return out, faits, manuels


def run(apply: bool) -> dict:
    rapport: dict = {"convertis": {}, "manuels": {}, "fichiers_vus": 0, "sites_convertis": 0}
    cibles = sorted(set(ROOT.glob("app/**/*.py")) | set(ROOT.glob("tools/**/*.py")))
    for p in cibles:
        if not _in_scope(p):
            continue
        rapport["fichiers_vus"] += 1
        new, faits, manuels = _scan_file(p)
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if manuels:
            rapport["manuels"][rel] = manuels
        if new is None or not faits:
            continue
        rapport["convertis"][rel] = faits
        rapport["sites_convertis"] += len(faits)
        if apply:
            p.write_text(new, encoding="utf-8")
    return rapport


def _main() -> int:
    ap = argparse.ArgumentParser(description="Phase 0 renommage: deriver la racine depuis __file__")
    ap.add_argument("--apply", action="store_true", help="ecrit les fichiers (defaut: dry-run)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = run(a.apply)
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0
    mode = "APPLIQUE" if a.apply else "DRY-RUN"
    print(f"[phase0] {mode} — {r['fichiers_vus']} fichiers en perimetre, "
          f"{r['sites_convertis']} site(s) converti(s) dans {len(r['convertis'])} fichier(s)")
    for rel, faits in sorted(r["convertis"].items()):
        print(f"  + {rel} ({len(faits)})")
    if r["manuels"]:
        print(f"[phase0] {sum(len(v) for v in r['manuels'].values())} site(s) MANUEL(S) "
              f"dans {len(r['manuels'])} fichier(s) — non touches:")
        for rel, ms in sorted(r["manuels"].items()):
            for m in ms:
                print(f"  ! {rel}:{m['ligne']}  {m['motif']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
