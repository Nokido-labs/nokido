#!/usr/bin/env python3
"""
forge_domain_mapper.py — Du verbe et de la cible au DOMAINE, sans appel LLM.

POURQUOI
========
`forge_intent_parser.parse_intent` extrait deja `action`, `target`, `verbs`,
`entities`. Ce qui manquait : en deduire le DOMAINE metier, pour que
`anchor_solution(domain=...)` soit rempli automatiquement et que les regles d'or
du bon domaine soient injectees. Deduction pure, O(1), zero latence.

REUTILISER, PAS INVENTER
========================
Nokido a DEJA sa taxonomie de domaines : `forge_silo_engine.SiloDomain`, **six**
valeurs (code, security, strategy, synthesis, recon, doc). On
l'importe. Definir une liste concurrente (security/network/refactoring/infra)
creerait une SECONDE taxonomie contredisant la premiere — motif d'echec deja paye
deux fois : deux mecanismes d'intention (2026-07-26, cerveau codeur tue 5 fois) et
la tentation d'un second collecteur de traces (2026-08-12).

Depuis la separation offensif/defensif (1c, 2026-08-22), SiloDomain a SIX valeurs
defensives (EXPLOIT/CTF partis vers la zone lab bornee). C'est le code qui fait foi.

AMORCE DERIVEE
==============
Les mots-cles `security` ne sont pas tous ecrits a la main : tout outil dont le
ring minimal est <= 2 dans `_TOOL_MIN_RING` est STRUCTURELLEMENT sensible
(`write` et `set_mode` sont a 0, donc reserves au ring MASTER). Leurs noms
alimentent le domaine security sans qu'on ait a en juger.

TROIS ETATS, PAS DEUX
=====================
Aucune correspondance -> liste VIDE, jamais un domaine par defaut. Un defaut qui
ressemble a une deduction est indistinguable d'une vraie — c'est la pathologie
corrigee cinq fois le 2026-08-12 (« ABSENTE » au lieu d'« INDETERMINE »).
L'appelant decide alors : ancres generiques, ou demander.

USAGE
=====
    from forge_domain_mapper import deduire_domaines
    doms = deduire_domaines(verbe="bloquer", cible="port 80", entites=["docker"])
    # -> ["security"]   (verbe +3 l'emporte sur cible +2)
"""

from __future__ import annotations

__FORGE_COLOR__ = "cerveau/intent : du verbe et de la cible vers le domaine, sans LLM"  # organe declare le 2026-09-06 (audit de raccordement)

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Poids : le VERBE porte l'intention, la cible n'est que le sujet, les entites le
# decor. « bloquer le port 80 » est de la securite, pas du reseau.
POIDS_VERBE, POIDS_CIBLE, POIDS_ENTITE = 3, 2, 1

# Criticite decroissante — sert UNIQUEMENT a trier les ex aequo, jamais a en
# eliminer : on rend tous les domaines a egalite (multi-tag).
PRIORITE = ["security", "recon", "code", "strategy", "synthesis", "doc"]

# Mots-cles par domaine. Ecrits a la main faute de source derivable — sauf
# `security`, complete par les outils a ring bas (cf. `_amorce_sensibles`).
MOTS: dict[str, set[str]] = {
    "code": {"refactor", "lint", "typing", "module", "fonction", "classe",
             "import", "patch", "diff", "commit", "test", "bug"},
    "security": {"auth", "token", "secret", "credential", "firewall", "tls",
                 "crypto", "ring", "membrane", "dlp", "acl", "privilege",
                 "vault", "dpapi", "sandbox"},
    "strategy": {"architecture", "roadmap", "decision", "plan", "priorite",
                 "arbitrage", "jalon", "milestone"},
    "synthesis": {"resume", "synthese", "rapport", "fusion", "digest", "bilan"},
    "recon": {"scan", "reseau", "dns", "port", "netcfg", "osint", "inventaire",
              "topologie", "socket", "proxy", "gateway"},
    "doc": {"doc", "readme", "documentation", "explication", "schema",
            "diagramme", "changelog"},
}

