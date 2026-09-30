"""forge_config_refs_audit.py — traque les REFERENCES MORTES dans les configs.

POURQUOI CET OUTIL (owner 2026-07-24 : « pourquoi ton audit du nokido.env t'a
echappe ? »). Parce que `forge_organ_smoke_audit` ne lit que du CODE Python :
imports, API, phases du tick. Les fichiers de configuration lui sont invisibles.

Or le meme motif a coute trois pannes le meme jour :

  1. `.github/workflows/ci-selfhosted.yml` -> PYBIN = `envs/laforge_py314/python.exe`,
     environnement conda jamais cree (sequelle de renommage). 2 SEMAINES de CI rouge.
  2. `~/.codex/config.toml` -> `codex-security/0.1.11/mcp/server.mjs`, supprime par
     la mise a jour vers 0.1.12. Le serveur MCP ne demarrait plus.
  3. `nokido.env` -> commande d'install citant `--plugins`, option QUI N'EXISTE PAS
     dans install_v2.sh (seul `--ggmlbn` installe le plugin GGML).

Invariant commun : **une reference VERSIONNEE ou ABSOLUE survit a la mise a jour de
ce qu'elle designe**, et l'erreur qui en resulte parle d'autre chose que du chemin
mort (« handshake failed », « is not recognized », « Illegal option »). Personne ne
regarde le fichier de config, on cherche la panne ailleurs.

Ce scanner ne juge PAS la semantique : il verifie l'EXISTENCE des chemins cites.
C'est deterministe, sans faux positif couteux, et cela aurait attrape 2 des 3 cas.

LECTURE SEULE.

CLI :
    LAFORGE_PYTHON tools/forge_config_refs_audit.py            # rc=1 si reference morte
    LAFORGE_PYTHON tools/forge_config_refs_audit.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Configs du depot + configs clientes hors depot (elles cassent AUSSI le travail).
SCAN_GLOBS = [
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    "proxy_deno/core/*.toml",
    "*.env",
    "config/*.json",
    "config/*.toml",
]
EXTRA_FILES = [
    Path(os.path.expanduser("~")) / ".codex" / "config.toml",
]

# Chemins absolus Windows ou POSIX. DEUX motifs, et c'est essentiel :
# entre quotes, un chemin peut contenir des ESPACES — le depot lui-meme vit dans
# `%NOKIDO_WORKSPACE%`. Un motif unique s'arretant au premier blanc
# tronquait donc TOUS les chemins du projet a « %USERPROFILE%/Script » et les
# ecartait faute d'extension : le scanner etait aveugle la ou il sert le plus.
_PATH_QUOTED = re.compile(r"""['"]((?:[A-Za-z]:[\\/]|/(?:usr|opt|home|etc)/)[^'"]+)['"]""")
_PATH_BARE = re.compile(r"""(?:^|[=\s])((?:[A-Za-z]:[\\/]|/(?:usr|opt|home|etc)/)[^'"\s,\]\}]+)""")

# Extensions qui designent un fichier EXECUTABLE ou charge : une reference morte y
# est fatale. On ignore les repertoires de donnees, souvent crees a la volee.
_MEANINGFUL = (".exe", ".py", ".mjs", ".js", ".ps1", ".sh", ".bat", ".cmd", ".dll", ".json", ".toml", ".yml")


def _exists(p: Path) -> bool | None:
    """True/False, ou None si l'existence est INDECIDABLE.

    `Path.exists()` ne se contente pas de rendre False sous Windows : il LEVE
    PermissionError quand le compte n'a pas le droit de statuer (mesure 24-07 :
    WinError 5 sur `%USERPROFILE%\\.deno\\bin\\deno.exe` depuis le compte du
    hub). Sans ce garde, le scanner ne rendait pas un faux positif — il CRASHAIT.
    """
    try:
        return p.exists()
    except (PermissionError, OSError):
        return None


def _is_observable(p: Path) -> bool:
    """Peut-on CONCLURE a l'absence de `p` ? Faux si aucun ancetre n'est lisible.

    Sans ce garde, un chemin situe hors du perimetre du compte courant se lit
    « inexistant » alors qu'il est seulement invisible.
    """
    for parent in p.parents:
        try:
            if parent.exists():
                os.listdir(parent)   # leve PermissionError si hors perimetre
                return True
        except PermissionError:
            return False
        except OSError:
            continue
    return False


def _iter_files():
    seen = set()
    for g in SCAN_GLOBS:
        for p in ROOT.glob(g):
            if p.is_file() and p not in seen:
                seen.add(p)
                yield p
    for p in EXTRA_FILES:
        if p.is_file() and p not in seen:
            seen.add(p)
            yield p


# Rempli par scan() : nombre de references qu'on n'a PAS pu verifier.
LAST_UNOBSERVABLE = 0


def scan() -> list[dict]:
    global LAST_UNOBSERVABLE
    LAST_UNOBSERVABLE = 0
    out: list[dict] = []
    for f in _iter_files():
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith("#") or s.startswith("//") or s.startswith(";"):
                # TOUT commentaire est ignore, y compris une affectation desactivee :
                # neutraliser une reference morte en la commentant est precisement le
                # remede, la re-signaler ensuite ferait du bruit sur un probleme resolu
                # (mesure : ma propre correction de NETCFG_EXE se re-signalait).
                continue
            cands = [m.group(1) for m in _PATH_QUOTED.finditer(line)]
            if not cands:
                cands = [m.group(1) for m in _PATH_BARE.finditer(line)]
            for cand in cands:
                raw = cand.rstrip("\\/,; ")
                if not raw.lower().endswith(_MEANINGFUL):
                    continue
                if "${" in raw or "%" in raw or "{{" in raw:
                    continue  # chemin templatise : non resoluble ici
                p = Path(raw)
                if _exists(p):
                    continue
                if _exists(p) is None or not _is_observable(p):
                    LAST_UNOBSERVABLE += 1
                    # « absent » et « je ne peux pas voir » ne sont PAS la meme chose.
                    # Mesure du 24-07 : lance depuis le hub, ce scanner a declare
                    # MORTS quatre binaires bien presents (deno, llama-server, ollama,
                    # lms) — le compte de service ne voit pas C:\Users\<owner>\...
                    # Un scanner qui crie au loup quatre fois se fait ignorer la
                    # cinquieme, quand il a raison.
                    continue
                out.append({
                    "fichier": str(f).replace(str(ROOT) + os.sep, ""),
                    "ligne": i,
                    "reference": raw,
                    "detail": ("reference INEXISTANTE — l'erreur qui en resultera "
                               "parlera d'autre chose que de ce chemin"),
                })
    return out


def _main() -> int:
    ap = argparse.ArgumentParser(description="References mortes dans les configs")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = scan()
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        if not res:
            if LAST_UNOBSERVABLE:
                # « rien trouve » et « rien pu regarder » ne doivent pas se lire pareil.
                print(f"[config-refs] aucune reference morte MAIS {LAST_UNOBSERVABLE} "
                      f"reference(s) NON VERIFIABLE(S) depuis ce compte "
                      f"(profil owner invisible) — relancer cote CLIENT pour conclure")
            else:
                print("[config-refs] aucune reference morte")
        else:
            print(f"[config-refs] {len(res)} reference(s) MORTE(S) :")
            for r in res:
                print(f"  ! {r['fichier']}:{r['ligne']}  ->  {r['reference']}")
    return 1 if res else 0


if __name__ == "__main__":
    sys.exit(_main())
