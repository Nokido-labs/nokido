#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Combien de modeles sont JOIGNABLES en palier gratuit — et le rester.

Les catalogues bougent sans prevenir : en une journee on a vu GitHub Models
retire (410), `llama-3.3-70b-versatile` disparaitre de Groq, `gemini-2.5-pro`
devenir « no longer available to new users », les slugs `:free` d'OpenRouter
changer de forme. Cabler des noms de modeles a la main, c'est signer pour les
repayer tous les trimestres.

Ce module mesure trois choses DISTINCTES, qu'on confond tout le temps :

  DECLARE   le catalogue liste le modele                     (`GET /models`)
  GRATUIT   le fournisseur annonce un prix nul               (`pricing`, `:free`)
  JOIGNABLE une completion reelle a REPONDU                  (preuve)

Un modele declare n'est pas joignable ; un modele gratuit peut etre sature
(429) ; un modele joignable aujourd'hui peut disparaitre demain. Seule la
troisieme colonne est une preuve, et elle coute un appel — on l'echantillonne.

QUOTA : rapporte quand le fournisseur l'expose (OpenRouter `/key`, en-tetes
`x-ratelimit-*`), NON MESURE sinon. On ne devine pas un quota.

Sortie : `sandbox/free_tier_census.json`, horodate — deux passes comparees
disent ce qui a bouge chez qui.

    run action=run_job script=tools/forge_free_tier_census.py online=true
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ROOT d'abord : `nokido_agent` (lu pour les cles) se resout depuis la RACINE.
# Sans elle, le recenseur lance en job mourait en ModuleNotFoundError (2026-09-23).
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

SORTIE = ROOT / "sandbox" / "free_tier_census.json"
ECHANTILLON = 2        # completions reelles par fournisseur
TIMEOUT = 25

# (etiquette, cle, base OpenAI-compatible). La base sert AUSSI a completer.
SURFACES = [
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    ("cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1"),
    ("sambanova", "SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1"),
    ("deepinfra", "DEEPINFRA", "https://api.deepinfra.com/v1/openai"),
    ("nvidia", "NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1"),
    ("zai", "ZAI_API_KEY", "https://api.z.ai/api/paas/v4"),
    ("mammouth", "MAMMOUTH_API_TOKEN", "https://api.mammouth.ai/v1"),
    ("hf", "HF_TOKEN", "https://router.huggingface.co/v1"),
    ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com"),
    ("ollama", "", "http://127.0.0.1:11434/v1"),
    ("lmstudio", "LMSTUDIO_TOKEN", "http://127.0.0.1:1234/v1"),
    ("litellm", "", "http://127.0.0.1:4000/v1"),
]

_INADAPTES = ("embed", "bge-", "nomic", "whisper", "tts", "clip", "guard",
              "rerank", "moderation", "image", "vision", "moondream", "llava")


