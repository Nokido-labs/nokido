#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_organ_edges.py — ARETES du corps : part_of et connected_to, puis
« si cet organe tombe, qu'est-ce qui meurt en aval ».

__FORGE_COLOR__ = "observabilite/anatomie-graphe"

POURQUOI (mandat owner 2026-07-26, bibliographie FMA)
-----------------------------------------------------
La carte du corps (`sandbox/workspace/organ_map_full.json`, 714 modules classes)
est un DICTIONNAIRE PLAT : module -> organe. Elle dit OU vit chaque chose, jamais
CE QUI Y EST RELIE. Consequence mesurable : la question 2 de CLAUDE.md §10
(« quelle vascularisation ? ») se repond encore a la main, et « si ce module fuit,
qu'est-ce qui meurt ? » releve de l'intuition.

La FMA apporte exactement les deux relations qui manquent — `part_of` et
`connected_to`. On n'a pas besoin de charger 100 Mo d'OWL ni un raisonneur pour
s'en servir : on emprunte le VOCABULAIRE et on l'applique au corps reel.
  part_of      : module -> organe        (deja mesure par le census)
  connected_to : module -> modules importes (arete de dependance reelle)

CE QUI N'EST PAS DUPLIQUE
-------------------------
  - Le parcours de graphe : `app/forge_graph_cve_propagation.propagate_cve(
    cve_id, entry_module, graph: dict[str, list[str]], max_depth)` existe, rend
    {affected, depth_map, risk_score}. On l'ALIMENTE, on n'ecrit pas de BFS.
  - Les imports : `tools/forge_body_regulation_audit.scan_imports()` les extrait
    deja. On l'utilise s'il est disponible, avec un scanner de secours local
    (regex sur les imports de modules forge_*/nokido_*) pour ne jamais dependre
    d'une signature qu'on n'a pas verifiee.
  - Les organes : `organ_map_full.json`, sinon `forge_module_census.organ`.

LE SENS DE L'ARETE COMPTE
------------------------
« Qui meurt si X meurt » n'est PAS « ce que X importe » : c'est l'INVERSE — ceux
qui importent X. Le BFS est donc lance sur le graphe RENVERSE. Confondre les deux,
c'est repondre a la question opposee avec l'air d'avoir raison.

COUT SYSTEME
------------
Zero resident : aucun daemon, aucun thread, aucune dependance externe. Un scan de
fichiers a la demande, un JSON statique regenerable.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

OUT_PATH = ROOT / "sandbox" / "organ_edges.json"
ORGAN_MAP = ROOT / "sandbox" / "workspace" / "organ_map_full.json"
SKIP_DIRS = {"_attic", "backups", "workspace", "_mcp_repos", "__pycache__"}
_IMPORT = re.compile(r"^\s*(?:import|from)\s+((?:forge|nokido)_[A-Za-z0-9_]+)", re.M)


def _modules() -> dict[str, Path]:
    """Nom de module -> chemin, pour app/ et tools/."""
    out: dict[str, Path] = {}
    for sub in ("app", "tools"):
        base = ROOT / sub
        if not base.is_dir():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                if fn.endswith(".py"):
                    out.setdefault(fn[:-3], Path(root) / fn)
    return out


def _connected_to() -> tuple[dict[str, list[str]], str]:
    """Arete de dependance : module -> modules qu'il importe.

    On tente d'abord l'extracteur existant ; sa forme de retour n'est pas
    supposee, elle est INSPECTEE. En cas de doute, scanner local — mieux vaut une
    mesure maison explicite qu'une adaptation devinee a une signature.
    """
    try:
        from nokido_agent.tools import forge_body_regulation_audit as audit

        raw = audit.scan_imports()
        cand = raw[0] if isinstance(raw, tuple) and raw else raw
        if isinstance(cand, dict) and cand:
            probe = next(iter(cand.values()))
            if isinstance(probe, (list, set, tuple)):
                return ({str(k): sorted(str(x) for x in v) for k, v in cand.items()},
                        "forge_body_regulation_audit.scan_imports")
    except Exception:  # noqa: BLE001
        pass

    graph: dict[str, list[str]] = {}
    known = _modules()
    for name, path in known.items():
        try:
            txt = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        deps = {m for m in _IMPORT.findall(txt) if m in known and m != name}
        graph[name] = sorted(deps)
    return graph, "scanner local (regex imports forge_*/nokido_*)"


