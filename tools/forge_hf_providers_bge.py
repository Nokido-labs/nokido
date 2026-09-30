#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_hf_providers_bge.py - QUI sert reellement `BAAI/bge-m3` derriere le routeur HF.

__FORGE_COLOR__ = "vegetatif/embedding : recense les fournisseurs qui servent bge-m3 via le routeur Hugging Face"

Contexte (2026-09-06). L'appel direct a `hf-inference` rend **402 : monthly included
credits depleted** -- normal, un compte Free ne recoit que **0,10 $/mois** (2 $ en PRO).
Mais Hugging Face n'est pas qu'un fournisseur : c'est un ROUTEUR vers une vingtaine de
plateformes, dont trois font du *feature extraction*. La question utile n'est donc pas
« HF a-t-il du credit » mais **« quel fournisseur sert bge-m3, et a quel prix »** -- avec
une nuance de facturation qui change tout :

  - requete ROUTEE par HF        -> facturee par HF, les credits mensuels s'appliquent ;
  - **cle fournisseur PERSONNELLE** -> facturee par le fournisseur, credits HF ignores.

La seconde voie permet donc d'utiliser un quota gratuit d'un fournisseur tiers SANS
dependre des 0,10 $ de HF. Encore faut-il savoir qui sert le modele : c'est ce que ce
script mesure, en interrogeant l'API publique du Hub (aucune cle requise, lecture seule).

    LAFORGE_PYTHON tools/forge_hf_providers_bge.py [--modele BAAI/bge-m3]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

# AMORCE DU CHEMIN : sans elle, `forge_secrets` (dans app/) est introuvable et le script
# rend « coffre illisible » -- ce qui se lit comme « pas de clef » alors que la clef est
# la. Meme famille que la migration de pouls du 2026-09-05 : un `sys.path` manquant tue
# un organe en silence. La portee compte, pas la presence.
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

BASE = "https://huggingface.co/api/models"


def _lire(url: str, timeout: float = 25.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "Nokido-forge/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _fournisseurs(modele: str) -> list[dict]:
    """Mapping fournisseur -> statut pour un modele. Liste vide = AUCUN, et on le DIT."""
    d = _lire(f"{BASE}/{modele}?expand%5B%5D=inferenceProviderMapping")
    m = (d or {}).get("inferenceProviderMapping") or []
    if isinstance(m, dict):  # forme historique {provider: {...}}
        m = [dict(v or {}, provider=k) for k, v in m.items()]
    return m


def catalogue_siliconflow() -> int:
    """Liste les modeles d'embedding servis par SiliconFlow (.com), clef au coffre.

    Mesure 2026-09-06 : `.cn` rend `401 Api key is invalid` et `.com` rend
    `400 Model does not exist` -- DEUX plateformes distinctes, comptes NON partages.
    Le 400 prouve que l'auth passe sur `.com` : reste a trouver le nom exact du modele,
    que seul le catalogue peut donner. Deviner un nom, c'est reproduire l'erreur.
    """
    try:
        from nokido_agent.app.forge_secrets import get_secret

        cle = get_secret("SILICONFLOW") or ""
    except Exception as e:  # noqa: BLE001
        # DIRE LEQUEL : un `ModuleNotFoundError` nu ne distingue pas « forge_secrets
        # absent du chemin » de « une dependance interne de forge_secrets manque ».
        print(f"coffre illisible ({type(e).__name__}: {e}) -- INDETERMINE")
        print(f"  sys.path[0:3] = {sys.path[:3]}")
        return 2
    if not cle:
        print("clef SILICONFLOW absente du coffre -- INDETERMINE")
        return 2
    for base in ("https://api.siliconflow.com", "https://api.siliconflow.cn"):
        url = f"{base}/v1/models?sub_type=embedding"
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + cle.strip()})
        try:
            with urllib.request.urlopen(req, timeout=30.0) as r:
                d = json.loads(r.read().decode("utf-8"))
            noms = [m.get("id") for m in (d.get("data") or [])]
            print(f"\n=== {base} : {len(noms)} modele(s) d'embedding ===")
            for n in noms:
                marque = "   <== bge-m3" if n and "bge-m3" in n.lower() else ""
                print("   ", n, marque)
        except urllib.error.HTTPError as e:
            print(f"\n=== {base} : HTTP {e.code} ===")
        except Exception as e:  # noqa: BLE001
            print(f"\n=== {base} : {type(e).__name__} -- INDETERMINE ===")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--siliconflow", action="store_true",
                    help="lister les modeles d'embedding servis par SiliconFlow")
    ap.add_argument("--modele", default="BAAI/bge-m3")
    ap.add_argument("--alternatives", action="store_true",
                    help="lister aussi les modeles d'embedding servis par au moins un fournisseur")
    a = ap.parse_args()
    if a.siliconflow:
        return catalogue_siliconflow()

    print(f"=== {a.modele} : fournisseurs derriere le routeur HF ===")
    try:
        fs = _fournisseurs(a.modele)
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} -- INDETERMINE (le Hub a refuse, ce n'est pas une absence)")
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"  {type(e).__name__}: {e} -- INDETERMINE, pas une absence")
        return 2

    if not fs:
        print("  AUCUN fournisseur ne sert ce modele via le routeur HF")
    for f in fs:
        print("  %-16s task=%-20s status=%-10s id=%s" % (
            f.get("provider", "?"), f.get("task", "?"), f.get("status", "?"),
            f.get("providerId", "?")))

    if a.alternatives:
        print("\n=== modeles d'embedding servis par au moins un fournisseur ===")
        print("(pour memoire : un autre modele = un AUTRE espace vectoriel, "
              "inutilisable tel quel dans rag_chunks)")
        try:
            lst = _lire(f"{BASE}?pipeline_tag=feature-extraction&inference_provider=all"
                        f"&sort=likes&limit=15")
            for m in lst or []:
                print("  %-52s likes=%s" % (m.get("id"), m.get("likes")))
        except Exception as e:  # noqa: BLE001
            print(f"  liste INDETERMINEE ({type(e).__name__})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
