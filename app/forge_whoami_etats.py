# -*- coding: utf-8 -*-
"""Etats de `hub action=whoami` : VRAI, FAUX ou ILLISIBLE, jamais deduits d'un silence.

Module pur : le handler lui passe ce qu'il a deja lu, rien n'est sonde ici. Classement par liste BLANCHE : un groupe
n'est VRAI que si TOUS ses elements sont prouves ; une mesure perimee est ILLISIBLE, jamais FAUX ; le statut du
superviseur est une DECLARATION, d'ou `preuve: DECLARE` et aucun age tant que rien ne le mesure.
"""
from __future__ import annotations

__FORGE_COLOR__ = "observabilite/etats-whoami"

import re

# Clients dont on sait qu'ils parlent au hub ; `AGY` et `ANTIGRAVITY` sont le meme.
_AGENTS_ATTENDUS = ("CLAUDE", "ANTIGRAVITY", "CODEX", "CLINE", "VIBE", "MISTRAL", "OPENCODE_GLM")
_ALIAS = {"AGY": "ANTIGRAVITY"}
_MAX_EXECUTEURS = 12
_RE_MORT = re.compile(r"prouve mort|slot perime", re.I)
_NATURES = {"disabled": "POLITIQUE", "sleeping": "A_LA_DEMANDE", "stopped": "ARRETE",
            "crashed": "PANNE", "error": "PANNE", "failed": "PANNE", "quarantine": "PANNE"}


def _global(items: list) -> str:
    """Liste blanche : VRAI seulement si tout est prouve ; sinon ILLISIBLE, ou FAUX si TOUT est prouve faux."""
    etats = {i["etat"] for i in items}
    if etats == {"VRAI"}:
        return "VRAI"
    if etats == {"FAUX"}:
        return "FAUX"
    return "ILLISIBLE"


def _providers(vivants, ecartes) -> dict:
    items = [{"nom": str(p.get("model") or p.get("provider") or p) if isinstance(p, dict) else str(p),
              "etat": "VRAI", "preuve": "DECLARE"} for p in (vivants or [])]
    for nom, motif in (ecartes or {}).items():
        items.append({"nom": str(nom), "etat": "FAUX" if _RE_MORT.search(str(motif)) else "ILLISIBLE",
                      "motif": str(motif)[:80]})
    if not items:
        return {"etat": "ILLISIBLE", "raison": "aucune mesure de provider", "items": []}
    return {"etat": _global(items), "items": items}


def _agents(online, m2m_etat: str = "OK") -> dict:
    vus = {}
    for brute in online or []:
        ligne = brute if isinstance(brute, dict) else dict(brute) if hasattr(brute, "keys") else {}
        nom = str(ligne.get("agent") or ligne.get("from_agent") or "").upper().replace("AGT_", "")
        if nom:
            vus[_ALIAS.get(nom, nom)] = ligne
    items = []
    base_lue = (m2m_etat == "OK")
    for nom in _AGENTS_ATTENDUS:
        if nom in vus:
            items.append({"agent": nom, "etat": "VRAI", "last": vus[nom].get("last"), "preuve": "DECLARE"})
        else:
            raison = ("aucun message dans la fenetre, absence non prouvee" if base_lue
                      else "base M2M non lue (%s)" % m2m_etat)
            items.append({"agent": nom, "etat": "ILLISIBLE", "raison": raison})
    return {"etat": _global(items), "items": items}


def _executeurs(services) -> dict:
    if not isinstance(services, dict):
        return {"etat": "ILLISIBLE", "raison": "superviseur injoignable", "items": [], "coupes": 0}
    noms = sorted(n for n in services if str(n).startswith("NokidoTaskExecutor"))
    items = []
    for nom in noms[:_MAX_EXECUTEURS]:
        sv = services[nom] if isinstance(services[nom], dict) else {}
        statut = str(sv.get("status") or "")
        if statut in ("running", "starting"):
            items.append({"service": nom, "etat": "VRAI", "preuve": "DECLARE", "restarts": sv.get("restarts")})
        elif statut in _NATURES:
            items.append({"service": nom, "etat": "FAUX", "nature": _NATURES[statut]})
        else:
            items.append({"service": nom, "etat": "ILLISIBLE", "nature": "INCONNU", "statut": statut or None})
    if not items:
        return {"etat": "ILLISIBLE", "raison": "aucun executeur au superviseur", "items": [], "coupes": 0}
    return {"etat": _global(items), "items": items, "coupes": max(0, len(noms) - _MAX_EXECUTEURS)}


def etats_whoami(providers_vivants, providers_ecartes, online, services, m2m_etat: str = "OK") -> dict:
    """Bloc `status_etats` : chaque groupe avec son etat ; ce qui n'est pas lu se dit ILLISIBLE."""
    return {
        "providers": _providers(providers_vivants, providers_ecartes),
        "agents_pairs": _agents(online, m2m_etat=m2m_etat),
        "executeurs": _executeurs(services),
        "refus_recents": {"etat": "ILLISIBLE", "raison": "refus des gardes non journalises par client"},
    }
