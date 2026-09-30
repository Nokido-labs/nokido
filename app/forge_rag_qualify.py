# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_171156_cerberusok
#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: Args/Returns/Raises
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:cerberus-ok|temp:0.00|risk:0.40|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"
"""
forge_rag_qualify.py — Qualification intrinsèque des chunks RAG
===============================================================
Changement de paradigme : la sentinel ne fait plus que bloquer/autoriser.
Chaque chunk porte sa qualification comme donnée intrinsèque.

Principe :
  La donnée sait ce qu'elle est.
  Le moteur de recherche utilise cette qualification pour pondérer.
  La sentinel reste pour contrôler QUI peut écrire,
  mais ce COMMENT la donnée est qualifiée est séparé.

Structure de qualification (dans meta JSON) :
  ring            : int   — 0=SYSTEM 1=DEV 2=TRUSTED 3=COLLAB 4=UNTRUSTED
  ring_label      : str   — "SYSTEM"|"DEV"|"TRUSTED"|"COLLAB"|"UNTRUSTED"
  consensus_level : str   — "gold"|"verified"|"draft"|"raw"
  trust_score     : float — 0.0→1.0 (pondération dans search)
  mutable         : bool  — False = chunk ne peut pas être écrasé par ring >= 3
  verified_by     : list  — agents ayant validé (ex: ["nr_runner", "claude"])
  qualified_at    : str   — ISO timestamp
  origin_type     : str   — "document"|"session"|"disco"|"nr"|"code"|"system"

trust_score par consensus :
  gold     → 1.0   (SYSTEM/DEV — source de référence)
  verified → 0.8   (TRUSTED — workflow validé)
  draft    → 0.5   (COLLAB — à valider)
  raw      → 0.2   (UNTRUSTED — bruit possible)
"""


import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"

# ─────────────────────────────────────────────────────────────────────────────
# Constantes de qualification
# ─────────────────────────────────────────────────────────────────────────────

CONSENSUS_TRUST: Dict[str, float] = {
    "gold": 1.0,
    "verified": 0.8,
    "draft": 0.5,
    "raw": 0.2,
}

# Ring → consensus par défaut
RING_CONSENSUS: Dict[int, str] = {
    0: "gold",
    1: "gold",
    2: "verified",
    3: "draft",
    4: "raw",
}

# Règles de qualification par origine de source
# Utilisées pour la migration rétroactive des chunks sans auteur
SOURCE_RULES: List[Tuple[str, Dict]] = [
    # Sources système — toujours gold
    ("nr_report:", {"ring": 0, "consensus": "gold", "origin": "nr", "mutable": False}),
    ("system:", {"ring": 0, "consensus": "gold", "origin": "system", "mutable": False}),
    # Code source Nokido — gold (c'est la vérité du projet)
    ("session:self_code", {"ring": 0, "consensus": "gold", "origin": "code", "mutable": False}),
    # Documents de référence indexés manuellement — verified
    (".pdf", {"ring": 2, "consensus": "verified", "origin": "document", "mutable": True}),
    (".md", {"ring": 2, "consensus": "verified", "origin": "document", "mutable": True}),
    (".txt", {"ring": 2, "consensus": "verified", "origin": "document", "mutable": True}),
    # Sessions de conversation — draft (non vérifiées)
    ("session:", {"ring": 3, "consensus": "draft", "origin": "session", "mutable": True}),
    # Contenu web disco — draft
    ("disco:", {"ring": 3, "consensus": "draft", "origin": "disco", "mutable": True}),
]


# ─────────────────────────────────────────────────────────────────────────────
# Qualification d'un chunk individuel
# ─────────────────────────────────────────────────────────────────────────────


