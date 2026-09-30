"""nokido_nssm_path_audit.py — quels services nomment le dossier du depot.

POURQUOI. Le renommage du dossier casse tout service dont NSSM garde le chemin: le
superviseur redemarre alors sur un chemin qui n'existe plus. Cet inventaire etait
declare ANGLE MORT parce que `nssm dump` ne rend rien depuis les comptes de service.
Mesure du 2026-08-11: ce n'est pas l'information qui manque, c'est l'outil — les
parametres NSSM vivent dans le registre, et HKLM\\SYSTEM\\CurrentControlSet\\Services
est LISIBLE sans elevation. "Illisible" designait la commande, pas la donnee.

TROIS ETATS, JAMAIS DEUX. Le rapport imprime son denominateur: services enumeres,
services sans clef Parameters (ceux qui ne sont pas des services NSSM), et services
dont les parametres sont ILLISIBLES depuis ce compte. Sans ces nombres, "33 concernes"
ne se distingue pas de "je n'ai pas pu regarder".

SECRETS. `AppEnvironmentExtra` porte des jetons en clair (mesure du jour: quatre
services au moins). Cet outil n'imprime donc JAMAIS la valeur d'une variable
d'environnement — seulement son NOM, et un marqueur quand la valeur nomme le depot.

LECTURE SEULE. Ne modifie aucun service.

CLI :
    LAFORGE_PYTHON tools/nokido_nssm_path_audit.py
    LAFORGE_PYTHON tools/nokido_nssm_path_audit.py --json
"""
from __future__ import annotations

__FORGE_COLOR__ = "outillage/renommage"

import argparse
import json
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # pas Windows: l'outil n'a pas d'objet
    winreg = None  # type: ignore[assignment]

BASE = r"SYSTEM\CurrentControlSet\Services"
ROOT = Path(__file__).resolve().parent.parent
# Le nom du dossier tel qu'il apparait dans les chemins des services.
NEEDLE = ROOT.name
PARENT_NEEDLE = ROOT.parent.name
# Valeurs NSSM qui portent un chemin. AppEnvironmentExtra est traite a part: il porte
# des SECRETS, on n'en rend que les noms de variables.
PATH_VALUES = ("Application", "AppDirectory", "AppParameters", "AppStdout", "AppStderr")


def _env_names(raw) -> list[str]:
    """Noms des variables d'environnement, sans AUCUNE valeur."""
    items = raw if isinstance(raw, (list, tuple)) else [raw]
    out = []
    for it in items:
        s = str(it)
        out.append(s.split("=", 1)[0] if "=" in s else s)
    return out


def scan() -> dict:
    if winreg is None:
        return {"erreur": "registre Windows indisponible sur cette plateforme"}
    services: list[str] = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, BASE) as k:
        i = 0
        while True:
            try:
                services.append(winreg.EnumKey(k, i))
                i += 1
            except OSError:
                break

    concernes: list[dict] = []
    sans_parametres = illisibles = 0
    for s in services:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{BASE}\\{s}\\Parameters") as pk:
                vals = {}
                j = 0
                while True:
                    try:
                        n, v, _ = winreg.EnumValue(pk, j)
                        vals[n] = v
                        j += 1
                    except OSError:
                        break
        except FileNotFoundError:
            sans_parametres += 1
            continue
        except (PermissionError, OSError):
            illisibles += 1
            continue

        touche: dict[str, str] = {}
        for n in PATH_VALUES:
            v = str(vals.get(n, ""))
            if NEEDLE in v or PARENT_NEEDLE in v:
                touche[n] = v
        env_noms = _env_names(vals.get("AppEnvironmentExtra", []))
        env_touche = [
            nom for nom, brut in zip(env_noms, (vals.get("AppEnvironmentExtra") or []))
            if NEEDLE in str(brut) or PARENT_NEEDLE in str(brut)
        ]
        if touche or env_touche:
            concernes.append({
                "service": s,
                "valeurs": touche,
                "env_qui_nomment_le_depot": env_touche,   # NOMS seulement, jamais les valeurs
                "env_total": len(env_noms),
            })

    return {
        "dossier_cherche": NEEDLE,
        "services_enumeres": len(services),
        "sans_clef_parameters": sans_parametres,
        "illisibles_depuis_ce_compte": illisibles,
        "concernes": concernes,
    }


def _main() -> int:
    ap = argparse.ArgumentParser(description="Services NSSM qui nomment le dossier du depot")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = scan()
    if "erreur" in r:
        print("[nssm-audit]", r["erreur"])
        return 2
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0
    print(f"[nssm-audit] dossier « {r['dossier_cherche']} » — {len(r['concernes'])} service(s) a "
          f"reecrire au cutover")
    print(f"[nssm-audit] denominateur : {r['services_enumeres']} services enumeres, "
          f"{r['sans_clef_parameters']} sans clef Parameters (non NSSM), "
          f"{r['illisibles_depuis_ce_compte']} ILLISIBLE(S) depuis ce compte")
    for c in r["concernes"]:
        champs = ", ".join(sorted(c["valeurs"]))
        suffixe = ""
        if c["env_qui_nomment_le_depot"]:
            suffixe = f" | env: {', '.join(c['env_qui_nomment_le_depot'])} (noms seuls)"
        print(f"  - {c['service']}: {champs}{suffixe}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
