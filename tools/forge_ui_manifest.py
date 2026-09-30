#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_ui_manifest.py — le MANIFEST vivant de l'interface (keystone).

Premiere brique de l'architecture « UI qui se deduit du corps » (owner + ChatGPT,
2026-08-15). Le corps ne demande pas a l'UI quoi afficher : l'UI demande au corps
QUELS ORGANES existent, QUELLES CAPACITES ils portent, QUEL est leur ETAT, et
QUELLE NOUVEAUTE vient d'apparaitre. Ce module repond -- un UI Manifest que le
dashboard, le SSE et le futur homeostat UI consomment. web_hub redevient
l'epiderme, pas le cerveau de l'interface.

REGLE NON NEGOCIABLE (ChatGPT) : une capacite se DECLARE (registre-contrat
ci-dessous), JAMAIS deduite d'un nom de fichier. Un organe sans capacite declaree
reste INVISIBLE a l'interface. On evite ainsi « j'ajoute forge_xxx.py -> 6 boutons
apparaissent ». Ajouter une surface = ajouter une entree DECLAREE ici.

ETAT reel, jamais un faux « live » :
  live     : backend declare ET repond (port/health OK)
  dormant  : backend declare mais NE REPOND PAS (eteint, non lance)
  absent   : backend non installe (ex. depot prive separe)
  internal : organe in-process (physiologie, regulation) — toujours la
  inconnu  : sonde impossible

Usage :
    forge_ui_manifest.py            # affiche le manifest lisible
    forge_ui_manifest.py --json     # le manifest machine (ce que l'UI consomme)
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SEEN = os.path.join(ROOT, "sandbox", "ui_organ_seen.json")
_LF_ROOT = os.path.dirname(ROOT)  # parent du depot Nokido (siblings prives)

# ── 1. REGISTRE-CONTRAT DES SURFACES ──────────────────────────────────────────
# Chaque entree DECLARE : l'organe, ses capacites, comment sonder son backend,
# les actions offertes, et une importance de base. C'est le SEUL endroit ou une
# surface devient visible. probe = (kind, cible) :
#   port    : TCP connect sur 127.0.0.1:<cible>
#   path    : le chemin (relatif a _LF_ROOT) existe (depot/outillage installe)
#   internal: in-process, toujours live
SURFACES = {
    "dashboard": {"organe": "Interface", "capabilities": ["ui.dashboard"],
                  "probe": ("port", 7400), "actions": ["open"], "importance": 0.5},
    "physiologie": {"organe": "SN vegetatif", "capabilities": ["physiology.read"],
                    "probe": ("internal", None), "actions": ["read_constants"],
                    "importance": 0.7},
    "regulation": {"organe": "SN vegetatif",
                   "capabilities": ["regulation.learn", "regulation.propose"],
                   "probe": ("internal", None),
                   "actions": ["inspect_ledger", "propose"], "importance": 0.75},
    # 7474, PAS 7420 : mesure du 2026-08-18, le graph_explorer ECOUTE sur 7474
    # (app/web_hub/app.py:1035 le sait, avec le commentaire « graph_explorer
    # root »). Le manifest sondait 7420, ferme, et declarait donc « dormant » une
    # capacite VIVANTE — un faux negatif capacitif, precisement ce que ce
    # manifest est cense supprimer. Verifie par l'ecoute reelle, pas par la
    # declaration : 7474 OUVERT, 7420 ferme.
    "graph": {"organe": "Graph/Connaissances", "capabilities": ["graph.explore"],
              "probe": ("port", 7474), "actions": ["open"], "importance": 0.5},
    # Le TUI est une application **Textual** (terminal), PAS un service reseau :
    # mesure du 2026-08-18, `app/laforge_tui/laforge_tui.py` (10 Ko) ne contient
    # ni listen, ni bind, ni uvicorn, ni la moindre trace de 7440. Le sonder par
    # port le condamnait a « dormant » a perpetuite — et aucun service tui n'est
    # d'ailleurs declare au superviseur (54 services verifies). Sa disponibilite
    # se mesure a la PRESENCE de son module ; il se lance en console, pas par
    # une URL — d'ou l'action « lancer » et non « open ».
    # ⚠️ `path` resout depuis _LF_ROOT = le SUPER-DEPOT (« Script python IA »),
    # pas depuis Nokido : le prefixe est obligatoire, faute de quoi la surface
    # ressort « absent » alors que le module est la — faux negatif introduit puis
    # corrige le 2026-08-18.
    "tui": {"organe": "Sens/Toucher", "capabilities": ["tui.shell"],
            "probe": ("path", "Nokido/app/laforge_tui"), "actions": ["lancer"], "importance": 0.4},
    # ctf / recon : RETIRES du coeur le 2026-09-01 (domaine du depot separe
    # `laforge-redteam`). Un manifeste ne declare que ce que le coeur porte.
    "netcfg": {"organe": "Sens/Toucher",
               "capabilities": ["netcfg.inventory", "netcfg.topology", "netcfg.drift"],
               "probe": ("port", 7500), "actions": ["inventory", "topology"],
               "importance": 0.5},
}