def qualify_chunk(
    source: str,
    author: str = "",
    meta: Optional[Dict] = None,
    text: str = "",
) -> Dict[str, Any]:
    """
    Détermine la qualification complète d'un chunk.

    Priorité de résolution :
      1. meta existant avec ring explicite → on complète seulement
      2. author avec prefixe ring (system:, dev:, workflow:...) → ring déduit
      3. SOURCE_RULES sur la source → règles par type de document
      4. Fallback → draft ring=3

    Retourne un dict à merger dans meta JSON du chunk.
    """
    meta = dict(meta) if meta else {}

    # 1. Déjà qualifié — compléter seulement les champs manquants
    if "ring" in meta and "consensus_level" in meta and "trust_score" in meta:
        return meta

    # 2. SOURCE a priorité sur author pour les sources à ring forcé
    # Ex: source=disco: force ring=3 même si author prétend system
    # Règle : si _from_source retourne ring < 3, l'author peut l'élever
    #         mais si source force ring=3 (disco:, session:), on ne descend jamais
    _src_ring, _src_cons, _src_origin, _src_mutable = _from_source(source)
    _FORCED_SOURCES = ("disco:", "session:")
    source_forces_ring = any((source or "").lower().startswith(p) for p in _FORCED_SOURCES)

    if source_forces_ring:
        # La source impose le ring — l'auteur ne peut pas le surclasser
        ring, consensus, origin, mutable = _src_ring, _src_cons, _src_origin, _src_mutable
    else:
        # Déduire depuis l'auteur (prefixe ring)
        ring, consensus, origin, mutable = _from_author(author)
        # Si auteur non conclusif, utiliser les règles source
        if ring is None:
            ring, consensus, origin, mutable = _src_ring, _src_cons, _src_origin, _src_mutable

    # 3. Calculer trust_score
    trust_score = CONSENSUS_TRUST.get(consensus, 0.2)

    # 4. Construire le patch
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    patch = {
        "ring": ring,
        "ring_label": _ring_label(ring),
        "consensus_level": consensus,
        "trust_score": trust_score,
        "mutable": mutable,
        "verified_by": meta.get("verified_by", []),
        "qualified_at": meta.get("qualified_at", now),
        "origin_type": origin,
    }

    # Conserver les clés existantes non-qualif
    for k, v in meta.items():
        if k not in patch:
            patch[k] = v

    # Quarantaine anti-poisoning (risque #1, foie/intestin) : contenu web flagge
    # injection par forge_crawl_tool -> trust plancher + flag, jamais consolide
    # ni range haut au retrieval. Additif ; le marqueur vient de forge_crawl_tool.
    if text and "CONTENU WEB NON-FIABLE" in text:
        patch["trust_score"] = 0.0
        patch["injection_flagged"] = True

    return patch


def _ring_label(ring: int) -> str:
    """Return the label corresponding to the ring number."""
    labels = ["SYSTEM", "DEV", "TRUSTED", "COLLAB", "UNTRUSTED"]
    return labels[ring] if 0 <= ring < len(labels) else "UNTRUSTED"


def _from_author(author: str) -> Tuple[Optional[int], str, str, bool]:
    """Déduit ring/consensus depuis le prefixe de l'auteur."""
    if not author:
        return None, "draft", "unknown", True
    a = author.lower().strip()
    prefix = a.split(":")[0] if ":" in a else a
    _MAP = {
        "system": (0, "gold", "system", False),
        "dev": (1, "gold", "dev", True),
        "workflow": (2, "verified", "workflow", True),
        "trusted": (2, "verified", "trusted", True),
        "audit": (2, "verified", "workflow", True),
        "ci": (2, "verified", "workflow", True),
        "collab": (3, "draft", "collab", True),
        "llm": (3, "draft", "collab", True),
        "laforge": (0, "gold", "system", False),
        "claude": (1, "gold", "dev", True),
        "cline": (2, "verified", "trusted", True),
        "ollama": (3, "draft", "collab", True),
    }
    if prefix in _MAP:
        return _MAP[prefix]
    return None, "draft", "unknown", True


def _from_source(source: str) -> Tuple[int, str, str, bool]:
    """Applique les SOURCE_RULES sur le nom de source."""
    s = (source or "").lower()
    for pattern, rules in SOURCE_RULES:
        if pattern in s:
            return (rules["ring"], rules["consensus"], rules["origin"], rules["mutable"])
    return 3, "draft", "unknown", True


# ─────────────────────────────────────────────────────────────────────────────
# Migration rétroactive en lot
# ─────────────────────────────────────────────────────────────────────────────


