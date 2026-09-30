#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quels endpoints savent VRAIMENT appeler un outil ?

Le profilage attribuait `tool_call` sur `supported_parameters`, c'est-a-dire sur
une DECLARATION du catalogue. Or trois comportements se cachent derriere le
meme champ, et seul le premier merite le role :

  APPELLE   le modele rend un `tool_calls` nomme, avec des arguments JSON
            valides -> il sait orchestrer ;
  IGNORE    il accepte le parametre et repond en TEXTE, sans jamais appeler ->
            le role lui donnerait un orchestrateur qui bavarde ;
  REFUSE    il rejette la requete (400) -> le champ etait decoratif.

La distinction est tout le sujet : un modele qui ignore l'outil ne rougit
nulle part, il rend juste une phrase. Cable en orchestration, il ferait echouer
la chaine en silence — exactement le motif des faux-verts payes le 2026-08-18.

On envoie donc un outil reel et un prompt qui n'a pas d'autre reponse
raisonnable que de l'appeler, puis on VERIFIE le nom de la fonction et le JSON
de ses arguments.

    run action=run_job script=tools/forge_tool_call_probe.py online=true

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `fusionner` — Les nouvelles mesures REMPLACENT celles du meme (fournisseur, modele) ; les autres restent.
"""
from __future__ import annotations

__FORGE_COLOR__ = "metabolisme/provider : quels endpoints savent vraiment appeler un outil"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.tools.forge_endpoint_commun import catalogue, plus_petits, requete  # noqa: E402

SORTIE = ROOT / "sandbox" / "tool_call_probe.json"
TIMEOUT = 45
PAR_FOURNISSEUR = 3
ESPACEMENT_S = 2.0

SURFACES = [
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    ("lmstudio", "LMSTUDIO_TOKEN", "http://127.0.0.1:1234/v1"),
    ("ollama", "", "http://127.0.0.1:11434/v1"),
]

# La liste des modeles ecartes vit dans forge_endpoint_commun (socle partage).

# Un outil dont l'appel est la SEULE reponse raisonnable : le modele ne peut pas
# connaitre un numero de commande, il doit demander l'outil.
OUTIL = {
    "type": "function",
    "function": {
        "name": "etat_commande",
        "description": "Donne l'etat d'expedition d'une commande a partir de son numero.",
        "parameters": {
            "type": "object",
            "properties": {
                "numero": {"type": "string", "description": "Numero de commande, ex. CMD-4711"},
            },
            "required": ["numero"],
        },
    },
}
DEMANDE = "Ou en est la commande CMD-4711 ? Utilise l'outil disponible."


# `requete`, `catalogue` et le tri par taille viennent du socle commun : ils
# etaient identiques dans quatre sondes, et le cliquet de clones l'a vu.


def interroger(base: str, cle: str, modele: str) -> dict:
    """APPELLE / IGNORE / REFUSE / NON_MESURE, avec la preuve lue dans la reponse."""
    charge = json.dumps({
        "model": modele,
        "messages": [{"role": "user", "content": DEMANDE}],
        "tools": [OUTIL],
        "tool_choice": "auto",
        "max_tokens": 160,
    }).encode("utf-8")
    try:
        with urllib.request.urlopen(requete(f"{base}/chat/completions", cle, charge),
                                    timeout=TIMEOUT) as r:
            corps = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(300).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            detail = exc.reason or ""
        # 429 (limite de debit) et 5xx (panne du fournisseur) ne disent RIEN de la capacite
        # d'appeler un outil. MESURE 2026-09-25 : 4 modeles Mistral classes REFUSE sur un
        # « Rate limit exceeded » -- inconnu n'est pas non.
        if exc.code == 429 or exc.code >= 500:
            return {"etat": "NON_MESURE", "motif": f"HTTP {exc.code} (debit/panne) — {detail[:100]}"}
        return {"etat": "REFUSE", "motif": f"HTTP {exc.code} — {detail[:120]}"}
    except Exception as exc:  # noqa: BLE001
        return {"etat": "NON_MESURE", "motif": type(exc).__name__}

    message = ((corps.get("choices") or [{}])[0].get("message") or {})
    appels = message.get("tool_calls") or []
    if not appels:
        texte = (message.get("content") or "").strip()
        return {"etat": "IGNORE",
                "motif": f"a repondu en texte : {texte[:70]!r}" if texte else "ni outil ni texte"}

    fonction = (appels[0].get("function") or {})
    nom = fonction.get("name")
    if nom != OUTIL["function"]["name"]:
        return {"etat": "IGNORE", "motif": f"a appele '{nom}', pas l'outil fourni"}
    brut = fonction.get("arguments")
    try:
        args = json.loads(brut) if isinstance(brut, str) else (brut or {})
    except ValueError:
        return {"etat": "IGNORE", "motif": f"arguments non JSON : {str(brut)[:60]!r}"}
    if "numero" not in args:
        return {"etat": "IGNORE", "motif": f"argument requis absent : {args}"}
    return {"etat": "APPELLE", "motif": f"numero={args.get('numero')!r}"}


def _cle(nom_cle: str) -> str:
    """Cle du fournisseur (coffre d'abord) ; '' pour une surface locale sans cle."""
    if not nom_cle:
        return ""
    from nokido_agent.app.forge_secrets import get_secret

    return get_secret(nom_cle) or ""


def fusionner(anciens: list[dict], nouveaux: list[dict]) -> list[dict]:
    """Les nouvelles mesures REMPLACENT celles du meme (fournisseur, modele) ; les autres restent.

    Une mesure CIBLEE (--modeles) ne doit pas effacer le reste de la liste blanche que la
    passerelle lit dans ce rapport.
    """
    remesures = {(r.get("fournisseur"), r.get("modele")) for r in nouveaux}
    return [r for r in anciens if (r.get("fournisseur"), r.get("modele")) not in remesures] + nouveaux


def _mesurer_designes(designes: str) -> list[dict]:
    """`fournisseur/modele,...` : les modeles FORTS, que le tri par taille n'atteint jamais.

    MESURE 2026-09-25 : opencode via la passerelle -> Groq gratuit « TPM Limit 8000, Requested
    25631 » ; les seuls modeles prouves APPELLE etaient les petits. Un fournisseur inconnu est
    SAUTE et DIT, jamais devine.
    """
    import time

    surfaces = {nom: (env_key, base) for nom, env_key, base in SURFACES}
    resultats = []
    dernier_appel: dict[str, float] = {}
    for demande in (d.strip() for d in designes.split(",")):
        fournisseur, _, modele = demande.partition("/")
        if not modele or fournisseur not in surfaces:
            print(f"  {demande[:50]:52} SAUTE : fournisseur hors surfaces ({', '.join(surfaces)})")
            continue
        env_key, base = surfaces[fournisseur]
        # Offres gratuites a 1 requete/s (Mistral) : espacer les appels d'un meme fournisseur.
        attente = ESPACEMENT_S - (time.monotonic() - dernier_appel.get(fournisseur, -ESPACEMENT_S))
        if attente > 0:
            time.sleep(attente)
        dernier_appel[fournisseur] = time.monotonic()
        fiche = interroger(base, _cle(env_key), modele)
        fiche.update(fournisseur=fournisseur, modele=modele, annonce=None)
        print(f"  {demande[:50]:52} {fiche['etat']:11} {fiche['motif'][:60]}")
        resultats.append(fiche)
    return resultats


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Quels endpoints savent VRAIMENT appeler un outil ?")
    ap.add_argument("--modeles", default="",
                    help="fournisseur/modele,... : mesure CEUX-LA et fusionne au rapport existant")
    a = ap.parse_args(argv)
    if a.modeles:
        nouveaux = _mesurer_designes(a.modeles)
        anciens = []
        if SORTIE.exists():
            anciens = json.loads(SORTIE.read_text(encoding="utf-8")).get("resultats") or []
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps({"resultats": fusionner(anciens, nouveaux)},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{sum(r['etat'] == 'APPELLE' for r in nouveaux)}/{len(nouveaux)} designe(s) "
              f"appellent un outil -- fusionne(s) dans {SORTIE.name}")
        return 0

    resultats = []
    for etiquette, env_key, base in SURFACES:
        cle = _cle(env_key)
        _code, modeles, _entetes = catalogue(base, cle)
        if not modeles:
            print(f"\n=== {etiquette} — catalogue muet, NON MESURE")
            continue
        choisis = plus_petits(modeles, PAR_FOURNISSEUR)
        print(f"\n=== {etiquette}")
        for meta in choisis:
            modele = str(meta.get("id"))
            fiche = interroger(base, cle, modele)
            annonce = "tools" in (meta.get("supported_parameters") or [])
            fiche.update(fournisseur=etiquette, modele=modele, annonce=annonce)
            ecart = ""
            if annonce and fiche["etat"] != "APPELLE":
                ecart = "  <-- ANNONCE mais n'appelle pas"
            if not annonce and fiche["etat"] == "APPELLE":
                ecart = "  <-- appelle SANS l'annoncer"
            print(f"  {modele[:40]:42} annonce={str(annonce):5} {fiche['etat']:11} "
                  f"{fiche['motif'][:60]}{ecart}")
            resultats.append(fiche)

    capables = [r for r in resultats if r["etat"] == "APPELLE"]
    print(f"\n{len(capables)}/{len(resultats)} endpoint(s) appellent REELLEMENT un outil")
    for r in capables:
        print(f"  {r['fournisseur']}:{r['modele']}")
    menteurs = [r for r in resultats if r["annonce"] and r["etat"] != "APPELLE"]
    if menteurs:
        print(f"\n{len(menteurs)} annoncent `tools` sans l'honorer — les cabler en "
              f"orchestration ferait echouer la chaine EN SILENCE :")
        for r in menteurs:
            print(f"  {r['fournisseur']}:{r['modele']} — {r['etat']}")
    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps({"resultats": resultats}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print(f"detail : {SORTIE.relative_to(ROOT)}")
    except OSError as exc:
        print(f"(rapport non ecrit : {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
