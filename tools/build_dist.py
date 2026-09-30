"""tools/build_dist.py — build REPRODUCTIBLE de la distribution propriétaire.

Capture l'invocation pyarmor/nuitka qui produisait `dist_laforge/` à la main
(POC : pyarmor sur llm/rag/cerberus/ssh + nuitka sur forge_retry_strategies).
But : rendre la protection IP du Track B (B2B) rejouable + CI-able, au lieu
d'artefacts orphelins non reproductibles.

ATTENTION : un `.whl` standard = source en clair. La protection vient d'ICI
(pyarmor = bytecode obfusqué, ou nuitka = binaire natif). Choisir UNE stratégie.

Usage :
    LAFORGE_PYTHON tools/build_dist.py --backend pyarmor --mode groups
    LAFORGE_PYTHON tools/build_dist.py --backend pyarmor --mode whole
    LAFORGE_PYTHON tools/build_dist.py --backend nuitka --module app/forge_retry_strategies.py
    LAFORGE_PYTHON tools/build_dist.py --check        # juste vérifier les outils
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist_laforge"

# Groupes module -> globs source (édite ici pour ajuster le périmètre protégé).
GROUPS: dict[str, list[str]] = {
    "core": ["app/forge_context.py", "app/forge_runtime.py", "app/forge_runner.py"],
    "llm": ["app/forge_llm_*.py", "app/forge_handoff.py", "app/forge_ollama.py", "app/forge_llamacpp.py"],
    "rag": ["app/forge_rag_*.py", "app/forge_self_correction.py"],
    "cerberus": ["app/forge_semantic_firewall.py", "app/forge_sovereign_membrane.py", "app/forge_integrity.py"],
    "ssh": ["app/netcfg_*.py"],
}


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None or _module(tool)


def _module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def _run(cmd: list[str]) -> int:
    print("  $", " ".join(cmd))
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def _expand(globs: list[str]) -> list[str]:
    files: list[str] = []
    for g in globs:
        files += [str(p.relative_to(ROOT)) for p in ROOT.glob(g) if p.is_file()]
    return sorted(set(files))


def build_pyarmor(mode: str) -> int:
    py = sys.executable
    base = [py, "-m", "pyarmor.cli", "gen"]
    if not _module("pyarmor"):
        print("ERR: pyarmor non installé —  pip install pyarmor")
        return 2
    if mode == "whole":
        dest = OUT / "app"
        print(f"[pyarmor] whole app/ + tools/ -> {dest}")
        return _run(base + ["--recursive", "--output", str(dest), "app", "tools"])
    rc = 0
    for group, globs in GROUPS.items():
        files = _expand(globs)
        if not files:
            print(f"[pyarmor] groupe {group}: aucun fichier (glob vide) — skip")
            continue
        dest = OUT / "modules" / group
        print(f"[pyarmor] groupe {group}: {len(files)} fichiers -> {dest}")
        rc |= _run(base + ["--output", str(dest), *files])
    return rc


def build_nuitka(module: str) -> int:
    py = sys.executable
    if not _module("nuitka"):
        print("ERR: nuitka non installé —  pip install nuitka")
        return 2
    src = (ROOT / module).resolve()
    if not src.is_file():
        print(f"ERR: module introuvable: {module}")
        return 2
    dest = OUT / "core"
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[nuitka] {module} -> {dest} (module compilé .pyd)")
    return _run([py, "-m", "nuitka", "--module", str(src), f"--output-dir={dest}", "--remove-output"])


def main() -> int:
    ap = argparse.ArgumentParser(prog="build_dist", description="Build distribution propriétaire obfusquée")
    ap.add_argument("--backend", choices=["pyarmor", "nuitka"], default="pyarmor")
    ap.add_argument("--mode", choices=["groups", "whole"], default="groups", help="pyarmor: par groupe ou tout app/")
    ap.add_argument("--module", default="app/forge_retry_strategies.py", help="nuitka: module à compiler")
    ap.add_argument("--check", action="store_true", help="vérifie les outils dispo et sort")
    a = ap.parse_args()

    print("pyarmor:", "OK" if _module("pyarmor") else "ABSENT", " | nuitka:", "OK" if _module("nuitka") else "ABSENT")
    if a.check:
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    rc = build_nuitka(a.module) if a.backend == "nuitka" else build_pyarmor(a.mode)
    if rc == 0:
        print(f"\n✅ build OK -> {OUT}  (gitignoré ; pousser sur index privé / livrer à part)")
    else:
        print(f"\n❌ build échec (rc={rc})")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
