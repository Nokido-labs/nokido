#!/usr/bin/env python3
"""Mesure LECTURE SEULE des regressions potentielles du scope de role par defaut.

Pour chaque identite vue dans logs/mcp_audit.log sur la fenetre (7 j) :
  - quels outils le scope de role (CORE + groupe) lui laisserait visibles ;
  - lesquels de ses outils EFFECTIVEMENT appeles disparaitraient de tools/list
    (= regressions potentielles), et lesquels seraient reintegres par la regle
    « appele >= N fois en 7 j rejoint le groupe ».
Ecrit aussi le snapshot d'usage lu par `forge_tool_scope` (sandbox/tool_usage_role.json).

Usage : python tools/forge_scope_role_mesure.py [--audit P] [--catalogue J] [--jours 7]
        [--min-calls 3] [--sortie J] [--snapshot J] [--maintenant ISO]
Le dispatch n'est jamais touche : un outil hors scope reste appelable ; il s'agit
d'un diagnostic de visibilite.
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/mesure : regressions potentielles du scope de role MCP, lecture seule"  # organe declare le 2026-10-25 (gate anatomie, CI 7991f0daa)

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent


def _racine_donnees():
    """DONNEES par forge_db_path.racine_donnees() (cliquet racine_donnees) ; repli : racine du code, comme avant."""
    try:
        from nokido_agent.app.forge_db_path import racine_donnees
    except ImportError:
        try:
            from forge_db_path import racine_donnees
        except ImportError:
            return ROOT
    return racine_donnees()


_RACINE_DONNEES = _racine_donnees()
_LIGNE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d) \| NetworkChannel\.[A-Za-z_]+:([^ |]+) \| (.*)$")
_AGENT = re.compile(r'"agent": "([^"]+)"')


def parse_line(line: str) -> Optional[Tuple[str, str, str]]:
    """(horodatage, outil, AGENT) ou None si la ligne n'est pas un appel attribuable."""
    m = _LIGNE.match(line or "")
    if not m:
        return None
    a = _AGENT.search(m.group(3))
    if not a:
        return None
    return m.group(1), m.group(2), a.group(1).upper()


def usage_par_agent(lines: Iterable[str], since: str, catalogue: Set[str]) -> Dict[str, Dict[str, int]]:
    """Compte les appels par agent/outil depuis `since` (ISO), outils du catalogue seulement."""
    out: Dict[str, Counter] = defaultdict(Counter)
    for ln in lines:
        r = parse_line(ln)
        if not r:
            continue
        ts, tool, agent = r
        if ts < since or tool not in catalogue:
            continue
        out[agent][tool] += 1
    return {a: dict(c) for a, c in out.items()}


def regressions(usage: Dict[str, Dict[str, int]],
                scope_fn: Callable[[str], Optional[Set[str]]],
                min_calls: int = 3) -> Dict[str, dict]:
    """Par agent : outils utilises qui sortiraient de sa liste, avec/sans la regle d'usage."""
    rep: Dict[str, dict] = {}
    for agent, calls in sorted(usage.items()):
        scope = scope_fn(agent)
        if scope is None:  # pas de scope derivable -> liste pleine (fail-open)
            rep[agent] = {"scope": False, "taille_scope": None, "appels": sum(calls.values()),
                          "disparaissent": {}, "reintegres": {}, "regressions_apres_usage": {}}
            continue
        gone = {t: n for t, n in calls.items() if t not in scope}
        back = {t: n for t, n in gone.items() if n >= min_calls}
        rep[agent] = {"scope": True, "taille_scope": len(scope), "appels": sum(calls.values()),
                      "disparaissent": gone, "reintegres": back,
                      "regressions_apres_usage": {t: n for t, n in gone.items() if t not in back}}
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", default=str(_RACINE_DONNEES / "logs" / "mcp_audit.log"))
    ap.add_argument("--catalogue", default=str(_RACINE_DONNEES / "sandbox" / "workspace" / "poids_outils_mcp_20261024.json"))
    ap.add_argument("--jours", type=int, default=7)
    ap.add_argument("--min-calls", type=int, default=3)
    ap.add_argument("--maintenant", default=None, help="ISO ; defaut = horloge")
    ap.add_argument("--sortie", default=None)
    ap.add_argument("--snapshot", default=str(_RACINE_DONNEES / "sandbox" / "tool_usage_role.json"))
    a = ap.parse_args(argv)

    sys.path.insert(0, str(ROOT / "app"))
    import forge_tool_scope as ts

    cat_raw = json.loads(Path(a.catalogue).read_text(encoding="utf-8"))
    rows = cat_raw.get("par_outil") if isinstance(cat_raw, dict) else cat_raw
    catalogue = {(r.get("outil") or r.get("name")) if isinstance(r, dict) else r for r in rows}
    tokens = {r["outil"]: r.get("tokens") for r in rows if isinstance(r, dict) and "outil" in r}
    now = datetime.fromisoformat(a.maintenant) if a.maintenant else datetime.now()
    since = (now - timedelta(days=a.jours)).strftime("%Y-%m-%dT%H:%M:%S")
    with open(a.audit, encoding="utf-8", errors="replace") as fh:
        usage = usage_par_agent(fh, since, catalogue)

    def scope_base(agent: str):
        # scope de role SANS la regle d'usage : on mesure ce qui disparaitrait
        sc = ts.role_scope_for(agent, base_only=True)
        return sc

    rep = regressions(usage, scope_base, a.min_calls)
    for agent, r in rep.items():
        sc = ts.role_scope_for(agent, base_only=True)
        r["visibles"] = sorted(sc & catalogue) if sc else None
        r["tokens_visibles"] = (sum(tokens.get(t) or 0 for t in sc if t in catalogue) if sc else None)
        r["groupe"] = (ts._ROLE_CACHE.get(agent, {}) or {}).get("groupe")
        r["methode"] = ts.methode_du_role(agent)
    meta = {"genere": now.strftime("%Y-%m-%dT%H:%M:%S"), "depuis": since, "jours": a.jours,
            "min_calls": a.min_calls, "audit": a.audit, "n_catalogue": len(catalogue)}
    if a.sortie:
        Path(a.sortie).write_text(json.dumps({"meta": meta, "agents": rep}, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    if a.snapshot:
        Path(a.snapshot).write_text(json.dumps({**meta, "usage": usage}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    print(json.dumps({"meta": meta, "n_agents": len(rep)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
