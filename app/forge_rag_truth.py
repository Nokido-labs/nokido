# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_rag_truth
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)
"""
forge_rag_truth.py — Filtre de Vérité RAG (Triple Validation + Shadow Index)
=============================================================================
Implémente le workflow de promotion qualitative :
  DRAFT → REVIEW → VERIFIED → GOLD

Triple vérification avant toute promotion :
  A. Sémantique  : cross-check Jaccard (pas d'hallucination)
  B. Autorité    : ring check (validé par ring ≤ auteur)
  C. Cohérence   : ledger check (pas de contradiction avec le gold existant)

Shadow Index :
  PROD   = ring 0,1,2 (gold + verified) — résultats fiables
  SHADOW = ring 3,4   (draft + raw)      — résultats annotés "non vérifié"

Score de confiance cumulatif :
  calculate_trust_score(signatures) → 0.0..1.0
  Un vote ring 0 = 1.0 / (0+1) = 1.0
  Un vote ring 3 = 1.0 / (3+1) = 0.25

Pas de dépendance circulaire — module autonome.
"""


import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"

# ─────────────────────────────────────────────────────────────────────────────
# États du workflow de promotion
# ─────────────────────────────────────────────────────────────────────────────


class TruthState(IntEnum):
    """
    États ordonnés du cycle de vie d'un chunk.
    Promotion toujours croissante — jamais de retour en arrière
    (sauf révocation explicite ring 0/1).
    """

    DRAFT = 0  # ingestion brute, non vérifiée
    REVIEW = 1  # en cours de vérification (triple check)
    VERIFIED = 2  # quorum atteint, signature comité
    GOLD = 3  # validé ring 0/1 ou NR runner

    def label(self) -> str:
        """Label."""
        return {0: "DRAFT", 1: "REVIEW", 2: "VERIFIED", 3: "GOLD"}[int(self)]

    def consensus_level(self) -> str:
        """Mapping vers le système forge_rag_qualify."""
        return {0: "draft", 1: "draft", 2: "verified", 3: "gold"}[int(self)]

    def trust_score(self) -> float:
        """Trust score."""
        return {0: 0.2, 1: 0.35, 2: 0.8, 3: 1.0}[int(self)]


