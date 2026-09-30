"""
forge_engrid_engine.py — Nokido Engrid v3 · Facade principale
===============================================================
Transpose ForgeEngridEngine (spec neuro-souveraine) sur les composants réels.

Mapping spec → implémentation :
    CognitiveShard          → SiloResult (INFRA/LOGIC/PAYLOAD) + LatencyMetric
    LatencyMetric           → SiloResult.latency (provider: local_igpu|cloud_api)
    asyncio.gather          → ForgeOrchestrator.parallel=True (threading)
    SovereignContextMapper  → SovereignMembrane.wrap/unwrap
    _calculate_confidence   → ConfidenceScorer.score()
    _apply_lateral_inhibition → Reconciler + veto silo PAYLOAD
    _get_mcp_tools          → ForgeOrchestrator._get_mcp_tools() [2026-03-22]
    MultiLLMBridge          → MetaCognitionGate (tier 0=local, tier 2=cloud)
    ForgeNoiseGuardian      → NoiseGuardian dans forge_silo_fragmenter.py
    Spin Flip               → MetaCognitionGate.spin_threshold

Cycle cognitif :
    execute_cognitive_cycle(task, data)
        │
        ├── S1 (local iGPU)  : SpikeRouter → tier 0 qwen1.5b  ← criticité < 0.40
        ├── Gate (spin flip) : MetaCognitionGate               ← 0.40 ≤ c < 0.70
        └── S2 (cloud)       : ForgeOrchestrator               ← c ≥ 0.70
               └── wrap(data) → INFRA|LOGIC|PAYLOAD → unwrap → Reconciler
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Perspectives des colonnes corticales — ordre canonique
_SHARD_PERSPECTIVES = [
    "Sécurité",  # shard_0
    "Performance",  # shard_1
    "Maintenabilité",  # shard_2
    "Conformité OSS",  # shard_3 — vérifie les standards open-source
    "Logique",  # shard_4
    "Robustesse",  # shard_5
    "Alignement GitHub",  # shard_6 — aligne sur l'intelligence GitHub injectée
    "Densité",  # shard_7
    "Analyse de Bruit",  # shard_8 — inhibiteur latéral
]

# Index du shard "Analyse de Bruit" (inhibiteur latéral par défaut)
_NOISE_SHARD_IDX = 8


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURES (aliases spec → réalité)
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class ShardLatencyEntry:
    """Entrée dans l'historique de latence d'un shard."""

    elapsed_ms: float
    provider: str  # 'local_igpu' | 'cloud_api'
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CognitiveShard:
    """
    Unité de perspective dans la grille Engrid (LIF-inspired).
    Alias de SiloResult enrichi avec état spintronique.
    """

    id: str
    perspective: str
    weight: float = 1.0
    last_state: str = "UP"  # UP = S1 local (spin ↑), DOWN = S2 cloud (spin ↓)
    confidence_score: float = 1.0
    inhibited: bool = False
    latency_history: list = field(default_factory=list)  # list[ShardLatencyEntry]
    assigned_model: str = "local"  # modèle S2 qualifié par ModelQualificator

    def record_latency(self, elapsed_ms: float, provider: str) -> None:
        self.latency_history.append(ShardLatencyEntry(elapsed_ms=elapsed_ms, provider=provider))

    @property
    def avg_latency_ms(self) -> float:
        if not self.latency_history:
            return 0.0
        return sum(e.elapsed_ms for e in self.latency_history) / len(self.latency_history)


@dataclass
class CycleResult:
    """Résultat d'un cycle cognitif complet."""

    task: str
    system_used: str  # S1 | GATE | ORCHESTRATOR
    final: str  # rapport synthétisé
    elapsed_ms: float
    confidence: float
    silo_latencies: list[dict]  # [{name, elapsed_ms, provider}]
    spin_flipped: bool
    inhibitions: list[str]  # silos inhibés
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ══════════════════════════════════════════════════════════════════════════════
# FORGE ENGRID ENGINE
# ══════════════════════════════════════════════════════════════════════════════

