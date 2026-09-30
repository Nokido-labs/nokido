# -*- coding: utf-8 -*-
"""tools/forge_hub_memory_probe.py — d'ou viennent les Go d'un process du corps.

POURQUOI. Mesure du 2026-09-19 : le hub engageait 2,8 a 3,0 Go de memoire PRIVEE
alors que son import complet coute 27 Mo (390 modules, aucune bibliotheque
lourde). Quatre pistes ont ete ECARTEES par la mesure -- imports directs, chaine
transitive, fichier mappe (`mmap_size`, non compte dans `private` sous Windows),
et fuite (plateau a 2,5 % d'amplitude sur 18 echantillons). L'origine restait
inconnue faute d'INSTRUMENT : `memory_maps()` rend `AccessDenied` depuis le
compte sandbox, et la fiche du 2026-08-20 etablit que ni scalene ni memray
n'atteignent la memoire native sous Windows.

CE QUE CETTE SONDE FAIT. Elle ventile le RSS d'un process par ORIGINE (heap
anonyme = allocation Python, fichiers mappes, DLL/extensions, base SQLite) au
lieu de rendre un total opaque. Un total ne se corrige pas ; une ventilation, si.

CE QU'ELLE NE FAIT PAS, et le DIT. Elle ne profile pas les objets Python
(`tracemalloc` exigerait d'instrumenter le process cible avant son demarrage).
Elle n'attribue rien qu'elle n'a pas lu : un mapping illisible est COMPTE comme
illisible, jamais reparti au prorata sur les autres.

LE COMPTE IMPORTE. `memory_maps()` exige des droits sur le process cible. Sous
`LaForgeSbxOffline` (defaut) il echoue. Le canal privilegie du depot est
`run action=trusted_script` -> `LaForgeTrusted`. La sonde NOMME son compte
effectif dans sa sortie : sans lui, un `AccessDenied` se lit a tort comme
« rien a voir » alors que c'est « je n'ai pas pu regarder ».

Usage :
    run action=trusted_script path=tools/forge_hub_memory_probe.py script_args="--pid 20240"
    run action=trusted_script path=tools/forge_hub_memory_probe.py script_args="--service NokidoMCP"
"""

from __future__ import annotations

__FORGE_COLOR__ = "observabilite/trace : ventiler la memoire d'un process par origine"

import argparse
import getpass
import json
import sys
from collections import defaultdict

SUPERVISEUR = "http://127.0.0.1:8765/supervisor/status"


def _pid_du_service(nom: str):
    """pid declare au superviseur, ou (None, motif) -- jamais un None muet."""
    import urllib.request

    try:
        with urllib.request.urlopen(SUPERVISEUR, timeout=5) as r:
            d = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        return None, "superviseur injoignable (%s)" % type(e).__name__
    s = (d.get("services") or {}).get(nom)
    if not s or not s.get("pid"):
        return None, "service %r absent du registre ou sans pid" % nom
    return int(s["pid"]), ""


def _categorie(chemin: str) -> str:
    n = (chemin or "").lower()
    if not chemin or "anon" in n:
        return "heap anonyme (allocation Python)"
    if n.endswith((".db", ".db-wal", ".db-shm", ".sqlite")):
        return "base SQLite mappee"
    if n.endswith((".pyd", ".dll", ".so")):
        return "DLL / extensions natives"
    if n.endswith(".exe"):
        return "interpreteur"
    return "autre fichier mappe"


def ventiler(pid: int) -> dict:
    """RSS par ORIGINE. Rend AUSSI ce qui n'a pas pu etre lu, et sous quel compte."""
    import psutil

    p = psutil.Process(pid)
    mi = p.memory_info()
    out = {
        "pid": pid,
        "compte_effectif": getpass.getuser(),
        "rss_go": round(mi.rss / 1e9, 3),
        "prive_go": round(getattr(mi, "private", 0) / 1e9, 3) or None,
        "threads": p.num_threads(),
    }
    try:
        maps = p.memory_maps(grouped=True)
    except Exception as e:  # noqa: BLE001
        out["ventilation"] = None
        out["illisible"] = (
            "memory_maps refuse (%s) sous le compte %s — relancer via "
            "`action=trusted_script`. ABSENCE DE MESURE, pas absence de cause."
            % (type(e).__name__, out["compte_effectif"])
        )
        return out
    par_cat = defaultdict(float)
    for mm in maps:
        par_cat[_categorie(mm.path)] += float(getattr(mm, "rss", 0) or 0)
    out["mappings"] = len(maps)
    out["ventilation_go"] = {
        k: round(v / 1e9, 3) for k, v in sorted(par_cat.items(), key=lambda x: -x[1])
    }
    out["top"] = [
        {"rss_mo": round((getattr(mm, "rss", 0) or 0) / 1e6, 1),
         "chemin": (mm.path or "[anonyme]")[-70:]}
        for mm in sorted(maps, key=lambda x: -(getattr(x, "rss", 0) or 0))[:10]
    ]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pid", type=int, help="process a ventiler")
    ap.add_argument("--service", help="nom de service ; son pid est demande au superviseur")
    a = ap.parse_args(argv)

    pid = a.pid
    if pid is None:
        if not a.service:
            print(json.dumps({"erreur": "donner --pid ou --service"}, ensure_ascii=False))
            return 2
        pid, motif = _pid_du_service(a.service)
        if pid is None:
            print(json.dumps({"erreur": motif}, ensure_ascii=False))
            return 1
    try:
        print(json.dumps(ventiler(pid), ensure_ascii=False, indent=2))
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"erreur": "%s: %s" % (type(e).__name__, str(e)[:160]),
                          "compte_effectif": getpass.getuser()}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