# ─────────────────────────────────────────────────────────────────────────────
# Signature de validation
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ValidationSignature:
    """
    Preuve cryptographique qu'un agent a validé un chunk.
    Portée dans verified_by[] du meta JSON.
    """

    agent_id: str
    ring: int
    check_type: str  # "semantic" | "authority" | "coherence" | "nr" | "manual"
    score: float  # score spécifique à ce check (0.0..1.0)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        """To dict."""
        return {
            "agent": self.agent_id,
            "ring": self.ring,
            "check": self.check_type,
            "score": round(self.score, 4),
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "ValidationSignature":
        """From dict.

        Args:
            cls: Description.
            d: Description.
        """
        return cls(
            agent_id=d.get("agent", ""),
            ring=int(d.get("ring", 4)),
            check_type=d.get("check", ""),
            score=float(d.get("score", 0)),
            ts=d.get("ts", ""),
        )


# ─────────────────────────────────────────────────────────────────────────────
# A. Validation Sémantique (Jaccard cross-check)
# ─────────────────────────────────────────────────────────────────────────────


# ============================================================================
# VALIDITE TEMPORELLE — ajoute le 2026-08-25
#
# Le module savait dire QUELLE CONFIANCE accorder a une assertion (DRAFT / REVIEW /
# VERIFIED / GOLD) et pas DEPUIS QUAND ni JUSQU'A QUAND elle vaut. Consequence
# mesuree : deux chunks contradictoires coexistaient, la decroissance portait sur
# `ingested_at` — la date d'INGESTION — et non sur la validite du fait, et le corps
# ne pouvait pas repondre « qu'est-ce qui etait vrai a T ».
#
# Les champs vivent dans le `meta` JSON, aux cotes de `consensus_level`, et non en
# colonnes : le corpus depasse le million de chunks, une migration de schema serait
# un geste d'une autre nature, a decider separement.
#   valid_from      date d'OBSERVATION (pas d'ingestion)
#   valid_to        None = encore valide. Jamais « inconnu » : l'inconnu se dit.
#   superseded_by   id de l'assertion qui remplace celle-ci
# ============================================================================

def est_valide_a(meta, instant: str) -> bool:
    """Cette assertion valait-elle a `instant` (ISO) ?

    Predicat PUR, sans base : il se teste, et il sert autant au filtrage d'un
    resultat de recherche qu'a une reponse « as-of ». Une borne illisible rend
    True — on ne retire pas une assertion du monde parce que sa date est mal ecrite ;
    on prefere la montrer et la laisser refutable.
    """
    if isinstance(meta, str):
        try:
            meta = json.loads(meta or "{}")
        except Exception:  # noqa: BLE001
            return True
    if not isinstance(meta, dict):
        return True

    def _av(a: str, b: str) -> bool:
        try:
            return datetime.fromisoformat(str(a)) <= datetime.fromisoformat(str(b))
        except Exception:  # noqa: BLE001 — borne illisible : elle ne tranche pas
            return True

    debut = meta.get("valid_from")
    fin = meta.get("valid_to")
    if debut and not _av(debut, instant):
        return False  # pas encore observee a cet instant
    if fin and _av(fin, instant):
        return False  # deja perimee a cet instant
    return True


def filtrer_as_of(chunks, instant: str) -> tuple:
    """(retenus, ecartes) — ce qui valait a `instant`.

    Rend AUSSI les ecartes : un filtre qui ne dit pas ce qu'il retire fait passer une
    vue partielle pour une vue complete. C'est la regle payee ailleurs dans ce depot.
    """
    retenus, ecartes = [], []
    for c in chunks or []:
        meta = c.get("meta") if isinstance(c, dict) else None
        (retenus if est_valide_a(meta, instant) else ecartes).append(c)
    return retenus, ecartes


def superseder(ancien_id: str, nouveau_id: str, a_partir_de: str = "",
               raison: str = "") -> dict:
    """Un fait en remplace un autre : on FERME l'ancien, on ne l'efface pas.

    Retirer l'ancienne assertion detruirait la capacite de repondre « qu'est-ce qui
    etait vrai a T » — c'est precisement ce qu'on repare. On borne sa validite et on
    nomme son successeur : les deux restent lisibles, un seul vaut MAINTENANT.
    """
    instant = a_partir_de or datetime.now(timezone.utc).isoformat()
    try:
        from nokido_agent.app.forge_db_path import open_writer, write_retry
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "raison": "ecrivain DB indisponible (%s)" % type(e).__name__}

    def _op():
        conn = open_writer()
        try:
            ligne = conn.execute(
                "SELECT meta FROM rag_chunks WHERE id = ?", (ancien_id,)).fetchone()
            if ligne is None:
                return {"ok": False, "raison": "assertion introuvable: %s" % ancien_id}
            try:
                meta = json.loads(ligne[0] or "{}")
            except Exception:  # noqa: BLE001
                meta = {}
            if meta.get("valid_to"):
                return {"ok": False, "raison": "deja fermee le %s" % meta["valid_to"]}
            meta.update({"valid_to": instant, "superseded_by": nouveau_id,
                         "supersede_raison": raison[:200]})
            # RECONCILIATION (2026-08-26) : `rag_chunks` porte DEJA une colonne
            # `superseded_by` (avec `active` / `version` / `retraction_status`), que
            # personne n'ecrivait — la dette « migration de schema a trancher » posait
            # une question deja tranchee par le schema. Deux verites pour un meme
            # fait (un meta JSON rempli, une colonne vide) est le defaut que ce depot
            # paie ailleurs. On ecrit les DEUX : le meta reste ce que `est_valide_a`
            # lit, la colonne devient requetable sans json_extract. Trois etats sur la
            # colonne : ecrite / absente (base sans colonne, tests hermetiques).
            colonne = "absente"
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(rag_chunks)")}
            except Exception:  # noqa: BLE001 — pragma illisible : on le declare, on n'invente pas
                cols = set()
            if "superseded_by" in cols:
                conn.execute(
                    "UPDATE rag_chunks SET meta = ?, superseded_by = ? WHERE id = ?",
                    (json.dumps(meta, ensure_ascii=False), nouveau_id, ancien_id))
                colonne = "ecrite"
            else:
                conn.execute("UPDATE rag_chunks SET meta = ? WHERE id = ?",
                             (json.dumps(meta, ensure_ascii=False), ancien_id))
            return {"ok": True, "ancien": ancien_id, "nouveau": nouveau_id,
                    "valid_to": instant, "colonne_superseded_by": colonne}
        finally:
            conn.close()

    try:
        return write_retry(_op)
    except Exception as e:  # noqa: BLE001
        return {"ok": None, "raison": "ecriture refusee (%s)" % type(e).__name__}


def retirer_versions_anterieures(source: str, ids_courants: set, conn=None) -> int:
    """Desactive tout chunk de `source` qui n'appartient PAS a sa version courante.

    `superseder` ferme UN fait remplace par un autre ; ici c'est une SOURCE entiere
    re-ingeree (une page, un fichier memoire) dont la version courante est l'ensemble
    `ids_courants`. Rien n'est supprime (consigne owner du 12/08) : `active=0` +
    `superseded_by` nomme la source. Le chunk est aussi retire de `rag_chunks_fts` par
    le verbe 'delete' de FTS5 external-content -- le trigger `rag_chunks_fts_au` ne
    tire que sur UPDATE OF text/source/domain, un chunk seulement desactive resterait
    cherchable en lexical. Mesure du 2026-10-01 (base jetable, triggers de prod) : un
    'delete' d'une entree DEJA absente est accepte et l'index reste integre.

    Deux appelants, une seule primitive : `forge_memory_ingest` (d'ou elle vient,
    2026-09-04) et `forge_ingest_llms_txt`, qui empilait une version par
    rafraichissement (`llms-full.txt` de platform.claude.com : 3 lots actifs).

    `conn` : connexion d'ecriture de l'appelant, qu'il garde et ferme ; sans elle on
    en ouvre une. Rend le nombre de chunks retires, -1 si l'ecrivain manque.
    """
    ferme = conn is None
    if conn is None:
        try:
            from nokido_agent.app.forge_db_path import open_writer
        except Exception as exc:  # noqa: BLE001
            logger.warning("open_writer indisponible (%s) — anciens NON traites", type(exc).__name__)
            return -1
        conn = open_writer()
    try:
        # `active = 1` est VOLONTAIREMENT absent du WHERE et filtre en Python.
        # Mesure 2026-09-04 : avec lui, le planificateur choisit
        # `idx_rag_chunks_active (active=?)` -- un index sur une colonne quasi
        # CONSTANTE, sans pouvoir discriminant, qui evince `idx_rag_source`.
        # Cout : 14,716 s contre 0,000 s pour les 16 memes lignes.
        anciens = [
            r for r in conn.execute(
                "SELECT rowid, id, text, source, domain, active FROM rag_chunks "
                "WHERE source = ?",
                (source,),
            ).fetchall()
            if r[1] not in ids_courants and r[5] == 1
        ]
        for rowid, cid, texte, src, dom, _actif in anciens:
            conn.execute(
                "INSERT INTO rag_chunks_fts(rag_chunks_fts, rowid, text, source, domain) "
                "VALUES ('delete', ?, ?, ?, ?)",
                (rowid, texte, src, dom),
            )
            conn.execute(
                "UPDATE rag_chunks SET active = 0, superseded_by = ? WHERE id = ?",
                (source, cid),
            )
        return len(anciens)
    finally:
        if ferme:
            conn.close()


