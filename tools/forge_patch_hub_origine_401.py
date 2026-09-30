"""Patch : faire dire au hub QUI emet les requetes rejetees en 401.

Pourquoi ce script existe plutot qu'un `governed_edit` direct : `tools/nokido_hub.py`
est un CRITICAL_FILE et l'edition gouvernee le refuse sans
`LAFORGE_ALLOW_CRITICAL_WRITE=1` — variable qui vit dans l'environnement du hub et
ne redescend pas dans un process vivant. La voie prevue par la doctrine est alors
« privilege = code revu » : le patch est ECRIT ici, commite (donc relisible et
reversible par git), puis applique via `run action=trusted_script`.

Ce que le patch corrige. Mesure 2026-08-04 : 114 406 rejets `ERR:401` dans
`network_log`, soit 44 % de tout le trafic du hub, contre 303 autres erreurs. Ils
arrivent a cadence de TIMER — exactement 5 par minute, toujours a la seconde 49-50,
depuis 127.0.0.1, et reprennent 4 s apres chaque boot. Impossible de savoir QUI
appelle : ces lignes n'ont ni en-tete, ni charge, ni port source, et les requetes
sont trop breves pour etre attrapees par echantillonnage psutil. Un signal dense
qui ne dit pas son origine ne permet pas d'agir — c'est ce qui a laisse l'anomalie
invisible pendant des semaines.

Le patch ajoute une branche `HTTP_DIRECT` au `channel_meta` que `_log_network`
construit DEJA par canal (GEMINI_OAUTH, CLINE_MCP...), et transmet `request` au
point de rejet. Cout : une resolution `psutil.net_connections()` au plus toutes les
60 s, sur un chemin qui ne voit que ~5 requetes/minute.

Usage :
    run action=trusted_script path=tools/forge_patch_hub_origine_401.py            # dry-run
    run action=trusted_script path=tools/forge_patch_hub_origine_401.py \
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
SENTINELLE = "_origine_appelant"   # idempotence : deja patche si present

HELPER = '''# Cache de resolution port source -> process. `psutil.net_connections()` coute
# 50-200 ms : a 5 requetes/min c'est negligeable, mais un flood ne doit pas
# transformer le journal en goulot. Une resolution au plus toutes les 60 s.
_ORIGINE_CACHE: dict = {"ts": 0.0, "par_port": {}}
_ORIGINE_INTERVALLE_S = 60.0


def _origine_appelant(port: int) -> dict:
    """Qui appelle, vu depuis le systeme. Rend le MOTIF quand on ne peut pas voir.

    Mesure 2026-08-04 : 114 406 rejets ERR:401 (44 % du trafic du hub), ~5/min au
    timer depuis 127.0.0.1, et aucun moyen de savoir qui appelle car le journal
    n'enregistrait ni en-tete, ni charge, ni port source.

    Trois etats, jamais deux : « pas trouve » et « pas pu regarder » ne sont pas la
    meme chose, et les confondre est precisement ce qui a rendu cette anomalie
    invisible.
    """
    if not port:
        return {}
    import time as _t

    cache = _ORIGINE_CACHE
    if port in cache["par_port"]:
        return cache["par_port"][port]
    maintenant = _t.time()
    if maintenant - cache["ts"] < _ORIGINE_INTERVALLE_S:
        return {"origine": "non_resolue", "raison": "cache_refroidissement"}
    cache["ts"] = maintenant
    try:
        import psutil as _ps
    except Exception:
        return {"origine": "illisible", "raison": "psutil_absent"}
    try:
        trouve = None
        for _c in _ps.net_connections(kind="inet"):
            if _c.laddr and _c.laddr.port == port and _c.pid:
                trouve = _c.pid
                break
        if trouve is None:
            # Requete breve : la connexion peut deja etre fermee, port recycle.
            return {"origine": "non_resolue", "raison": "connexion_fermee"}
        _p = _ps.Process(trouve)
        info = {"origine": "resolue", "pid": trouve, "process": _p.name()}
        try:
            info["cmdline"] = " ".join(_p.cmdline())[:200]
        except Exception:
            info["cmdline"] = "<illisible: autre compte>"
        try:
            info["compte"] = _p.username()
        except Exception:
            info["compte"] = "<illisible>"
        cache["par_port"][port] = info
        if len(cache["par_port"]) > 200:
            cache["par_port"].clear()
        return info
    except Exception as _e:  # noqa: BLE001
        return {"origine": "illisible", "raison": type(_e).__name__}


'''

REMPLACEMENTS = [
    # 1. le helper, juste avant _log_network
    ("def _log_network(\n    direction: str,\n    method: str = None,",
     HELPER + "def _log_network(\n    direction: str,\n    method: str = None,"),
    # 2. la branche HTTP_DIRECT dans channel_meta
    ('    elif _channel == "CLINE_MCP":\n        _channel_meta["client"] = "vscode_cline"',
     '    elif _channel == "CLINE_MCP":\n        _channel_meta["client"] = "vscode_cline"\n'
     '    elif _channel == "HTTP_DIRECT" and request is not None:\n'
     '        # Seul canal ou l\'appelant n\'est identifie par AUCUN en-tete : c\'est\n'
     '        # donc le seul ou il faut demander au systeme qui parle.\n'
     '        try:\n'
     '            _cli = getattr(request, "client", None)\n'
     '            _port = getattr(_cli, "port", None) if _cli else None\n'
     '            if _port:\n'
     '                _channel_meta["port_source"] = _port\n'
     '                _channel_meta.update(_origine_appelant(_port))\n'
     '        except Exception as _e:  # noqa: BLE001\n'
     '            _channel_meta["origine"] = "illisible"\n'
     '            _channel_meta["raison"] = type(_e).__name__'),
    # 3. transmettre `request` au point de rejet
    ('                method="UNAUTHORIZED",\n'
     '                agent=agent_hdr,\n'
     '                ring=ring,\n'
     '                status="ERR:401",\n'
     '                client_ip=client_ip,\n'
     '            )',
     '                method="UNAUTHORIZED",\n'
     '                agent=agent_hdr,\n'
     '                ring=ring,\n'
     '                status="ERR:401",\n'
     '                client_ip=client_ip,\n'
     '                # `request` transmis pour que le journal dise enfin QUI appelle\n'
     '                # (cf. _origine_appelant) : sans lui, 114 406 rejets anonymes.\n'
     '                request=request,\n'
     '            )'),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="Patch origine des 401 du hub")
    ap.add_argument("--apply", action="store_true",
                    help="ecrit reellement (sinon dry-run)")
    args = ap.parse_args()

    rapport: dict = {"cible": str(CIBLE), "mode": "apply" if args.apply else "dry-run"}
    if not CIBLE.exists():
        rapport["verdict"] = "CIBLE INTROUVABLE"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 1

    src = CIBLE.read_text(encoding="utf-8")
    rapport["taille_avant"] = len(src)
    if SENTINELLE in src:
        rapport["verdict"] = "DEJA PATCHE — rien a faire (idempotent)"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    # Chaque ancre doit etre UNIQUE : un remplacement ambigu sur un fichier
    # critique est un risque qu'on refuse de prendre.
    out = src
    detail = []
    for i, (avant, apres) in enumerate(REMPLACEMENTS, 1):
        n = out.count(avant)
        detail.append({"bloc": i, "occurrences": n})
        if n != 1:
            rapport["blocs"] = detail
            rapport["verdict"] = (
                f"ABANDON : le bloc {i} apparait {n} fois (1 attendue). "
                "Le fichier a change depuis l'ecriture du patch — le relire avant "
                "de reessayer, ne pas forcer.")
            print(json.dumps(rapport, ensure_ascii=False, indent=2))
            return 2
        out = out.replace(avant, apres, 1)
    rapport["blocs"] = detail
    rapport["taille_apres"] = len(out)

    try:
        compile(out, str(CIBLE), "exec")
        rapport["ast"] = "OK"
    except SyntaxError as e:
        rapport["ast"] = f"ECHEC ligne {e.lineno}: {e.msg}"
        rapport["verdict"] = "ABANDON : le resultat ne compile pas, rien ecrit"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 3

    if not args.apply:
        rapport["verdict"] = "DRY-RUN OK — relancer avec --apply pour ecrire"
        print(json.dumps(rapport, ensure_ascii=False, indent=2))
        return 0

    horo = time.strftime("%Y%m%d-%H%M%S")
    sauvegarde = CIBLE.with_suffix(f".py.avant-origine401-{horo}.bak")
    shutil.copy2(CIBLE, sauvegarde)
    CIBLE.write_text(out, encoding="utf-8")
    relu = CIBLE.read_text(encoding="utf-8")
    rapport["sauvegarde"] = str(sauvegarde)
    rapport["relecture_identique"] = (relu == out)
    rapport["verdict"] = (
        "APPLIQUE. Le hub tourne encore avec l'ancien code en memoire : l'effet "
        "n'apparaitra qu'au prochain rechargement. Retour arriere = restaurer la "
        "sauvegarde, ou `git checkout -- tools/nokido_hub.py`.")
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