def _req(url: str, cle: str, charge: bytes | None = None, timeout: int = TIMEOUT):
    entetes = {"User-Agent": "nokido-census"}
    if cle:
        entetes["Authorization"] = f"Bearer {cle}"
    if charge is not None:
        entetes["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=charge, headers=entetes)


def catalogue(base: str, cle: str) -> tuple[int, list[dict], dict]:
    """(code, modeles bruts, en-tetes) — les en-tetes portent parfois le quota."""
    try:
        with urllib.request.urlopen(_req(f"{base}/models", cle), timeout=TIMEOUT) as r:
            brut = json.loads(r.read().decode("utf-8", errors="replace"))
            donnees = brut.get("data") if isinstance(brut, dict) else brut
            return r.status, [m for m in (donnees or []) if isinstance(m, dict)], dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, [], {}
    except Exception:  # noqa: BLE001 - reseau, DNS, port ferme
        return -1, [], {}


def est_gratuit(modele: dict, etiquette: str) -> bool | None:
    """True/False si le fournisseur l'annonce, None s'il ne dit rien.

    None n'est PAS False : beaucoup d'API ne publient aucun prix, et compter
    « non gratuit » ce qui n'est pas annonce donnerait un chiffre faux.
    """
    identifiant = str(modele.get("id") or "")
    if identifiant.endswith(":free"):
        return True
    prix = modele.get("pricing")
    if isinstance(prix, dict):
        try:
            return all(float(prix.get(champ, 0) or 0) == 0.0
                       for champ in ("prompt", "completion"))
        except (TypeError, ValueError):
            return None
    if etiquette in ("ollama", "lmstudio", "litellm"):
        return True            # local : aucun paiement possible
    return None


def _taille(identifiant: str) -> float:
    import re

    trouve = re.findall(r"(\d+(?:\.\d+)?)\s*b\b", identifiant.lower())
    return min((float(x) for x in trouve), default=999.0)


# Outil minimal de la sonde (exigence swarm/MCP, owner 16/10) : un modele qui refuse `tools` n'est pas utilisable par
# le swarm, meme gratuit. Les EN-TETES DE LIMITE se lisent sur la COMPLETION (Groq, Mistral), pas sur le catalogue.
_OUTIL_SONDE = [{"type": "function", "function": {"name": "nokido_ping", "description": "sonde de support des outils",
                                                  "parameters": {"type": "object", "properties": {}}}}]
_MARQUES_LIMITE = ("ratelimit", "retry-after", "x-trial")
PAUSE_S = 1.5   # entre deux appels au MEME fournisseur : le 429 Mistral du 16/10 venait probablement de la sonde


def _limites(entetes) -> dict:
    items = entetes.items() if hasattr(entetes, "items") else []
    return {str(k).lower(): v for k, v in items if any(m in str(k).lower() for m in _MARQUES_LIMITE)}


def _lire_reponse(corps: dict) -> tuple[bool, str]:
    choix = (corps.get("choices") or [{}])[0]
    message = choix.get("message") or {}
    if str(message.get("content") or "").strip():
        return True, ""
    # Vecu 16/10 : un modele de RAISONNEMENT depense les 8 tokens a reflechir -- `content` vide, mais le
    # fournisseur a REPONDU (openrouter/free, nemotron-3-super:free, gpt-oss lus « reponse vide » a tort).
    if str(message.get("reasoning") or message.get("reasoning_content") or "").strip():
        return True, "OK (raisonnement seul, budget de 8 tokens)"
    if choix.get("finish_reason") == "length":
        return True, "OK (coupe par le budget de 8 tokens)"
    return False, "reponse vide"


def _completer(base: str, cle: str, modele: str, outils: bool):
    charge = {"model": modele, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 8}
    if outils:
        charge["tools"] = _OUTIL_SONDE
    with urllib.request.urlopen(_req(f"{base}/chat/completions", cle, json.dumps(charge).encode("utf-8")),
                                timeout=TIMEOUT) as r:
        entetes = getattr(r, "headers", None) or {}
        return json.loads(r.read().decode("utf-8", errors="replace")), entetes


def sonder(base: str, cle: str, modele: str, outils: bool = False) -> dict:
    """Une completion reelle : joignable, motif, en-tetes de limite de la COMPLETION, et (outils=True) support de
    `tools` -- None si non teste, False si le modele refuse (400/404/422) puis re-sonde sans."""
    d = {"joignable": False, "motif": "", "limites": {}, "outils": None}
    refus_avec_outils = False
    if outils:
        try:
            corps, entetes = _completer(base, cle, modele, True)
            ok, motif = _lire_reponse(corps)
            d.update(joignable=ok, motif=motif, limites=_limites(entetes), outils=True)
            return d
        except urllib.error.HTTPError as exc:
            if exc.code not in (400, 404, 422):
                d.update(motif=f"HTTP {exc.code}", limites=_limites(exc.headers or {}))
                return d
            refus_avec_outils = True
        except Exception as exc:  # noqa: BLE001
            d["motif"] = type(exc).__name__
            return d
    try:
        corps, entetes = _completer(base, cle, modele, False)
        ok, motif = _lire_reponse(corps)
        d.update(joignable=ok, motif=motif, limites=_limites(entetes))
        # Le refus des outils n'est PROUVE que si l'appel SANS outils reussit (vecu 16/10 : un modele absent, 404 avec
        # et sans outils, etait affiche « outils REFUSES ») ; sinon il reste INDETERMINE (None).
        if refus_avec_outils:
            d["outils"] = False
    except urllib.error.HTTPError as exc:
        d.update(motif=f"HTTP {exc.code}", limites=_limites(exc.headers or {}))
    except Exception as exc:  # noqa: BLE001
        d["motif"] = type(exc).__name__
    return d


def joignable(base: str, cle: str, modele: str) -> tuple[bool, str]:
    d = sonder(base, cle, modele)
    return d["joignable"], d["motif"]


def quota(etiquette: str, cle: str, entetes: dict) -> str:
    """Ce que le fournisseur EXPOSE. Jamais une estimation."""
    for nom, valeur in entetes.items():
        if "ratelimit" in nom.lower() and "remaining" in nom.lower():
            return f"{nom}={valeur}"
    if etiquette == "openrouter" and cle:
        try:
            with urllib.request.urlopen(_req("https://openrouter.ai/api/v1/key", cle),
                                        timeout=TIMEOUT) as r:
                d = (json.loads(r.read().decode("utf-8", errors="replace")) or {}).get("data") or {}
                # Owner 16/10 : /key EXPOSE aussi le palier et le debit -- les dire, ou dire qu'ils manquent.
                palier = d.get("is_free_tier")
                rl = d.get("rate_limit") if isinstance(d.get("rate_limit"), dict) else None
                debit = (f"{rl.get('requests')}/{rl.get('interval')}" if rl and rl.get("requests") is not None
                         else "NON EXPOSE")
                return (f"usage={d.get('usage')} limite={d.get('limit')} "
                        f"restant={d.get('limit_remaining')} "
                        f"palier_gratuit={'INCONNU' if palier is None else palier} debit={debit}")
        except Exception:  # noqa: BLE001 - endpoint absent ou refuse
            return "NON MESURE (endpoint /key muet)"
    return "NON MESURE (le fournisseur ne l'expose pas)"


def comparer(precedent: dict, courant: list[dict]) -> list[str]:
    """Ce qui a BOUGE depuis la derniere passe — le coeur de l'adaptation.

    Un catalogue qui perd un modele ne previent personne : c'est l'appel suivant
    qui echoue, des semaines plus tard, et on accuse alors la cle. Comparer deux
    passes datees transforme cette panne differee en signal immediat.
    """
    if not precedent:
        return ["premiere passe : aucun point de comparaison"]
    avant = {f.get("fournisseur"): f for f in precedent.get("fournisseurs", [])}
    lignes = []
    for fiche in courant:
        nom = fiche.get("fournisseur")
        vieux = avant.get(nom)
        if not vieux:
            lignes.append(f"  + {nom} : nouveau dans le recensement")
            continue
        if vieux.get("etat") == "NON_MESURE" and fiche.get("etat") != "NON_MESURE":
            lignes.append(f"  ^ {nom} : REDEVENU mesurable")
        if fiche.get("etat") == "NON_MESURE" and vieux.get("etat") != "NON_MESURE":
            lignes.append(f"  ! {nom} : n'est PLUS mesurable (HTTP {fiche.get('code')})")
        d_av, d_ap = vieux.get("declares", 0), fiche.get("declares", 0)
        if d_av and d_ap and d_ap != d_av:
            signe = "+" if d_ap > d_av else "-"
            lignes.append(f"  {signe} {nom} : catalogue {d_av} -> {d_ap} modeles")
        g_av, g_ap = vieux.get("gratuits_annonces", 0), fiche.get("gratuits_annonces", 0)
        if g_av != g_ap:
            lignes.append(f"  $ {nom} : gratuits annonces {g_av} -> {g_ap}")
    for nom in avant:
        if not any(f.get("fournisseur") == nom for f in courant):
            lignes.append(f"  - {nom} : DISPARU du recensement")
    return lignes or ["  aucun changement depuis la passe precedente"]


def lire_cibles(argv) -> list[tuple[str, str]]:
    """`--cible fournisseur:modele,fournisseur:modele` -> [(fournisseur, modele), ...] ; [] sans l'option."""
    if "--cible" not in argv:
        return []
    i = argv.index("--cible")
    brut = argv[i + 1] if i + 1 < len(argv) else ""
    return [tuple(x.split(":", 1)) for x in brut.split(",") if ":" in x]  # type: ignore[misc]


def cibler(cibles) -> list[dict]:
    """Sonde des modeles NOMMES (owner 16/10 : une affirmation sans source -- « tel modele est gratuit chez tel
    fournisseur » -- se tranche par mesure). Pour chacun : DECLARE au catalogue de notre cle (None si le catalogue est
    illisible : jamais lu « absent »), JOIGNABLE par une completion reelle meme s'il n'est pas declare, quota expose."""
    from nokido_agent.app.forge_secrets import get_secret

    par_nom = {etiquette: (env_key, base) for etiquette, env_key, base in SURFACES}
    lus: dict = {}
    sortie = []
    for fournisseur, modele in cibles:
        if fournisseur not in par_nom:
            sortie.append({"fournisseur": fournisseur, "modele": modele, "etat": "FOURNISSEUR_INCONNU"})
            continue
        env_key, base = par_nom[fournisseur]
        cle = (get_secret(env_key) or "") if env_key else ""
        if fournisseur not in lus:
            lus[fournisseur] = catalogue(base, cle)
        code, modeles, entetes = lus[fournisseur]
        declare = (modele in {str(m.get("id")) for m in modeles}) if code == 200 else None
        if any(s["fournisseur"] == fournisseur and "joignable" in s for s in sortie):
            time.sleep(PAUSE_S)   # jamais deux appels colles au meme fournisseur
        d = sonder(base, cle, modele, outils=True)
        sortie.append({"fournisseur": fournisseur, "modele": modele, "declare": declare, "joignable": d["joignable"],
                       "motif": d["motif"], "outils": d["outils"], "limites": d["limites"],
                       "quota": quota(fournisseur, cle, entetes)})
    return sortie


def consigner(resultats, registre: dict) -> dict:
    """Verse les verdicts d'une passe ciblee au registre (RED 4 du plan AGY, owner 16/10 : « y en a marre de refaire ces
    enquetes ») : cle fournisseur:modele, horodatee ; la mesure la plus recente remplace l'ancienne, les autres et le
    recensement restent. Un resultat SANS mesure garde son etat, jamais un « joignable: false » fabrique (UNKNOWN != NO)."""
    verdicts = dict(registre.get("verdicts") or {})
    quand = time.strftime("%Y-%m-%dT%H:%M:%S")
    for r in resultats:
        cle = "%s:%s" % (r["fournisseur"], r["modele"])
        entree = {k: v for k, v in r.items() if k not in ("fournisseur", "modele")}
        entree["mesure_le"] = quand
        # RED6 (19/10) : persistance d'un echec = echecs CONSECUTIFS ; un succes remet a zero, un resultat sans mesure
        # (joignable ni True ni False) ne touche pas au compteur.
        avant = verdicts.get(cle) or {}
        if entree.get("joignable") is False:
            entree["echecs_consecutifs"] = (int(avant.get("echecs_consecutifs") or 0)
                                            if avant.get("joignable") is False else 0) + 1
        elif entree.get("joignable") is True:
            entree["echecs_consecutifs"] = 0
        elif "echecs_consecutifs" in avant:
            entree["echecs_consecutifs"] = avant["echecs_consecutifs"]
        verdicts[cle] = entree
    return {**registre, "verdicts": verdicts}


REGISTRE_UNIFIE = ROOT / "data" / "surfaces_free_tier_registry.json"


def _spec_de(fournisseur: str, specs: dict) -> dict | None:
    """Fiche forge_provider_specs du fournisseur : cle exacte, sinon cle prefixee (`ollama` -> `ollama_local`)."""
    if fournisseur in specs:
        return specs[fournisseur]
    return next((v for k, v in specs.items() if k.startswith(fournisseur + "_")), None)


def registre_unifie(census: dict, specs: dict) -> dict:
    """RED4 (plan 60d8ed546, releve AGY job_6cfab01f) : registre UNIFIE des surfaces fournisseur:modele.

    Fusion des verdicts et des preuves du recensement avec forge_provider_specs. Liste BLANCHE : GRATUIT_PROUVE seulement
    si la surface est JOIGNABLE et son tier gratuit/local ; PAYANT_PROUVE sur un 402 ; tout le reste INCONNU. Une valeur
    non mesuree vaut None (acces_cli n'est mesure nulle part a ce jour)."""
    census = census or {}
    brutes = {}
    for f in census.get("fournisseurs") or []:
        for p in (f or {}).get("preuves") or []:
            cle = "%s:%s" % (f.get("fournisseur"), p.get("modele"))
            brutes[cle] = {"joignable": p.get("joignable"), "motif": p.get("motif"), "quota": f.get("quota"),
                           "mesure_le": census.get("horodatage")}
    for cle, v in (census.get("verdicts") or {}).items():
        brutes[cle] = dict(brutes.get(cle) or {}, **(v or {}))
    surfaces = []
    for cle, v in sorted(brutes.items()):
        fournisseur, _, modele = cle.partition(":")
        spec = _spec_de(fournisseur, specs or {})
        tier = str((spec or {}).get("tier") or "")
        if v.get("joignable") is True and tier in ("free", "local"):
            statut = "GRATUIT_PROUVE"
        elif str(v.get("motif") or "").startswith("HTTP 402"):
            statut = "PAYANT_PROUVE"
        else:
            statut = "INCONNU"
        surfaces.append({
            "fournisseur": fournisseur, "modele": modele, "statut_gratuit": statut,
            "declare": v.get("declare"), "gratuit_annonce": True if tier in ("free", "local") else None,
            "joignable": v.get("joignable"), "quota_primaire": v.get("quota"),
            "specialite": (spec or {}).get("notes"), "capabilities": (spec or {}).get("capabilities"),
            "acces_cli": None, "acces_swarm": True if spec else None,
            "outils_supportes": v.get("outils"), "mesure_le": v.get("mesure_le")})
    totaux = {"surfaces": len(surfaces),
              "joignables": sum(1 for s in surfaces if s["joignable"] is True),
              "gratuits_prouves": sum(1 for s in surfaces if s["statut_gratuit"] == "GRATUIT_PROUVE"),
              "inconnus": sum(1 for s in surfaces if s["statut_gratuit"] == "INCONNU")}
    return {"version_schema": "1", "horodatage": census.get("horodatage"), "surfaces": surfaces, "totaux": totaux}


def _ecrire_registre_unifie(cible) -> int:
    try:
        census = json.loads(SORTIE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"recensement ILLISIBLE ({type(exc).__name__}) : registre unifie NON ecrit")
        return 1
    try:
        from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        from forge_provider_specs import PROVIDER_SPECS
    reg = registre_unifie(census, PROVIDER_SPECS)
    cible = Path(cible)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"registre unifie : {cible} -- {reg['totaux']}")
    return 0


