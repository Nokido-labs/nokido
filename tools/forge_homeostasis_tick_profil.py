#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_homeostasis_tick_profil.py - UN tick d'Homeostasis, profile phase par phase.

__FORGE_COLOR__ = "observabilite/regulation : profil RSS et duree de chaque phase d'un tick d'Homeostasis"

Pourquoi : `NokidoHomeostasis` a ete coupe le 2026-09-05 (« 4,9 Go liberes a son arret +
51 Mo/s de lecture - l'organe de regulation saturait la machine qu'il regule »). L'owner
veut le rallumer « une fois verifie son cablage reel et qu'il ne soit pas gourmand ».
La lecture de code designe deux suspects (l'autoencodeur torch de la nouveaute, le
worker pluripotent qui rechauffe le RAG) ; ce script MESURE au lieu de designer :
il enveloppe `_safe_call` (la porte de TOUTES les phases) et note, par phase, la duree
et le delta RSS du processus. La nouveaute n'est pas une phase `_safe_call` : elle est
mesuree a part, autour de `_get_novelty` + `_get_novelty_vector`.

Un tick reel a des EFFETS (reconcile, moisson des orphelins, drain GOAP) : c'est le
cycle que le daemon executerait ; on l'execute UNE fois, on ne le fabrique pas.
`--tick N` choisit le numero de tick (1 = coeur seul ; 0 = coeur + phases horaires,
2 h, 6 h, mais PAS la renale quotidienne, qui exige tc > 0 et tc % 288 == 0).

Usage (run_job) : LAFORGE_PYTHON tools/forge_homeostasis_tick_profil.py [--tick 1]
Rapport : sandbox/homeostasis_tick_profil.json + stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT = ROOT / "sandbox" / "homeostasis_tick_profil.json"


