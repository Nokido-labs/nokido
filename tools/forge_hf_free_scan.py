#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Hugging Face : le champ `is_free` existe-t-il, et que vaut-il pour nous ?

Une analyse externe affirme que HF publie un champ `is_free` dans son catalogue
de providers, qu'un compte gratuit recoit $0,10 de credits mensuels, et qu'un
modele marque `is_free` ne les consommerait pas — donc resterait utilisable
credits epuises. Notre mesure du 2026-08-18 dit que `router.huggingface.co`
rend **402 « You have depleted your monthly included credits »**.

Les deux peuvent etre vrais en meme temps : credits a zero POUR LES MODELES
PAYANTS, et acces conserve aux modeles gratuits. Ce module tranche par
l'experience au lieu de choisir un camp :

  1. quels endpoints HF exposent reellement `is_free` (plusieurs candidats,
     l'API a bouge) ;
  2. combien de modeles y sont marques gratuits ;
  3. est-ce qu'un de ces modeles REPOND malgre le 402 des autres.

Le point 3 est le seul qui decide. Un champ dans un JSON ne nourrit personne.

    run action=run_job script=tools/forge_hf_free_scan.py online=true
"""
from __future__ import annotations

__FORGE_COLOR__ = "metabolisme/provider : Hugging Face, le champ is_free et sa valeur"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SORTIE = ROOT / "sandbox" / "hf_free_scan.json"
TIMEOUT = 30
ROUTER = "https://router.huggingface.co/v1"

CANDIDATS = [
    ("router /v1/models", f"{ROUTER}/models"),
    ("hub inferenceProviderMapping",
     "https://huggingface.co/api/models?inference_provider=all"
     "&expand[]=inferenceProviderMapping&limit=200"),
    ("hub trending+mapping",
     "https://huggingface.co/api/models?pipeline_tag=text-generation"
     "&expand[]=inferenceProviderMapping&sort=trendingScore&limit=200"),
]


def _get(url: str, cle: str) -> tuple[int, str]:
    entetes = {"User-Agent": "nokido-hf-scan"}
    if cle:
        entetes["Authorization"] = f"Bearer {cle}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=entetes),
                                    timeout=TIMEOUT) as r:
            return r.status, r.read(400000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.reason or "")
    except Exception as exc:  # noqa: BLE001
        return -1, type(exc).__name__


def _marques_gratuites(corps: str) -> list[tuple[str, str]]:
    """[(modele, provider)] portant is_free vrai, quelle que soit la forme."""
    try:
        brut = json.loads(corps)
    except ValueError:
        return []
    entrees = brut.get("data") if isinstance(brut, dict) else brut
    trouves: list[tuple[str, str]] = []
    for entree in (entrees or []):
        if not isinstance(entree, dict):
            continue
        nom = str(entree.get("id") or entree.get("modelId") or "")
        mapping = entree.get("inferenceProviderMapping") or entree.get("providers") or []
        if isinstance(mapping, dict):
            mapping = [dict(v, provider=k) if isinstance(v, dict) else {"provider": k}
                       for k, v in mapping.items()]
        for fiche in mapping:
            if not isinstance(fiche, dict):
                continue
            if fiche.get("is_free") is True or fiche.get("isFree") is True:
                trouves.append((nom, str(fiche.get("provider") or fiche.get("providerId") or "?")))
    return trouves


def essayer(modele: str, cle: str) -> tuple[bool, str]:
    charge = json.dumps({"model": modele,
                         "messages": [{"role": "user", "content": "ping"}],
                         "max_tokens": 8}).encode("utf-8")
    req = urllib.request.Request(f"{ROUTER}/chat/completions", data=charge, headers={
        "Authorization": f"Bearer {cle}", "Content-Type": "application/json",
        "User-Agent": "nokido-hf-scan"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            corps = json.loads(r.read().decode("utf-8", errors="replace"))
            texte = ((corps.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            return bool(texte.strip()), texte.strip()[:60] or "reponse vide"
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(300).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            detail = exc.reason or ""
        return False, f"HTTP {exc.code} — {detail[:160]}"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def main() -> int:
    from nokido_agent.app.forge_secrets import get_secret

    cle = get_secret("HF_TOKEN") or ""
    if not cle:
        print("HF_TOKEN absente du coffre — NON MESURE")
        return 3

    gratuits: list[tuple[str, str]] = []
    rapport = []
    for etiquette, url in CANDIDATS:
        code, corps = _get(url, cle)
        marques = _marques_gratuites(corps) if code == 200 else []
        presence = ("is_free" in corps) or ("isFree" in corps)
        print(f"{etiquette:32} HTTP {code:<5} champ is_free present : {presence} "
              f"— {len(marques)} modele(s) marque(s) gratuit(s)")
        rapport.append({"endpoint": etiquette, "code": code,
                        "champ_present": presence, "marques": len(marques)})
        gratuits.extend(marques)

    uniques = sorted(set(gratuits))
    print(f"\n{len(uniques)} couple(s) modele:provider marques gratuits")
    for nom, prov in uniques[:15]:
        print(f"    {nom}:{prov}")

    # LE test : un modele marque gratuit repond-il malgre le 402 des autres ?
    print("\n--- preuve par l'appel ---")
    temoin = "openai/gpt-oss-120b"
    ok, motif = essayer(temoin, cle)
    print(f"  temoin (payant)  {temoin:44} {'REPOND' if ok else motif}")
    for nom, prov in uniques[:3]:
        cible = f"{nom}:{prov}"
        ok, motif = essayer(cible, cle)
        print(f"  marque gratuit   {cible[:44]:44} {'REPOND' if ok else motif}")
        rapport.append({"essai": cible, "repond": ok, "motif": motif})

    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps({"rapport": rapport,
                                      "gratuits": [f"{n}:{p}" for n, p in uniques]},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\ndetail : {SORTIE.relative_to(ROOT)}")
    except OSError as exc:
        print(f"(rapport non ecrit : {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
