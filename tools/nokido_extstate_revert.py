"""nokido_extstate_revert.py — revert rename KEEP-miss sur l'ETAT EXTERNE.

Le cutover laforge->nokido a renomme a tort des identifiants couples a de l'etat
OS NON renomme : noms d'env conda + noms de comptes/groupes Windows sandbox. Le
vrai env/compte reste 'laforge_*'/'LaForge*'. On reverte CES tokens precis pour que
le code corresponde a la realite. Phase +N renommera les comptes/env OS + flippera
ces refs ensemble (cf memory nokido_rename_project).

Tokens (substring, casse exacte) choisis pour qu'AUCUN identifiant interne nokido
legitime ne matche (NokidoOllama etc. intacts) :
  nokido_py314   -> laforge_py314   (env conda ; couvre py314 + py314t)
  NokidoSbx      -> LaForgeSbx      (comptes sandbox SbxOffline/SbxOnline)
  NokidoTrusted  -> LaForgeTrusted  (compte Trusted + groupe TrustedRunners)
  NokidoSandbox  -> LaForgeSandbox  (groupes SandboxUsers/Online/Offline)

Fichiers TRACKES seulement (git ls-files ; fallback os.walk code-dirs). Preserve
les fins de ligne (newline=''). Dry par defaut ; --apply ecrit.
"""

__FORGE_COLOR__ = "infra/rename : revert des KEEP-miss sur l'etat externe"  # organe declare le 2026-09-06 (audit de raccordement)
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBS = [
    ("nokido_py314", "laforge_py314"),
    ("NokidoSbx", "LaForgeSbx"),
    ("NokidoTrusted", "LaForgeTrusted"),
    ("NokidoSandbox", "LaForgeSandbox"),
]
CODE_DIRS = ("app", "tools", "proxy_deno", "config", "docs", "tests", "scripts", "benchmarks", "deploy")
SKIP = {".git", "__pycache__", "node_modules", ".venv", "sandbox", "RAG", "logs"}


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8", timeout=30, errors="replace").stdout.splitlines()
        if out:
            return [p.replace("/", os.sep) for p in out if p.strip()]
    except Exception:
        pass
    files = []
    for d in CODE_DIRS:
        for dp, dn, fn in os.walk(os.path.join(ROOT, d)):
            dn[:] = [x for x in dn if x not in SKIP]
            files.extend(os.path.relpath(os.path.join(dp, f), ROOT) for f in fn)
    return files


def main():
    apply = "--apply" in sys.argv
    changed = 0
    for rel in _tracked():
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            continue
        if os.path.basename(rel) == "nokido_extstate_revert.py":
            continue  # ne PAS s'auto-modifier (corromprait SUBS = no-op mappings)
        try:
            with open(p, "r", encoding="utf-8", errors="surrogateescape", newline="") as f:
                txt = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        new = txt
        for a, b in SUBS:
            new = new.replace(a, b)
        if new != txt:
            changed += 1
            n = sum(1 for o, m in zip(txt.split("\n"), new.split("\n")) if o != m)
            print(f"  {rel}  ({n} lignes)")
            if apply:
                with open(p, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
                    f.write(new)
    print(f"{'APPLIED' if apply else 'DRY'}: {changed} fichiers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
