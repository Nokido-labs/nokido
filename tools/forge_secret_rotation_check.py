#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_secret_rotation_check.py -- ces secrets de l'historique servent-ils ENCORE ?

POURQUOI
========
Le balayage du 2026-08-29 a trouve 20 secrets reels dans l'histoire d'`alpha` et
`beta` (`LaForge.env`, `.env.bak`, `- Copie.env`, `live_bridge.map`). La question
qui decide de l'urgence n'est pas « y a-t-il des secrets » mais **« sont-ils
encore VIVANTS »** : une cle deja rotationnee est un dechet, une cle encore en
service est une breche ouverte.

METHODE
=======
On compare des EMPREINTES, jamais des valeurs : SHA-256 tronque a 12 hex de
chaque secret historique, puis des secrets EN SERVICE (coffre + fichier
d'environnement courant). Une empreinte commune = la cle historique est toujours
celle qui sert -> ROTATION URGENTE. Aucune correspondance = deja rotationnee.

L'empreinte tronquee ne permet pas de retrouver la valeur, et elle suffit
largement a l'egalite : on compare des chaines identiques, pas des voisines.

TROIS ETATS
===========
  VIVANT      au moins un secret historique est encore en service
  ROTATIONNE  aucun secret historique ne correspond a un secret en service
  INDETERMINE on n'a pas pu lire les secrets en service -- surtout PAS un feu vert
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/verification-rotation"

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT))

# Cles que l'on sait avoir fuite. Mesure 2026-08-29 (motifs elargis) : la fuite
# ne se limite PAS a google/github -- les memes fichiers d'environnement portent
# groq, huggingface et openai. Interroger 4 noms aurait rendu un « ROTATIONNE »
# vrai pour ces 4 et MUET pour les autres, ce qui se lit comme un feu vert.
CLES_SUSPECTES = [
    "GOOGLE_API_KEY", "GEMINI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN",
    "GROQ_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "OPENAI_API_KEY",
    "MISTRAL_API_KEY", "CODEBERG_TOKEN", "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY", "CEREBRAS_API_KEY", "NVIDIA_API_KEY",
]


def _empreinte(valeur) -> str:
    if isinstance(valeur, str):
        valeur = valeur.encode("utf-8", "replace")
    return hashlib.sha256(valeur).hexdigest()[:12]


def empreintes_historiques():
    """{empreinte: [chemins]} des secrets reels trouves dans l'historique.

    ⚠ `_git` de l'audit rend une CHAINE, pas un tuple (rc, out, err). Une
    premiere version testait `_git(...)[0] == 0` -- soit le premier CARACTERE
    compare a 0, toujours faux : aucune ref retenue, rien scanne, et un verdict
    « PROPRE » fabrique par une liste vide. Faux negatif du cote le plus cher,
    attrape parce que 0 contredisait les 20 secrets mesures juste avant. On
    verifie donc les refs par un appel dont on LIT le code de retour.
    """
    import subprocess
    from nokido_agent.tools.forge_history_secret_audit import (EXCEPTIONS, MOTIFS, REFS_PUBLIABLES,
                                            _est_factice, _git, lire_blobs)
    inventaire = {}
    refs = [r for r in REFS_PUBLIABLES
            if subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                               "rev-parse", "--verify", "--quiet", r],
                              capture_output=True).returncode == 0]
    if not refs:
        raise RuntimeError("aucune ref publiable resolvable : audit impossible")
    for ligne in _git("rev-list", *refs, "--objects").splitlines():
        p = ligne.split(" ", 1)
        if len(p) == 2 and p[1].strip():
            inventaire.setdefault(p[0], p[1].strip())
    trouves = {}
    for sha, data, _t in lire_blobs(list(inventaire)):
        if data is None or inventaire.get(sha) in EXCEPTIONS:
            continue
        for motif in MOTIFS.values():
            for h in re.findall(motif, data):
                if not _est_factice(h):
                    trouves.setdefault(_empreinte(h), set()).add(inventaire.get(sha, "?"))
    return {k: sorted(v) for k, v in trouves.items()}


