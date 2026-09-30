"""
forge_metacognition_gate.py — Nokido Engrid v3 · Couche 1
============================================================
MetaCognitionGate : filtre intelligent entre le prompt entrant
et le backend LLM. Se place entre l'utilisateur et la Membrane.

Architecture Engrid :
    User/Silo  →  MetaCognitionGate  →  SovereignMembrane  →  Cloud/Local LLM
                        │
                        ├── Score de confiance par silo
                        ├── Spin Flip (escalade modèle si confiance < seuil)
                        ├── Trigger adversarial (keywords sensibles)
                        └── Energy Budget (tokens cumulés par requête)

Modèles disponibles (ordre d'escalade) :
    Tier 0 : qwen2.5-coder:1.5b   — rapide, local, économique
    Tier 1 : laforge-qwen:latest   — équilibré, local
    Tier 2 : qwen2.5-coder:7b      — puissant, local
    Tier 3 : cloud (via Membrane)  — ultime recours

Décision de spin flip :
    score_confiance < SPIN_THRESHOLD → upgrade tier
    keyword adversarial détecté      → tier min = 2
    energy_budget dépassé            → refus ou tier 0 forcé
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════════════════

SPIN_THRESHOLD = 0.60  # score < 0.60 → escalade
ENERGY_BUDGET_TOK = 8000  # tokens max cumulés par session de gate
LIF_TAU_SEC = 3600  # constante de décroissance LIF (1h) — energy(t) = energy_0 * exp(-(t-t0)/tau)
ADVERSARIAL_TIER = 2  # tier minimum si keyword adversarial détecté

MODEL_TIERS = [
    "qwen2.5-coder:1.5b",  # tier 0
    "laforge-qwen:latest",  # tier 1
    "qwen2.5-coder:7b",  # tier 2
    "cloud",  # tier 3
]

# Patterns qui forcent tier ≥ ADVERSARIAL_TIER
ADVERSARIAL_PATTERNS = [
    r"\bCVE-\d{4}-\d+\b",
    r"\b(?:exec|execve|system|popen|subprocess)\b",
    r"\b(?:exploit|pwn|shellcode|payload)\b",
    r"\b(?:kernel|ring0|ring3|privesc|privilege.escal)\b",
    r"\b(?:rootkit|backdoor|implant|beacon)\b",
    r"\b(?:reverse.?shell|bind.?shell|meterpreter)\b",
    r"\b(?:sql.?inject|xss|csrf|ssrf|rce|lfi|rfi)\b",
    r"\b(?:mimikatz|secretsdump|ntlmrelay|responder)\b",
    r"\b(?:overflow|heap.spray|use.after.free|uaf)\b",
]

# Patterns d'hedging qui baissent le score de confiance
HEDGING_PATTERNS = [
    r"\b(?:peut.?être|probablement|possiblement|il.?se.?peut)\b",
    r"\b(?:je.?ne.?suis.?pas.?sûr|incertain|à.?vérifier)\b",
    r"\b(?:perhaps|maybe|possibly|might|could.?be|not.?sure)\b",
    r"\b(?:unclear|uncertain|approximately|roughly|around)\b",
    r"\b(?:I.?think|I.?believe|I.?assume|I.?guess)\b",
    r"\b(?:seems?|appears?|looks?.?like|suggests?)\b",
    r"\.{3}",  # ellipsis → hésitation
    r"\b(?:etc\.?|and so on|etc)\b",  # fin de liste flou
]

# Seuils de longueur (tokens estimés = chars / 4)
MIN_RESPONSE_TOKENS = 20  # réponse trop courte → confiance réduite
MAX_RESPONSE_TOKENS = 2000  # réponse très longue → pas de malus


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class GateDecision:
    """Décision du gate pour un prompt donné."""

    prompt_hash: str
    tier_initial: int
    tier_final: int
    score: float
    adversarial: bool
    adversarial_hits: list[str]
    energy_before: int
    energy_after: int
    spin_flipped: bool
    blocked: bool
    block_reason: str
    model_selected: str
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class GateResult:
    """Résultat complet après passage par le gate."""

    response: str
    decision: GateDecision
    confidence: float
    model_used: str
    elapsed_ms: float
    tokens_used: int


@dataclass
class SiloScore:
    """Score de confiance calculé pour une réponse de silo."""

    raw_score: float  # score brut [0, 1]
    hedging_count: int  # occurrences de hedging
    length_penalty: float  # pénalité si trop court
    length_bonus: float  # bonus si longueur idéale
    final_score: float  # score final [0, 1]


# ══════════════════════════════════════════════════════════════════════════════
# CONFIDENCE SCORER
# ══════════════════════════════════════════════════════════════════════════════


class ConfidenceScorer:
    """
    Calcule le score de confiance d'une réponse LLM.

    Heuristiques :
        - Base : 1.0
        - Chaque occurrence de hedging : -0.08 (cumulatif)
        - Réponse < MIN_RESPONSE_TOKENS : -0.30
        - Réponse dans [MIN, MAX] tokens : +0.05 (bonus qualité)
        - Répétitions de phrases : -0.10
        - Réponse = refus/erreur : 0.0 forcé
    """

    _REFUSAL_PATTERNS = [
        r"(?i)^(je|i)?\s*(ne\s*peux\s*pas|cannot|can'?t|refuse|décline|sorry)",
        r"(?i)(erreur|error|exception|traceback|timeout)",
        r"(?i)(no\s+result|aucun\s+résultat|pas\s+de\s+résultat)",
    ]

    def score(self, response: str) -> SiloScore:
        if not response or not response.strip():
            return SiloScore(0.0, 0, -0.30, 0.0, 0.0)

        # Refus / erreur → score nul
        for pat in self._REFUSAL_PATTERNS:
            if re.search(pat, response[:200]):
                return SiloScore(0.0, 0, 0.0, 0.0, 0.0)

        base = 1.0
        hedging_count = 0

        # Hedging
        for pat in HEDGING_PATTERNS:
            hits = len(re.findall(pat, response, re.IGNORECASE))
            hedging_count += hits
            base -= hits * 0.04  # calibré: hedging naturel LLM ≠ incertitude critique

        # Longueur
        est_tokens = len(response) // 4
        length_penalty = 0.0
        length_bonus = 0.0

        if est_tokens < MIN_RESPONSE_TOKENS:
            length_penalty = -0.45
            base += length_penalty
        elif MIN_RESPONSE_TOKENS <= est_tokens <= MAX_RESPONSE_TOKENS:
            length_bonus = 0.05
            base += length_bonus

        # Répétitions (phrases identiques consécutives)
        sentences = [s.strip() for s in re.split(r"[.!?\n]", response) if len(s.strip()) > 15]
        if len(sentences) > 2:
            seen = set()
            dupes = 0
            for s in sentences:
                if s in seen:
                    dupes += 1
                seen.add(s)
            base -= dupes * 0.10

        final = max(0.0, min(1.0, base))
        return SiloScore(base, hedging_count, length_penalty, length_bonus, final)


# ══════════════════════════════════════════════════════════════════════════════
# METACOGNITION GATE
# ══════════════════════════════════════════════════════════════════════════════


class MetaCognitionGate:
    """
    Couche 1 Engrid — décide quel modèle appeler et si la réponse
    obtenue est suffisamment fiable.

    Usage typique :
        gate = MetaCognitionGate()
        result = gate.process(prompt, tier_hint=0)
        print(result.response, result.confidence)

    Le gate peut être chaîné avec SovereignMembrane :
        gate  = MetaCognitionGate(membrane=SovereignMembrane(mission_id="x"))
        result = gate.process(prompt)
        # → membrane.wrap() est appelé automatiquement avant l'envoi cloud
    """

    def __init__(
        self,
        membrane=None,  # SovereignMembrane optionnelle
        spin_threshold: float = SPIN_THRESHOLD,
        energy_budget: int = ENERGY_BUDGET_TOK,
        adversarial_tier: int = ADVERSARIAL_TIER,
        ollama_url: str = "http://127.0.0.1:11434/api/generate",
        on_decision: Callable[[GateDecision], None] | None = None,
        log_path: str = "",
    ):
        self.membrane = membrane
        self.spin_threshold = spin_threshold
        self.energy_budget = energy_budget
        self.adversarial_tier = adversarial_tier
        self.ollama_url = ollama_url
        self.on_decision = on_decision
        self._scorer = ConfidenceScorer()
        self._energy_used: float = 0.0  # tokens (décroît selon LIF)
        self._last_spike_ts: float = time.time()  # timestamp dernier spike
        self._lif_tau: float = LIF_TAU_SEC
        self._decisions: list[GateDecision] = []

        # Log SQLite optionnel
        self._log_path = log_path or str(
            Path(__file__).resolve().parent.parent / "recon_silo" / "recon_data" / "gate_log.db"
        )
        self._init_log_db()
        # Persistance energy budget entre restarts (fix: LIF reset sur restart)
        self._restore_energy()

    # ── DB log ────────────────────────────────────────────────────────────────

    def _init_log_db(self) -> None:
        import sqlite3

        Path(self._log_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._log_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS gate_decisions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts              TEXT,
                    prompt_hash     TEXT,
                    tier_initial    INTEGER,
                    tier_final      INTEGER,
                    score           REAL,
                    adversarial     INTEGER,
                    spin_flipped    INTEGER,
                    blocked         INTEGER,
                    block_reason    TEXT,
                    model_selected  TEXT,
                    energy_after    INTEGER,
                    elapsed_ms      REAL
                )
            """)
            conn.commit()

    def _log_decision(self, d: GateDecision, elapsed_ms: float) -> None:
        import sqlite3

        try:
            with sqlite3.connect(self._log_path) as conn:
                conn.execute(
                    """
                    INSERT INTO gate_decisions
                    (ts,prompt_hash,tier_initial,tier_final,score,adversarial,
                     spin_flipped,blocked,block_reason,model_selected,energy_after,elapsed_ms)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                    (
                        d.ts,
                        d.prompt_hash,
                        d.tier_initial,
                        d.tier_final,
                        d.score,
                        int(d.adversarial),
                        int(d.spin_flipped),
                        int(d.blocked),
                        d.block_reason,
                        d.model_selected,
                        d.energy_after,
                        elapsed_ms,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"[Gate] Log DB write failed: {e}")

    # ── Adversarial check ─────────────────────────────────────────────────────

    def _check_adversarial(self, prompt: str) -> tuple[bool, list[str]]:
        hits = []
        for pat in ADVERSARIAL_PATTERNS:
            m = re.search(pat, prompt, re.IGNORECASE)
            if m:
                hits.append(m.group(0))
        return bool(hits), hits

    # ── Energy budget ─────────────────────────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def _lif_decay(self) -> None:
        """
        Applique la décroissance LIF sur _energy_used.
        energy(t) = energy_0 * exp(-(t - t_last) / tau)
        Inspiré du modèle LIF domain-wall (vlsi-nanocomputing/LIF-Neuron).
        """
        now = time.time()
        elapsed = now - self._last_spike_ts
        if elapsed > 0 and self._energy_used > 0:
            self._energy_used = self._energy_used * math.exp(-elapsed / self._lif_tau)
        self._last_spike_ts = now

    def _restore_energy(self) -> None:
        """Restaure l'energy_used depuis SQLite (survit aux restarts)."""
        try:
            with sqlite3.connect(self._log_path) as conn:
                row = conn.execute("SELECT energy_after, ts FROM gate_decisions ORDER BY id DESC LIMIT 1").fetchone()
                if row:
                    import time as _t, math as _m

                    energy, ts_str = row
                    # Appliquer la décroissance LIF depuis le dernier enregistrement
                    elapsed = _t.time() - _t.mktime(_t.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S"))
                    restored = energy * _m.exp(-elapsed / self._lif_tau)
                    self._energy_used = max(0.0, restored)
                    self._last_spike_ts = _t.time()
        except Exception:
            pass

    def _check_energy(self, prompt: str) -> tuple[bool, str]:
        self._lif_decay()  # décroissance avant toute vérification
        cost = self._estimate_tokens(prompt)
        if self._energy_used + cost > self.energy_budget:
            return True, (
                f"Energy budget épuisé : {self._energy_used:.0f}/{self.energy_budget} tokens "
                f"(après décroissance LIF τ={self._lif_tau:.0f}s). "
                f"Ce prompt coûterait ~{cost} tokens de plus."
            )
        return False, ""

    # ── LLM call ──────────────────────────────────────────────────────────────

    def _call_ollama(self, model: str, prompt: str, max_tokens: int = 600) -> str:
        import urllib.request as _ur

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.15, "num_predict": max_tokens},
        }
        req = _ur.Request(
            self.ollama_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = json.loads(_ur.urlopen(req, timeout=60).read())
        return resp.get("response", "").strip()

    # ── Core process ──────────────────────────────────────────────────────────

    def process(
        self,
        prompt: str,
        tier_hint: int = 0,
        max_spins: int = 2,
        context: str = "",
        model_hint: str = "",
    ) -> GateResult:
        """
        Traite un prompt avec spin flip automatique.

        Args:
            prompt     : le prompt à envoyer au LLM
            tier_hint  : tier de départ (0=rapide, 2=puissant)
            max_spins  : escalades max autorisées
            context    : contexte additionnel (non compté dans budget)
            model_hint : ID modèle recommandé par ModelQualificator
                         (ex: "openrouter/deepseek/deepseek-r1").
                         Si non-ollama → force tier=3 (cloud via Membrane).
                         Si ollama → injecté directement dans _call_ollama.

        Returns:
            GateResult avec réponse, score de confiance, modèle utilisé.
        """
        t0 = time.perf_counter()

        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:12]
        full_prompt = (context + "\n\n" + prompt).strip() if context else prompt

        # ── 1. Energy budget ──────────────────────────────────────────────────
        energy_before = self._energy_used
        budget_exceeded, budget_reason = self._check_energy(full_prompt)
        if budget_exceeded:
            decision = GateDecision(
                prompt_hash=prompt_hash,
                tier_initial=tier_hint,
                tier_final=tier_hint,
                score=0.0,
                adversarial=False,
                adversarial_hits=[],
                energy_before=energy_before,
                energy_after=energy_before,
                spin_flipped=False,
                blocked=True,
                block_reason=budget_reason,
                model_selected="BLOCKED",
            )
            self._decisions.append(decision)
            elapsed = (time.perf_counter() - t0) * 1000
            self._log_decision(decision, elapsed)
            return GateResult("", decision, 0.0, "BLOCKED", elapsed, 0)

        # ── 2. Adversarial check ──────────────────────────────────────────────
        is_adv, adv_hits = self._check_adversarial(full_prompt)
        tier = max(tier_hint, self.adversarial_tier if is_adv else 0)

        # ── 2b. model_hint du ModelQualificator ───────────────────────────────
        # Translate l'ID modèle en tier hint, en respectant le plancher adversarial
        _model_hint_tier = 0
        if model_hint:
            if "ollama" not in model_hint and model_hint not in ("local", ""):
                # Modèle cloud qualifié → tier 3 (via Membrane)
                _model_hint_tier = 3
            elif "7b" in model_hint or "7B" in model_hint:
                _model_hint_tier = 2  # qwen 7b
            elif "1.5b" in model_hint or "1.5B" in model_hint:
                _model_hint_tier = 0
            else:
                _model_hint_tier = 1  # laforge-qwen ou autre local
            tier = max(tier, _model_hint_tier)
            logger.debug(f"[Gate] model_hint={model_hint!r} → tier_hint={_model_hint_tier}")

        if is_adv:
            logger.info(f"[Gate] Adversarial keywords: {adv_hits} → tier≥{self.adversarial_tier}")

        # ── 3. Membrane wrap si cloud ─────────────────────────────────────────
        send_prompt = full_prompt
        if tier >= 3 and self.membrane is not None:
            wrapped = self.membrane.wrap(full_prompt)
            send_prompt = wrapped.content
            logger.info(f"[Gate] Membrane: {wrapped.alias_count} alias substitués")

        # ── 4. Spin loop ──────────────────────────────────────────────────────
        tier_initial = tier
        response = ""
        score_obj = SiloScore(0.0, 0, 0.0, 0.0, 0.0)
        spin_count = 0
        spin_flipped = False

        for spin in range(max_spins + 1):
            model = MODEL_TIERS[min(tier, len(MODEL_TIERS) - 1)]

            if model == "cloud":
                # Placeholder cloud — à brancher sur forge_sovereign_membrane
                if self.membrane is not None:
                    try:
                        response = self._call_ollama(
                            MODEL_TIERS[2], send_prompt
                        )  # Fallback tier 2 si cloud non configuré
                    except Exception as e:
                        response = f"Erreur cloud: {e}"
                else:
                    response = "[Gate] Cloud non configuré — membrane manquante."
            else:
                try:
                    # Si model_hint est un modèle ollama spécifique, l'utiliser directement
                    _effective_model = model
                    if model_hint and "ollama/" in model_hint and tier < 3:
                        _effective_model = model_hint.replace("ollama/", "")
                    response = self._call_ollama(_effective_model, send_prompt)
                except Exception as e:
                    response = f"Erreur modèle {model}: {e}"
                    logger.warning(f"[Gate] LLM error tier={tier}: {e}")

            # Score de confiance
            score_obj = self._scorer.score(response)

            logger.debug(
                f"[Gate] spin={spin} tier={tier} model={model} "
                f"score={score_obj.final_score:.2f} hedging={score_obj.hedging_count}"
            )

            # Spin flip ?
            if score_obj.final_score >= self.spin_threshold or tier >= len(MODEL_TIERS) - 1:
                break  # confiance OK ou tier max atteint

            if spin < max_spins:
                tier += 1
                spin_count += 1
                spin_flipped = True
                logger.info(
                    f"[Gate] Spin flip: score={score_obj.final_score:.2f} < "
                    f"{self.spin_threshold} → tier {tier - 1}→{tier} ({MODEL_TIERS[min(tier, len(MODEL_TIERS) - 1)]})"
                )
                # Re-wrap si on passe en cloud
                if tier >= 3 and self.membrane is not None:
                    wrapped = self.membrane.wrap(full_prompt)
                    send_prompt = wrapped.content

        # ── 5. Energy accounting ──────────────────────────────────────────────
        tokens_used = self._estimate_tokens(full_prompt) + self._estimate_tokens(response)
        self._lif_decay()  # decay avant d'ajouter le coût du spike
        self._energy_used += tokens_used

        # ── 6. Unwrap si membrane ─────────────────────────────────────────────
        if tier >= 3 and self.membrane is not None:
            try:
                response = self.membrane.unwrap(response)
            except Exception:
                pass

        # ── 7. Decision record ────────────────────────────────────────────────
        elapsed = (time.perf_counter() - t0) * 1000
        model_used = MODEL_TIERS[min(tier, len(MODEL_TIERS) - 1)]

        decision = GateDecision(
            prompt_hash=prompt_hash,
            tier_initial=tier_initial,
            tier_final=tier,
            score=score_obj.final_score,
            adversarial=is_adv,
            adversarial_hits=adv_hits,
            energy_before=energy_before,
            energy_after=self._energy_used,
            spin_flipped=spin_flipped,
            blocked=False,
            block_reason="",
            model_selected=model_used,
        )

        self._decisions.append(decision)
        self._log_decision(decision, elapsed)

        if self.on_decision:
            try:
                self.on_decision(decision)
            except Exception:
                pass

        return GateResult(
            response=response,
            decision=decision,
            confidence=score_obj.final_score,
            model_used=model_used,
            elapsed_ms=elapsed,
            tokens_used=tokens_used,
        )

    # ── Helpers publics ───────────────────────────────────────────────────────

    def reset_energy(self) -> None:
        """Remet le compteur d'énergie et le timestamp LIF à zéro."""
        self._energy_used = 0.0
        self._last_spike_ts = time.time()

    def energy_status(self) -> dict:
        self._lif_decay()  # snapshot après décroissance
        elapsed = time.time() - self._last_spike_ts
        # taux de décroissance instantané (%/min)
        decay_rate_per_min = (1 - math.exp(-60 / self._lif_tau)) * 100
        return {
            "used": round(self._energy_used, 1),
            "budget": self.energy_budget,
            "remaining": round(max(0.0, self.energy_budget - self._energy_used), 1),
            "pct": round(self._energy_used / self.energy_budget * 100, 1),
            "lif_tau_sec": self._lif_tau,
            "decay_rate_%/min": round(decay_rate_per_min, 2),
            "idle_sec": round(elapsed, 1),
        }

    def decision_history(self, last: int = 10) -> list[dict]:
        return [
            {
                "ts": d.ts,
                "model": d.model_selected,
                "score": round(d.score, 3),
                "tier": f"{d.tier_initial}→{d.tier_final}",
                "spin": d.spin_flipped,
                "adversarial": d.adversarial,
                "energy": d.energy_after,
            }
            for d in self._decisions[-last:]
        ]

    def summary(self) -> dict:
        if not self._decisions:
            return {"decisions": 0}
        scores = [d.score for d in self._decisions if not d.blocked]
        spins = sum(1 for d in self._decisions if d.spin_flipped)
        blocks = sum(1 for d in self._decisions if d.blocked)
        return {
            "decisions": len(self._decisions),
            "spins": spins,
            "blocks": blocks,
            "avg_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
            "min_score": round(min(scores), 3) if scores else 0.0,
            "energy": self.energy_status(),
        }