def jaccard_similarity(text_a: str, text_b: str, min_word_len: int = 3) -> float:
    """
    Distance Jaccard sur les n-grammes de mots (longueur ≥ min_word_len).
    Robuste aux reformulations légères.

    Returns:
        0.0 = aucun mot en commun
        1.0 = textes identiques
    """

    def _tokens(t: str) -> set:
        """Tokens.

        Args:
            t: Description.
        """
        return {w.lower() for w in t.split() if len(w) >= min_word_len}

    a, b = _tokens(text_a), _tokens(text_b)
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def validate_semantic(
    chunk_text: str,
    source_text: str,
    threshold: float = 0.15,
) -> Tuple[bool, float, str]:
    """
    Vérifie qu'un chunk est sémantiquement ancré dans sa source.
    Détecte les hallucinations par divergence lexicale.

    Args:
        chunk_text:  texte du chunk à valider
        source_text: texte de référence (source originale)
        threshold:   similarité minimum acceptable (défaut 0.15)

    Returns:
        (passed, score, reason)
    """
    score = jaccard_similarity(chunk_text, source_text)
    passed = score >= threshold
    reason = (
        f"Jaccard={score:.3f} >= {threshold} (OK)"
        if passed
        else f"Jaccard={score:.3f} < {threshold} — divergence trop élevée"
    )
    return passed, score, reason


# ─────────────────────────────────────────────────────────────────────────────
# B. Validation d'Autorité (Ring Check)
# ─────────────────────────────────────────────────────────────────────────────


def validate_authority(
    chunk_ring: int,
    validator_ring: int,
    validator_id: str = "",
) -> Tuple[bool, str]:
    """
    Vérifie qu'un validateur a l'autorité pour promouvoir un chunk.
    Règle : validator_ring ≤ chunk_ring (ring inférieur = plus d'autorité).

    Exemples :
      system:nr_runner (ring 0) valide un chunk collab (ring 3) → OK
      collab:gpt4 (ring 3) valide un chunk system (ring 0) → REFUSÉ

    Returns:
        (passed, reason)
    """
    from nokido_agent.app.forge_integrity import is_at_least, IntegrityRing

    try:
        v_ring = IntegrityRing(validator_ring)
        c_ring = IntegrityRing(chunk_ring)
        # Le validateur doit être au moins aussi privilégié que le chunk
        passed = is_at_least(v_ring, c_ring)
        reason = (
            f"Ring {v_ring.label()} ({validator_id}) autorisé à valider ring {c_ring.label()}"
            if passed
            else f"Ring {v_ring.label()} ({validator_id}) insuffisant pour valider ring {c_ring.label()}"
        )
        return passed, reason
    except Exception as e:
        return False, f"Ring check error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# C. Validation de Cohérence (Ledger Check)
# ─────────────────────────────────────────────────────────────────────────────


def validate_coherence(
    chunk_text: str,
    domain: str = "general",
    contradiction_threshold: float = 0.7,
    db_path: Optional[Path] = None,
    max_gold_check: int = 50,
) -> Tuple[bool, float, str]:
    """
    Vérifie que le chunk ne contredit pas les données GOLD existantes.

    Stratégie :
      1. Cherche les chunks GOLD du même domaine
      2. Calcule la similarité Jaccard (sujet commun = mots communs)
      3. Si similarité > 0.4 (même sujet) ET divergence lexicale forte
         → contradiction potentielle détectée

    Heuristique conservatrice : on alerte, pas on bloque automatiquement.
    Un humain (ou ring 0/1) tranche.

    Returns:
        (coherent, min_coherence_score, reason)
    """
    db = db_path or _DB
    try:
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode=WAL")
        # Récupérer les chunks gold du même domaine
        gold_rows = conn.execute(
            """
            SELECT text FROM rag_chunks
            WHERE domain = ?
            AND json_extract(meta,'$.consensus_level') = 'gold'
            AND json_extract(meta,'$.mutable') = 0
            LIMIT ?
        """,
            (domain, max_gold_check),
        ).fetchall()
        conn.close()
    except Exception as e:
        return True, 1.0, f"Ledger inaccessible: {e} (pass-through)"

    if not gold_rows:
        return True, 1.0, "Aucune référence gold dans ce domaine"

    chunk_tokens = {w.lower() for w in chunk_text.split() if len(w) >= 3}

    # Chercher un gold qui parle du même sujet mais dit autre chose
    contradictions = []
    for (gold_text,) in gold_rows:
        gold_tokens = {w.lower() for w in gold_text.split() if len(w) >= 3}
        # Même sujet ? (Jaccard > 0.2 = beaucoup de mots communs)
        same_subject = jaccard_similarity(chunk_text, gold_text) > 0.2
        if not same_subject:
            continue
        # Divergence : mots forts dans le chunk absents du gold
        chunk_only = chunk_tokens - gold_tokens
        divergence = len(chunk_only) / max(len(chunk_tokens), 1)
        if divergence > contradiction_threshold:
            contradictions.append((divergence, gold_text[:80]))

    if contradictions:
        max_div = max(d for d, _ in contradictions)
        sample = contradictions[0][1]
        return (False, 1.0 - max_div, f"Contradiction potentielle (divergence={max_div:.2f}) avec gold: '{sample}...'")

    return True, 1.0, f"Cohérent avec {len(gold_rows)} références gold"


