#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Socle commun des sondes d'endpoints — interroger, lister, trier.

Quatre sondes ecrites le 2026-08-18 (`forge_provider_catalogue`,
`forge_endpoint_profiling`, `forge_tool_call_probe`, `forge_free_tier_census`,
`forge_local_llm_bringup`) ont reinvente les memes trois gestes : construire une
requete authentifiee, lire un catalogue `/models`, trier les modeles par taille.
Le cliquet de duplication les a groupees en deux paquets de clones — et il avait
raison : la punition de la semaine etait precisement d'avoir empile des outils
sans les factoriser.

Ce module porte les gestes partages. Ce qu'il ne porte PAS, volontairement :
l'interpretation. Chaque sonde decide seule ce qu'un 402 ou un texte vide
signifie pour SA question — c'est la que se joue la difference entre MORT et
NON_MESURE, et elle n'est pas la meme pour un catalogue, un appel d'outil ou une
mise en route locale.
"""
from __future__ import annotations

__FORGE_COLOR__ = "metabolisme/provider : socle commun des sondes d'endpoints LLM"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import re
import urllib.error
import urllib.request

TIMEOUT = 30

# Ni generation de texte, ni chat : les sonder ferait des 404 qu'on lirait
# comme des pannes.
ECARTES = ("embed", "bge-", "nomic", "whisper", "tts", "clip", "guard",
           "rerank", "moderation", "asr", "image", "vision", "moondream", "llava")


def requete(url: str, cle: str = "", charge: bytes | None = None,
            agent: str = "nokido-sonde") -> urllib.request.Request:
    """Requete authentifiee. La cle voyage en EN-TETE, jamais dans l'URL."""
    entetes = {"User-Agent": agent}
    if cle:
        entetes["Authorization"] = f"Bearer {cle}"
    if charge is not None:
        entetes["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=charge, headers=entetes)


def lire(url: str, cle: str = "", charge: bytes | None = None,
         timeout: int = TIMEOUT, taille_max: int = 400_000) -> tuple[int, str, dict]:
    """(code HTTP, corps, en-tetes). -1 = injoignable, jamais confondu avec un refus."""
    try:
        with urllib.request.urlopen(requete(url, cle, charge), timeout=timeout) as r:
            return r.status, r.read(taille_max).decode("utf-8", errors="replace"), dict(r.headers)
    except urllib.error.HTTPError as exc:
        corps = ""
        try:
            corps = exc.read(500).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - corps illisible
            corps = exc.reason or ""
        return exc.code, corps, dict(getattr(exc, "headers", {}) or {})
    except Exception as exc:  # noqa: BLE001 - DNS, TLS, port ferme
        return -1, f"{type(exc).__name__}", {}


def catalogue(base: str, cle: str = "", timeout: int = TIMEOUT) -> tuple[int, list[dict], dict]:
    """(code, modeles, en-tetes). Les en-tetes portent parfois le quota."""
    code, corps, entetes = lire(f"{base.rstrip('/')}/models", cle, timeout=timeout)
    if code != 200:
        return code, [], entetes
    try:
        brut = json.loads(corps)
    except ValueError:
        return code, [], entetes
    donnees = brut.get("data") if isinstance(brut, dict) else brut
    return code, [m for m in (donnees or []) if isinstance(m, dict)], entetes


def taille_apparente(identifiant: str) -> float:
    """Milliards de parametres lus dans le nom (1.5b, 7b, 405b), sinon 999.

    Sert a preferer les PETITS : prouver qu'un service repond avec un 7B a froid
    demande plus de 240 s, le meme service repond en 4 s avec un 1.5B.
    """
    trouve = re.findall(r"(\d+(?:\.\d+)?)\s*b\b", identifiant.lower())
    return min((float(x) for x in trouve), default=999.0)


def utiles(modeles: list[dict]) -> list[dict]:
    """Modeles de generation seulement — embeddings et audio ecartes."""
    return [m for m in modeles
            if not any(mot in str(m.get("id", "")).lower() for mot in ECARTES)]


def plus_petits(modeles: list[dict], combien: int) -> list[dict]:
    return sorted(utiles(modeles), key=lambda m: taille_apparente(str(m.get("id", ""))))[:combien]
