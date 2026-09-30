#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Demande a GitHub ce que chaque token peut REELLEMENT faire.

Deux PAT `github_pat_...` de 93 caracteres sont indiscernables a l'oeil : meme
prefixe, meme longueur, et le nom sous lequel ils sont ranges n'est qu'une
etiquette posee par un humain presse. Le 2026-08-18, cette confusion a coute un
secret ecrase — le nom du `.env` disait `GITHUB_TOKEN`, la valeur etait un
jeton Models. Aucune inspection locale ne peut trancher : seul le porteur des
droits sait ce qu'il accorde.

La sonde interroge donc trois surfaces et rapporte des CODES, jamais des
valeurs :
  * `GET /user`                       -> identite (login), si le jeton la porte
  * `GET /repos/<owner>/<repo>`       -> acces DEPOT (200 = oui)
  * `GET models.github.ai/catalog/models` -> acces MODELS

ANGLE MORT, mesure le 2026-08-18 : la colonne MODELS a rendu **410 Gone pour
les trois jetons testes**, y compris un jeton Models valide et un jeton revoque.
Cet endpoint ne discrimine donc RIEN — le catalogue a bouge. La sonde tranche
aujourd'hui par la colonne DEPOT (200 vs 404), qui, elle, a separe proprement le
PAT depot du jeton Models. Ne pas lire un 410 comme « pas de droit models ».

Lecture seule : aucun de ces appels n'ecrit quoi que ce soit chez GitHub.

Sources testees automatiquement (aucun argument : `run_job` n'en transmet pas) :
les cles GitHub du coffre, et la ligne active du `.env` si elle existe encore.

Usage :
    run action=run_job script=tools/forge_token_probe.py online=true
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/secret : ce que chaque jeton GitHub peut reellement faire"  # organe declare le 2026-09-06 (audit de raccordement)

import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEPOT = "user/nokido"
CLES_COFFRE = ("GITHUB_TOKEN", "GITHUB_MODELS_TOKEN")
TIMEOUT = 15


def empreinte(valeur: str) -> str:
    return hashlib.sha256(valeur.encode("utf-8")).hexdigest()[:12] if valeur else ""


def _appel(url: str, jeton: str, charge: bytes | None = None) -> tuple[int, str]:
    """(code HTTP, detail court). Jamais le jeton, jamais le corps complet."""
    entetes = {
        "Authorization": f"Bearer {jeton}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "nokido-token-probe",
    }
    if charge is not None:
        entetes["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=charge, headers=entetes)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            corps = r.read(4096).decode("utf-8", errors="replace")
            detail = ""
            try:
                obj = json.loads(corps)
                if isinstance(obj, dict):
                    choix = obj.get("choices")
                    if isinstance(choix, list) and choix:
                        detail = "inference OK"
                    else:
                        detail = str(obj.get("login") or obj.get("full_name")
                                     or obj.get("total_count") or "")
                elif isinstance(obj, list):
                    detail = f"{len(obj)} entree(s)"
            except ValueError:
                detail = ""
            return r.status, detail
    except urllib.error.HTTPError as exc:
        return exc.code, exc.reason or ""
    except Exception as exc:  # noqa: BLE001 - reseau ferme, DNS, TLS
        return -1, type(exc).__name__


def sources() -> list[tuple[str, str]]:
    """[(etiquette, valeur)] — coffre d'abord, puis la ligne encore en clair."""
    from nokido_agent.app.forge_machine_vault import vault_get

    out: list[tuple[str, str]] = []
    for cle in CLES_COFFRE:
        val = vault_get(cle) or ""
        if val:
            out.append((f"coffre:{cle}", val))
    for nom in ("Nokido.env", "nokido.env"):
        env = ROOT / nom
        if not env.exists():
            continue
        for i, ligne in enumerate(env.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = ligne.strip()
            if s.startswith("#") or "=" not in s:
                continue
            cle, _, val = s.partition("=")
            if "GITHUB" in cle.upper() and val.strip():
                out.append((f"{nom}:{i}:{cle.strip()}", val.strip()))
        break
    return out


# Endpoints MODELS : le catalogue a bouge plusieurs fois et un 410 sur l'un ne
# dit RIEN de la capacite reelle. Seule une inference qui repond tranche.
_MODELS = [
    ("catalog.github.ai", "https://models.github.ai/catalog/models", None),
    ("inference.azure", "https://models.inference.ai.azure.com/models", None),
    ("api.github/models", "https://api.github.com/models", None),
    ("INFERENCE reelle", "https://models.github.ai/inference/chat/completions",
     json.dumps({"model": "openai/gpt-4o-mini",
                 "messages": [{"role": "user", "content": "ping"}],
                 "max_tokens": 1}).encode("utf-8")),
]


def main() -> int:
    cands = sources()
    if not cands:
        print("aucun jeton GitHub trouve (coffre vide, .env sans ligne active)")
        return 1
    print(f"{'source':40} {'empreinte':14} {'/user':22} {'depot':10}")
    for etiquette, valeur in cands:
        cu, du = _appel("https://api.github.com/user", valeur)
        cr, _dr = _appel(f"https://api.github.com/repos/{DEPOT}", valeur)
        print(f"{etiquette:40} {empreinte(valeur):14} {f'{cu} {du}'[:21]:22} {cr:<10}")

    print("\n--- surfaces MODELS (le point conteste) ---")
    for etiquette, valeur in cands:
        print(f"  {etiquette} ({empreinte(valeur)})")
        for nom, url, charge in _MODELS:
            code, detail = _appel(url, valeur, charge)
            print(f"     {nom:20} {code:<6} {detail[:60]}")

    print("\n200 = accorde · 401 = jeton refuse · 403/404 = pas ce droit")
    print("410 = endpoint retire · -1 = reseau ferme (NON mesure, pas un refus)")
    print("Aucune valeur de jeton n'a ete affichee ni journalisee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