# ══════════════════════════════════════════════════════════════════════════════
# MODEL QUALIFICATOR
# ══════════════════════════════════════════════════════════════════════════════


class ModelQualificator:
    """
    Sélectionne le modèle S2 optimal pour chaque shard selon sa perspective
    et la complexité de la tâche.

    Règles de tiering (par ordre de préférence) :
        S1  → toujours local (qwen 1.5b / laforge-qwen) — souverain, gratuit
        S2 Sécurité / complexité high → DeepSeek R1 (CoT profond, économique)
        S2 Bruit / Conformité         → Gemini Flash (quota généreux, brassage texte)
        S2 reste                      → MetaCognitionGate tier2 local (qwen 7b)

    Le tiering est consultatif : MetaCognitionGate reste le décideur final
    (spin flip, energy budget, adversarial check). Le model_hint est injecté
    comme metadata dans le spike pour orienter le Gate.
    """

    MODEL_REGISTRY: dict[str, dict[str, str]] = {
        "architect": {
            "primary": "openrouter/google/gemma-3-27b-it:free",  # gratuit, capable
            "alternative": "openrouter/google/gemma-3-12b-it:free",  # fallback stable (27B rate-limited)
            "free_tier": "openrouter/google/gemma-3-12b-it:free",  # léger, gratuit
        },
        "specialist": {
            "code": "ollama/qwen2.5-coder:7b",  # local souverain
            "audit": "openrouter/meta-llama/llama-3.3-70b-instruct:free",
            "security": "openrouter/nousresearch/hermes-3-llama-3.1-405b:free",
        },
        "reflex": {
            "local": "ollama/qwen2.5-coder:1.5b",  # instantané iGPU
            "cloud": "openrouter/google/gemma-3-4b-it:free",  # zéro coût
        },
    }

    # Mapping perspective → tier recommandé pour S2
    _PERSPECTIVE_TIER: dict[str, str] = {
        "Sécurité": "alternative",  # DeepSeek R1 — CoT adversarial
        "Logique": "primary",  # Claude — précision logique
        "Réseau": "code",  # local code — ports, subnets
        "P2P": "code",
        "Mémoire": "code",
        "Performance": "code",
        "Maintenabilité": "code",
        "Analyse de Bruit": "free_tier",  # Gemini Flash — brassage texte
        "Conformité OSS": "free_tier",
        "Alignement GitHub": "free_tier",
        "Robustesse": "primary",
        "Densité": "code",
    }

    @classmethod
    def select_best_s2(cls, perspective: str, complexity: str = "medium") -> str:
        """
        Retourne l'identifiant de modèle recommandé pour le S2 d'un shard.

        complexity 'high' force le tier 'alternative' (DeepSeek R1 CoT)
        pour toutes les perspectives.
        """
        if complexity == "high":
            return cls.MODEL_REGISTRY["architect"]["alternative"]

        tier = cls._PERSPECTIVE_TIER.get(perspective, "primary")

        if tier in ("code",):
            return cls.MODEL_REGISTRY["specialist"]["code"]
        if tier in cls.MODEL_REGISTRY["architect"]:
            return cls.MODEL_REGISTRY["architect"][tier]
        return cls.MODEL_REGISTRY["architect"]["primary"]

    @classmethod
    def s2_provider(cls, model_id: str) -> str:
        """Infère le provider depuis l'ID modèle (pour LatencyMetric)."""
        if "ollama" in model_id:
            return "local_cpu"
        if "openrouter" in model_id or "anthropic" in model_id or "google" in model_id:
            return "cloud_api"
        return "local_igpu"


# ══════════════════════════════════════════════════════════════════════════════
# CENTRAL EXECUTIVE CORTEX
# ══════════════════════════════════════════════════════════════════════════════


