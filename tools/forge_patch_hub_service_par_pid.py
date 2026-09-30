"""Jointure PID -> NOM DE SERVICE : que le journal nomme, au lieu de numeroter.

Un PID n'est pas une identite. Mesure 2026-08-04 : le meme service est passe de
18372 a 18688 en un redemarrage, et une attribution artisanale port->PID a produit
successivement une accusation fausse puis une retractation fausse — les ports comme
les PID sont recycles, et croiser deux fenetres temporelles fabrique des coupables.

Nokido possede DEJA l'abstraction qui regle ca : le superviseur Deno tient 54
services a noms stables et expose leur PID courant sur `:8765/supervisor/status`.
Ajouter un PM2 ou un Supervisor par-dessus donnerait deux gestionnaires sur les
memes processus — ils se disputeraient les relances. Ce patch ne fait donc que
CABLER ce qui existe : apres avoir resolu un PID, demander son nom a l'organe qui
l'a lance, au lieu de le deduire.

Ce que ca change en pratique : `network_log` porte `"service": "NokidoTraceSidecar"`
et plus seulement `"pid": 18688`. Un nom survit au redemarrage ; un PID non.

Cout borne : le registre est mis en cache 120 s, et la resolution PID elle-meme
n'a lieu qu'une fois par port grace au cache existant. Timeout court (1,5 s) car
l'appel se fait sur le chemin synchrone du log — le superviseur absent ne doit pas
retarder une reponse HTTP. Trois etats rendus, jamais deux : le nom, `inconnu`
(le PID n'est pas un service declare) ou `illisible` (+ raison).

Usage :
    run action=trusted_script path=tools/forge_patch_hub_service_par_pid.py
    run action=trusted_script path=tools/forge_patch_hub_service_par_pid.py \
        script_args="--apply"
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/observabilite"

import argparse
import json
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIBLE = ROOT / "tools" / "nokido_hub.py"
SENTINELLE = "_service_du_pid"

HELPER = '''# Registre du superviseur : nom de service <- pid. Cache 120 s, l'appel se faisant
# sur le chemin SYNCHRONE du log (un superviseur lent ne doit pas retarder une
# reponse HTTP). Cf. tools/forge_patch_hub_service_par_pid.py.
_SERVICES_CACHE: dict = {"ts": 0.0, "par_pid": {}, "erreur": None}
_SERVICES_TTL_S = 120.0


def _service_du_pid(pid: int) -> str:
    """Nom du service qui porte ce PID, demande a l'organe qui l'a lance.

    Un PID n'est pas une identite : il est reattribue a chaque redemarrage (mesure
    2026-08-04, 18372 -> 18688 pour le meme service). Le superviseur, lui, tient
    des noms stables. On les lui DEMANDE plutot que de les deduire.

    Rend le nom, "inconnu" (PID vivant mais pas un service declare) ou
    "illisible:<motif>" — ne jamais confondre les trois.
    """
    import time as _t
    import urllib.request as _u

    cache = _SERVICES_CACHE
    if _t.time() - cache["ts"] > _SERVICES_TTL_S:
        cache["ts"] = _t.time()
        try:
            with _u.urlopen("http://127.0.0.1:8765/supervisor/status", timeout=1.5) as _r:
                _d = _json.loads(_r.read())
            cache["par_pid"] = {
                s.get("pid"): nom
                for nom, s in (_d.get("services") or {}).items()
                if s.get("pid")
            }
            cache["erreur"] = None
        except Exception as _e:  # noqa: BLE001
            cache["erreur"] = type(_e).__name__
    if cache["erreur"] and not cache["par_pid"]:
        return "illisible:" + cache["erreur"]
    return cache["par_pid"].get(pid, "inconnu")


'''

AVANT_HELPER = "def _origine_appelant(port: int) -> dict:"
AVANT_JOINTURE = '''        cache["par_port"][port] = info
        cache["ts"] = maintenant'''
APRES_JOINTURE = '''        # Le nom SURVIT au redemarrage, le PID non : c'est lui qu'on veut voir
        # dans le journal, et lui que le raisonnement doit manipuler.
        try:
            info["service"] = _service_du_pid(trouve)
        except Exception as _e:  # noqa: BLE001
            info["service"] = "illisible:" + type(_e).__name__
        cache["par_port"][port] = info
        cache["ts"] = maintenant'''


def main() -> int:
    ap = argparse.ArgumentParser(description="Jointure PID -> nom de service")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rapport: dict = {"cible": str(CIBLE), "mode": "apply" if args.apply else "dry-run"}
    if not CIBLE.exists():
        rapport["verdict"] = "CIBLE INTROUVABLE"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 1
    src = CIBLE.read_text(encoding="utf-8")
    if SENTINELLE in src:
        rapport["verdict"] = "DEJA PATCHE — rien a faire (idempotent)"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0
    if "_origine_appelant" not in src:
        rapport["verdict"] = "ABANDON : patch d'origine absent, l'appliquer d'abord"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 2

    out = src
    detail = []
    for i, (a, b) in enumerate(((AVANT_HELPER, HELPER + AVANT_HELPER),
                                (AVANT_JOINTURE, APRES_JOINTURE)), 1):
        n = out.count(a)
        detail.append({"bloc": i, "occurrences": n})
        if n != 1:
            rapport["blocs"] = detail
            rapport["verdict"] = f"ABANDON : bloc {i} vu {n} fois (1 attendue), ne pas forcer"
            print(json.dumps(rapport, ensure_ascii=False, indent=2))
            return 3
        out = out.replace(a, b, 1)
    rapport["blocs"] = detail

    # `json` doit etre joignable sous l'alias utilise par le helper.
    if "import json as _json" not in out:
        out = out.replace("_SERVICES_CACHE: dict", "import json as _json\n\n_SERVICES_CACHE: dict", 1)

    try:
        compile(out, str(CIBLE), "exec")
        rapport["ast"] = "OK"
    except SyntaxError as e:
        rapport["ast"] = f"ECHEC ligne {e.lineno}: {e.msg}"
        rapport["verdict"] = "ABANDON : ne compile pas, rien ecrit"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 4

    if not args.apply:
        rapport["verdict"] = "DRY-RUN OK — relancer avec --apply"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    horo = time.strftime("%Y%m%d-%H%M%S")
    sauvegarde = CIBLE.with_suffix(f".py.avant-servicepid-{horo}.bak")
    shutil.copy2(CIBLE, sauvegarde)
    CIBLE.write_text(out, encoding="utf-8")
    rapport["sauvegarde"] = str(sauvegarde)
    rapport["relecture_identique"] = (CIBLE.read_text(encoding="utf-8") == out)
    rapport["verdict"] = ("APPLIQUE. Effet au prochain rechargement du hub. "
                          "Retour arriere : git checkout -- tools/nokido_hub.py")
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
