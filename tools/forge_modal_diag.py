# -*- coding: utf-8 -*-
"""Diagnostic Modal : sommes-nous authentifies, et l'endpoint est-il deploye ?

Modal s'authentifie de DEUX facons : un fichier `~/.modal.toml` (ecrit par
`modal token new|set`) ou le couple d'env `MODAL_TOKEN_ID` + `MODAL_TOKEN_SECRET`.
Le `.env` de Nokido ne porte que le token-ID (ligne 361, collee comme une
commande, pas comme une variable) : un ID SEUL ne suffit pas, il manque le
token-secret `as-...`.

⚠️ Distinguer ABSENT de REFUSE : « chemin introuvable » = le fichier n'existe
pas ; « acces refuse » = il EXISTE mais l'ACL le protege (le compte de service
n'est pas l'owner). Confondre les deux fait conclure « jamais configure » sur un
fichier parfaitement present.

N'imprime JAMAIS un secret : presence, longueur et prefixe de 3 caracteres seuls.

    run action=trusted_script path=tools/forge_modal_diag.py
"""
import os
import subprocess
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


def _forme(v: str) -> str:
    if not v:
        return "VIDE"
    if v.startswith("ak-"):
        return "token-ID (ak-)"
    if v.startswith("as-"):
        return "token-SECRET (as-)"
    if v.startswith("http"):
        return "URL"
    return "opaque"


def main() -> int:
    print("=== COMPTE QUI EXECUTE ===")
    print("  user     :", os.environ.get("USERNAME"))
    print("  HOME     :", os.environ.get("USERPROFILE"))

    print("\n=== FICHIER .modal.toml (auth persistee) ===")
    cands = [
        Path(os.environ.get("USERPROFILE", "")) / ".modal.toml",
        Path("%USERPROFILE%/.modal.toml"),
        Path.home() / ".modal.toml",
    ]
    vus = set()
    for c in cands:
        s = str(c)
        if s in vus or not s.strip():
            continue
        vus.add(s)
        try:
            if c.is_file():
                # On lit les NOMS de profils, jamais les valeurs.
                profils = []
                for ligne in c.read_text(encoding="utf-8", errors="replace").splitlines():
                    ligne = ligne.strip()
                    if ligne.startswith("[") and ligne.endswith("]"):
                        profils.append(ligne)
                print("  PRESENT  %s  (%d octets) profils=%s"
                      % (s, c.stat().st_size, profils or "aucun"))
            else:
                print("  ABSENT   %s" % s)
        except PermissionError:
            print("  REFUSE   %s  <- EXISTE mais ACL (pas 'absent')" % s)
        except Exception as e:  # noqa: BLE001
            print("  ERR      %s  %s" % (s, type(e).__name__))

    print("\n=== VARIABLES D'ENV MODAL ===")
    for k in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "LAFORGE_MODAL_EMBED_URL"):
        v = os.environ.get(k) or ""
        print("  %-26s %s  len=%d  %s" % (
            k, "PRESENTE" if v else "absente", len(v), _forme(v) if v else ""))

    print("\n=== COFFRE DPAPI ===")
    try:
        from nokido_agent.app.forge_secrets import get_secret

        for k in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "MODAL", "LAFORGE_MODAL_EMBED_URL"):
            try:
                v = get_secret(k) or ""
            except Exception:  # noqa: BLE001 - nom absent du coffre
                v = ""
            print("  %-26s %s  len=%d  %s" % (
                k, "PRESENTE" if v else "absente", len(v), _forme(v) if v else ""))
    except Exception as e:  # noqa: BLE001
        print("  coffre illisible ici :", type(e).__name__)

    print("\n=== CLI MODAL ===")
    exe = None
    for cand in (r"%USERPROFILE%\miniforge3\Scripts\modal.exe", "modal"):
        if cand == "modal" or Path(cand).is_file():
            exe = cand
            break
    print("  binaire :", exe or "ABSENT")
    if exe:
        for sous in (["profile", "current"], ["app", "list"]):
            try:
                r = subprocess.run([exe] + sous, capture_output=True, text=True,
                                   errors="replace", timeout=45)
                sortie = ((r.stdout or "") + (r.stderr or "")).strip()
                print("  $ modal %s -> rc=%d" % (" ".join(sous), r.returncode))
                for l in sortie.splitlines()[:12]:
                    print("      " + l[:150])
            except subprocess.TimeoutExpired:
                print("  $ modal %s -> TIMEOUT (auth interactive ?)" % " ".join(sous))
            except Exception as e:  # noqa: BLE001
                print("  $ modal %s -> %s" % (" ".join(sous), type(e).__name__))
    return 0


if __name__ == "__main__":
    sys.exit(main())