# Verbes par domaine — signal le plus fort.
VERBES: dict[str, set[str]] = {
    "code": {"refactor", "corrig", "implement", "cod", "patch", "nettoy",
             "renomm", "test"},
    "security": {"securis", "chiffr", "bloqu", "proteg", "audit", "durci",
                 "caviard", "revoqu", "isol"},
    "strategy": {"planifi", "arbitr", "prioris", "decid", "concev", "cadr"},
    "synthesis": {"resum", "synthetis", "fusionn", "condens", "agreg"},
    "recon": {"scann", "sond", "inventori", "cartographi", "explor", "mesur"},
    "doc": {"document", "expliqu", "dessin", "redig", "illustr"},
}


# ── Corrections apprises ────────────────────────────────────────────────────
# `forge_nlu.CorrectionHistory` existe deja, mais elle est EN MEMOIRE SEULE
# (`List[CorrectionEntry]`, maxlen 200, aucune persistance) : branche telle quelle,
# toute correction mourrait au premier redemarrage du hub. On en reutilise la FORME
# — text / predicted / correct / ts / features — avec un stockage sur disque, sinon
# l'apprentissage n'existe pas. Une correction non persistee n'est pas un apprentissage,
# c'est un oubli differe.
CORRECTIONS = ROOT / "sandbox" / "domain_corrections.json"


def _cle(verbe: str, cible: str) -> str:
    return f"{' '.join(_tokens(verbe or ''))}|{' '.join(_tokens(cible or ''))}"


def _charger_corrections() -> dict[str, list[str]]:
    if not CORRECTIONS.exists():
        return {}
    try:
        doc = json.loads(CORRECTIONS.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"[domain_mapper] corrections illisibles ({type(e).__name__}) — ignorees",
              flush=True)
        return {}
    return {e["cle"]: e["correct"] for e in doc.get("entries", []) if e.get("cle")}