def migrate_qualify_all(db_path: Optional[Path] = None, dry_run: bool = False) -> Dict[str, int]:
    """
    Qualifie rétroactivement tous les chunks sans qualification.
    Opération idempotente — re-lancer est sûr.

    Returns:
        {"total": n, "updated": n, "already_qualified": n, "errors": n}
    """
    db = db_path or _DB
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")

    stats = {"total": 0, "updated": 0, "already_qualified": 0, "errors": 0}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    rows = conn.execute("SELECT id, source, author, meta FROM rag_chunks").fetchall()
    stats["total"] = len(rows)

    updates = []
    for chunk_id, source, author, meta_s in rows:
        try:
            meta = json.loads(meta_s) if meta_s else {}

            # Déjà qualifié ?
            if "trust_score" in meta and "ring" in meta and "consensus_level" in meta:
                stats["already_qualified"] += 1
                continue

            # Qualifier
            qualified = qualify_chunk(
                source=source or "",
                author=author or "",
                meta=meta,
            )
            qualified["qualified_at"] = now
            qualified["migration"] = True

            updates.append((json.dumps(qualified, ensure_ascii=False), chunk_id))

        except Exception as e:
            logger.debug(f"[qualify] chunk {chunk_id}: {e}")
            stats["errors"] += 1

    if updates and not dry_run:
        conn.executemany("UPDATE rag_chunks SET meta=? WHERE id=?", updates)
        conn.commit()

    stats["updated"] = len(updates)
    conn.close()

    logger.info(
        f"[qualify] migration: {stats['total']} chunks, "
        f"{stats['updated']} mis à jour, "
        f"{stats['already_qualified']} déjà qualifiés, "
        f"{stats['errors']} erreurs"
    )
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Pondération dans search()
# ─────────────────────────────────────────────────────────────────────────────


# Autorite par ORIGINE. La source de verite qui manquait a toute la chaine de
# confiance : `apply_trust_weight` lit `meta["trust_score"]`, absent de ~694k chunks
# sur 694k -> defaut 0.5 -> facteur x0.8 IDENTIQUE partout -> l'ordre ne bouge pas.
# Mesure 24-07 : 504 727 chunks de docsets tiers contre 99 de doctrine souveraine
# (5000:1), tous a epistemic_weight 0.498. Une recherche sur « attestation » rendait
# quatre pages Docker et aucune ligne de COGNITION.md, qui portait pourtant la
# reponse mot pour mot.
#
# Barème DELIBEREMENT modere (cf. docstring d'apply_trust_weight) : il corrige un
# prior d'origine, il n'ecrase pas la pertinence. Un docset tres pertinent doit
# encore pouvoir battre une doctrine hors-sujet.
_AUTHORITY: tuple[tuple[str, float], ...] = (
    # doctrine souveraine — fait foi sur « comment Nokido pense/agit »
    ("cognition.md", 1.0),
    ("rules_shared.md", 1.0),
    ("claude.md", 1.0),
    ("gemini.md", 1.0),
    # TRACE BRUTE d'activite (tool_calls indexes verbatim). Teste AVANT `session:` :
    # l'ordre compte, le premier prefixe qui matche gagne. Mesure 24-07 : une recherche
    # renvoyait en TETE `session:auto_CLAUDE_495806`, chunk contenant l'appel d'outil
    # ou la requete elle-meme figurait — le RAG rendait son propre echo avant la
    # doctrine. Une trace prouve QU'ON A FAIT, jamais QUE C'ETAIT JUSTE.
    ("session:auto_", 0.30),
    ("[tool_call]", 0.30),
    ("conv_claude", 0.35),
    ("conv_", 0.35),
    # experience vecue et VALIDEE (lecons, ancrages explicites)
    ("lessons_learned", 0.88),
    ("session:", 0.85),
    ("memory/", 0.85),
    # le corps lui-meme : le code fait autorite sur ce qu'il fait
    ("app/", 0.80),
    ("tools/", 0.80),
    ("proxy_deno/", 0.78),
    ("docs/", 0.75),
    # documentation TIERCE : utile, jamais prescriptive pour Nokido
    ("docset:", 0.45),
    ("http://", 0.35),
    ("https://", 0.35),
    ("web:", 0.35),
)
_AUTHORITY_DEFAUT = 0.60