def _part_of() -> tuple[dict[str, str], str]:
    """module -> organe. Carte du census si presente, sinon classement du census."""
    if ORGAN_MAP.exists():
        try:
            d = json.loads(ORGAN_MAP.read_text(encoding="utf-8", errors="replace"))
            if isinstance(d, dict) and d:
                # L'ORIENTATION se DETECTE, elle ne se suppose pas. Premiere version
                # de ce module : suppose module -> organe, resultat mesure
                # `modules_avec_organe: 0` et un seul « organe ». CLAUDE.md §10 dit
                # bien « carte organe -> module » : la carte est INVERSEE.
                out: dict[str, str] = {}
                probe = next(iter(d.values()))
                if isinstance(probe, (list, tuple, set)):          # organe -> [modules]
                    for organ, mods in d.items():
                        for m in (mods or []):
                            out[Path(str(m)).stem] = str(organ)
                elif isinstance(probe, dict):                      # module -> {organ: ...}
                    for k, v in d.items():
                        val = (v or {}).get("organ") or (v or {}).get("organe")
                        if val:
                            out[Path(str(k)).stem] = str(val)
                else:                                              # module -> "organe"
                    for k, v in d.items():
                        out[Path(str(k)).stem] = str(v)
                if out:
                    return out, "%s (%s)" % (
                        ORGAN_MAP.name,
                        "organe->modules" if isinstance(probe, (list, tuple, set))
                        else "module->organe")
        except Exception:  # noqa: BLE001
            pass
    try:
        from nokido_agent.tools import forge_module_census as census

        return ({m: census.organ(m) for m in _modules()},
                "forge_module_census.organ")
    except Exception:  # noqa: BLE001
        return {}, "aucune source d'organe disponible — part_of vide (dit explicitement)"


def build(save: bool = True) -> dict:
    connected, src_edges = _connected_to()
    part_of, src_organ = _part_of()

    reverse: dict[str, list[str]] = defaultdict(list)
    for mod, deps in connected.items():
        for d in deps:
            reverse[d].append(mod)
    reverse = {k: sorted(set(v)) for k, v in reverse.items()}

    organ_edges: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for mod, deps in connected.items():
        o_from = part_of.get(mod)
        if not o_from:
            continue
        for d in deps:
            o_to = part_of.get(d)
            if o_to and o_to != o_from:
                organ_edges[o_from][o_to] += 1

    doc = {
        "sources": {"connected_to": src_edges, "part_of": src_organ},
        "counts": {
            "modules": len(connected),
            "aretes_connected_to": sum(len(v) for v in connected.values()),
            "modules_avec_organe": sum(1 for m in connected if part_of.get(m)),
            "organes": len(set(part_of.values())) if part_of else 0,
        },
        "part_of": part_of,
        "connected_to": connected,
        "depends_on_me": reverse,
        "organ_to_organ": {k: dict(v) for k, v in organ_edges.items()},
    }
    if save:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def _load() -> dict:
    if OUT_PATH.exists():
        try:
            return json.loads(OUT_PATH.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            pass
    return build(save=True)


def downstream(module: str, max_depth: int = 3) -> dict:
    """Qui meurt en aval si `module` tombe.

    ATTENTION AU SENS : on parcourt `depends_on_me` (ceux qui IMPORTENT le module),
    pas ses propres imports. Le BFS vient de forge_graph_cve_propagation.
    """
    doc = _load()
    rev = doc.get("depends_on_me") or {}
    part_of = doc.get("part_of") or {}
    mod = Path(module).stem
    try:
        from nokido_agent.app.forge_graph_cve_propagation import propagate_cve
    except Exception as exc:  # noqa: BLE001
        return {"error": "BFS indisponible: %s" % exc}

    res = propagate_cve("organ-failure:%s" % mod, mod, rev, max_depth=max_depth)
    by_organ: dict[str, list[str]] = defaultdict(list)
    for m in res.get("affected", []):
        by_organ[part_of.get(m, "non classe")].append(m)
    return {
        "module": mod,
        "organe": part_of.get(mod, "non classe"),
        "connu_du_graphe": mod in rev or mod in (doc.get("connected_to") or {}),
        "aval_direct": (rev.get(mod) or [])[:40],
        "aval_total": len(res.get("affected", [])),
        "profondeur_max": max_depth,
        "risk_score": res.get("risk_score"),
        "organes_touches": {k: len(v) for k, v in sorted(by_organ.items())},
        "modules_touches": res.get("affected", [])[:60],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Aretes du corps : part_of / connected_to + aval.")
    ap.add_argument("--build", action="store_true", help="regenerer sandbox/organ_edges.json")
    ap.add_argument("--module", metavar="NOM", help="qui meurt en aval si ce module tombe")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.module:
        r = downstream(args.module, max_depth=args.depth)
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if r.get("connu_du_graphe") else 1

    doc = build(save=True)
    if args.json:
        print(json.dumps(doc["counts"] | {"sources": doc["sources"]}, ensure_ascii=False, indent=2))
        return 0
    c = doc["counts"]
    print("ARETES DU CORPS -> %s" % OUT_PATH)
    print("  sources        : connected_to=%s | part_of=%s"
          % (doc["sources"]["connected_to"], doc["sources"]["part_of"]))
    print("  modules        : %d  (avec organe : %d)" % (c["modules"], c["modules_avec_organe"]))
    print("  aretes         : %d" % c["aretes_connected_to"])
    print("  organes        : %d" % c["organes"])
    top = sorted(((len(v), k) for k, v in (doc.get("depends_on_me") or {}).items()), reverse=True)
    print("\n  modules les plus PORTEURS (le plus de dependants) :")
    for n, m in top[:12]:
        print("     %-38s %3d dependants  [%s]" % (m, n, (doc["part_of"] or {}).get(m, "non classe")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
