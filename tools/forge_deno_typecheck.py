"""forge_deno_typecheck.py — Typecheck des sources Deno AVANT restart du superviseur.

Pourquoi cet outil existe : le superviseur est le seul organe qui relance les autres.
Une erreur TypeScript ne se voit qu'au demarrage — et un superviseur qui ne demarre
pas emporte la stack avec lui. Le valider AVANT le restart transforme une panne
generale en refus local.

Pourquoi il est LANCE EN PRIVILEGIE : le binaire Deno vit dans le profil de l'owner
(`C:/Users/<owner>/.deno/bin/deno.exe`, cf. services.toml). Les comptes bac a sable ne
voient pas ce profil : ils repondent « absent » la ou le fichier existe. « Je ne peux
pas voir » n'est PAS « rien trouve » — d'ou le diagnostic imprime en cas d'echec,
plutot qu'un vert trompeur.

Usage :  LAFORGE_PYTHON tools/forge_deno_typecheck.py [fichier.ts ...]
Sans argument : les sources TypeScript de proxy_deno/core.
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/quality : typecheck des sources Deno avant restart du superviseur"  # organe declare le 2026-09-06 (audit de raccordement)

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "proxy_deno" / "core"
DEFAULT_TARGETS = ("supervisor.ts",)


def deno_path() -> Path | None:
    """Chemin du binaire Deno, lu dans services.toml — jamais devine."""
    toml = CORE / "services.toml"
    try:
        data = tomllib.loads(toml.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"[deno] services.toml illisible ({e}) — repli sur le PATH", flush=True)
        return None
    # Les chemins de binaires vivent dans la table [vars] (verifie, pas suppose) ;
    # les autres emplacements ne sont que des replis.
    for scope in (data.get("vars") or {}, data.get("env") or {}, data):
        for key in ("DENO", "deno"):
            val = scope.get(key) if isinstance(scope, dict) else None
            if isinstance(val, str) and val:
                return Path(val)
    return None


def check(targets: list[str]) -> int:
    exe = deno_path()
    if exe and not exe.exists():
        print(f"[deno] INTROUVABLE : {exe}", flush=True)
        print("       Si ce script tourne sous un compte de service, c'est probablement"
              " un defaut de VISIBILITE du profil owner, pas une absence.", flush=True)
        print("       -> relancer via run action=trusted_script.", flush=True)
        return 2
    cmd_base = [str(exe)] if exe else ["deno"]

    rc_total = 0
    for t in targets:
        p = (CORE / t) if not Path(t).is_absolute() else Path(t)
        if not p.exists():
            print(f"[deno] SKIP {t} : fichier absent", flush=True)
            rc_total = max(rc_total, 2)
            continue
        try:
            r = subprocess.run(
                cmd_base + ["check", "--no-lock", p.name],
                cwd=str(p.parent), capture_output=True, text=True,
                errors="replace", timeout=300,
            )
        except FileNotFoundError:
            print(f"[deno] binaire injoignable ({cmd_base[0]})", flush=True)
            return 2
        except subprocess.TimeoutExpired:
            print(f"[deno] TIMEOUT sur {t} (>300s)", flush=True)
            return 2
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode == 0:
            print(f"[deno] OK   {t}", flush=True)
        else:
            print(f"[deno] FAIL {t} (rc={r.returncode})", flush=True)
            for line in out.splitlines()[:25]:
                print("       " + line[:180], flush=True)
            rc_total = 1
    return rc_total


def main() -> int:
    targets = sys.argv[1:] or list(DEFAULT_TARGETS)
    rc = check(targets)
    print("VERDICT :", {0: "compile", 1: "ERREURS DE TYPE", 2: "NON VERIFIE"}[rc], flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