def trust_weight(source: str) -> float:
    """Autorite d'une source, dans [0, 1] — contrat attendu par forge_rag_introspect.

    Repond a « qui parle ? », jamais a « est-ce pertinent ? ». La pertinence reste
    le travail du reranker ; ceci ne fait que departager a pertinence comparable.
    """
    # Normaliser les separateurs AVANT de comparer : les sources ingerees sous
    # Windows portent des antislashs (`app\forge_agent_proxy.py`) et rataient les
    # prefixes ecrits en slash. Mesure 24-07 : 1317 chunks de code et de docs Nokido
    # retombaient au defaut faute de ce seul caractere.
    s = (source or "").lower().replace("\\", "/").lstrip("./")
    for prefixe, poids in _AUTHORITY:
        if prefixe in s:
            return poids
    # Source DEGRADEE : l'ingestion a pris un fragment de contenu pour un nom.
    # Mesure 24-07 : ~14k chunks portent « == », « ==== », « # SECTION »,
    # « Directory structure », ou rien du tout. Une source qui ne designe aucun
    # fichier, aucune URL et aucun espace de noms ne permet pas de savoir qui parle
    # — on ne peut pas lui accorder l'autorite du doute. Le remede de fond est
    # cote ingestion ; ceci evite qu'un artefact prime sur une source identifiee.
    if not any(marqueur in s for marqueur in ("/", ":", ".")):
        return 0.35
    # Meme artefact, deguise : « Directory structure: », « # SECTION: ctf/ (447 files) »,
    # « Cree le 2026-04-25 dans le cadre du durcissement... » passent le test ci-dessus
    # grace a un « : » ou un « . » de PROSE. Une vraie source ne contient pas d'espace
    # sans porter d'extension de fichier.
    if " " in s:
        _base = s.rsplit("#", 1)[0]
        _ext = _base.rsplit(".", 1)[-1] if "." in _base else ""
        if not (0 < len(_ext) <= 5 and _ext.isalnum()):
            return 0.35
    return _AUTHORITY_DEFAUT


def apply_trust_weight(
    base_score: float,
    meta: Dict,
    min_consensus: str = "",
) -> Tuple[float, bool]:
    """
    Applique le trust_score au score de similarité.
    Retourne (weighted_score, include).

    min_consensus : si fourni, exclut les chunks en dessous de ce niveau.
      Ex: min_consensus="verified" → exclut draft et raw.

    Pondération :
      weighted = base_score * (0.6 + 0.4 * trust_score)
      → gold    : ×1.0  (0.6 + 0.4×1.0)
      → verified: ×0.92 (0.6 + 0.4×0.8)
      → draft   : ×0.80 (0.6 + 0.4×0.5)
      → raw     : ×0.68 (0.6 + 0.4×0.2)

    La pondération est intentionnellement modérée pour ne pas écraser
    un chunk draft très pertinent face à un chunk gold hors-sujet.
    """
    trust = meta.get("trust_score", 0.5)
    consensus = meta.get("consensus_level", "draft")

    # Filtre min_consensus
    if min_consensus:
        _ORDER = {"gold": 0, "verified": 1, "draft": 2, "raw": 3}
        if _ORDER.get(consensus, 3) > _ORDER.get(min_consensus, 3):
            return 0.0, False

    weighted = base_score * (0.6 + 0.4 * trust)
    return round(weighted, 6), True


def consensus_filter(
    chunks: List[Dict],
    min_consensus: str = "",
    max_ring: int = 4,
) -> List[Dict]:
    """
    Filtre une liste de chunks par niveau de confiance minimum.

    Args:
        chunks:        liste de chunks (avec meta qualifiée)
        min_consensus: "gold"|"verified"|"draft"|"raw" (vide = pas de filtre)
        max_ring:      ring maximum accepté (0=SYSTEM seul, 4=tous)

    Usage dans @rag :
        docs = consensus_filter(docs, min_consensus="verified")
        # → exclut les draft et raw des résultats d'audit
    """
    if not min_consensus and max_ring >= 4:
        return chunks

    _ORDER = {"gold": 0, "verified": 1, "draft": 2, "raw": 3}
    min_order = _ORDER.get(min_consensus, 4)

    result = []
    for c in chunks:
        meta = c.get("meta_parsed") or {}
        consensus = meta.get("consensus_level", "draft")
        ring = meta.get("ring", 3)
        if _ORDER.get(consensus, 3) <= min_order and ring <= max_ring:
            result.append(c)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers pour le MCP server (rag_ingest + rag_search)
# ─────────────────────────────────────────────────────────────────────────────


def qualify_for_ingest(
    text: str,
    source: str,
    domain: str,
    author: str,
) -> Dict[str, Any]:
    """
    Construit le meta dict complet pour une ingestion MCP.
    Appelé juste avant INSERT dans rag_chunks.
    """
    return qualify_chunk(source=source, author=author, text=text)


def enrich_search_result(result: Dict, raw_meta: str) -> Dict:
    """
    Enrichit un résultat de recherche avec les champs de qualification.
    Appelé après SELECT dans rag_search.
    """
    try:
        meta = json.loads(raw_meta) if raw_meta else {}
    except Exception:
        meta = {}
    result["trust_score"] = meta.get("trust_score", 0.5)
    result["consensus_level"] = meta.get("consensus_level", "draft")
    result["ring"] = meta.get("ring", 3)
    result["ring_label"] = meta.get("ring_label", "COLLAB")
    result["mutable"] = meta.get("mutable", True)
    return result