def _rss_go() -> float:
    import psutil
    return round(psutil.Process().memory_info().rss / 2**30, 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", type=int, default=1)
    ap.add_argument("--ticks", type=int, default=1,
                    help="nombre de ticks CONSECUTIFS dans le MEME processus (comme le "
                         "daemon). C'est la seule facon de voir une accumulation : un "
                         "tick unique ne dit rien des 4,9 Go liberes le 2026-09-05.")
    ap.add_argument("--pause", type=float, default=0.0,
                    help="secondes entre deux ticks (le daemon reel dort 5 min)")
    ap.add_argument("--tracemalloc", action="store_true",
                    help="attribuer la memoire RETENUE aux lignes de code (couteux ~2x, "
                         "mais seul moyen de nommer le coupable d'une retention)")
    a = ap.parse_args()

    rss0 = _rss_go()
    t_imp = time.time()
    from nokido_agent.app import forge_homeostasis_orchestrator as H  # type: ignore
    rss_import = _rss_go()
    phases: list[dict] = []

    _orig = H._safe_call

    def _profil(fn_name, fn, timeout_s=None):
        r0, t0 = _rss_go(), time.time()
        try:
            return _orig(fn_name, fn, timeout_s) if timeout_s is not None else _orig(fn_name, fn)
        finally:
            phases.append({"phase": fn_name, "s": round(time.time() - t0, 2),
                           "rss_avant_go": r0, "rss_apres_go": _rss_go(),
                           "delta_go": round(_rss_go() - r0, 3)})

    H._safe_call = _profil

    # La nouveaute (torch) n'est pas une phase `_safe_call` : on l'entoure a part, avec
    # la MEME enveloppe de chronometrage (`chrono`) que le reste -- deux enveloppes
    # jumelles ecrites a la main sont exactement ce que le cliquet de duplication a
    # signale le 2026-09-06.
    from nokido_agent.tools.forge_embed_lot_commun import chrono  # noqa: E402

    H._get_novelty = chrono(phases, "novelty:_get_novelty(import torch+autoencodeur)",
                            H._get_novelty, rss=_rss_go)
    H._get_novelty_vector = chrono(phases, "novelty:_get_novelty_vector",
                                   H._get_novelty_vector, rss=_rss_go)

    # QUATRE CAS QUE LE SEUL RSS NE DISTINGUE PAS (analyse externe du 2026-09-06) :
    #   A. allocation temporaire  -> RSS monte puis redescend
    #   B. high-water de l'allocateur -> RSS reste haut, objets liberes (arenas gardees)
    #   C. reference RETENUE      -> RSS ET nombre d'objets montent tick apres tick
    #   D. cache charge une fois  -> un saut au 1er tick, puis plat
    # Seul `retenu` (RSS a la fin du tick N moins RSS a la fin du tick N-1) tranche entre
    # D et C ; seul le compteur d'objets suivis par le ramasse-miettes separe B de C.
    import gc

    if a.tracemalloc:
        import tracemalloc

        tracemalloc.start(12)
    t_tick = time.time()
    state = {"tick_count": a.tick}
    out, erreur = None, None
    par_tick: list[dict] = []
    rss_pic = _rss_go()
    for n in range(a.ticks):
        t0, r0 = time.time(), _rss_go()
        marque = len(phases)
        gc.collect()
        objets0 = len(gc.get_objects())
        instant0 = None
        if a.tracemalloc:
            import tracemalloc

            instant0 = tracemalloc.take_snapshot()
        try:
            out = H.tick(state)
        except Exception as e:  # noqa: BLE001
            erreur = f"tick {n + 1}: {type(e).__name__}: {e}"
            break
        # `tick` ne met pas a jour le compteur : c'est le daemon qui le fait. On le
        # reproduit, sinon les phases horaires/2h/6h ne se declencheraient jamais.
        state["tick_count"] = state.get("tick_count", 0) + 1
        gc.collect()  # ce qui survit a un collect explicite est RETENU, pas en attente
        objets1 = len(gc.get_objects())
        r1 = _rss_go()
        rss_pic = max(rss_pic, r1)
        ligne = {"tick": n + 1, "tick_count": state["tick_count"] - 1,
                 "s": round(time.time() - t0, 1), "rss_avant_go": r0,
                 "rss_apres_go": r1, "delta_go": round(r1 - r0, 3),
                 "retenu_go": (round(r1 - par_tick[-1]["rss_apres_go"], 3) if par_tick else None),
                 "objets_gc": objets1, "objets_retenus": objets1 - objets0,
                 "phases": len(phases) - marque}
        if a.tracemalloc and instant0 is not None:
            import tracemalloc

            diff = tracemalloc.take_snapshot().compare_to(instant0, "lineno")[:3]
            ligne["top_retenu"] = [f"{s.traceback[0]} {round(s.size_diff / 2**20, 1)} Mo"
                                   for s in diff if s.size_diff > 0]
        par_tick.append(ligne)
        print(f"[tick {n + 1}/{a.ticks}] {ligne}", flush=True)
        if a.pause and n + 1 < a.ticks:
            time.sleep(a.pause)
    duree = round(time.time() - t_tick, 1)
    rss_fin = _rss_go()

    rapport = {
        "tick": a.tick, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rss_depart_go": rss0, "rss_apres_import_go": rss_import,
        "import_s": round(t_imp and (time.time() - t_imp) - duree, 1),
        "rss_fin_go": rss_fin, "duree_tick_s": duree, "erreur": erreur,
        "ticks_demandes": a.ticks, "par_tick": par_tick, "rss_pic_go": rss_pic,
        # Le 1er tick paie l'initialisation (imports, modeles, caches) : il est EXCLU de
        # la moyenne, sinon un cout d'amorcage se lit comme une fuite (cas D pris pour C).
        "retenu_moyen_go_par_tick_hors_premier": (
            round(sum(t["retenu_go"] for t in par_tick[1:] if t.get("retenu_go") is not None)
                  / max(len(par_tick) - 1, 1), 4) if len(par_tick) >= 2 else None),
        "objets_retenus_hors_premier": (
            sum(t["objets_retenus"] for t in par_tick[1:]) if len(par_tick) >= 2 else None),
        "phases": sorted(phases, key=lambda p: -abs(p["delta_go"])),
        "phases_ok": {k: bool(v.get("ok")) for k, v in ((out or {}).get("phases") or {}).items()},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rapport, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(rapport, indent=1, ensure_ascii=False), flush=True)
    lourdes = [p for p in phases if abs(p["delta_go"]) >= 0.3 or p["s"] >= 30]
    print(f"[verdict] rss {rss0} -> import {rss_import} -> fin {rss_fin} Go en {duree} s ; "
          f"phases lourdes (>=0,3 Go ou >=30 s) : {[(p['phase'], p['delta_go'], p['s']) for p in lourdes]}", flush=True)
    return 0 if erreur is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
