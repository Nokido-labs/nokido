#!/usr/bin/env python3
"""forge_firehose_guard.py — garde anti-régression "firehose / fuite" pour le gate git.

Né de l'incident 47GB/OOM (2026-06-11) : un hub qui logge PAR REQUÊTE + un superviseur
qui lit le firehose + une table SQLite sans purge. On câble la LEÇON en garde-fou
permanent : scanne les fichiers STAGED pour les 3 patterns statiquement détectables et
WARN (jamais bloquant — philosophie du gate : block=secrets only).

Patterns détectés :
  1. subprocess Popen/run en mode texte SANS `errors=` -> _readerthread UnicodeDecodeError
     en boucle (un enfant qui sort du binaire crashe + spamme + accumule en RAM).
  2. .ts : Deno.readTextFile / readAll / readAllSync = lecture de fichier ENTIER en RAM
     -> OOM si le fichier a firehosé (cf openLog 47GB).
  3. CREATE TABLE <x> sans que <x> soit référencé dans forge_log_retention.py -> table
     INSERT-only sans purge = croissance illimitée (cf network_log 307k rows).

Usage (appelé par forge_git_gate precommit) :
  LAFORGE_PYTHON tools/forge_firehose_guard.py            # scanne le staged
  LAFORGE_PYTHON tools/forge_firehose_guard.py f1.py f2.ts  # scanne des fichiers donnés
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RETENTION = ROOT / "tools" / "forge_log_retention.py"

_RE_SUBPROCESS = re.compile(r"subprocess\.(Popen|run|check_output|call)\s*\(")
_RE_TEXT_MODE = re.compile(r"\b(text\s*=\s*True|universal_newlines\s*=\s*True|encoding\s*=)")
_RE_ERRORS = re.compile(r"\berrors\s*=")
_RE_DENO_WHOLE = re.compile(r"Deno\.(readTextFile|readAll|readTextFileSync|readAllSync)\s*\(")
_RE_CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?([A-Za-z_][A-Za-z0-9_]*)", re.I)

# Ces fichiers CONTIENNENT les patterns comme LOGIQUE de détection -> ne pas s'auto-flaguer.
_SKIP = {"forge_firehose_guard.py", "forge_git_gate.py"}


def _staged_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, errors="replace", timeout=15,
        ).stdout
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def _retention_text() -> str:
    try:
        return RETENTION.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _subprocess_sans_errors(rel: str, src: str) -> list[str]:
    """Appels subprocess en mode texte sans `errors=`, detectes par l'AST.

    L'ancienne version cherchait `errors=` dans une FENETRE DE 3 LIGNES autour de
    l'appel. Tout appel plus long — la forme la plus courante des qu'il y a une liste
    d'arguments — mettait son `errors=` hors de la fenetre et declenchait un FAUX
    POSITIF. Mesure du 2026-08-05 : apres avoir corrige 215 sites, le gate en
    signalait encore une dizaine qui portaient POURTANT le correctif deux lignes plus
    bas.

    Un garde qui crie a faux se fait desarmer : c'est la raison de ce changement,
    autant que l'exactitude. L'AST ignore la mise en forme, donc le verdict ne depend
    plus de la longueur de l'appel.
    """
    import ast

    appels = {"run", "Popen", "check_output", "call", "check_call"}
    try:
        arbre = ast.parse(src)
    except SyntaxError:
        # Un fichier non parsable n'est PAS un fichier sain : on le DIT, plutot que
        # de rendre une liste vide qui se lirait « aucun probleme ».
        return ["%s: non parsable — controle subprocess NON effectue sur ce fichier" % rel]
    out = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Call):
            continue
        nom = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        if nom not in appels:
            continue
        kw = {k.arg for k in n.keywords if k.arg}
        if any(k in kw for k in ("text", "universal_newlines", "encoding")) and "errors" not in kw:
            out.append("%s:%d subprocess mode-texte SANS errors= -> crash "
                       "_readerthread sur binaire (errors='replace')" % (rel, n.lineno))
    return out


def scan(files: list[str]) -> list[str]:
    warns: list[str] = []
    retention = _retention_text()
    for rel in files:
        p = (ROOT / rel) if not Path(rel).is_absolute() else Path(rel)
        if not p.exists() or p.name in _SKIP:
            continue
        ext = p.suffix.lower()
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        if ext == ".py":
            warns.extend(_subprocess_sans_errors(rel, "\n".join(lines)))
        for i, ln in enumerate(lines, 1):
            if ext in (".ts", ".js") and _RE_DENO_WHOLE.search(ln):
                warns.append(f"{rel}:{i} {_RE_DENO_WHOLE.search(ln).group(1)} = lecture fichier ENTIER en RAM -> OOM si firehosé (seek/stream)")
            m = _RE_CREATE_TABLE.search(ln)
            if m:
                tbl = m.group(1)
                if tbl.lower() not in ("if",) and tbl not in retention:
                    warns.append(f"{rel}:{i} CREATE TABLE {tbl} non référencée dans forge_log_retention.py -> croissance illimitée (câbler une purge)")
    return warns


def main(argv: list[str]) -> int:
    files = argv[1:] if len(argv) > 1 else _staged_files()
    if not files:
        return 0
    warns = scan(files)
    if warns:
        print("[firehose-guard] WARN (anti-régression incident 47GB) :")
        for w in warns:
            print(f"  ! {w}")
        print("  -> throttle le log / errors='replace' / seek au lieu de read-whole / câble une purge. (warn, non bloquant)")
    return 0  # JAMAIS bloquant


if __name__ == "__main__":
    sys.exit(main(sys.argv))
