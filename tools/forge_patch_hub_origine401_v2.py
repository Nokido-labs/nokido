"""Correctif : le cache de resolution bloquait l'identification qu'il devait servir.

Defaut mesure le 2026-08-04, une heure apres l'application du patch v1 : les rejets
`ERR:401` portaient bien `port_source`, mais TOUS rendaient
`{"origine": "non_resolue", "raison": "cache_refroidissement"}`. Cause : le helper
posait `cache["ts"] = maintenant` AVANT de tenter la resolution. Un seul echec
(connexion deja fermee, port recycle) armait donc un refroidissement de 60 s
pendant lequel plus aucune tentative n'avait lieu — et comme les rejets arrivent
groupes 5 par minute, l'identification n'aboutissait jamais.

Le garde de cout etait juste dans son intention (ne pas appeler
`psutil.net_connections()` a chaque requete) mais faux dans sa mecanique : il
refroidissait sur l'ECHEC, c'est-a-dire exactement quand il fallait reessayer.

Correctif : le refroidissement n'est arme QUE sur une resolution reussie. Tant
qu'on n'a identifie personne, chaque rejet redonne une chance — 5 tentatives par
minute a ~100 ms, soit moins de 1 % d'un coeur, sur un chemin qui ne voit que ces
5 requetes. Une fois l'appelant connu, le cache par port reprend son role et le
cout retombe a zero.

Lecon a garder : un garde de cout qui s'arme sur l'echec transforme une mesure
manquante en silence permanent. Meme famille que les capteurs qui confondent
« pas trouve » et « pas pu regarder ».

Usage :
    run action=trusted_script path=tools/forge_patch_hub_origine401_v2.py
    run action=trusted_script path=tools/forge_patch_hub_origine401_v2.py \
        script_args="--apply"
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/observabilite"

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIBLE = ROOT / "tools" / "nokido_hub.py"
SENTINELLE_V2 = "refroidissement arme UNIQUEMENT sur succes"

AVANT = '''    maintenant = _t.time()
    if maintenant - cache["ts"] < _ORIGINE_INTERVALLE_S:
        return {"origine": "non_resolue", "raison": "cache_refroidissement"}
    cache["ts"] = maintenant
    try:
        import psutil as _ps
    except Exception:
        return {"origine": "illisible", "raison": "psutil_absent"}'''

APRES = '''    maintenant = _t.time()
    # refroidissement arme UNIQUEMENT sur succes : le poser avant la tentative
    # transformait le moindre echec en silence de 60 s, donc en identification
    # jamais aboutie (mesure 2026-08-04). Tant qu'on ne sait pas QUI appelle,
    # chaque rejet redonne une chance ; des qu'on le sait, le cache par port
    # rend le cout nul.
    if cache.get("connu") and maintenant - cache["ts"] < _ORIGINE_INTERVALLE_S:
        return {"origine": "non_resolue", "raison": "cache_refroidissement"}
    try:
        import psutil as _ps
    except Exception:
        cache["ts"] = maintenant  # psutil absent : inutile de reessayer en boucle
        cache["connu"] = True
        return {"origine": "illisible", "raison": "psutil_absent"}'''

AVANT2 = '''        cache["par_port"][port] = info
        if len(cache["par_port"]) > 200:
            cache["par_port"].clear()
        return info'''

APRES2 = '''        cache["par_port"][port] = info
        cache["ts"] = maintenant
        cache["connu"] = True
        if len(cache["par_port"]) > 200:
            cache["par_port"].clear()
        return info'''


def main() -> int:
    ap = argparse.ArgumentParser(description="Correctif cache origine 401")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    rapport: dict = {"cible": str(CIBLE), "mode": "apply" if args.apply else "dry-run"}
    if not CIBLE.exists():
        rapport["verdict"] = "CIBLE INTROUVABLE"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 1
    src = CIBLE.read_text(encoding="utf-8")
    if SENTINELLE_V2 in src:
        rapport["verdict"] = "DEJA CORRIGE — rien a faire (idempotent)"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0
    if "_origine_appelant" not in src:
        rapport["verdict"] = "ABANDON : patch v1 absent, appliquer d'abord forge_patch_hub_origine_401.py"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 2

    out = src
    detail = []
    for i, (a, b) in enumerate(((AVANT, APRES), (AVANT2, APRES2)), 1):
        n = out.count(a)
        detail.append({"bloc": i, "occurrences": n})
        if n != 1:
            rapport["blocs"] = detail
            rapport["verdict"] = f"ABANDON : bloc {i} vu {n} fois (1 attendue), ne pas forcer"
            print(json.dumps(rapport, ensure_ascii=False, indent=2))
            return 3
        out = out.replace(a, b, 1)
    rapport["blocs"] = detail

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
    sauvegarde = CIBLE.with_suffix(f".py.avant-origine401v2-{horo}.bak")
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
