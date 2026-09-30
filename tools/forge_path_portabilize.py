"""tools/forge_path_portabilize.py — make hardcoded home paths portable.

Replaces literal %USERPROFILE% paths across git-tracked files with portable
equivalents, so the public distribution runs on any machine (and stops leaking
the dev home layout). SAFE by construction:

  .py   : path string-literals  __import__("os").path.expanduser("~\\X") ->
          __import__("os").path.expanduser("~\\X")   (no import dependency).
          f-strings are SKIPPED (can't wrap) and listed for manual review.
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
    def repl(m):
        if "f" in m.group("pre").lower():
            return m.group(0)  # f-string -> leave (reported separately)
        rest = HOME_ANY.sub("~", m.group("body"), count=1)
        return (f'__import__("os").path.expanduser('
                f'{m.group("pre")}{m.group("q")}{rest}{m.group("q")})')
    new = PY_LIT.sub(repl, text)
    n = len(PY_LIT.findall(text))
    manual = [x[:90] for x in FSTR.findall(text)] if FSTR.search(text) else []
    return new, n, manual


def simple_sub(text, repl):
    return HOME_ANY.sub(repl, text), len(HOME_ANY.findall(text))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default="C:/tmp/path_portabilize_report.json")
    args = ap.parse_args()

    rep = {"applied": args.apply, "files": [], "manual_review": [], "compile_fail": []}
    for rel in tracked_files():
        if rel.startswith("_attic/") or "/_attic/" in rel:
            continue
        if not os.path.isfile(rel):
            continue
        ext = os.path.splitext(rel)[1].lower()
        try:
            text = open(rel, encoding="utf-8", errors="replace").read()
        except Exception:
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
        "out": args.out}))


if __name__ == "__main__":
    raise SystemExit(main())