# Surface déportée (lab borné) : déclarée au manifeste UI SEULEMENT si le lab est actif.
# Hors lab, aucune carte offensive n'est rendue dans l'interface. Gel, pas suppression.
import os as _os
if _os.environ.get("NOKIDO_REDTEAM_INTENTS_JSON"):
    SURFACES["redteam"] = {"organe": "Redteam", "capabilities": ["redteam.offensive"],
                           "probe": ("path", "laforge-redteam"), "actions": ["enable"],
                           "importance": 0.3}


def _port_ouvert(port: int) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", int(port)), 0.6)
        s.close()
        return True
    except Exception:  # noqa: BLE001 - port ferme / injoignable
        return False


# SANTE APPLICATIVE — endpoint qui prouve que l'APPLICATION repond, et pas
# seulement que le port accepte une connexion.
#
# Il n'existe AUCUN endpoint universel, c'est tout le probleme. Mesure du
# 2026-08-18 sur les services vivants :
#     :7400 /health=200   /ping=401  /=401
#     :7474 /health=401   /ping=200  /=200
#     :7500 /health=404   /ping=404  /=200
#     :8766 /health=200
# Sonder « /health » partout declarerait donc graph et netcfg MORTS alors qu'ils
# repondent. Cette table existait deja — `_HEALTH_HINTS`, enfermee dans la
# fonction /status de app/web_hub/app.py, donc invisible d'ici : le probleme
# n'etait pas deux verites rivales, mais une connaissance NON PARTAGEE.
# ⚠️ Elle s'y trompait sur netcfg (/health -> 404) : valeurs ci-dessous MESUREES.
SANTE = {
    7400: "/health",
    7401: "/health",
    7410: "/ping",   # recon_silo : /ping, pas /health
    7430: "/ping",   # ctf_web : /ping, pas /health
    7440: "/",
    7474: "/",       # graph_explorer : racine
    7500: "/",       # netcfg : mesure 404 sur /health, 200 sur /
    8766: "/health",
}


def _app_repond(port: int, timeout: float = 2.0) -> bool:
    """L'APPLICATION derriere le port repond-elle ? (transport != application)

    Un 401 compte comme VIVANT : le service a compris la requete et l'a refusee,
    donc il tourne. Seuls l'absence de reponse et le 5xx disent qu'il est casse.
    """
    import urllib.error
    import urllib.request

    chemin = SANTE.get(int(port), "/")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:%s%s" % (port, chemin), timeout=timeout)
        return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500      # 401/403/404 = l'app parle, donc elle vit
    except Exception:            # muet-ok : pas de reponse = applicatif muet
        return False


def _etat(surface: dict) -> str:
    kind, cible = surface.get("probe", (None, None))
    if kind == "internal":
        return "internal"
    if kind == "port":
        if not _port_ouvert(cible):
            return "dormant"
        # Port ouvert ne prouve QUE le transport. Un service peut tenir son port
        # tout en etant fige, mal configure, ou remplace par un autre process.
        return "live" if _app_repond(cible) else "degraded"
    if kind == "path":
        return "live" if os.path.isdir(os.path.join(_LF_ROOT, str(cible))) else "absent"
    return "inconnu"