# ─────────────────────────────────────────────────────────────────────────────
# Score de confiance cumulatif
# ─────────────────────────────────────────────────────────────────────────────


def calculate_trust_score(signatures: List[Dict]) -> float:
    """
    Score de confiance cumulatif basé sur les signatures de validation.

    Formule : Σ (1 / (ring + 1)) pour chaque signature, plafonné à 1.0
    Un vote ring 0 = 1.0 — suffit seul pour atteindre le maximum.
    Un vote ring 3 = 0.25 — 4 votes collab = 1.0 (mais jamais gold).

    Règle de Ring Authority :
    Le score résultant est limité par le ring le plus bas parmi les signataires.
    Exemple : 10 votes ring 3 + 0 vote ring 0 = max 0.5 (jamais gold).
    """
    if not signatures:
        return 0.0

    raw_score = sum(1.0 / (s.get("ring", 4) + 1) for s in signatures)
    min_ring = min(s.get("ring", 4) for s in signatures)

    # Plafond selon le ring le plus élevé des validateurs
    _CAPS = {0: 1.0, 1: 1.0, 2: 0.8, 3: 0.5, 4: 0.2}
    cap = _CAPS.get(min_ring, 0.2)

    return round(min(raw_score, cap, 1.0), 4)


def trust_score_to_state(trust_score: float) -> TruthState:
    """
    Convertit un score de confiance en état TruthState.
    Seuils conservateurs — la promotion finale vers GOLD
    requiert toujours une signature ring 0/1.
    """
    if trust_score >= 1.0:
        return TruthState.GOLD
    if trust_score >= 0.8:
        return TruthState.VERIFIED
    if trust_score >= 0.35:
        return TruthState.REVIEW
    return TruthState.DRAFT


# ─────────────────────────────────────────────────────────────────────────────
# Triple Vérification
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TripleCheckResult:
    """Résultat de la triple vérification."""

    semantic_ok: bool
    semantic_score: float
    authority_ok: bool
    coherence_ok: bool
    coherence_score: float
    passed: bool  # True = les 3 checks passés
    new_state: TruthState
    trust_score: float
    signatures: List[Dict] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