def empreintes_en_service():
    """{empreinte: [origines]} des secrets REELLEMENT utilises aujourd'hui."""
    vues, illisibles = {}, []
    try:
        from nokido_agent.app.forge_secrets import get_secret
        for cle in CLES_SUSPECTES:
            try:
                v = get_secret(cle)
            except Exception as e:  # noqa: BLE001
                illisibles.append("%s (%s)" % (cle, type(e).__name__))
                continue
            if v:
                vues.setdefault(_empreinte(v), set()).add("coffre:%s" % cle)
    except Exception as e:  # noqa: BLE001
        illisibles.append("coffre indisponible (%s)" % type(e).__name__)

    for nom in ("Nokido.env", "Nokido.env.secrets", ".env"):
        p = ROOT / nom
        try:
            texte = p.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            continue
        except OSError as e:
            illisibles.append("%s (%s)" % (nom, type(e).__name__))
            continue
        for ligne in texte.splitlines():
            if "=" not in ligne or ligne.strip().startswith("#"):
                continue
            cle, _, val = ligne.partition("=")
            val = val.strip().strip('"').strip("'")
            if len(val) >= 20:
                vues.setdefault(_empreinte(val), set()).add("%s:%s" % (nom, cle.strip()))
    return {k: sorted(v) for k, v in vues.items()}, illisibles


def verifier():
    try:
        hist = empreintes_historiques()
    except Exception as e:  # noqa: BLE001
        return {"verdict": "INDETERMINE", "secrets_historiques": 0,
                "secrets_en_service_lus": 0, "encore_vivants": [],
                "sources_illisibles": ["historique illisible : %s" % e]}
    service, illisibles = empreintes_en_service()
    communes = sorted(set(hist) & set(service))
    if not hist:
        # 0 secret historique CONTREDIT la mesure du 2026-08-29 (20 trouves) :
        # c'est un signe de sonde cassee, pas une bonne nouvelle.
        verdict = "INDETERMINE" if illisibles else "PROPRE"
    elif communes:
        verdict = "VIVANT"
    elif not service:
        verdict = "INDETERMINE"
    else:
        verdict = "ROTATIONNE"
    return {
        "verdict": verdict,
        "secrets_historiques": len(hist),
        "secrets_en_service_lus": len(service),
        "encore_vivants": [{"empreinte": c, "fichiers_historiques": hist[c],
                            "origines_actuelles": service[c]} for c in communes],
        "sources_illisibles": illisibles,
    }


# Ou revoquer, par type de motif. Revoquer = desactiver CHEZ LE FOURNISSEUR ;
# remplacer la valeur en local ne ferme rien.
CONSOLES = {
    "google_api": "Google Cloud — APIs & Services > Credentials (console.cloud.google.com/apis/credentials)",
    "github_pat": "GitHub — Settings > Developer settings > Personal access tokens",
    "groq": "Groq — console.groq.com/keys",
    "huggingface": "HuggingFace — huggingface.co/settings/tokens",
    "openai": "OpenAI — platform.openai.com/api-keys",
    "anthropic": "Anthropic — console.anthropic.com/settings/keys",
    "url_avec_mdp": "Jeton porte dans une URL de push (Codeberg/GitHub) — revoquer le jeton concerne",
    "aws_akid": "AWS — IAM > Users > Security credentials",
    "stripe": "Stripe — dashboard.stripe.com/apikeys",
    "slack": "Slack — api.slack.com/apps > OAuth & Permissions",
    "jwt": "Jeton applicatif : faire tourner la cle de signature emettrice",
    "cle_privee": "Cle privee : la considerer compromise et regenerer la paire",
}


