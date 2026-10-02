# -*- coding: utf-8 -*-
"""
forge_dialogue_outcome.py — AXE 8 : évaluateur d'issue d'un échange de dialogue.
================================================================================
Juge le succès/échec d'un tour user↔assistant et émet la récompense correspondante.
Le SUBSTRAT existe déjà — ce module = la pièce manquante (le juge de l'échange) :

  intrinsèque  : forge_metacognition_gate.ConfidenceScorer (qualité écrite réponse)
  extrinsèque  : réaction user au tour suivant (correction/rejet vs approbation)
       ↓ fusion → Outcome(success, score, signals)
  record_outcome → forge_motivation.reward/punish (keyé persona:dialogue:<topic>)
       ↓ (motivation émet déjà via forge_endocrine)
  DOPAMINE_SUCCESS / CORTISOL_FRUSTRATION  → relu par PersonaEngine (modulation voix)

Anti-dup : réutilise ConfidenceScorer + motivation + endocrine. Voir
docs/specs/axe8_persona_unifiee_plan.md §0.bis.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

__FORGE_COLOR__ = "GREEN"

_RAG_DB = Path(__file__).resolve().parent.parent / "RAG" / "embeddings.db"

# Seuil de qualité intrinsèque (ConfidenceScorer) au-delà duquel, sans réaction
# user explicite, l'échange est considéré réussi.
CONFIDENCE_OK = 0.5

# Réaction user NÉGATIVE → l'assistant s'est trompé / a été corrigé (échec).
_NEG = [
    r"\bnon\b", r"\bfaux\b", r"\berreur\b", r"\bpas (?:ça|ca|bon)\b",
    r"\b(?:ça|ca) (?:marche|va) pas\b", r"\bmarche pas\b", r"\bc'?est pas\b",
    r"\bpas du tout\b", r"\bn'?importe quoi\b", r"\brecommence\b", r"\bretente\b",
    r"\bwrong\b", r"\bincorrect\b", r"\bnope\b", r"\bactually no\b",
]
# Réaction user POSITIVE → validation explicite (succès).
_POS = [
    r"\bparfait\b", r"\bnickel\b", r"\bexact\b", r"\bmerci\b", r"\bgo\b",
    r"\boui\b", r"\bsuper\b", r"\bcontinue\b", r"\bbien jou", r"\bcorrect\b",
    r"\bperfect\b", r"\bgreat\b", r"\bthanks\b", r"\bnice\b",
]


@dataclass
class Outcome:
    success: bool
    score: float
    signals: list = field(default_factory=list)
    time_s: float = 1.0
    n_steps: int = 1
    topic: str = "general"


def _match_any(patterns, text):
    t = (text or "").lower()
    return [p for p in patterns if re.search(p, t)]


def evaluate_exchange(user_msg, assistant_msg, next_user_msg="", *, time_s=1.0, n_steps=1, topic="general"):
    """Évalue un échange. Fusionne qualité intrinsèque + réaction user extrinsèque."""
    signals = []

    # Intrinsèque (réutilise ConfidenceScorer — hedging/longueur/refus/répétition).
    try:
        from nokido_agent.app.forge_metacognition_gate import ConfidenceScorer

        intr = float(ConfidenceScorer().score(assistant_msg).final_score)
    except Exception:
        intr = 1.0
    signals.append(f"intrinsic={intr:.2f}")

    neg = _match_any(_NEG, next_user_msg)
    pos = _match_any(_POS, next_user_msg)
    if neg:
        signals.append(f"user_correction:{len(neg)}")
    if pos:
        signals.append(f"user_approval:{len(pos)}")

    # Décision : correction explicite → échec. Approbation explicite → succès.
    # Sinon (signaux mixtes ou absents) → on s'en remet à la qualité intrinsèque.
    if neg and not pos:
        success = False
    elif pos and not neg:
        success = True
    else:
        success = intr >= CONFIDENCE_OK

    return Outcome(
        success=success,
        score=intr,
        signals=signals,
        time_s=time_s,
        n_steps=n_steps,
        topic=topic or "general",
    )


# ── Seams monkeypatchables (isolent les écritures DB en test) ─────────────────
def _reward(method, time_s, n_steps, success, target=""):
    from nokido_agent.app.forge_motivation import reward

    return reward(method, time_s, n_steps, success=success, target=target)


def _punish(method, error="", target=""):
    from nokido_agent.app.forge_motivation import punish

    return punish(method, error, target)


def record_outcome(outcome):
    """Émet la récompense/punition selon l'issue → dopamine/cortisol via motivation.
    Keyé `persona:dialogue:<topic>` pour conditionner la voix (PersonaEngine)."""
    method = f"persona:dialogue:{outcome.topic}"
    if outcome.success:
        return _reward(method, outcome.time_s, outcome.n_steps, True)
    return _punish(method, error=";".join(outcome.signals))


def evaluate_and_record(user_msg, assistant_msg, next_user_msg="", *, time_s=1.0, n_steps=1, topic="general"):
    """Helper : évalue puis émet. Point d'appel unique pour les callers (PR-3/4)."""
    out = evaluate_exchange(
        user_msg, assistant_msg, next_user_msg, time_s=time_s, n_steps=n_steps, topic=topic
    )
    try:
        record_outcome(out)
    except Exception:
        pass
    return out