def apprendre(verbe: str, cible: str, entites: list | None,
              correct: list[str]) -> dict:
    """Enregistre une correction owner : « ce cas-la, c'est CE domaine ».

    Rend la correction relisible et rejouable, contrairement a un ajustement de
    mots-cles qu'on ne saurait pas justifier six mois plus tard.
    """
    doc = {"entries": []}
    if CORRECTIONS.exists():
        try:
            doc = json.loads(CORRECTIONS.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass  # muet-ok : fichier corrompu -> on repart d'un doc neuf, signale au retour
    predit = deduire_domaines(verbe, cible, entites, _sans_corrections=True)
    doc.setdefault("entries", []).append({
        "cle": _cle(verbe, cible), "text": f"{verbe} {cible}"[:200],
        "predicted": predit, "correct": correct,
        "features": [str(e)[:40] for e in (entites or [])], "ts": time.time(),
    })
    CORRECTIONS.parent.mkdir(parents=True, exist_ok=True)
    CORRECTIONS.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    _CORR.clear()
    _CORR.update(_charger_corrections())
    return {"ok": True, "predit": predit, "correct": correct, "n": len(doc["entries"])}


def _tokens(terme: str) -> list[str]:
    """Decoupe en mots. `auth_token` -> ['auth','token'], `port 80` -> ['port','80']."""
    return [t for t in re.split(r"[^a-z0-9]+", terme.lower()) if t]


def _matche(terme: str, motifs: set[str]) -> bool:
    """Vrai si un motif est PREFIXE d'un token du terme.

    Pas `motif in terme` : la sous-chaine attrape aussi les mots qui CONTIENNENT
    le motif. Mesure du 2026-08-12 : « rapport » matchait « port », donc
    « resumer le rapport » sortait en `recon`. Le prefixe de token garde la
    tolerance utile (`auth_token` -> `auth`, `refactoring` -> `refactor`) et
    supprime ce faux positif.
    """
    toks = _tokens(terme)
    return any(t.startswith(m) for t in toks for m in motifs)


def _amorce_sensibles() -> set[str]:
    """Outils structurellement sensibles, deduits de la table des rings.

    Un ring minimal BAS = moins d'agents y ont droit = plus sensible
    (`write` et `set_mode` sont a 0, donc MASTER seulement). Aucune appreciation
    humaine ici : c'est la politique d'acces qui parle.
    """
    try:
        from nokido_agent.app.forge_mcp_registry import ToolRegistry
        table = getattr(ToolRegistry, "_TOOL_MIN_RING", {})
    except Exception:  # noqa: BLE001 — amorce absente, on garde la liste ecrite
        return set()
    return {str(n).lower() for n, r in table.items() if isinstance(r, int) and r <= 2}


_SENSIBLES = _amorce_sensibles()
_CORR: dict[str, list[str]] = _charger_corrections()


def _domaines_connus() -> list[str]:
    """Les valeurs de `SiloDomain`, source de verite. Repli sur PRIORITE."""
    try:
        from nokido_agent.app.forge_silo_engine import SiloDomain
        return [d.value for d in SiloDomain]
    except Exception:  # noqa: BLE001
        return list(PRIORITE)


def deduire_domaines(verbe: str = "", cible: str = "",
                     entites: list | None = None,
                     _sans_corrections: bool = False) -> list[str]:
    """Domaines pertinents, tries par criticite. Liste VIDE si rien ne matche.

    Ne rend jamais un domaine par defaut : l'absence de deduction doit se voir.
    Une correction apprise sur le meme (verbe, cible) prime sur le calcul.
    """
    if not _sans_corrections:
        corr = _CORR.get(_cle(verbe, cible))
        if corr:
            return list(corr)
    scores: dict[str, int] = {d: 0 for d in _domaines_connus()}

    v = (verbe or "").lower()
    if v:
        for dom, racines in VERBES.items():
            if dom in scores and _matche(v, racines):
                scores[dom] += POIDS_VERBE

    termes: list[tuple[str, int]] = []
    if cible:
        termes.append((str(cible).lower(), POIDS_CIBLE))
    termes += [(str(e).lower(), POIDS_ENTITE) for e in (entites or []) if e]

    for terme, poids in termes:
        for dom, mots in MOTS.items():
            if dom in scores and _matche(terme, mots):
                scores[dom] += poids
        # Amorce derivee : citer un outil a ring bas oriente vers la securite.
        if "security" in scores and _matche(terme, _SENSIBLES):
            scores["security"] += poids

    maxi = max(scores.values()) if scores else 0
    if maxi == 0:
        return []  # PAS de defaut : « je n'ai pas deduit » doit rester lisible
    # Multi-tag ELARGI : on retient le vainqueur ET tout domaine substantiellement
    # present (nomme par la cible, ou par deux entites). Le seul ex aequo strict
    # etait trop etroit : « refactoriser le module auth » est du code — le verbe
    # porte l'intention — mais toucher a `auth` a des implications de securite, et
    # les regles d'or des DEUX domaines doivent etre injectees. Un tag de trop ne
    # coute qu'une ancre ; un tag manquant coute une regle non appliquee.
    retenus = [d for d, s in scores.items() if s == maxi or s >= POIDS_CIBLE]
    retenus.sort(key=lambda d: PRIORITE.index(d) if d in PRIORITE else 99)
    return retenus


def _selftest() -> int:
    cas = [
        ({"verbe": "bloquer", "cible": "port 80", "entites": ["docker"]}, "security"),
        ({"verbe": "scanner", "cible": "reseau local", "entites": []}, "recon"),
        # code l'emporte (verbe +3) mais security est retenu en second : toucher
        # a `auth` doit injecter les regles de securite, meme si l'acte est du code.
        ({"verbe": "refactoriser", "cible": "module auth", "entites": []}, "security"),
        ({"verbe": "resumer", "cible": "rapport", "entites": []}, "synthesis"),
        ({"verbe": "", "cible": "", "entites": []}, None),
    ]
    ko = 0
    for args, attendu in cas:
        got = deduire_domaines(**args)
        ok = (got[0] if got else None) == attendu
        ko += 0 if ok else 1
        print(f"  {'OK ' if ok else 'KO '} {args} -> {got or 'aucun'} (attendu {attendu})")
    print(f"[domain_mapper] {len(cas) - ko}/{len(cas)} · amorce sensibles={len(_SENSIBLES)}")
    return 1 if ko else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(_selftest())
