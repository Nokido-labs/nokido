"""forge_repo_lang_stats.py — Octets trackes par langage (ce que voit linguist).

GitHub linguist compte les octets des fichiers TRACKES. Ce script reproduit le
calcul pour savoir ce qui gonfle une langue (ex: 99.8% Python) -> base pour
ecrire les directives `.gitattributes` (linguist-vendored / -generated).

Run : run action=trusted_script path=tools/forge_repo_lang_stats.py
"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, timeout=90
    , errors="replace").stdout
    files = out.splitlines()
    sizes, pydir = {}, {}
    for f in files:
        ext = os.path.splitext(f)[1].lower() or "(none)"
        try:
            sz = os.path.getsize(ROOT / f)
        except OSError:
            continue
        sizes[ext] = sizes.get(ext, 0) + sz
        if ext == ".py":
            top = "/".join(f.split("/")[:2]) if "/" in f else f
            pydir[top] = pydir.get(top, 0) + sz
    tot = sum(sizes.values()) or 1
    print(f"{len(files)} fichiers trackes, {tot / 1e6:.1f} MB")
    print("=== octets par extension ===")
    for ext, sz in sorted(sizes.items(), key=lambda x: -x[1])[:14]:
        print(f"  {ext:<10} {sz / 1024:10.0f} KB  {100 * sz / tot:5.1f}%")
    print("=== .py par sous-dossier (top 14) ===")
    for d, sz in sorted(pydir.items(), key=lambda x: -x[1])[:14]:
        print(f"  {d:<32} {sz / 1024:10.0f} KB")


if __name__ == "__main__":
    main()
