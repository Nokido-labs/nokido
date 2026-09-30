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


def joignable(base: str, cle: str, modele: str) -> tuple[bool, str]:
    charge = json.dumps({"model": modele,
                         "messages": [{"role": "user", "content": "ping"}],
                         "max_tokens": 8}).encode("utf-8")
    try:
        with urllib.request.urlopen(_req(f"{base}/chat/completions", cle, charge),
                                    timeout=TIMEOUT) as r:
            corps = json.loads(r.read().decode("utf-8", errors="replace"))
            choix = (corps.get("choices") or [{}])[0]
            texte = (choix.get("message") or {}).get("content") or ""
            return bool(texte.strip()), "" if texte.strip() else "reponse vide"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


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
                return (f"usage={d.get('usage')} limite={d.get('limit')} "
                        f"restant={d.get('limit_remaining')}")
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


def main() -> int:
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
        print(f"{etiquette:12} declares={len(utiles):<4} gratuits_annonces={len(gratuits):<4} "
              f"prix_non_publie={len(inconnus):<4} echantillon_joignable={joints}/{len(preuves)}"
              f"  quota: {quota(etiquette, cle, entetes)}")
        for p in preuves:
            print(f"               {p['modele'][:44]:46} {'OK' if p['joignable'] else p['motif']}")
        rapport.append({"fournisseur": etiquette, "declares": len(utiles),
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
             "totaux": {"declares": total_declare, "gratuits_annonces": total_gratuit,
                        "echantillons_joignables": total_joignable}},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"registre : {SORTIE.relative_to(ROOT)} — deux passes comparees disent ce qui a bouge")
    except OSError as exc:
        print(f"(registre non ecrit : {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