def a_revoquer():
    """Liste actionnable : fournisseur, console, et de quoi RECONNAITRE la cle
    dans l'interface — jamais sa valeur.

    Les consoles listent les cles par date et par derniers caracteres : on donne
    donc les 4 derniers (usage courant d'identification, comme pour une carte)
    et l'empreinte, qui ne permettent ni de reconstituer ni d'utiliser la cle.
    """
    from nokido_agent.tools.forge_history_secret_audit import (EXCEPTIONS, MOTIFS, REFS_PUBLIABLES,
                                            _est_factice, _git, lire_blobs)
    import subprocess
    refs = [r for r in REFS_PUBLIABLES
            if subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                               "rev-parse", "--verify", "--quiet", r],
                              capture_output=True).returncode == 0]
    inventaire = {}
    for ligne in _git("rev-list", *refs, "--objects").splitlines():
        p = ligne.split(" ", 1)
        if len(p) == 2 and p[1].strip():
            inventaire.setdefault(p[0], p[1].strip())
    par_cle = {}
    for sha, data, _t in lire_blobs(list(inventaire)):
        if data is None or inventaire.get(sha) in EXCEPTIONS:
            continue
        for typ, motif in MOTIFS.items():
            for h in re.findall(motif, data):
                if _est_factice(h):
                    continue
                brut = h.decode("ascii", "replace")
                cle = _empreinte(h)
                e = par_cle.setdefault(cle, {
                    "type": typ, "empreinte": cle,
                    "derniers_caracteres": brut[-4:],
                    "console": CONSOLES.get(typ, "fournisseur inconnu"),
                    "fichiers": set()})
                e["fichiers"].add(inventaire.get(sha, "?"))
    for e in par_cle.values():
        e["fichiers"] = sorted(e["fichiers"])[:4]
    return sorted(par_cle.values(), key=lambda e: (e["type"], e["empreinte"]))


# Sondes de VALIDITE : un appel en LECTURE SEULE vers le fournisseur legitime.
# (url, mode d'authentification). Aucune ecriture, aucun tiers, aucune trace de
# la valeur : c'est la demarche standard de reponse a incident -- on ne revoque
# pas 8 cles a l'aveugle, on regarde d'abord lesquelles vivent encore.
SONDES = {
    "github_pat": ("https://api.github.com/user", "bearer"),
    "openai": ("https://api.openai.com/v1/models", "bearer"),
    "groq": ("https://api.groq.com/openai/v1/models", "bearer"),
    "huggingface": ("https://huggingface.co/api/whoami-v2", "bearer"),
    "google_api": ("https://generativelanguage.googleapis.com/v1beta/models", "query"),
    # Le jeton porte dans une URL de push est un jeton Codeberg : on le teste la.
    "url_avec_mdp": ("https://codeberg.org/api/v1/user", "token"),
}

# Google refuse une cle invalide en HTTP 400 (pas 401) avec un motif explicite
# dans le corps. Sans lire ce corps, la sonde rendait INDETERMINE sur une cle
# pourtant clairement morte -- et un indetermine se solde par une rotation
# inutile. Mesure 2026-08-29.
_MOTIFS_INVALIDE = re.compile(
    r"(?i)api[_ ]key not valid|invalid[_ ]api[_ ]key|api key expired|"
    r"invalid authentication|invalid[_ ]token|bad credentials")


def _sonder(typ, valeur, timeout=12):
    """-> (etat, detail). VALIDE / REVOQUEE / INDETERMINE.

    401/403 sur un jeton porteur = plus utilisable. 200 = ENCORE ACTIVE.
    Tout le reste (reseau, 5xx, quota) est INDETERMINE : on ne conclut pas a la
    revocation parce qu'on n'a pas pu demander.
    """
    import urllib.error
    import urllib.request
    cible = SONDES.get(typ)
    if not cible:
        return "INDETERMINE", "aucune sonde pour ce type"
    url, mode = cible
    if mode == "token":
        # Jeton extrait d'une URL `scheme://user:JETON@hote`.
        valeur = valeur.split("://", 1)[-1].split(":", 1)[-1].rstrip("@")
    req = urllib.request.Request(url + ("?key=" + valeur if mode == "query" else ""))
    if mode == "bearer":
        req.add_header("Authorization", "Bearer " + valeur)
    elif mode == "token":
        req.add_header("Authorization", "token " + valeur)
    req.add_header("User-Agent", "nokido-rotation-check")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return ("VALIDE", "HTTP %s -- la cle repond ENCORE" % r.status)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "REVOQUEE", "HTTP %s -- refusee par le fournisseur" % e.code
        try:
            corps = e.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001 - corps illisible : on reste prudent
            corps = ""
        if _MOTIFS_INVALIDE.search(corps):
            return "REVOQUEE", "HTTP %s -- le fournisseur la declare invalide" % e.code
        return "INDETERMINE", "HTTP %s%s" % (e.code, " (motif non concluant)" if corps else "")
    except Exception as e:  # noqa: BLE001 - reseau : surtout pas « revoquee »
        return "INDETERMINE", "%s" % type(e).__name__


