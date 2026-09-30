"""forge_explore_rank.py — classement des extraits de recon AVANT la coupe du digest.

Défaut mesuré le 2026-08-02 : `forge_deep_explore` construisait son digest avec
`hits[:60]`, soit les 60 PREMIERS dans l'ordre de parcours des fichiers (alphabétique),
sans aucun classement. Une recherche large (`check_`, qui matche `check_access`,
`check_competence`, `check_write`…) remplissait donc tout le budget avec
`forge_access_switches`, `forge_active_inference`, `forge_agentic`… et n'atteignait
jamais le module cherché : 90 hits, digest inutilisable, et l'agent qui repart en
lectures natives — exactement la fuite de tokens que ce tool existe pour éviter.

Le tri est DÉTERMINISTE : zéro token, zéro embedding, zéro appel LLM. Un reranking
sémantique serait ici hors de proportion — le signal est déjà dans le nom du fichier et
la nature de la ligne.

Vit hors de `forge_mcp_registry` (CRITICAL_FILE) pour deux raisons : le registre garde un
patch de trois lignes, et cette logique devient testable en isolé.
"""

from __future__ import annotations

import re

__FORGE_COLOR__ = "cognition/attention-selective"

_MOT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def score(hit: dict, termes: set[str]) -> int:
    """Pertinence d'un extrait. Le nom du fichier prime, la prose vient en dernier."""
    chemin = str(hit.get("file") or "").lower().replace("\\", "/")
    base = chemin.rsplit("/", 1)[-1]
    extrait = str(hit.get("excerpt") or "")
    nu = extrait.strip()
    s = 0
    if any(t in base for t in termes):
        s += 4
    if nu.startswith(("def ", "class ", "async def ")):
        s += 3
    elif any(t in extrait.lower() for t in termes):
        s += 1
    if nu.startswith(("#", '"""', "'''", "*")):
        s -= 2  # prose : informative, mais jamais avant le code qu'elle décrit
    return s


def classer(hits: list[dict], query: str, par_fichier: int = 3, plafond: int = 60) -> list[dict]:
    """Classe puis coupe, en bornant la part de chaque fichier.

    `par_fichier` empêche un seul module bavard d'absorber tout le budget : à budget
    égal, vingt fichiers vus valent mieux que six. `sorted` étant stable, l'ordre
    alphabétique subsiste à score égal — le résultat reste reproductible.
    """
    termes = {m.group(0).lower() for m in _MOT.finditer(query or "")}
    vus: dict[str, int] = {}
    retenus: list[dict] = []
    for h in sorted(hits, key=lambda x: -score(x, termes)):
        f = str(h.get("file") or "")
        if vus.get(f, 0) >= par_fichier:
            continue
        vus[f] = vus.get(f, 0) + 1
        retenus.append(h)
        if len(retenus) >= plafond:
            break
    return retenus
