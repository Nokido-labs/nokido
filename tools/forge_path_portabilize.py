"""tools/forge_path_portabilize.py — make hardcoded home paths portable.

Replaces literal %USERPROFILE% paths across git-tracked files with portable
equivalents, so the public distribution runs on any machine (and stops leaking
the dev home layout). SAFE by construction:

  .py   : a WHOLE string literal starting with the home path, r"C:\\Users\\<owner>\\X" ->
          __import__("os").path.expanduser(r"~\\X")   (no import dependency).
          Only complete STRING tokens are rewritten (Python tokenizer) : a quoted
          path NESTED in another literal (f-string, regex, command line, docstring)
          is never touched and is listed for manual review (2026-10-09 : the former
          regex wrote the expression AS TEXT inside such literals -- 4 inert icacls
          in forge_sandbox_setup, a dead regex in multi_llm_daemon, and this very
          docstring ; py_compile could not see it, the result still compiles).
          Each modified .py is re-validated with py_compile ; on ANY failure
          the original is restored and the file is reported (never left broken).
  .bat  : -> %USERPROFILE%      .ps1 : -> $env:USERPROFILE
  .sh   : -> $HOME              .md  : -> ~   (doc examples)

DRY-RUN by default (writes nothing, just a report). Pass --apply to write.
Run from the repo root in the OWNER session (needs git + write access).

  LAFORGE_PYTHON tools/forge_path_portabilize.py            # dry-run report
  LAFORGE_PYTHON tools/forge_path_portabilize.py --apply    # write + validate
"""
from __future__ import annotations

__FORGE_COLOR__ = "infra/config : rend portables les chemins home figes dans les fichiers suivis"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import os
import py_compile
import re
import subprocess

HOME_ANY = re.compile(r"C:[\\/]+Users[\\/]+user")
# A python string literal whose body starts with the home path.
PY_LIT = re.compile(
    r"""(?P<pre>[rRbBuUfF]*)(?P<q>['"])(?P<body>C:[\\/]+Users[\\/]+user[^'"]*)(?P=q)"""
)
FSTR = re.compile(r"""[fF][rRbBuU]*['"][^'"]*C:[\\/]+Users[\\/]+user""")


def tracked_files():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    for line in out.stdout.splitlines():
        s = line.strip()
        if s:
            yield s


def py_transform(text):
    """Reecrit seulement les jetons STRING ENTIERS dont le corps commence par le chemin home ; toute autre occurrence
    (sous-chaine entre guillemets d'un autre litteral, f-string, docstring) est laissee intacte et listee."""
    import io
    import tokenize

    try:
        jetons = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        return text, 0, ["tokenize impossible : fichier laisse intact"]
    debuts = [0]
    for ligne in text.splitlines(keepends=True):
        debuts.append(debuts[-1] + len(ligne))
    remplacements, manual = [], []
    for t in jetons:
        if not HOME_ANY.search(t.string):
            continue
        m = PY_LIT.fullmatch(t.string) if t.type == tokenize.STRING else None
        if not m or "f" in m.group("pre").lower():
            manual.append(t.string[:90])
            continue
        rest = HOME_ANY.sub("~", m.group("body"), count=1)
        nouveau = f'__import__("os").path.expanduser({m.group("pre")}{m.group("q")}{rest}{m.group("q")})'
        (l1, c1), (l2, c2) = t.start, t.end
        remplacements.append((debuts[l1 - 1] + c1, debuts[l2 - 1] + c2, nouveau))
    for a, b, r in reversed(remplacements):
        text = text[:a] + r + text[b:]
    return text, len(remplacements), manual


def simple_sub(text, repl):
    return HOME_ANY.sub(repl, text), len(HOME_ANY.findall(text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default="C:/tmp/path_portabilize_report.json")
    args = ap.parse_args()

    rep = {"applied": args.apply, "files": [], "manual_review": [], "compile_fail": [], "illisibles": []}
    for rel in tracked_files():
        if rel.startswith("_attic/") or "/_attic/" in rel:
            continue
        if not os.path.isfile(rel):
            continue
        ext = os.path.splitext(rel)[1].lower()
        try:
            text = open(rel, encoding="utf-8", errors="replace").read()
        except OSError as e:
            # Un fichier non lu n'est pas un fichier sans chemin d'owner : le rapport le DIT (« 0 fichier » mentait
            # sur la couverture quand l'ACL du compte refusait la lecture).
            rep["illisibles"].append({"file": rel, "err": type(e).__name__})
            continue
        if not HOME_ANY.search(text):
            continue

        if ext == ".py":
            new, n, manual = py_transform(text)
            if manual:
                rep["manual_review"].append({"file": rel, "fstrings": manual})
        elif ext == ".bat":
            new, n = simple_sub(text, "%USERPROFILE%")
        elif ext == ".ps1":
            new, n = simple_sub(text, "$env:USERPROFILE")
        elif ext == ".sh":
            new, n = simple_sub(text, "$HOME")
        elif ext in (".md", ".markdown"):
            new, n = simple_sub(text, "~")
        else:
            continue

        if new == text:
            continue
        rep["files"].append({"file": rel, "replaced": n})

        if args.apply:
            with open(rel, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            if ext == ".py":
                try:
                    py_compile.compile(rel, doraise=True)
                except py_compile.PyCompileError as e:
                    with open(rel, "w", encoding="utf-8", newline="") as f:
                        f.write(text)  # rollback
                    rep["files"].pop()
                    rep["compile_fail"].append({"file": rel, "err": str(e)[:200]})

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print("PORTABILIZE " + json.dumps({
        "applied": args.apply, "files": len(rep["files"]),
        "manual": len(rep["manual_review"]), "compile_fail": len(rep["compile_fail"]),
        "illisibles": len(rep["illisibles"]), "out": args.out}))


if __name__ == "__main__":
    raise SystemExit(main())
