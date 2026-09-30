#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Confronte les modeles Gemini declares dans le routeur a ceux qui EXISTENT.

Mesure du 2026-08-18 : les quatre slots `gemini_*` rendaient
`404 NOT_FOUND — This model models/gemini-2… is not found`, avec une cle
PARFAITEMENT valide. Ce n'etait donc ni un droit ni un quota : les noms de
modeles avaient ete renommes chez Google, et le routeur continuait de demander
des identifiants qui n'existent plus. Aucun garde ne pouvait le voir, puisque
la cle repondait.

Ce module LIT le catalogue du fournisseur (`client.models.list()`) et le
confronte a `forge_llm_router.PROVIDERS`. Il ne devine aucun nom : deviner est
precisement ce qui a cree la panne.

LECTURE SEULE par defaut ; `--json` pour une sortie machine. La correction des
slots reste un geste humain — remplacer un modele par un autre change le
comportement du routeur, ce n'est pas une operation cosmetique.

Usage :
    run action=run_job script=tools/forge_gemini_models_sync.py online=true
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def modeles_declares() -> dict[str, list[str]]:
    """slot -> modeles demandes, pour les slots Gemini du routeur."""
    from nokido_agent.app.forge_llm_router import PROVIDERS

    return {n: list(f.get("models") or [])
            for n, f in PROVIDERS.items()
            if n.startswith("gemini") or "gemini" in (f.get("env_key") or "").lower()}


def catalogue() -> tuple[list[str], str]:
    """(modeles generatifs disponibles, motif si vide). Aucune cle affichee."""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        cle = get_secret("GEMINI_API_KEY") or ""
    except Exception as exc:  # noqa: BLE001
        return [], f"coffre indisponible ({type(exc).__name__})"
    if not cle:
        return [], "GEMINI_API_KEY absente du coffre"
    try:
        from google import genai

        client = genai.Client(api_key=cle)
        noms = []
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                noms.append(str(getattr(m, "name", "")).replace("models/", ""))
        return sorted(n for n in noms if n), ""
    except Exception as exc:  # noqa: BLE001 - SDK absent, reseau, quota
        return [], f"{type(exc).__name__}: {exc}"[:120]


def _normaliser(nom: str) -> str:
    """`gemini/gemini-2.5-flash` et `models/gemini-2.5-flash` -> `gemini-2.5-flash`.

    Le routeur prefixe par le fournisseur, l'API par `models/`. Comparer les
    deux formes brutes declarait INTROUVABLE un modele parfaitement vivant —
    faute de sonde, encore, pas faute de service.
    """
    court = nom.replace("models/", "").strip()
    if "/" in court:
        court = court.split("/", 1)[1]
    return court


def confronter(declares: dict[str, list[str]], dispo: list[str]) -> list[dict]:
    vivants = {_normaliser(d) for d in dispo}
    out = []
    for slot, modeles in sorted(declares.items()):
        for m in modeles:
            court = _normaliser(m)
            existe = court in vivants
            # Suggestion : meme famille (prefixe avant le premier tiret de version)
            racine = court.rsplit("-", 1)[0]
            proches = [d for d in sorted(vivants) if d.startswith(racine)] if not existe else []
            if not proches and not existe:
                famille = court.split("-")[0] + "-" + (court.split("-")[1] if "-" in court else "")
                proches = [d for d in sorted(vivants) if d.startswith(famille)][:5]
            out.append({"slot": slot, "modele": court, "existe": existe,
                        "candidats": proches[:5]})
    return out


def essayer(modele: str) -> tuple[bool, str]:
    """Generation minimale. Figurer au catalogue ne prouve pas repondre : un
    modele peut y etre liste et rendre 404 sur la version d'API utilisee."""
    try:
        from nokido_agent.app.forge_secrets import get_secret
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=get_secret("GEMINI_API_KEY") or "")
        # 16 tokens, pas 1 : a 1 le modele est coupe AVANT le premier mot et rend
        # un texte vide qu'on lirait comme une panne (artefact paye 3 fois le 18/08).
        r = client.models.generate_content(
            model=modele, contents="ping",
            config=types.GenerateContentConfig(max_output_tokens=16))
        return bool(getattr(r, "text", None)), ""
    except Exception as exc:  # noqa: BLE001 - on VEUT le message entier
        return False, f"{type(exc).__name__}: {exc}"[:220]


def main() -> int:
    declares = modeles_declares()
    dispo, motif = catalogue()
    if not dispo:
        print(f"CATALOGUE NON MESURE : {motif}")
        print("  -> ne PAS conclure que les modeles sont morts : on n'a pas su demander")
        return 3
    lignes = confronter(declares, dispo)
    if "--json" in sys.argv:
        print(json.dumps({"disponibles": dispo, "confrontation": lignes}, ensure_ascii=False))
        return 0
    print(f"{len(dispo)} modele(s) generatif(s) disponibles avec cette cle")
    manquants = [x for x in lignes if not x["existe"]]
    for x in lignes:
        etat = "OK" if x["existe"] else "INTROUVABLE"
        print(f"  {x['slot']:20} {x['modele']:34} {etat}")
        if x["candidats"]:
            print(f"      candidats : {', '.join(x['candidats'])}")
    print(f"\n{len(manquants)}/{len(lignes)} modele(s) declare(s) n'existent plus chez le fournisseur")
    if manquants:
        print("Corriger les slots a la main : changer de modele change le comportement.")

    if "--essai" in sys.argv:
        print("\n--- generation reelle (16 tokens) ---")
        a_tester = sorted({x["modele"] for x in lignes if x["existe"]})
        # Un 429 vise UN modele (quota par modele), pas le compte : quand la
        # famille cablee est saturee, une autre du meme catalogue reste souvent
        # ouverte. On elargit donc l'essai a un echantillon de chaque famille.
        if "--large" in sys.argv:
            familles = ("gemini-flash", "gemini-3", "gemma-4", "gemini-pro")
            a_tester = sorted(set(a_tester) | {
                d for d in dispo
                if d.startswith(familles) and "image" not in d and "tts" not in d
                and "robotics" not in d and "computer-use" not in d})
        try:
            from nokido_agent.app.forge_secrets import get_secret

            impose = get_secret("GEMINI_MODEL") or ""
        except Exception:  # noqa: BLE001 - facade absente
            impose = ""
        if impose:
            print(f"  (GEMINI_MODEL={impose} PRIME sur le modele de chaque classe)")
            a_tester = sorted(set(a_tester) | {_normaliser(impose)})
        for m in a_tester:
            ok, motif = essayer(m)
            print(f"  {m:34} {'REPOND' if ok else 'NON'}  {motif}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