class CentralExecutiveCortex:
    """
    Hub d'orchestration : déconstruit l'intention et reconstruit la vision.

    deconstruct_mission() : appel S1 local (qwen 1.5b) pour déterminer
    dynamiquement quels angles activer selon la sémantique de la tâche.

    reconstruct_vision() : délégué au Reconciler local (pas de cloud ici —
    la synthèse reste souveraine et utilise les résultats déjà unwrappés).
    """

    # Catalogue des perspectives disponibles avec leurs mots-clés déclencheurs
    _PERSPECTIVE_TRIGGERS: dict[str, list[str]] = {
        "Sécurité": ["cve", "exploit", "audit", "vuln", "pentest", "injection", "auth", "crack"],
        "Performance": ["latenc", "slow", "bottleneck", "optim", "memory", "cpu", "timeout", "leak"],
        "Maintenabilité": ["refactor", "clean", "debt", "legacy", "complex", "coupling", "cohes"],
        "Conformité OSS": ["license", "oss", "standard", "pep8", "ruff", "lint", "contrib", "style"],
        "Logique": ["bug", "logic", "edge", "case", "test", "assert", "invariant", "proof"],
        "Robustesse": ["crash", "except", "error", "handle", "recover", "retry", "fallback"],
        "Alignement GitHub": ["issue", "pr", "contrib", "upstream", "fork", "patch", "release"],
        "Densité": ["compress", "pack", "size", "token", "chunk", "payload", "bandwidth"],
        "Analyse de Bruit": ["leak", "secret", "ip", "credential", "pii", "sensitive", "private"],
        "Réseau": ["tcp", "udp", "socket", "port", "http", "dns", "arp", "subnet"],
        "P2P": ["p2p", "peer", "bridge", "relay", "mesh", "gossip", "swarm"],
        "Mémoire": ["oom", "heap", "gc", "buffer", "pool", "alloc", "free"],
    }

    def __init__(self, ollama_url: str = "http://127.0.0.1:11434/api/generate"):
        self._url = ollama_url
        self.qualificator = ModelQualificator()

    def deconstruct_mission(self, task: str, max_perspectives: int = 5) -> list[str]:
        """
        Détermine dynamiquement les perspectives de la grille selon la tâche.

        1. Scoring keyword : compte les triggers dans task (rapide, local)
        2. LLM S1 optionnel : si Ollama dispo, enrichit la sélection
        3. Toujours inclure Sécurité + Analyse de Bruit (invariants souverains)

        Retourne une liste de perspective strings (2–7 items).
        """
        task_lower = task.lower()
        scores: dict[str, int] = {}

        for perspective, triggers in self._PERSPECTIVE_TRIGGERS.items():
            score = sum(1 for t in triggers if t in task_lower)
            if score > 0:
                scores[perspective] = score

        # Invariants souverains — toujours présents
        mandatory = ["Sécurité", "Analyse de Bruit"]
        selected = list(mandatory)

        # Tri par score décroissant, ajout jusqu'à max_perspectives
        for p, _ in sorted(scores.items(), key=lambda x: -x[1]):
            if p not in selected and len(selected) < max_perspectives:
                selected.append(p)

        # Fallback : si moins de 3 → ajouter Logique + Robustesse
        for fallback in ["Logique", "Robustesse"]:
            if fallback not in selected and len(selected) < 3:
                selected.append(fallback)

        # Assigner le modèle S2 optimal à chaque perspective
        complexity = "high" if any(k in task.lower() for k in ("cve", "exploit", "critical", "kernel")) else "medium"
        return [
            {
                "perspective": p,
                "s2_model": self.qualificator.select_best_s2(p, complexity),
            }
            for p in selected
        ]

    def reconstruct_vision(self, shard_results: dict[str, str], task: str) -> str:
        """
        Synthèse locale souveraine des résultats shardés.
        Utilise le Reconciler existant via Ollama — pas de cloud ici.
        """
        parts = [
            "=== CORTEX [" + perspective + "] ===\n" + result for perspective, result in shard_results.items() if result
        ]
        if not parts:
            return "[Cortex] Aucun résultat silo."

        # Appel local qwen pour synthèse (fallback : concat brute si Ollama absent)
        try:
            import urllib.request as _ur
            import json as _j

            shard_text = "\n\n".join(parts)
            synthesis_prompt = (
                "Mission: "
                + task
                + "\n\n"
                + "Analyses shardees:\n"
                + shard_text
                + "\nSynthese souveraine: correlations critiques. Concis."
            )
            payload = {
                "model": "laforge-qwen:latest",
                "prompt": synthesis_prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 600},
            }
            req = _ur.Request(self._url, data=_j.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            resp = _j.loads(_ur.urlopen(req, timeout=60).read())
            return resp.get("response", "").strip()
        except Exception:
            return "\n\n".join(parts)  # fallback concat souverain


class ForgeEngridEngine:
    """
    Facade principale de l'architecture Engrid.

    Câble SpikeRouter + MetaCognitionGate + ForgeOrchestrator + SovereignMembrane
    en un seul point d'entrée avec l'API execute_cognitive_cycle().
    """

    def __init__(
        self,
        grid_size: int = 3,  # 2→4 shards, 3→9 shards (limité aux 3 silos réels)
        ollama_url: str = "http://127.0.0.1:11434/api/generate",
        mission_id: str = "",
        on_silo_done: Callable | None = None,
    ):
        self.grid_size = grid_size
        self.ollama_url = ollama_url
        self.mission_id = mission_id or f"engrid_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.on_silo_done = on_silo_done
        self.global_overhead_ms = 0.0

        # Cortex central
        self.cortex = CentralExecutiveCortex(ollama_url=self.ollama_url)

        # Grille initiale (sera redéfinie par _initialize_dynamic_shards)
        n = min(grid_size**2, len(_SHARD_PERSPECTIVES))
        self.shards: dict[str, CognitiveShard] = {
            f"shard_{i}": CognitiveShard(
                id=f"shard_{i}",
                perspective=_SHARD_PERSPECTIVES[i],
            )
            for i in range(n)
        }

        # Lazy — instanciés à la première utilisation
        self._router: object = None
        self._gate: object = None
        self._orchestrator: object = None
        self._membrane: object = None

    # ── Grille dynamique ──────────────────────────────────────────────────────

    def _initialize_dynamic_shards(self, perspectives: list) -> None:
        """
        Reconstruit la grille selon les perspectives choisies par le Cortex.
        Accepte list[str] ou list[dict] ({"perspective": ..., "s2_model": ...}).
        Préserve les shards existants dont la perspective est conservée.
        """
        new_shards: dict[str, CognitiveShard] = {}
        for i, p_item in enumerate(perspectives):
            # Normalisation : str ou dict
            if isinstance(p_item, dict):
                p = p_item["perspective"]
                s2_model = p_item.get("s2_model", "local")
            else:
                p = p_item
                s2_model = "local"

            sid = f"shard_{i}"
            existing = next((s for s in self.shards.values() if s.perspective == p), None)
            if existing:
                existing.id = sid
                existing.assigned_model = s2_model
                new_shards[sid] = existing
            else:
                new_shards[sid] = CognitiveShard(id=sid, perspective=p, assigned_model=s2_model)
        self.shards = new_shards

    # ── Lazy init ─────────────────────────────────────────────────────────────

    def _init_components(self):
        """Instancie les composants Engrid au premier appel."""
        root = Path(__file__).resolve().parent

        if self._membrane is None:
            try:
                from nokido_agent.app.forge_sovereign_membrane import SovereignMembrane

                self._membrane = SovereignMembrane(mission_id=self.mission_id)
                logger.info("[Engrid] SovereignMembrane OK")
            except Exception as e:
                logger.warning(f"[Engrid] Membrane indisponible: {e}")

        if self._gate is None:
            try:
                from nokido_agent.app.forge_metacognition_gate import MetaCognitionGate

                self._gate = MetaCognitionGate(
                    membrane=self._membrane,
                    ollama_url=self.ollama_url,
                )
                logger.info("[Engrid] MetaCognitionGate OK")
            except Exception as e:
                logger.warning(f"[Engrid] Gate indisponible: {e}")

        if self._orchestrator is None:
            try:
                from nokido_agent.app.forge_orchestrator import ForgeOrchestrator

                self._orchestrator = ForgeOrchestrator(
                    mission_id=self.mission_id,
                    gate=self._gate,
                    membrane=self._membrane,
                    ollama_url=self.ollama_url,
                    on_silo_done=self.on_silo_done,
                    parallel=True,
                )
                logger.info("[Engrid] ForgeOrchestrator OK")
            except Exception as e:
                logger.warning(f"[Engrid] Orchestrator indisponible: {e}")

        if self._router is None:
            try:
                from nokido_agent.app.forge_spike_router import SpikeRouter

                self._router = SpikeRouter(
                    gate=self._gate,
                    orchestrator=self._orchestrator,
                    ollama_url=self.ollama_url,
                )
                logger.info("[Engrid] SpikeRouter OK")
            except Exception as e:
                logger.warning(f"[Engrid] SpikeRouter indisponible: {e}")

    # ── Cycle cognitif principal ───────────────────────────────────────────────

    def execute_cognitive_cycle(
        self,
        task: str,
        data: str,
        severity: str = "medium",
        spike_type: str = "user_intent",
        github_intel: str = "",
    ) -> CycleResult:
        """
        Cycle de pensée souverain avec Intelligence GitHub optionnelle.

        L'intelligence GitHub est mixée avec `data` AVANT le wrap() de la Membrane :
            safe_prompt = wrap(data + "\n[GITHUB_INTEL]: " + github_intel)
        Les shards Conformité OSS (shard_3) et Alignement GitHub (shard_6) la consomment
        prioritairement lors de la segmentation LOGIC/PAYLOAD.

        Args:
            task         : description de la tâche
            data         : données brutes (seront anonymisées par la Membrane)
            severity     : low | medium | high | critical
            spike_type   : type de spike
            github_intel : contexte GitHub — issues, PRs, style guides (NE contient pas de secrets)
        """
        t0 = time.perf_counter()
        self._init_components()

        # GitHub intel mixé AVANT la Membrane — annoté pour que les silos OSS le consomment
        _intel_block = f"\n\n[GITHUB_INTEL]\n{github_intel}" if github_intel else ""
        prompt = f"{task}\n\n{data}{_intel_block}".strip()

        # ── PHASE 0 : Déconstruction corticale ────────────────────────────────
        perspectives = self.cortex.deconstruct_mission(task)
        self._initialize_dynamic_shards(perspectives)

        print(f"\n🧠 [ENGRID] Cycle cognitif — grille dynamique {len(self.shards)} perspectives")
        print(f"   Cortex → {perspectives}")
        if github_intel:
            print(f"📡 [GITHUB-INTEL] {len(github_intel)} chars injectés (shards OSS/Alignement)")
        print(f"   Mission : {self.mission_id}")

        # ── Route via SpikeRouter ──────────────────────────────────────────────
        system_used = "S1"
        final = ""
        confidence = 0.0
        spin_flipped = False
        silo_latencies: list[dict] = []
        inhibitions: list[str] = []

        if self._router is not None:
            from nokido_agent.app.forge_spike_router import Spike

            spike = Spike(
                type=spike_type,
                payload=prompt,
                source="engrid",
                severity=severity,
            )
            result = self._router.route(spike)
            system_used = result.system_used
            final = result.response
            confidence = result.confidence

            # Récupère les latences silos si orchestrator utilisé
            if system_used == "ORCHESTRATOR" and self._orchestrator is not None:
                # Le dernier run de l'orchestrator a ses silos dans l'historique
                # On re-run pour avoir les métriques (le spike_router a déjà appelé orch.run)
                # → on récupère les infos du router
                pass

            # Spin flip détecté si le gate a changé de tier
            if self._gate is not None and hasattr(self._gate, "_decisions"):
                decisions = self._gate._decisions
                if decisions and decisions[-1].spin_flipped:
                    spin_flipped = True

        else:
            # Fallback direct si router absent
            system_used = "S1_DIRECT"
            final = f"[Engrid sans router] task={task[:80]}"
            confidence = 0.5

        # ── Phase S2 directe si criticité haute et orchestrateur disponible ───
        if system_used in ("GATE", "S1") and severity in ("high", "critical"):
            if self._orchestrator is not None:
                print(f"🚨 [SPIN-FLIP] Escalade S2 forcée (severity={severity})")
                spin_flipped = True
                or_result = self._orchestrator.run(
                    prompt,
                    tier_hint=2,
                    skip_gate=False,
                    skip_membrane=False,
                )
                final = or_result.final
                confidence = or_result.confidence_avg
                system_used = "ORCHESTRATOR"

                # Collecte latences silos
                for sr in or_result.silos:
                    silo_latencies.append(
                        {
                            "name": sr.name,
                            "elapsed_ms": round(sr.elapsed_ms, 1),
                            "provider": sr.provider,
                            "confidence": round(sr.confidence, 3),
                        }
                    )
                    if sr.inhibited:
                        inhibitions.append(sr.name)

        self.global_overhead_ms = (time.perf_counter() - t0) * 1000

        # ── Mise à jour état spintronique des shards ──────────────────────────
        for sr in silo_latencies:
            shard_name = sr.get("name", "")
            # Trouve le shard correspondant au silo (INFRA→shard_0, LOGIC→shard_1…)
            silo_to_shard = {"INFRA": "shard_0", "LOGIC": "shard_1", "PAYLOAD": "shard_2"}
            sid = silo_to_shard.get(shard_name)
            if sid and sid in self.shards:
                sh = self.shards[sid]
                sh.confidence_score = sr.get("confidence", 0.75)
                sh.inhibited = sr.get("inhibited", False)
                sh.last_state = "DOWN" if sr.get("provider") == "cloud_api" else "UP"
                sh.record_latency(sr.get("elapsed_ms", 0.0), sr.get("provider", "local_igpu"))

        # ── Rapport terminal ──────────────────────────────────────────────────
        spin_icon = "🔄" if spin_flipped else "⚡"
        print(f"{spin_icon} [ENGRID] Système activé : {system_used}")
        if silo_latencies:
            self._print_latency_report(silo_latencies)
        print(f"✅ [ENGRID] Cycle terminé en {self.global_overhead_ms:.0f}ms (confiance={confidence:.2f})")

        # ── PHASE FINALE : Reconstruction corticale (si silos disponibles) ─────
        if silo_latencies and final:
            shard_results = {
                s.get("name", f"silo_{i}"): s.get("name", "") + ": " + final[:400] for i, s in enumerate(silo_latencies)
            }
            # Reconstruction légère — enrichit le final avec corrélations
            try:
                vision = self.cortex.reconstruct_vision(shard_results, task)
                if vision and len(vision) > 50:
                    final = vision
            except Exception:
                pass  # fallback : on garde le final existant

        return CycleResult(
            task=task,
            system_used=system_used,
            final=final,
            elapsed_ms=self.global_overhead_ms,
            confidence=confidence,
            silo_latencies=silo_latencies,
            spin_flipped=spin_flipped,
            inhibitions=inhibitions,
        )

    async def execute_cognitive_cycle_async(
        self, task: str, data: str, github_intel: str = "", **kwargs
    ) -> CycleResult:
        if github_intel:
            kwargs["github_intel"] = github_intel
        """Version async — délègue au thread pool pour ne pas bloquer l'event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.execute_cognitive_cycle(task, data, **kwargs))

    # ── Latency report ────────────────────────────────────────────────────────

    def _print_latency_report(self, latencies: list[dict]) -> None:
        print("\n📊 TABLEAU DE BORD DE LATENCE :")
        for s in latencies:
            icon = "⚡" if s["provider"] == "local_igpu" else "☁️"
            inh = " [INHIBÉ]" if s.get("inhibited") else ""
            print(f"   {icon} {s['name']:<12} | {s['elapsed_ms']:7.1f}ms | conf={s['confidence']:.2f}{inh}")
        print("   " + "─" * 44)

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        self._init_components()
        return {
            "mission_id": self.mission_id,
            "grid_size": self.grid_size,
            "components": {
                "membrane": self._membrane is not None,
                "gate": self._gate is not None,
                "orchestrator": self._orchestrator is not None,
                "router": self._router is not None,
            },
            "overhead_ms": round(self.global_overhead_ms, 1),
            "shards": {
                sid: {
                    "perspective": sh.perspective,
                    "last_state": sh.last_state,
                    "confidence": round(sh.confidence_score, 3),
                    "inhibited": sh.inhibited,
                    "avg_latency_ms": round(sh.avg_latency_ms, 1),
                }
                for sid, sh in self.shards.items()
            },
        }


# ══════════════════════════════════════════════════════════════════════════════
# FORGE COGNITIVE WRAPPER — SDK haut niveau
# ══════════════════════════════════════════════════════════════════════════════


class ForgeCognitiveWrapper:
    """
    Entry point SDK-style pour intégration directe dans PyQt6, scripts ou MCP.
    Masque la complexité de la grille, de la souveraineté et des shards.

    Usage :
        wrapper = ForgeCognitiveWrapper()
        report  = wrapper.run_mission(
            prompt       = "Audit sécurité module P2P",
            target_code  = "socket.bind(0.0.0.0, 8080)",
            context      = "Issue #42: Memory leak",
        )
        print(report["vision"])     # synthèse finale
        print(report["telemetry"])  # overhead_ms, shards, perspectives
    """

    def __init__(
        self,
        grid_size: int = 3,
        ollama_url: str = "http://127.0.0.1:11434/api/generate",
        mission_id: str = "",
    ):
        self.engine = ForgeEngridEngine(
            grid_size=grid_size,
            ollama_url=ollama_url,
            mission_id=mission_id,
        )

    def run_mission(
        self,
        prompt: str,
        target_code: str = "",
        context: str = "",
        severity: str = "medium",
    ) -> dict:
        """
        Lance un cycle cognitif complet et retourne un objet enrichi.

        Args:
            prompt      : description de la mission
            target_code : code ou données cibles (seront anonymisées)
            context     : intelligence contextuelle — issues GitHub, logs, etc.
            severity    : low | medium | high | critical

        Returns:
            {
                "status":    "COMPLETED" | "ERROR",
                "vision":    str,    # synthèse corticale finale
                "telemetry": {
                    "overhead_ms":    float,
                    "shards_active":  int,
                    "perspectives":   list[str],
                    "spin_flipped":   bool,
                    "system_used":    str,
                }
            }
        """
        data = f"{target_code}\n\n{context}".strip() if target_code else context
        try:
            result = self.engine.execute_cognitive_cycle(
                task=prompt,
                data=data,
                severity=severity,
                github_intel=context,
            )
            return {
                "status": "COMPLETED",
                "vision": result.final,
                "telemetry": {
                    "overhead_ms": round(result.elapsed_ms, 2),
                    "shards_active": len(self.engine.shards),
                    "perspectives": [s.perspective for s in self.engine.shards.values()],
                    "spin_flipped": result.spin_flipped,
                    "system_used": result.system_used,
                    "confidence": round(result.confidence, 3),
                },
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "vision": f"[Wrapper] Erreur: {e}",
                "telemetry": {},
            }