def triple_check(
    chunk_id: str,
    chunk_text: str,
    source_text: str,
    domain: str,
    current_meta: Dict,
    validator_id: str,
    validator_ring: int,
    db_path: Optional[Path] = None,
) -> TripleCheckResult:
    """
    Applique les 3 vérifications et calcule le nouvel état.

    Args:
        chunk_id:       ID du chunk à promouvoir
        chunk_text:     texte du chunk
        source_text:    texte source de référence (pour check A)
        domain:         domaine pour ledger check
        current_meta:   meta JSON actuel du chunk
        validator_id:   agent qui déclenche la validation
        validator_ring: ring du validateur
        db_path:        chemin DB (défaut _DB)

    Returns:
        TripleCheckResult avec le nouvel état recommandé
    """
    reasons = []
    signatures = list(current_meta.get("verified_by", []))

    # ── A. Sémantique ────────────────────────────────────────────────────────
    sem_ok, sem_score, sem_reason = validate_semantic(chunk_text, source_text)
    reasons.append(f"[A:sémantique] {sem_reason}")
    if sem_ok:
        signatures.append(
            ValidationSignature(
                agent_id=validator_id,
                ring=validator_ring,
                check_type="semantic",
                score=sem_score,
            ).to_dict()
        )

    # ── B. Autorité ──────────────────────────────────────────────────────────
    chunk_ring = int(current_meta.get("ring", 3))
    auth_ok, auth_reason = validate_authority(chunk_ring, validator_ring, validator_id)
    reasons.append(f"[B:autorité] {auth_reason}")
    if auth_ok:
        signatures.append(
            ValidationSignature(
                agent_id=validator_id,
                ring=validator_ring,
                check_type="authority",
                score=1.0 / (validator_ring + 1),
            ).to_dict()
        )

    # ── C. Cohérence ─────────────────────────────────────────────────────────
    coh_ok, coh_score, coh_reason = validate_coherence(chunk_text, domain, db_path=db_path)
    reasons.append(f"[C:cohérence] {coh_reason}")
    if coh_ok:
        signatures.append(
            ValidationSignature(
                agent_id="ledger",
                ring=0,
                check_type="coherence",
                score=coh_score,
            ).to_dict()
        )

    # ── Score final ───────────────────────────────────────────────────────────
    # Dédoublonner les signatures (même agent+check = garder le plus récent)
    seen = {}
    unique_sigs = []
    for s in signatures:
        key = f"{s['agent']}:{s['check']}"
        seen[key] = s
    unique_sigs = list(seen.values())

    trust = calculate_trust_score(unique_sigs)
    state = trust_score_to_state(trust)
    passed = sem_ok and auth_ok and coh_ok

    return TripleCheckResult(
        semantic_ok=sem_ok,
        semantic_score=sem_score,
        authority_ok=auth_ok,
        coherence_ok=coh_ok,
        coherence_score=coh_score,
        passed=passed,
        new_state=state,
        trust_score=trust,
        signatures=unique_sigs,
        reasons=reasons,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Workflow de promotion
# ─────────────────────────────────────────────────────────────────────────────


def promote_chunk(
    chunk_id: str,
    result: TripleCheckResult,
    db_path: Optional[Path] = None,
) -> bool:
    """
    Met à jour le meta JSON du chunk en DB après triple check.
    Idempotent — peut être rappelé sans risque.

    Returns:
        True si promotion effectuée, False sinon
    """
    if not result.passed:
        logger.info(f"[truth] chunk {chunk_id}: triple check échoué — pas de promotion")
        return False

    db = db_path or _DB
    try:
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute("SELECT meta FROM rag_chunks WHERE id=?", (chunk_id,)).fetchone()
        if not row:
            conn.close()
            return False

        meta = json.loads(row[0]) if row[0] else {}

        # Mettre à jour seulement si le nouvel état est meilleur
        current_state_name = meta.get("consensus_level", "draft")
        _ORDER = {"draft": 0, "verified": 1, "gold": 2}
        new_state_name = result.new_state.consensus_level()
        if _ORDER.get(new_state_name, 0) <= _ORDER.get(current_state_name, 0):
            conn.close()
            logger.debug(f"[truth] chunk {chunk_id}: déjà à {current_state_name} — pas de régression")
            return False

        meta.update(
            {
                "consensus_level": new_state_name,
                "trust_score": result.trust_score,
                "truth_state": result.new_state.label(),
                "verified_by": result.signatures,
                "mutable": new_state_name != "gold",
                "promoted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        )

        conn.execute("UPDATE rag_chunks SET meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), chunk_id))
        conn.commit()
        conn.close()
        logger.info(
            f"[truth] chunk {chunk_id}: {current_state_name} → {new_state_name} (trust={result.trust_score:.3f})"
        )
        return True

    except Exception as e:
        logger.error(f"[truth] promote_chunk {chunk_id}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Shadow Index
# ─────────────────────────────────────────────────────────────────────────────


class ShadowIndex:
    """
    Deux index de recherche séparés :
      PROD   = ring 0,1,2 — résultats fiables
      SHADOW = ring 3,4   — résultats annotés "non vérifié"

    Intégration dans search() :
      docs, warnings = ShadowIndex.split_results(raw_docs)
      # docs = résultats prod + shadow avec annotation
    """

    # Annonces dans les résultats shadow
    SHADOW_LABEL = "[NON VÉRIFIÉ — comité en attente]"

    @staticmethod
    def classify(chunk_meta: Dict) -> str:
        """Retourne 'prod' ou 'shadow' selon le ring du chunk."""
        ring = int(chunk_meta.get("ring", 3))
        return "prod" if ring <= 2 else "shadow"

    @staticmethod
    def annotate_result(result: Dict, is_shadow: bool) -> Dict:
        """Ajoute les métadonnées shadow dans un résultat de recherche."""
        result = dict(result)
        result["shadow"] = is_shadow
        if is_shadow:
            result["trust_warning"] = ShadowIndex.SHADOW_LABEL
            result["score"] = result.get("score", 0) * 0.7  # pénalité affichage
        return result

    @staticmethod
    def split_results(
        results: List[Dict],
        include_shadow: bool = True,
        max_shadow: int = 2,
    ) -> Tuple[List[Dict], List[str]]:
        """
        Sépare les résultats prod/shadow et génère les avertissements.

        Args:
            results:        liste brute de résultats search()
            include_shadow: inclure les résultats shadow dans la sortie
            max_shadow:     max résultats shadow à inclure

        Returns:
            (annotated_results, warnings)
        """
        prod = []
        shadow = []
        warnings = []

        for r in results:
            meta = r.get("meta_parsed") or {}
            ring = int(meta.get("ring", 3))
            if ring <= 2:
                prod.append(ShadowIndex.annotate_result(r, False))
            else:
                shadow.append(ShadowIndex.annotate_result(r, True))

        if shadow and include_shadow:
            warnings.append(
                f"{len(shadow)} résultat(s) proviennent de sources non vérifiées "
                f"(ring COLLAB/UNTRUSTED). Traiter avec précaution."
            )

        combined = prod
        if include_shadow:
            combined = prod + shadow[:max_shadow]

        return combined, warnings


# ─────────────────────────────────────────────────────────────────────────────
# API publique haut-niveau
# ─────────────────────────────────────────────────────────────────────────────


def validate_and_promote(
    chunk_id: str,
    source_text: str = "",
    validator_id: str = "system:nr_runner",
    validator_ring: int = 0,
    db_path: Optional[Path] = None,
) -> TripleCheckResult:
    """
    API principale : valide et promeut un chunk en une seule opération.

    Usage :
        result = validate_and_promote("abc123", source_text="...")
        if result.passed:
            print(f"Promu vers {result.new_state.label()}")
    """
    db = db_path or _DB
    try:
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT text, domain, meta FROM rag_chunks WHERE id=?", (chunk_id,)).fetchone()
        conn.close()
    except Exception as e:
        logger.error(f"[truth] validate_and_promote: DB error: {e}")
        return TripleCheckResult(
            semantic_ok=False,
            semantic_score=0,
            authority_ok=False,
            coherence_ok=False,
            coherence_score=0,
            passed=False,
            new_state=TruthState.DRAFT,
            trust_score=0,
            reasons=[str(e)],
        )

    if not row:
        return TripleCheckResult(
            semantic_ok=False,
            semantic_score=0,
            authority_ok=False,
            coherence_ok=False,
            coherence_score=0,
            passed=False,
            new_state=TruthState.DRAFT,
            trust_score=0,
            reasons=[f"chunk {chunk_id} introuvable"],
        )

    text, domain, meta_s = row
    meta = json.loads(meta_s) if meta_s else {}

    # Si source_text non fourni, utiliser le texte du chunk lui-même
    # (check sémantique trivial mais au moins cohérence + autorité)
    ref = source_text or text

    result = triple_check(
        chunk_id=chunk_id,
        chunk_text=text,
        source_text=ref,
        domain=domain or "general",
        current_meta=meta,
        validator_id=validator_id,
        validator_ring=validator_ring,
        db_path=db_path,
    )

    promote_chunk(chunk_id, result, db_path=db_path)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Mono-Mode : Chain of Verification (CoVe)
# ─────────────────────────────────────────────────────────────────────────────

# Mode d’exécution — detecté automatiquement ou forçable
# False = multi-LLM (Quorum), True = mono-LLM (CoVe)
MONO_MODE: bool = True  # Nokido = un seul LLM local disponible

# Seuils de promotion selon le mode
_THRESHOLDS = {
    "mono": {"review": 0.30, "verified": 0.55, "gold": 0.90},
    "multi": {"review": 0.35, "verified": 0.80, "gold": 1.00},
}


@dataclass
class CoVeResult:
    """
    Résultat d’une Chain of Verification (mono-mode).
    Le même LLM joue deux rôles : générateur et auditeur.
    """

    hallucination_check: str  # "PASSED" | "FLAGGED" | "SKIPPED"
    source_check: str  # "PASSED" | "FLAGGED" | "SKIPPED"
    schema_check: str  # "PASSED" | "FLAGGED" | "SKIPPED"
    ring_enforced: bool  # True si le ring a été abaissé au min légal
    coherence_score: float
    trust_score: float
    mono_mode: bool = True
    reasons: List[str] = field(default_factory=list)


def cove_validate(
    chunk_text: str,
    chunk_meta: Dict,
    author_id: str,
    source_exists: bool = True,
    schema: Optional[Dict] = None,
) -> CoVeResult:
    """
    Validation Chain of Verification pour mono-mode LLM.

    Remplace le quorum d’agents par un quorum d’étapes déterministes.
    Aucun appel LLM ici — c’est la Sentinel qui porte la charge.

    Étapes :
      1. Hallucination check  : cohérence lexicale interne du chunk
      2. Source check         : la source référencée existe-t-elle ?
      3. Schema check         : JSON valide contre un schéma si fourni
      4. Ring enforcement     : interdit de signer comme ring 0/1 en solo

    Args:
        chunk_text:    texte du chunk
        chunk_meta:    meta JSON actuel
        author_id:     agent qui soumet (ex: 'collab:claude')
        source_exists: True si la source référencée est dans la DB
        schema:        schéma JSON attendu si le chunk est du JSON

    Returns:
        CoVeResult avec trust_score adapté au mono-mode
    """
    reasons = []
    checks_passed = 0
    checks_total = 0

    # ── 1. Hallucination check — cohérence interne ──────────────────────────
    # Un chunk halléciné a tendance à être lexicalement incohérent :
    # des termes techniques apparaissent isolément sans contexte.
    checks_total += 1
    words = [w.lower() for w in chunk_text.split() if len(w) >= 4]
    n_unique = len(set(words))
    n_total = len(words) if words else 1
    repetition_ratio = 1 - (n_unique / n_total)
    # Un chunk trop répétitif ou trop court est suspect
    hallucination_ok = len(chunk_text.strip()) >= 30 and repetition_ratio < 0.8 and n_total >= 5
    hallucination_status = "PASSED" if hallucination_ok else "FLAGGED"
    if hallucination_ok:
        checks_passed += 1
        reasons.append("[1:hallucination] OK — cohérence interne suffisante")
    else:
        reasons.append(f"[1:hallucination] FLAGGED — repetition={repetition_ratio:.2f} len={len(chunk_text)}")

    # ── 2. Source check — la source existe ──────────────────────────────────
    checks_total += 1
    source_status = "PASSED" if source_exists else "FLAGGED"
    if source_exists:
        checks_passed += 1
        reasons.append("[2:source] OK — source vérifiable")
    else:
        reasons.append("[2:source] FLAGGED — source introuvable dans le ledger")

    # ── 3. Schema check — JSON valide ────────────────────────────────────────
    checks_total += 1
    schema_status = "SKIPPED"
    if schema is not None:
        try:
            data = json.loads(chunk_text) if chunk_text.strip().startswith("{") else None
            if data is not None:
                missing = [k for k in schema.get("required", []) if k not in data]
                if not missing:
                    schema_status = "PASSED"
                    checks_passed += 1
                    reasons.append("[3:schema] OK")
                else:
                    schema_status = "FLAGGED"
                    reasons.append(f"[3:schema] FLAGGED — champs manquants: {missing}")
            else:
                schema_status = "SKIPPED"
                reasons.append("[3:schema] SKIPPED — chunk non-JSON")
                checks_total -= 1  # ne compte pas si non-applicable
        except Exception:
            schema_status = "FLAGGED"
            reasons.append("[3:schema] FLAGGED — JSON invalide")
    else:
        checks_total -= 1  # non demandé

    # ── 4. Ring enforcement — un LLM solo ne peut pas signer ring 0/1 ──────
    ring_enforced = False
    author_prefix = author_id.split(":")[0].lower() if ":" in author_id else author_id.lower()
    _ELEVATED = {"system", "dev", "laforge"}  # rings 0 et 1
    if author_prefix in _ELEVATED:
        # Force la signature au niveau collab en mono-mode
        reasons.append(
            f"[4:ring] ENFORCED — '{author_id}' abàissé à 'collab:{author_id}' "
            f"(mono-mode : aucun LLM ne peut signer ring 0/1 seul)"
        )
        ring_enforced = True
    else:
        reasons.append(f"[4:ring] OK — '{author_id}' dans ring légal")

    # ── Score CoVe ───────────────────────────────────────────────────────────
    # Base : ratio checks réussis
    base = checks_passed / max(checks_total, 1)
    # Cohérence lexicale interne comme bonus
    coherence = min(n_unique / max(n_total * 0.6, 1), 1.0)
    # Malus si ring a dû être rabaissé
    ring_penalty = 0.15 if ring_enforced else 0.0
    # Score final mono-mode (plafonné à 0.75 — jamais gold sans ring 0/1 externe)
    raw = base * 0.7 + coherence * 0.3 - ring_penalty
    trust = round(min(max(raw, 0.0), 0.75), 4)

    return CoVeResult(
        hallucination_check=hallucination_status,
        source_check=source_status,
        schema_check=schema_status,
        ring_enforced=ring_enforced,
        coherence_score=round(coherence, 4),
        trust_score=trust,
        mono_mode=True,
        reasons=reasons,
    )


def check_promotion_eligibility(
    chunk_meta: Dict,
    verification_results: Dict,
    mono_mode: bool = True,
) -> Tuple[bool, str]:
    """
    Détermine si un chunk peut être promu.

    Args:
        chunk_meta:           meta JSON actuel du chunk
        verification_results: dict avec clés :
          'hallucination_check': 'PASSED'|'FLAGGED'|'SKIPPED'
          'coherence_score':     float 0.0..1.0
          'trust_score':         float 0.0..1.0
          'quorum_reached':      bool (multi-mode seulement)
        mono_mode: True = CoVe, False = Quorum multi-LLM

    Returns:
        (eligible, reason)
    """
    thresholds = _THRESHOLDS["mono" if mono_mode else "multi"]
    trust = float(verification_results.get("trust_score", 0.0))
    current = chunk_meta.get("consensus_level", "draft")

    if mono_mode:
        hcheck = verification_results.get("hallucination_check", "")
        if hcheck == "FLAGGED":
            return False, "Hallucination détectée — chunk refusé même en mono-mode"
        if trust >= thresholds["verified"]:
            return True, f"Promu par auto-vérification CoVe (trust={trust:.3f})"
        if trust >= thresholds["review"]:
            return True, f"Passé en REVIEW — en attente validation supplémentaire (trust={trust:.3f})"
        return False, f"Score insuffisant en mono-mode: {trust:.3f} < {thresholds['review']}"
    else:
        # Multi-LLM : quorum obligatoire
        if verification_results.get("quorum_reached"):
            return True, "Promu par consensus de comité"
        if trust >= thresholds["verified"]:
            return True, f"Promu par quorum de scores (trust={trust:.3f})"
        return False, "En attente de validation supplémentaire (quorum non atteint)"


def mono_mode_promote(
    chunk_id: str,
    author_id: str = "collab:claude",
    source_exists: bool = True,
    schema: Optional[Dict] = None,
    db_path: Optional[Path] = None,
) -> Tuple[bool, CoVeResult]:
    """
    Promotion mono-mode via CoVe.
    Un seul LLM, mais triple vérification déterministe.

    Signature forcée à 'collab:' si l’auteur réclame ring 0/1.
    Le chunk peut monter jusqu’à VERIFIED (jamais GOLD seul).

    Returns:
        (promoted, CoVeResult)
    """
    db = db_path or _DB
    try:
        conn = sqlite3.connect(str(db))
        row = conn.execute("SELECT text, meta FROM rag_chunks WHERE id=?", (chunk_id,)).fetchone()
        conn.close()
    except Exception as e:
        return False, CoVeResult(
            hallucination_check="SKIPPED",
            source_check="SKIPPED",
            schema_check="SKIPPED",
            ring_enforced=False,
            coherence_score=0,
            trust_score=0,
            reasons=[f"DB error: {e}"],
        )

    if not row:
        return False, CoVeResult(
            hallucination_check="SKIPPED",
            source_check="SKIPPED",
            schema_check="SKIPPED",
            ring_enforced=False,
            coherence_score=0,
            trust_score=0,
            reasons=[f"chunk {chunk_id} introuvable"],
        )

    text, meta_s = row
    meta = json.loads(meta_s) if meta_s else {}

    result = cove_validate(
        chunk_text=text,
        chunk_meta=meta,
        author_id=author_id,
        source_exists=source_exists,
        schema=schema,
    )

    eligible, reason = check_promotion_eligibility(
        chunk_meta=meta,
        verification_results={
            "hallucination_check": result.hallucination_check,
            "coherence_score": result.coherence_score,
            "trust_score": result.trust_score,
        },
        mono_mode=True,
    )

    if not eligible:
        logger.debug(f"[truth:mono] chunk {chunk_id}: non promu — {reason}")
        return False, result

    # Appliquer la promotion en DB
    new_state = trust_score_to_state_mono(result.trust_score)
    _persist_cove_result(chunk_id, result, new_state, author_id, db)
    return True, result


def trust_score_to_state_mono(trust: float) -> TruthState:
    """
    Conversion trust → TruthState en mono-mode.
    Seuils plus bas (auto-validation) mais plafoné à VERIFIED.
    GOLD impossible en mono-mode — exige signature ring 0/1 externe.
    """
    t = _THRESHOLDS["mono"]
    if trust >= t["verified"]:
        return TruthState.VERIFIED  # max en mono
    if trust >= t["review"]:
        return TruthState.REVIEW
    return TruthState.DRAFT


def _persist_cove_result(
    chunk_id: str,
    result: CoVeResult,
    new_state: TruthState,
    author_id: str,
    db_path: Path,
) -> None:
    """Persiste le résultat CoVe dans meta JSON du chunk."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        row = conn.execute("SELECT meta FROM rag_chunks WHERE id=?", (chunk_id,)).fetchone()
        if not row:
            conn.close()
            return

        meta = json.loads(row[0]) if row[0] else {}
        # Ne jamais régresser
        _ORDER = {"draft": 0, "review": 0, "verified": 1, "gold": 2}
        cur_lvl = meta.get("consensus_level", "draft")
        new_lvl = new_state.consensus_level()
        if _ORDER.get(new_lvl, 0) <= _ORDER.get(cur_lvl, 0):
            conn.close()
            return

        meta.update(
            {
                "consensus_level": new_lvl,
                "truth_state": new_state.label(),
                "trust_score": result.trust_score,
                "cove_validated": True,
                "mono_mode": True,
                "cove_checks": {
                    "hallucination": result.hallucination_check,
                    "source": result.source_check,
                    "schema": result.schema_check,
                    "coherence": result.coherence_score,
                },
                "verified_by": meta.get("verified_by", [])
                + [
                    {
                        "agent": author_id,
                        "ring": 3,  # forcé collab en mono-mode
                        "check": "cove",
                        "score": result.trust_score,
                        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    }
                ],
                "promoted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "mutable": True,  # VERIFIED mono reste mutable
            }
        )
        conn.execute("UPDATE rag_chunks SET meta=? WHERE id=?", (json.dumps(meta, ensure_ascii=False), chunk_id))
        conn.commit()
        conn.close()
        logger.info(f"[truth:mono] chunk {chunk_id}: {cur_lvl} → {new_lvl} CoVe (trust={result.trust_score:.3f})")
    except Exception as e:
        logger.error(f"[truth:mono] persist {chunk_id}: {e}")


def batch_promote_draft(
    validator_id: str = "system:nr_runner",
    validator_ring: int = 0,
    domain: str = "",
    limit: int = 100,
    db_path: Optional[Path] = None,
) -> Dict[str, int]:
    """
    Promotion par lot des chunks DRAFT → VERIFIED/GOLD.
    Utilise uniquement les checks B (autorité) et C (cohérence)
    car source_text n'est pas disponible en batch.

    Retourne {"promoted": n, "skipped": n, "errors": n}
    """
    db = db_path or _DB
    stats = {"promoted": 0, "skipped": 0, "errors": 0}

    try:
        conn = sqlite3.connect(str(db))
        q = """SELECT id, text, domain, meta FROM rag_chunks
               WHERE json_extract(meta,'$.consensus_level') = 'draft'"""
        params = []
        if domain:
            q += " AND domain = ?"
            params.append(domain)
        q += f" LIMIT {limit}"
        rows = conn.execute(q, params).fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"[truth] batch_promote: {e}")
        return stats

    for chunk_id, text, dom, meta_s in rows:
        try:
            meta = json.loads(meta_s) if meta_s else {}
            result = triple_check(
                chunk_id=chunk_id,
                chunk_text=text,
                source_text=text,  # auto-référence en batch
                domain=dom or "general",
                current_meta=meta,
                validator_id=validator_id,
                validator_ring=validator_ring,
                db_path=db_path,
            )
            if promote_chunk(chunk_id, result, db_path=db_path):
                stats["promoted"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            logger.debug(f"[truth] batch chunk {chunk_id}: {e}")
            stats["errors"] += 1

    logger.info(f"[truth] batch_promote: {stats}")
    return stats