def _charger_seen() -> dict:
    try:
        with open(_SEEN, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def _novelty(nom: str, seen: dict, maintenant: float) -> tuple[float, dict]:
    """Nouveaute 0..1, decroissante sur ~24 h depuis la 1re apparition. Un organe
    neuf trone dans « NOUVEAUTES » quelques cycles, puis devient un element normal
    du corps -- analogue au mecanisme d'apprentissage."""
    vu = seen.get(nom)
    if vu is None:
        seen[nom] = maintenant
        return 1.0, seen
    age_h = max(0.0, (maintenant - float(vu)) / 3600.0)
    return round(max(0.0, 1.0 - age_h / 24.0), 3), seen


# Cache du dernier manifest. Mesure du 2026-08-18 : un appel coute **1,83 s**,
# constant — trois surfaces dormantes (ctf, recon, tui) dont chaque sonde attend
# l'expiration du connect(). Or `/organs` appelait ce manifest A CHAQUE RENDU :
# l'interface faisait donc patienter l'utilisateur le temps de sonder le reseau,
# et ecrivait un fichier au passage. Une UI ne doit jamais attendre une sonde.
# TTL court : assez pour absorber une rafale de rendus, assez bref pour qu'un
# service qui remonte apparaisse dans la foulee.
_TTL_CACHE_S = float(os.environ.get("NOKIDO_UI_MANIFEST_TTL_S", "10"))
_CACHE: dict = {"t": 0.0, "valeur": None}


def manifest(persist: bool = True, frais: bool = False) -> dict:
    """Le manifest vivant. `persist` ecrit le registre des 1res apparitions
    (pour la nouveaute) ; False en test/CI pour ne rien ecrire.

    `frais=True` force une mesure reelle en ignorant le cache (supervision,
    diagnostic). Le rendu UI, lui, doit se contenter du cache.
    """
    maintenant = time.time()
    if not frais and _CACHE["valeur"] is not None and (maintenant - _CACHE["t"]) < _TTL_CACHE_S:
        return _CACHE["valeur"]
    seen = _charger_seen()
    surfaces = []
    for nom, s in SURFACES.items():
        etat = _etat(s)
        nouveaute, seen = _novelty(nom, seen, maintenant)
        # importance effective : une surface DORMANT/ABSENT compte moins (rien a
        # montrer), une NOUVEAUTE remonte. L'UI homeostat s'en servira pour placer.
        imp = s.get("importance", 0.5)
        if etat in ("dormant", "absent"):
            imp *= 0.4
        imp = round(min(1.0, imp + 0.3 * nouveaute), 3)
        # URL REELLE, jamais supposee : uniquement si la surface est sondee par
        # port ET que ce port ecoute. Sans cela l'UI affichait des actions
        # (« open », « scan », « topology ») rendues en <span> decoratif, sans
        # aucune destination — une tuile promettait ce qu'elle ne pouvait pas
        # tenir. Une action sans destination verifiee ne doit pas ressembler a
        # un bouton.
        probe = s.get("probe") or ()
        url = None
        if len(probe) > 1 and probe[0] == "port" and probe[1] and etat == "live":
            url = "http://127.0.0.1:%s" % probe[1]
        surfaces.append({
            "surface": nom,
            "organe": s.get("organe"),
            "capabilities": s.get("capabilities", []),
            "etat": etat,
            "actions": s.get("actions", []),
            "url": url,
            "importance": imp,
            "nouveaute": nouveaute,
        })
    surfaces.sort(key=lambda x: x["importance"], reverse=True)
    if persist:
        try:
            os.makedirs(os.path.dirname(_SEEN), exist_ok=True)
            with open(_SEEN, "w", encoding="utf-8") as fh:
                json.dump(seen, fh, ensure_ascii=False, indent=1, sort_keys=True)
        except OSError:
            pass
    vivants = sum(1 for s in surfaces if s["etat"] in ("live", "internal"))
    resultat = {"genere_le": maintenant, "surfaces": surfaces,
                "resume": {"total": len(surfaces), "vivants": vivants,
                           "dormants": sum(1 for s in surfaces if s["etat"] == "dormant"),
                           "absents": sum(1 for s in surfaces if s["etat"] == "absent")}}
    _CACHE["t"] = maintenant
    _CACHE["valeur"] = resultat
    return resultat


def main() -> int:
    ap = argparse.ArgumentParser(description="Manifest vivant de l'interface")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-persist", action="store_true")
    a = ap.parse_args()

    m = manifest(persist=not a.no_persist)
    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=2))
        return 0
    r = m["resume"]
    print(f"[ui-manifest] {r['total']} surfaces — {r['vivants']} vivantes, "
          f"{r['dormants']} dormantes, {r['absents']} absentes")
    for s in m["surfaces"]:
        etoile = "*" if s["nouveaute"] >= 0.5 else " "
        print(f"  {etoile}[{s['etat']:<8}] {s['surface']:<12} imp={s['importance']:<5} "
              f"{'|'.join(s['capabilities'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
