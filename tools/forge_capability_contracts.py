#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_capability_contracts.py - contrat par capacite de la surface Nokido.

TROIS NIVEAUX DE PREUVE, jamais confondus :

  1. TRANSPORT  - le port accepte une connexion.
                  Ne prouve RIEN sur le service : un process fige tient son port.
  2. APPLICATIF - un endpoint HTTP repond (< 500). Un 401/403/404 compte comme
                  VIVANT : le service a compris la requete et l'a refusee.
  3. CAPACITE   - la FONCTION rend son service. C'est le seul niveau qui parle
                  du metier : ollama peut repondre tout en n'ayant AUCUN modele
                  charge ; qdrant peut repondre sans collection.

Pourquoi ce fichier (2026-08-18). Le manifest UI declarait 9 surfaces ; la mesure
en a trouve **19 atteignables**. Dix services vivants n'etaient declares nulle
part — ingress Anthropic/Gemini, proxy OpenAI, Qdrant et son sidecar, dispatcher
Go, MCP netcfg, bus Deno... Une capacite non declaree est une capacite qu'on ne
peut ni surveiller, ni reparer, ni retrouver apres une regression.

⚠️ AUCUN ENDPOINT DE SANTE UNIVERSEL. Mesure du 2026-08-18 : `/health` pour la
plupart, mais `/ping` pour graph, `/` pour netcfg, `/collections` pour qdrant,
`/api/tags` pour ollama, `/supervisor/status` pour le superviseur. Sonder
`/health` partout declarerait morts quatre services qui repondent. Chaque valeur
ci-dessous est MESUREE, aucune n'est supposee.

  LAFORGE_PYTHON tools/forge_capability_contracts.py
  LAFORGE_PYTHON tools/forge_capability_contracts.py --json
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "observabilite/audit : contrat par capacite, trois niveaux de preuve"  # organe declare le 2026-09-06 (audit de raccordement)

import argparse
import json
import socket

from nokido_agent.tools.forge_archeo_socle import port_ouvert as _port_ouvert
import sys
import urllib.error
import urllib.request

# (port, sante, capacite, sonde_capacite) - sonde_capacite : (chemin, cle_json)
# La cle est cherchee dans la reponse ; sa PRESENCE et sa non-vacuite prouvent
# que la fonction rend son service. None = pas de sonde fonctionnelle connue :
# on le DIT plutot que de faire passer un applicatif vivant pour une capacite.
CONTRATS = {
    "hub.mcp":            dict(port=8766, organe="SNC",            sante="/health",            cap=("/health", "status")),
    "supervision":        dict(port=8765, organe="SN vegetatif",   sante="/supervisor/status", cap=("/supervisor/status", "services")),
    "ui.dashboard":       dict(port=7400, organe="Interface",      sante="/health",            cap=None),
    "ui.webhub_deno":     dict(port=7401, organe="Interface",      sante="/health",            cap=None),
    "graph.explore":      dict(port=7474, organe="Graph",          sante="/ping",              cap=None),
    "netcfg.ui":          dict(port=7500, organe="Sens/Toucher",   sante="/",                  cap=None),
    "netcfg.mcp":         dict(port=8768, organe="Sens/Toucher",   sante="/health",            cap=None),
    "llm.inference":      dict(port=11434, organe="Metabolisme",   sante="/api/tags",          cap=("/api/tags", "models")),
    "llm.local_server":   dict(port=8091, organe="Metabolisme",    sante="/health",            cap=("/api/tags", "models")),
    "vector.qdrant":      dict(port=6333, organe="Memoire",        sante="/collections",       cap=("/collections", "result")),
    "vector.sidecar":     dict(port=8098, organe="Memoire",        sante="/health",            cap=None),
    "egress.web":         dict(port=7779, organe="Digestif/Sens",  sante="/health",            cap=None),
    "ingress.anthropic":  dict(port=7776, organe="Metabolisme",    sante="/health",            cap=None),
    "ingress.gemini":     dict(port=7778, organe="Metabolisme",    sante="/health",            cap=None),
    "proxy.openai":       dict(port=7777, organe="Metabolisme",    sante="/health",            cap=None),
    "bus.deno":           dict(port=8000, organe="SNC",            sante="/health",            cap=None),
    "organs.deno":        dict(port=8767, organe="Observabilite",  sante="/health",            cap=None),
    "hub.mcp_deno":       dict(port=8769, organe="SNC",            sante="/health",            cap=None),
    "dispatch.go":        dict(port=8779, organe="Locomoteur",     sante="/health",            cap=("/health", "ok")),
    # ctf.solve / recon.scan : contrats RETIRES du coeur le 2026-09-01. Leur
    # domaine vit dans le depot separe `laforge-redteam` ; un contrat garde ici
    # ferait croire que le coeur expose la capacite.
    # `tui.shell` N'EST PAS une capacite reseau et n'a donc pas sa place ici :
    # `app/laforge_tui/laforge_tui.py` est une application Textual (terminal),
    # sans listen ni bind, et aucun service tui n'est declare au superviseur.
    # La sonder par port produisait un « dormant » perpetuel — un faux negatif
    # structurel, impossible a reparer puisqu'il n'y a rien a demarrer.
    # Sa disponibilite se mesure a la presence de son module (cf.
    # forge_ui_manifest, sonde `path`).
}