def tester_validite():
    """Teste CHAQUE cle historique contre son fournisseur. La valeur ne sort
    jamais du process : ni journal, ni sortie, ni ligne de commande."""
    from nokido_agent.tools.forge_history_secret_audit import (EXCEPTIONS, MOTIFS, REFS_PUBLIABLES,
                                            _est_factice, _git, lire_blobs)
    import subprocess
    refs = [r for r in REFS_PUBLIABLES
            if subprocess.run(["git", "-c", "safe.directory=*", "-C", str(ROOT),
                               "rev-parse", "--verify", "--quiet", r],
                              capture_output=True).returncode == 0]
    inventaire = {}
    for ligne in _git("rev-list", *refs, "--objects").splitlines():
        p = ligne.split(" ", 1)
        if len(p) == 2 and p[1].strip():
            inventaire.setdefault(p[0], p[1].strip())
    vues, resultats = set(), []
    for sha, data, _t in lire_blobs(list(inventaire)):
        if data is None or inventaire.get(sha) in EXCEPTIONS:
            continue
        for typ, motif in MOTIFS.items():
            for h in re.findall(motif, data):
                if _est_factice(h):
                    continue
                emp = _empreinte(h)
                if emp in vues:
                    continue
                vues.add(emp)
                valeur = h.decode("ascii", "replace")
                etat, detail = _sonder(typ, valeur)
                resultats.append({"type": typ, "empreinte": emp,
                                  "derniers_caracteres": valeur[-4:],
                                  "etat": etat, "detail": detail,
                                  "console": CONSOLES.get(typ, "?")})
    return sorted(resultats, key=lambda e: (e["etat"] != "VALIDE", e["type"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--revocation", action="store_true",
                    help="liste actionnable : quoi revoquer, ou, et comment la reconnaitre")
    ap.add_argument("--tester-validite", action="store_true",
                    help="demande a CHAQUE fournisseur si la cle repond encore")
    args = ap.parse_args(argv)
    if args.tester_validite:
        res = tester_validite()
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            for e in res:
                print("  %-9s %-12s ...%s | %s"
                      % (e["etat"], e["type"], e["derniers_caracteres"], e["detail"]))
            vivantes = [e for e in res if e["etat"] == "VALIDE"]
            flous = [e for e in res if e["etat"] == "INDETERMINE"]
            print("\n  %d cle(s) ENCORE VALIDES -> a revoquer d'urgence" % len(vivantes))
            print("  %d indeterminee(s) : pas pu demander, ne rien conclure" % len(flous))
        return 1 if any(e["etat"] == "VALIDE" for e in res) else 0
    if args.revocation:
        liste = a_revoquer()
        if args.json:
            print(json.dumps(liste, ensure_ascii=False, indent=2))
            return 0
        par_type = {}
        for e in liste:
            par_type.setdefault(e["type"], []).append(e)
        for typ, entrees in sorted(par_type.items()):
            print("\n  %s  (%d cle%s)" % (typ.upper(), len(entrees),
                                          "s" if len(entrees) > 1 else ""))
            print("    ou : %s" % entrees[0]["console"])
            for e in entrees:
                print("    - se termine par ...%s | empreinte %s | vue dans %s"
                      % (e["derniers_caracteres"], e["empreinte"], e["fichiers"]))
        print("\n  %d cle(s) a revoquer au total." % len(liste))
        return 0
    r = verifier()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 1 if r["verdict"] == "VIVANT" else 0
    print("  secrets historiques distincts : %d" % r["secrets_historiques"])
    print("  secrets en service lus        : %d" % r["secrets_en_service_lus"])
    for s in r["sources_illisibles"]:
        print("  ILLISIBLE : %s  (pas pu regarder != absent)" % s)
    for v in r["encore_vivants"]:
        print("  ENCORE VIVANT : empreinte %s | historique %s | en service %s"
              % (v["empreinte"], v["fichiers_historiques"], v["origines_actuelles"]))
    print("\n  VERDICT : %s" % r["verdict"])
    if r["verdict"] == "ROTATIONNE":
        print("  Aucun secret de l'historique ne correspond a un secret en service.")
    elif r["verdict"] == "INDETERMINE":
        print("  Aucun secret en service n'a pu etre lu : ne RIEN conclure.")
    return 1 if r["verdict"] == "VIVANT" else 0


if __name__ == "__main__":
    sys.exit(main())