# ── AXE ÉCRIT : persistance des échanges RÉUSSIS comme exemplars few-shot ──────
def _persist_exemplar(user_msg, assistant_msg, topic="general", db_path=None):
    """Persiste un échange réussi (domain=dialogue_win) — rappelé par la persona
    (_pull_dialogue_exemplars) comme exemple écrit à imiter. Best-effort."""
    db = Path(db_path) if db_path else _RAG_DB
    text = f"[user] {(user_msg or '')[:600]}\n[assistant] {(assistant_msg or '')[:1200]}"
    cid = "dwin_" + hashlib.sha256((topic + text).encode()).hexdigest()[:16]
    try:
        con = sqlite3.connect(str(db), timeout=10)
        con.execute("PRAGMA journal_mode=WAL")
        # Forme sans existant (2026-10-01) : n'arme pas le trigger rag_chunks_fts_bi.
        con.execute(
            "INSERT OR IGNORE INTO rag_chunks (id, source, text, domain, ingested_at) SELECT ?,?,?,?,? "
            "WHERE NOT EXISTS (SELECT 1 FROM rag_chunks WHERE id = ?)",
            (cid, f"dialogue_win/{topic}", text, "dialogue_win", time.strftime("%Y-%m-%dT%H:%M:%S"), cid),
        )
        con.commit()
        con.close()
        return cid
    except Exception:
        return ""


def _prev_user(turns, i):
    for j in range(i - 1, -1, -1):
        if turns[j][0] == "user":
            return turns[j][1]
    return ""


def score_session_turns(turns, *, persist_wins=True, topic="general", start_index=0, require_next=False):
    """Scoring LIVE depuis les vrais tours conversationnels (axe écrit).

    turns = list[(role, text)] chronologique (role ∈ user|assistant). Pour chaque
    réponse assistant, fusionne sa qualité intrinsèque + la réaction user au tour
    SUIVANT (correction/approbation) → record_outcome (dopamine/cortisol). Les
    échanges nettement réussis sont persistés comme exemplars few-shot.

    start_index : ne traite que les tours d'indice >= start_index (watermark anti
                  double-comptage pour un hook qui re-tourne sur la même session).
    require_next : ne score que les échanges suivis d'un tour (réaction dispo) —
                   le dernier assistant sans réponse user est laissé pour plus tard.

    Conçu pour être appelé en hook fin-de-session (sur conv_indexer turns).
    """
    results = []
    n = len(turns)
    for i in range(n):
        if i < start_index:
            continue
        role, text = turns[i]
        if role != "assistant":
            continue
        has_next = i + 1 < n
        if require_next and not has_next:
            continue
        next_user = turns[i + 1][1] if has_next and turns[i + 1][0] == "user" else ""
        pu = _prev_user(turns, i)
        out = evaluate_and_record(pu, text, next_user, topic=topic)
        if persist_wins and out.success and (
            any("approval" in s for s in out.signals) or out.score >= 0.7
        ):
            _persist_exemplar(pu, text, out.topic)
        results.append(out)
    return results