# _port_ouvert vient du socle (import ci-dessus) : la sonde etait recopiee ici
# et dans forge_ui_coherence, a l'octet pres.


def _http(port: int, chemin: str, timeout: float = 2.5):
    """Rend (code, corps) ; code None = aucune reponse."""
    try:
        r = urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, chemin), timeout=timeout)
        return r.status, r.read(4000)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:  # muet-ok : pas de reponse = applicatif muet
        return None, b""


def verifier_une(nom: str, c: dict) -> dict:
    port = c["port"]
    r = {"capacite": nom, "organe": c["organe"], "port": port}

    if not _port_ouvert(port):
        r.update(transport=False, applicatif=None, capacite_ok=None, etat="dormant")
        return r
    r["transport"] = True

    code, _ = _http(port, c["sante"])
    r["applicatif"] = bool(code and code < 500)
    if not r["applicatif"]:
        r.update(capacite_ok=None, etat="degraded")
        return r

    sonde = c.get("cap")
    if not sonde:
        # Honnetete : applicatif vivant ne prouve pas la fonction metier.
        r.update(capacite_ok=None, etat="live")
        return r

    chemin, cle = sonde
    code, corps = _http(port, chemin)
    ok = False
    if code and code < 400 and corps:
        try:
            data = json.loads(corps.decode("utf-8", "replace"))
            val = data.get(cle) if isinstance(data, dict) else None
            ok = bool(val)
        except ValueError:
            ok = cle.encode() in corps
    r["capacite_ok"] = ok
    r["etat"] = "live" if ok else "degraded"
    return r


def verifier() -> dict:
    res = [verifier_une(n, c) for n, c in sorted(CONTRATS.items())]
    compte = {}
    for x in res:
        compte[x["etat"]] = compte.get(x["etat"], 0) + 1
    return {"contrats": res, "resume": compte}


def main() -> int:
    ap = argparse.ArgumentParser(description="Contrat par capacite de la surface Nokido.")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = verifier()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0 if not r["resume"].get("degraded") else 1

    print("%-20s %-16s %-6s %-9s %-10s %s" % ("capacite", "organe", "port", "transport", "applicatif", "capacite"))
    for x in r["contrats"]:
        def m(v):
            return "-" if v is None else ("oui" if v else "NON")
        print("%-20s %-16s %-6s %-9s %-10s %-8s %s"
              % (x["capacite"], x["organe"], x["port"], m(x.get("transport")),
                 m(x.get("applicatif")), m(x.get("capacite_ok")), x["etat"]))
    print("\nresume :", r["resume"])
    return 0 if not r["resume"].get("degraded") else 1


if __name__ == "__main__":
    sys.exit(main())
