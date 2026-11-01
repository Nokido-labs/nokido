"""forge_identites_audit.py -- inventaire MESURE des identites par canal et provenance (chantier identites, phase 1).

__FORGE_COLOR__ = "immunite/identite_audit : inventaire des identites (registre, coffre, journal MCP)"

Owner 22/10 : « chaque canal et chaque provenance doivent avoir leur identite et donc leur token, conforme RFC,
observabilite parfaite ». Defauts mesures le meme jour : boite agt_claude partagee Desktop/CLI (3 messages perdus),
CLAUDE_HEADLESS jamais authentifie (401 a chaque connexion, mailbox CLAUDE partagee).

Croise trois sources :
  - le registre `config/agent_identities.json` (ring, boite, canal declares) ;
  - le coffre : presence du jeton FORGE_TOKEN_<IDENTITE>, en BOOLEEN -- jamais une valeur ; illisible = INCONNU ;
  - le journal `logs/mcp_audit.log` : `ts | NetworkChannel.<CANAL>:<outil> | {... "agent": X, "ring": N ...} | STATUT`.
Rend : boites partagees, identites vues sur plusieurs canaux (provenances melangees sous un meme nom), identites
jamais authentifiees, sans jeton au coffre, vues hors registre, rings observes qui contredisent le registre, et le
nombre de lignes illisibles (comptees, pas ignorees). OBSERVE seulement : aucun blocage (observer avant d'enforcer).

Usage : LAFORGE_PYTHON tools/forge_identites_audit.py [--registre R] [--journal J] [--sans-coffre] [--sortie r.json]
Le coffre est lu avec les droits du compte qui lance : un autre compte peut voir autre chose, le rapport le dit.
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
_AGENT = re.compile(r'"agent":\s*"([^"]+)"')
_RING = re.compile(r'"ring":\s*"?(-?\d+)')


def _ligne(texte: str):
    parts = [p.strip() for p in texte.split("|")]
    if len(parts) < 4 or not parts[1].startswith("NetworkChannel."):
        return None
    m = _AGENT.search(texte)
    if not m:
        return None
    canal = parts[1][len("NetworkChannel."):].split(":", 1)[0]
    r = _RING.search(texte)
    refus = "UNAUTHORIZED" in parts[1] or parts[-1].startswith("ERR:401")
    return {"agent": m.group(1).upper(), "canal": canal, "ring": int(r.group(1)) if r else None,
            "statut": parts[-1].split()[0] if parts[-1] else "", "refus": refus}


def auditer(registre: dict, lignes, coffre=None) -> dict:
    """`coffre(nom)` -> True (jeton present), False (absent), None (illisible) ; coffre None = non lu."""
    agents = {n.upper(): (m if isinstance(m, dict) else {}) for n, m in ((registre or {}).get("agents") or {}).items()}
    par = defaultdict(lambda: {"ok": 0, "refus_401": 0, "autres": 0, "canaux": set(), "rings_ok": set()})
    illisibles = 0
    for texte in lignes:
        e = _ligne(texte)
        if e is None:
            if texte.strip():
                illisibles += 1
            continue
        s = par[e["agent"]]
        s["canaux"].add(e["canal"])
        if e["refus"]:
            s["refus_401"] += 1
        elif e["statut"] == "OK":
            s["ok"] += 1
            if e["ring"] is not None:
                s["rings_ok"].add(e["ring"])
        else:
            s["autres"] += 1
    boites = defaultdict(list)
    for n, m in agents.items():
        if m.get("mailbox"):
            boites[str(m["mailbox"]).upper()].append(n)
    sans, illisible = [], []
    if coffre is not None:
        for n, m in sorted(agents.items()):
            if m.get("jeton_direct") is False:
                continue
            v = coffre(n)
            if v is None:
                illisible.append(n)
            elif not v:
                sans.append(n)
    rings = {}
    for n, s in par.items():
        attendu = agents.get(n, {}).get("ring")
        obs = sorted(r for r in s["rings_ok"] if r != attendu)
        if n in agents and attendu is not None and obs:
            rings[n] = {"registre": attendu, "observes": obs}
    return {
        "coffre": "LU" if coffre is not None else "NON_LU",
        "lignes_illisibles": illisibles,
        "boites_partagees": {b: sorted(ns) for b, ns in sorted(boites.items()) if len(ns) > 1},
        "identites_multi_canaux": {n: sorted(s["canaux"]) for n, s in sorted(par.items()) if len(s["canaux"]) > 1},
        "jamais_authentifiees": sorted(n for n, s in par.items() if s["refus_401"] and not s["ok"]),
        "sans_jeton_au_coffre": sans,
        "jeton_illisible": illisible,
        "hors_registre": sorted(n for n in par if n not in agents),
        "rings_contredits": rings,
        "par_identite": {n: {"ok": s["ok"], "refus_401": s["refus_401"], "autres": s["autres"],
                             "canaux": sorted(s["canaux"])} for n, s in sorted(par.items())},
    }


def _coffre_reel(nom: str):
    try:
        if str(CODE) not in sys.path:
            sys.path.insert(0, str(CODE))
        from nokido_agent.app.forge_secrets import get_secret
        return bool(get_secret("FORGE_TOKEN_%s" % nom))
    except Exception:  # noqa: BLE001 -- illisible n'est pas absent : None
        return None


def _journal_defaut() -> Path:
    from nokido_agent.app.forge_db_path import racine_donnees
    return racine_donnees() / "logs" / "mcp_audit.log"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--registre", default=str(CODE / "config" / "agent_identities.json"))
    ap.add_argument("--journal", default=None)
    ap.add_argument("--sans-coffre", action="store_true", dest="sans_coffre")
    ap.add_argument("--sortie")
    a = ap.parse_args(argv)
    if str(CODE) not in sys.path:
        sys.path.insert(0, str(CODE))
    registre = json.loads(Path(a.registre).read_text(encoding="utf-8"))
    journal = Path(a.journal) if a.journal else _journal_defaut()
    with open(journal, encoding="utf-8", errors="replace") as f:
        r = auditer(registre, f, None if a.sans_coffre else _coffre_reel)
    r["compte"] = getpass.getuser()
    r["journal"] = str(journal)
    print("== identites (coffre %s, compte %s, %d ligne(s) illisible(s))"
          % (r["coffre"], r["compte"], r["lignes_illisibles"]))
    for cle in ("boites_partagees", "identites_multi_canaux", "jamais_authentifiees", "sans_jeton_au_coffre",
                "jeton_illisible", "hors_registre", "rings_contredits"):
        v = r[cle]
        print("   %-24s %3d  %s" % (cle, len(v), json.dumps(v, ensure_ascii=False)[:300]))
    if a.sortie:
        Path(a.sortie).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print("rapport : %s" % a.sortie)
    return 0


if __name__ == "__main__":
    sys.exit(main())