def main() -> int:
    if "--registre-unifie" in sys.argv:
        i = sys.argv.index("--registre-unifie")
        suivant = sys.argv[i + 1] if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--") else None
        return _ecrire_registre_unifie(suivant or REGISTRE_UNIFIE)
    cibles = lire_cibles(sys.argv[1:])
    if cibles:
        resultats = cibler(cibles)
        for r in resultats:
            if r.get("etat"):
                print(f"{r['fournisseur']:12} {r['modele'][:44]:46} {r['etat']}")
                continue
            declare = {True: "declare", False: "NON declare", None: "catalogue ILLISIBLE"}[r["declare"]]
            outils = {True: "outils OK", False: "outils REFUSES", None: "outils non testes"}[r.get("outils")]
            print(f"{r['fournisseur']:12} {r['modele'][:44]:46} {declare:20} "
                  f"{'JOIGNABLE' if r['joignable'] else 'injoignable (' + str(r['motif']) + ')'}  {outils}  "
                  f"limites: {r.get('limites') or 'aucun en-tete'}  quota: {r['quota']}")
        try:
            registre = json.loads(SORTIE.read_text(encoding="utf-8")) if SORTIE.exists() else {}
        except (OSError, json.JSONDecodeError) as exc:
            # un registre illisible n'est jamais reecrit : ce serait jeter le recensement et les verdicts anterieurs
            print(f"(registre ILLISIBLE : {type(exc).__name__} -- verdicts NON gardes, rien ecrase)")
            return 0
        try:
            SORTIE.parent.mkdir(parents=True, exist_ok=True)
            SORTIE.write_text(json.dumps(consigner(resultats, registre), ensure_ascii=False, indent=1),
                              encoding="utf-8")
            print(f"verdicts gardes : {SORTIE} (cle fournisseur:modele) -- la prochaine session les LIT")
        except OSError as exc:
            print(f"(verdicts NON gardes : {exc})")
        return 0
    from nokido_agent.app.forge_secrets import get_secret

    precedent = {}
    try:
        precedent = json.loads(SORTIE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        precedent = {}

    total_declare = total_gratuit = total_joignable = 0
    rapport = []
    for etiquette, env_key, base in SURFACES:
        cle = (get_secret(env_key) or "") if env_key else ""
        code, modeles, entetes = catalogue(base, cle)
        if code != 200:
            print(f"{etiquette:12} HTTP {code} — NON MESURE")
            rapport.append({"fournisseur": etiquette, "code": code, "etat": "NON_MESURE"})
            continue

        utiles = [m for m in modeles
                  if not any(mot in str(m.get("id", "")).lower() for mot in _INADAPTES)]
        # RED 3 du plan AGY (16/10) : « Groq : 6 modeles » etait compte APRES ce filtre -- dire les deux, et lesquels.
        ecartes = sorted(str(m.get("id")) for m in modeles if m not in utiles)
        gratuits = [m for m in utiles if est_gratuit(m, etiquette) is True]
        inconnus = [m for m in utiles if est_gratuit(m, etiquette) is None]

        # Preuve par echantillon : les plus PETITS repondent vite et suffisent
        # a prouver que le palier repond (un 405B a froid ne prouverait rien).
        candidats = sorted(gratuits or inconnus,
                           key=lambda m: _taille(str(m.get("id", ""))))[:ECHANTILLON]
        preuves = []
        for m in candidats:
            ok, motif = joignable(base, cle, str(m.get("id")))
            preuves.append({"modele": str(m.get("id")), "joignable": ok, "motif": motif})
        joints = sum(1 for p in preuves if p["joignable"])

        total_declare += len(utiles)
        total_gratuit += len(gratuits)
        total_joignable += joints
        print(f"{etiquette:12} declares={len(utiles):<4} (bruts={len(modeles)}, ecartes={len(ecartes)}) "
              f"gratuits_annonces={len(gratuits):<4} "
              f"prix_non_publie={len(inconnus):<4} echantillon_joignable={joints}/{len(preuves)}"
              f"  quota: {quota(etiquette, cle, entetes)}")
        for p in preuves:
            print(f"               {p['modele'][:44]:46} {'OK' if p['joignable'] else p['motif']}")
        rapport.append({"fournisseur": etiquette, "declares": len(utiles), "declares_bruts": len(modeles),
                        "declares_utiles": len(utiles), "ecartes": ecartes,
                        "gratuits_annonces": len(gratuits),
                        "prix_non_publie": len(inconnus), "preuves": preuves,
                        "quota": quota(etiquette, cle, entetes)})

    print(f"\nTOTAL declares={total_declare} · gratuits ANNONCES={total_gratuit} · "
          f"echantillons PROUVES joignables={total_joignable}")
    print(f"\n--- ce qui a bouge depuis {precedent.get('horodatage', '(jamais)')} ---")
    for ligne in comparer(precedent, rapport):
        print(ligne)
    print("« gratuits annonces » compte ce que les fournisseurs publient ; les autres "
          "ne publient aucun prix et ne sont donc ni comptes gratuits ni comptes payants.")
    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps(
            {"horodatage": time.strftime("%Y-%m-%dT%H:%M:%S"), "fournisseurs": rapport,
             "verdicts": precedent.get("verdicts") or {},
             "totaux": {"declares": total_declare, "gratuits_annonces": total_gratuit,
                        "echantillons_joignables": total_joignable}},
            ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            affiche = SORTIE.relative_to(ROOT)
        except ValueError:      # registre hors du depot (tmp de la CI de reference) : chemin complet, jamais une exception
            affiche = SORTIE
        print(f"registre : {affiche} — deux passes comparees disent ce qui a bouge")
    except OSError as exc:
        print(f"(registre non ecrit : {exc})")
    return 0


# ── Essaim cloud (RED 1da121b2a, owner 19/10 : l'essaim ne s'assigne que sur des couples PROUVES vivants) ────────────
# GREEN d'OPENCODE_GLM (cb9637e1f, session coupee par une panne du fournisseur) repris le 20/10 : porteurs indexes par
# FOURNISSEUR du census et hote compare (client.base_url compris), sonde illisible = INDETERMINE.

def porteurs_du_proxy(registre, surfaces) -> dict:
    """{fournisseur du census: [providers du proxy qui parlent au meme HOTE d'API]} ; un provider sans url est ignore."""
    from urllib.parse import urlsplit

    def _hote(p):
        u = getattr(p, "base_url", None) or getattr(getattr(p, "client", None), "base_url", None)
        return urlsplit(str(u)).netloc.lower() if u else None

    hotes = {nom: _hote(p) for nom, p in (registre or {}).items()}
    porteurs = {}
    for etiquette, _cle, base in surfaces:
        h = urlsplit(str(base or "")).netloc.lower()
        noms = sorted(n for n, x in hotes.items() if x and x == h)
        if noms:
            porteurs[etiquette] = noms
    return porteurs


def membres_essaim(candidats, porteurs) -> dict:
    """Chaque modele candidat devient `porteur:id_brut` (premier porteur par nom) ; un fournisseur sans porteur est
    NOMME dans `sans_porteur`, jamais tu."""
    membres, sans_porteur = [], []
    for fournisseur, modeles in (candidats or {}).items():
        siens = sorted(porteurs.get(fournisseur) or [])
        if not siens:
            sans_porteur.append(fournisseur)
            continue
        membres.extend("%s:%s" % (siens[0], m) for m in modeles)
    return {"membres": membres, "sans_porteur": sans_porteur}


async def sonder_essaim(membres, ask_fn) -> dict:
    """{membre: {"etat": OK|VIDE|KO|INDETERMINE, "ms"}} par `ask_fn(provider, tache, model=...)`, classe par la liste
    BLANCHE de forge_cli_swarm._classer ; une sonde qui leve est INDETERMINE (UNKNOWN n'est pas NO)."""
    import forge_cli_swarm as cs
    resultats = {}
    for membre in membres:
        provider, _, modele = membre.partition(":")
        t0 = time.time()
        try:
            r = await ask_fn(provider, "ping", model=modele or None)
            etat = cs._classer(bool(r.get("ok")), str(r.get("text") or ""), r.get("error"))
        except Exception:  # noqa: BLE001 - sonde illisible
            etat = "INDETERMINE"
        resultats[membre] = {"etat": etat, "ms": int((time.time() - t0) * 1000)}
    return resultats


def ecrire_membres_vivants(verdicts, chemin, maintenant=None) -> dict:
    """Registre horodate des seuls membres OK ; rend le document ecrit."""
    doc = {"membres_ok": [m for m, v in (verdicts or {}).items() if (v or {}).get("etat") == "OK"],
           "mesure_le": time.time() if maintenant is None else maintenant}
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


if __name__ == "__main__":
    raise SystemExit(main())
