# -*- coding: utf-8 -*-
"""Bootstrap Modal : .env -> coffre DPAPI -> CLI authentifie.

Les identifiants Modal vivent ligne ~361 de `Nokido.env`, colles sous forme de
COMMANDE (`modal token set --token-id ak-... --token-secret as-...`) et non de
variables. Ce script les extrait, les pose au COFFRE (regle owner : « TOUS les
clients passent par le vault ») puis authentifie le CLI.

⚠️ Les secrets ne transitent JAMAIS par les arguments : le hub journalise les
args de `run`. Le script lit le `.env` lui-meme et n'imprime que longueur +
prefixe de 3 caracteres.

⚠️ `vault_set` ECRASE en silence (incident 2026-08-18 : un PAT perdu parce que
migre sous un nom deja pris). On REFUSE donc d'ecrire sur un nom deja occupe par
une valeur differente, sauf --forcer.

    run action=trusted_script path=tools/forge_modal_auth_bootstrap.py
    run action=trusted_script path=tools/forge_modal_auth_bootstrap.py --script_args="--auth"
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

ENV = _ROOT / "Nokido.env"
RE_ID = re.compile(r"--token-id\s+(ak-[A-Za-z0-9_\-]+)")
RE_SECRET = re.compile(r"--token-secret\s+(as-[A-Za-z0-9_\-]+)")


def _masque(v: str) -> str:
    return "%s… (len=%d)" % (v[:3], len(v)) if v else "(vide)"


def _extraire() -> tuple[str, str]:
    if not ENV.is_file():
        raise SystemExit("Nokido.env introuvable : %s" % ENV)
    txt = ENV.read_text(encoding="utf-8", errors="replace")
    mi, ms = RE_ID.search(txt), RE_SECRET.search(txt)
    return (mi.group(1) if mi else ""), (ms.group(1) if ms else "")


def main() -> int:
    ap = argparse.ArgumentParser(description="Bootstrap auth Modal")
    ap.add_argument("--auth", action="store_true",
                    help="authentifie aussi le CLI (modal token set)")
    ap.add_argument("--forcer", action="store_true",
                    help="autorise l'ecrasement d'un nom deja pose au coffre")
    args = ap.parse_args()

    tid, tsec = _extraire()
    print("=== EXTRACTION DU .env (masque) ===")
    print("  token-id     :", _masque(tid))
    print("  token-secret :", _masque(tsec))
    if not (tid and tsec):
        print("  -> il manque une moitie du couple : Modal exige les DEUX")
        return 2

    print("\n=== MIGRATION AU COFFRE DPAPI ===")
    try:
        from nokido_agent.app.forge_secrets import get_secret, set_secret
    except Exception as e:  # noqa: BLE001
        print("  coffre indisponible (%s) -- migration impossible" % type(e).__name__)
        return 3

    for nom, val in (("MODAL_TOKEN_ID", tid), ("MODAL_TOKEN_SECRET", tsec)):
        try:
            deja = get_secret(nom) or ""
        except Exception:  # noqa: BLE001 - nom absent du coffre
            deja = ""
        if deja and deja != val and not args.forcer:
            print("  %-20s DEJA POSE avec une valeur DIFFERENTE -> refus "
                  "(--forcer pour ecraser)" % nom)
            continue
        if deja == val:
            print("  %-20s deja identique, rien a faire" % nom)
            continue
        try:
            set_secret(nom, val)
            relu = get_secret(nom) or ""
            print("  %-20s POSE, relecture %s" % (
                nom, "CONFORME" if relu == val else "DIVERGENTE (!)"))
        except Exception as e:  # noqa: BLE001
            print("  %-20s ECHEC ecriture : %s" % (nom, type(e).__name__))

    if not args.auth:
        print("\n[sans --auth] CLI non touche. Relancer avec --auth pour "
              "`modal token set`.")
        return 0

    print("\n=== AUTHENTIFICATION DU CLI ===")
    exe = r"%USERPROFILE%\miniforge3\Scripts\modal.exe"
    if not Path(exe).is_file():
        exe = "modal"
    try:
        # Les tokens passent par argv du CLI Modal (pas par les args du hub) :
        # c'est l'interface officielle de l'outil. Sortie filtree quand meme.
        r = subprocess.run([exe, "token", "set", "--token-id", tid,
                            "--token-secret", tsec],
                           capture_output=True, text=True, errors="replace", timeout=90)
        sortie = ((r.stdout or "") + (r.stderr or "")).strip()
        sortie = sortie.replace(tid, "<token-id>").replace(tsec, "<token-secret>")
        print("  rc=%d" % r.returncode)
        for l in sortie.splitlines()[:10]:
            print("    " + l[:150])
    except Exception as e:  # noqa: BLE001
        print("  echec token set :", type(e).__name__, e)
        return 4

    print("\n=== VERIFICATION (modal app list) ===")
    try:
        r = subprocess.run([exe, "app", "list"], capture_output=True, text=True,
                           errors="replace", timeout=90)
        sortie = ((r.stdout or "") + (r.stderr or "")).strip()
        print("  rc=%d" % r.returncode)
        for l in sortie.splitlines()[:15]:
            print("    " + l[:150])
    except Exception as e:  # noqa: BLE001
        print("  echec app list :", type(e).__name__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
