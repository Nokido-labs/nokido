"""
forge_orchestrator.py — Nokido Engrid v3 · Couche 2
======================================================
ForgeOrchestrator : chaîne complète multi-silos.

Pipeline :
    prompt brut
        │
    MetaCognitionGate  (score confiance, spin flip, energy budget)
        │
    SovereignMembrane  (wrap — anonymisation)
        │
    ┌───┴──────────────────────────┐
    SILO_INFRA   SILO_LOGIC   SILO_PAYLOAD
    (réseau)     (CWE/CVE)    (fuzzing/QA)
        │             │             │
    └───┬──────────────────────────┘
        │
    Réconciliateur local (unwrap + fusion)
        │
    Résultat final enrichi

Chaque silo reçoit une vue partielle du prompt (segmentation).
Le réconciliateur fusionne les 3 réponses localement.
Rien de sensible ne sort jamais en clair.
"""

from __future__ import annotations

# DEAD_IMPORT removed: import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES SILOS
# ══════════════════════════════════════════════════════════════════════════════

SILO_CONFIGS = {
    "INFRA": {
        "model": "qwen2.5-coder:1.5b",
        "focus": "infrastructure réseau : ports, services, topology, firewall",
        "extract": ["ports", "services", "os", "mac", "topology"],
        "prompt_suffix": (
            "Concentre-toi UNIQUEMENT sur l'infrastructure réseau : "
            "ports ouverts, services détectés, OS fingerprint, topologie. "
            "Pas de CVE, pas de remédiations — juste les faits réseau bruts. "
            "Format : liste structurée."
        ),
    },
    "LOGIC": {
        "model": "laforge-qwen:latest",
        "focus": "vulnérabilités logiques : CVE, CWE, patterns d'exploitation",
        "extract": ["cve", "cwe", "severity", "attack_vector"],
        "prompt_suffix": (
            "Concentre-toi UNIQUEMENT sur les vulnérabilités logiques : "
            "CVE, CWE, patterns d'exploitation, vecteurs d'attaque. "
            "Pas d'IPs, pas de ports — juste l'analyse de sécurité abstraite. "
            "Format : liste CVE/CWE avec sévérité."
        ),
    },
    "PAYLOAD": {
        "model": "qwen2.5-coder:1.5b",
        "focus": "surface d'attaque : endpoints, formats, fuzzing",
        "extract": ["endpoints", "input_vectors", "auth", "data_format"],
        "prompt_suffix": (
            "Concentre-toi UNIQUEMENT sur la surface d'attaque applicative : "
            "endpoints exposés, formats de données, mécanismes d'auth, "
            "vecteurs de fuzzing potentiels. "
            "Pas d'IPs, pas de CVE — juste la surface applicative. "
            "Format : liste structurée."
        ),
    },
}

# Timeout par silo (secondes)
SILO_TIMEOUT = 55

# Modèle réconciliateur
RECONCILER_MODEL = "laforge-qwen:latest"
RECONCILER_MAX_TOKENS = 800


# ══════════════════════════════════════════════════════════════════════════════
# STRUCTURES
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class LatencyMetric:
    """Trace le coût temporel et l'origine d'une inférence silo."""

    elapsed_ms: float
    provider: str  # 'local_igpu' | 'cloud_api'
    model: str
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class SiloResult:
    name: str
    response: str
    confidence: float
    model: str
    elapsed_ms: float
    error: str = ""
    provider: str = "local_igpu"  # 'local_igpu' | 'cloud_api'
    inhibited: bool = False  # True si veto latéral
    latency: LatencyMetric | None = None


@dataclass
class OrchestratorResult:
    """Résultat final fusionné par le réconciliateur."""

    final: str  # texte fusionné dé-anonymisé
    silos: list[SiloResult]  # résultats bruts par silo
    confidence_avg: float  # score moyen des silos
    gate_summary: dict  # résumé MetaCognitionGate
    mission_id: str
    elapsed_ms: float
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ══════════════════════════════════════════════════════════════════════════════
# SEGMENTEUR DE PROMPT
# ══════════════════════════════════════════════════════════════════════════════


class PromptSegmenter:
    """
    Découpe un prompt en 3 vues partielles pour les 3 silos.
    Chaque silo reçoit uniquement les informations pertinentes à son domaine.
    """

    # Lignes/patterns pertinents pour chaque silo
    _SILO_PATTERNS = {
        "INFRA": [
            r"\bport\b",
            r"\bservice\b",
            r"\bopen\b",
            r"\bfilter",
            r"\btcp\b",
            r"\budp\b",
            r"\bping\b",
            r"\bttl\b",
            r"\bmac\b",
            r"\barp\b",
            r"\bgateway\b",
            r"\bsubnet\b",
            r"\bos\b",
            r"\bfirmware\b",
            r"\bversion\b",
            r"\bbanner\b",
            r"\bip\b",
            r"\bhôte\b",
            r"\bhost\b",
            r"\bscan\b",
        ],
        "LOGIC": [
            r"\bcve\b",
            r"\bcwe\b",
            r"\bvuln",
            r"\bsever",
            r"\brce\b",
            r"\bsqli\b",
            r"\bxss\b",
            r"\bssrf\b",
            r"\bauth\b",
            r"\bcred",
            r"\bpassword\b",
            r"\btoken\b",
            r"\bpatch\b",
            r"\bremedi",
            r"\brisk\b",
            r"\bexploit",
            r"\battack\b",
            r"\bbypass\b",
            r"\binject",
        ],
        "PAYLOAD": [
            r"\bendpoint\b",
            r"\bapi\b",
            r"\bpath\b",
            r"\broute\b",
            r"\bhttp\b",
            r"\bget\b",
            r"\bpost\b",
            r"\bput\b",
            r"\bjson\b",
            r"\bxml\b",
            r"\bform\b",
            r"\bparam",
            r"\bfuzz\b",
            r"\binput\b",
            r"\bupload\b",
            r"\bfile\b",
            r"\bwss\b",
            r"\bwebsocket\b",
            r"\bsetup\b",
            r"\bconfig\b",
        ],
    }

    def segment(self, prompt: str) -> dict[str, str]:
        """
        Retourne un dict {silo_name: prompt_partiel}.
        Chaque vue inclut : header commun + lignes filtrées + suffix silo.
        """
        lines = prompt.splitlines()

        # Sépare le header (premières lignes avant les données hôtes)
        header_lines = []
        data_lines = []
        in_data = False
        for line in lines:
            if re.search(r"HOTE |hôte |\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", line, re.I):
                in_data = True
            if in_data:
                data_lines.append(line)
            else:
                header_lines.append(line)

        header = "\n".join(header_lines).strip()

        result = {}
        for silo, patterns in self._SILO_PATTERNS.items():
            compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
            filtered = []
            for line in data_lines:
                if any(c.search(line) for c in compiled):
                    filtered.append(line)

            # Fallback : si rien de pertinent → envoie un résumé minimal
            if not filtered and data_lines:
                filtered = data_lines[: min(10, len(data_lines))]

            view = (header + "\n\n" + "\n".join(filtered)).strip()
            view += "\n\n" + SILO_CONFIGS[silo]["prompt_suffix"]
            result[silo] = view

        return result


# ══════════════════════════════════════════════════════════════════════════════
# RÉCONCILIATEUR
# ══════════════════════════════════════════════════════════════════════════════


class Reconciler:
    """
    Fusionne les réponses des 3 silos en un rapport cohérent.
    Tourne localement — voit les données réelles (après unwrap).
    """

    def __init__(self, ollama_url: str = "http://127.0.0.1:11434/api/generate"):
        self._url = ollama_url

    def reconcile(self, silos: list[SiloResult], mission_id: str) -> str:
        """
        Fusionne les réponses silos avec inhibition latérale.
        Si le silo PAYLOAD détecte du contenu sensible (secrets non anonymisés),
        il pose un veto qui marque les autres silos comme inhibited.
        """
        # ── Inhibition latérale : veto silo PAYLOAD (détecteur de bruit) ─────
        payload_silo = next((s for s in silos if s.name == "PAYLOAD" and s.response), None)
        veto = False
        veto_reason = ""
        if payload_silo:
            import re as _re

            # Détecte IPs/secrets non anonymisés qui auraient traversé la membrane
            _LEAK_PATTERNS = [
                r"\b(?:\d{1,3}\.){3}\d{1,3}\b",  # IP brute
                r"\b(?:password|passwd|secret|token)\s*[=:]",  # credential leak
                r"-----BEGIN (?:RSA|EC|OPENSSH)",  # clé privée
            ]
            for pat in _LEAK_PATTERNS:
                if _re.search(pat, payload_silo.response, _re.IGNORECASE):
                    veto = True
                    veto_reason = f"Silo PAYLOAD: donnée sensible détectée ({pat[:30]})"
                    logger.warning(f"[Inhibition] VETO: {veto_reason}")
                    break
        if veto:
            for s in silos:
                if s.name != "PAYLOAD":
                    s.inhibited = True

        parts = []
        for s in silos:
            if s.response and not s.error:
                inhibit_tag = " [INHIBÉ]" if s.inhibited else ""
                parts.append(f"=== SILO {s.name} (confiance={s.confidence:.2f}{inhibit_tag}) ===\n{s.response}")

        if not parts:
            return "[Réconciliateur] Aucune réponse silo disponible."

        fusion_prompt = (
            f"Mission: {mission_id}\n\n"
            "Tu es le réconciliateur local. Tu reçois les analyses de 3 silos spécialisés "
            "(infrastructure, vulnérabilités logiques, surface applicative).\n"
            "Fusionne-les en un rapport de sécurité cohérent :\n"
            "1. Synthèse infrastructure\n"
            "2. Vulnérabilités identifiées (CVE/CWE)\n"
            "3. Surface d'attaque applicative\n"
            "4. Recommandations prioritaires\n\n"
            "Élimine les redondances. Sois concis et factuel.\n\n" + "\n\n".join(parts)
        )

        try:
            import urllib.request as _ur

            payload = {
                "model": RECONCILER_MODEL,
                "prompt": fusion_prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": RECONCILER_MAX_TOKENS},
            }
            req = _ur.Request(
                self._url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = json.loads(_ur.urlopen(req, timeout=90).read())
            return resp.get("response", "").strip()
        except Exception as e:
            logger.error(f"[Reconciler] Erreur LLM: {e}")
            # Fallback : concaténation brute
            return "\n\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATEUR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════


class ForgeOrchestrator:
    """
    Couche 2 Engrid — orchestre Gate + Membrane + Silos + Réconciliateur.

    Usage minimal :
        orch   = ForgeOrchestrator(mission_id="recon_20260328")
        result = orch.run(raw_prompt)
        print(result.final)

    Usage complet :
        membrane = SovereignMembrane(mission_id="recon_20260328")
        gate     = MetaCognitionGate(membrane=membrane)
        orch     = ForgeOrchestrator(mission_id="recon_20260328",
                                     gate=gate, membrane=membrane)
        result   = orch.run(raw_prompt)
    """

    def __init__(
        self,
        mission_id: str = "default",
        gate=None,  # MetaCognitionGate (optionnel — créé auto si absent)
        membrane=None,  # SovereignMembrane (optionnel — créé auto si absent)
        ollama_url: str = "http://127.0.0.1:11434/api/generate",
        on_silo_done: Callable[[SiloResult], None] | None = None,
        on_result: Callable[[OrchestratorResult], None] | None = None,
        parallel: bool = True,
    ):
        self.mission_id = mission_id
        self.ollama_url = ollama_url
        self.on_silo_done = on_silo_done
        self.on_result = on_result
        self.parallel = parallel

        # Lazy init Gate + Membrane si non fournis
        self._gate = gate
        self._membrane = membrane
        self._segmenter = PromptSegmenter()
        self._reconciler = Reconciler(ollama_url)

    def _lazy_init(self):
        """Instancie Gate et Membrane si non fournis à la construction."""
        if self._membrane is None:
            try:
                import sys

                sys.path.insert(0, str(Path(__file__).resolve().parent))
                from nokido_agent.app.forge_sovereign_membrane import SovereignMembrane

                self._membrane = SovereignMembrane(mission_id=self.mission_id)
                logger.info("[Orch] SovereignMembrane créée auto")
            except Exception as e:
                logger.warning(f"[Orch] Membrane indisponible: {e}")

        if self._gate is None:
            try:
                from nokido_agent.app.forge_metacognition_gate import MetaCognitionGate

                self._gate = MetaCognitionGate(
                    membrane=self._membrane,
                    ollama_url=self.ollama_url,
                )
                logger.info("[Orch] MetaCognitionGate créée auto")
            except Exception as e:
                logger.warning(f"[Orch] Gate indisponible: {e}")

    # ── LLM silo ──────────────────────────────────────────────────────────────

    def _call_silo(self, silo_name: str, prompt: str) -> SiloResult:
        """Appelle un silo LLM et retourne son résultat avec score de confiance."""
        cfg = SILO_CONFIGS[silo_name]
        model = cfg["model"]
        t0 = time.perf_counter()

        try:
            import urllib.request as _ur

            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 500},
            }
            req = _ur.Request(
                self.ollama_url,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            resp = json.loads(_ur.urlopen(req, timeout=SILO_TIMEOUT).read())
            text = resp.get("response", "").strip()
            elapsed = (time.perf_counter() - t0) * 1000

            # Score confiance via gate scorer si disponible
            confidence = 0.75  # défaut
            if self._gate is not None and hasattr(self._gate, "_scorer"):
                s = self._gate._scorer.score(text)
                confidence = s.final_score

            # Détecte si l'appel a dépassé le seuil cloud (>2s → probablement cloud)
            provider = "cloud_api" if elapsed > 2000 else "local_igpu"
            result = SiloResult(
                name=silo_name,
                response=text,
                confidence=confidence,
                model=model,
                elapsed_ms=elapsed,
                provider=provider,
                latency=LatencyMetric(elapsed_ms=elapsed, provider=provider, model=model),
            )

        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.error(f"[Orch] Silo {silo_name} erreur: {e}")
            result = SiloResult(
                name=silo_name,
                response="",
                confidence=0.0,
                model=model,
                elapsed_ms=elapsed,
                error=str(e),
            )

        if self.on_silo_done:
            try:
                self.on_silo_done(result)
            except Exception:
                pass

        return result

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(
        self,
        prompt: str,
        tier_hint: int = 0,
        skip_gate: bool = False,
        skip_membrane: bool = False,
    ) -> OrchestratorResult:
        """
        Pipeline complet : Gate → Membrane → Silos (parallèles) → Réconciliateur.

        Args:
            prompt        : prompt brut (données sensibles OK — sera anonymisé)
            tier_hint     : tier LLM de départ (0=rapide, 2=puissant)
            skip_gate     : passe le Gate (pour tests unitaires)
            skip_membrane : passe la Membrane (réseau local uniquement)
        """
        t0 = time.perf_counter()
        self._lazy_init()

        # ── 1. Gate — vérification adversariale + energy budget ───────────────
        gate_summary = {}
        if not skip_gate and self._gate is not None:
            # On utilise le gate en mode "dry run" pour la décision seulement
            # (pas d'appel LLM ici — le gate évalue le prompt entrant)
            is_adv, hits = self._gate._check_adversarial(prompt)
            budget_ok, budget_msg = self._gate._check_energy(prompt)
            if budget_ok:
                elapsed = (time.perf_counter() - t0) * 1000
                return OrchestratorResult(
                    final=f"[Orchestrateur bloqué] {budget_msg}",
                    silos=[],
                    confidence_avg=0.0,
                    gate_summary={"blocked": True, "reason": budget_msg},
                    mission_id=self.mission_id,
                    elapsed_ms=elapsed,
                )
            gate_summary = {
                "adversarial": is_adv,
                "adversarial_hits": hits,
                "tier_hint": max(tier_hint, 2 if is_adv else 0),
                "energy": self._gate.energy_status(),
            }
            tier_hint = gate_summary["tier_hint"]

        # ── 2. Membrane wrap ──────────────────────────────────────────────────
        safe_prompt = prompt
        wrapped_result = None
        if not skip_membrane and self._membrane is not None:
            try:
                wrapped_result = self._membrane.wrap(prompt)
                safe_prompt = wrapped_result.content
                logger.info(
                    f"[Orch] Membrane wrap: {wrapped_result.alias_count} alias, hash={wrapped_result.content_hash}"
                )
            except Exception as e:
                logger.warning(f"[Orch] Membrane wrap failed: {e} — on continue en clair")

        # ── 3. Segmentation en vues silos ─────────────────────────────────────
        silo_views = self._segmenter.segment(safe_prompt)

        # ── 4. Appels silos (parallèles ou séquentiels) ───────────────────────
        silo_results: list[SiloResult] = []

        if self.parallel:
            # ── Go dispatcher (goroutines, no GIL) ───────────────────────────
            _go_ok = False
            _go_url = getattr(self, "_go_dispatcher_url", "http://127.0.0.1:8779/dispatch")
            try:
                import urllib.request as _ur2

                _go_payload = json.dumps(
                    {
                        "ollama_url": self.ollama_url,
                        "silos": [
                            {"name": n, "model": SILO_CONFIGS[n]["model"], "prompt": v, "timeout": int(SILO_TIMEOUT)}
                            for n, v in silo_views.items()
                        ],
                    }
                ).encode()
                _go_req = _ur2.Request(_go_url, data=_go_payload, headers={"Content-Type": "application/json"})
                _go_resp = json.loads(_ur2.urlopen(_go_req, timeout=5).read())
                for r in _go_resp.get("results", []):
                    n = r["name"]
                    elapsed = float(r.get("elapsed_ms", 0))
                    if r.get("error"):
                        silo_results.append(
                            SiloResult(
                                name=n,
                                response="",
                                confidence=0.0,
                                model=SILO_CONFIGS[n]["model"],
                                elapsed_ms=elapsed,
                                error=r["error"],
                            )
                        )
                    else:
                        text = r.get("response", "").strip()
                        provider = "cloud_api" if elapsed > 2000 else "local_igpu"
                        silo_results.append(
                            SiloResult(
                                name=n,
                                response=text,
                                confidence=0.75,
                                model=SILO_CONFIGS[n]["model"],
                                elapsed_ms=elapsed,
                                provider=provider,
                                latency=LatencyMetric(
                                    elapsed_ms=elapsed, provider=provider, model=SILO_CONFIGS[n]["model"]
                                ),
                            )
                        )
                _go_ok = True
                logger.info(f"[Orch] go-dispatcher ok — {len(silo_results)} silos in {_go_resp.get('total_ms')}ms")
            except Exception as _go_e:
                logger.debug(f"[Orch] go-dispatcher unavailable ({_go_e}) — fallback asyncio")

            if not _go_ok:
                # Asyncio gather — remplace threading (Tulip pattern)
                import asyncio as _aio

                loop = None
                try:
                    loop = _aio.get_event_loop()
                except RuntimeError:
                    loop = _aio.new_event_loop()
                    _aio.set_event_loop(loop)

                async def _run_all():
                    async def _async_silo(n: str, v: str) -> SiloResult:
                        return await loop.run_in_executor(None, self._call_silo, n, v)

                    tasks = {n: _async_silo(n, v) for n, v in silo_views.items()}
                    results = await _aio.gather(*tasks.values(), return_exceptions=True)
                    return dict(zip(tasks.keys(), results))

                try:
                    if loop.is_running():
                        import concurrent.futures as _cf

                        with _cf.ThreadPoolExecutor(max_workers=len(silo_views)) as ex:
                            futures = {n: ex.submit(self._call_silo, n, v) for n, v in silo_views.items()}
                            for name, fut in futures.items():
                                try:
                                    silo_results.append(fut.result(timeout=SILO_TIMEOUT + 5))
                                except Exception:
                                    silo_results.append(
                                        SiloResult(
                                            name=name,
                                            response="",
                                            confidence=0.0,
                                            model=SILO_CONFIGS[name]["model"],
                                            elapsed_ms=0.0,
                                            error="timeout",
                                        )
                                    )
                    else:
                        store = loop.run_until_complete(_run_all())
                        for name, result in store.items():
                            if isinstance(result, Exception):
                                silo_results.append(
                                    SiloResult(
                                        name=name,
                                        response="",
                                        confidence=0.0,
                                        model=SILO_CONFIGS[name]["model"],
                                        elapsed_ms=0.0,
                                        error=str(result),
                                    )
                                )
                            else:
                                silo_results.append(result)
                except Exception as _ae:
                    logger.warning(f"Async gather err: {_ae} — fallback threading")
                    import threading as _th

                    store2 = {}
                    threads2 = []
                    for name, view in silo_views.items():

                        def _w(n=name, v=view):
                            store2[n] = self._call_silo(n, v)

                        t = _th.Thread(target=_w, daemon=True)
                        t.start()
                        threads2.append((name, t))
                    for name, t in threads2:
                        t.join(timeout=SILO_TIMEOUT + 5)
                        silo_results.append(
                            store2.get(
                                name,
                                SiloResult(
                                    name=name,
                                    response="",
                                    confidence=0.0,
                                    model=SILO_CONFIGS[name]["model"],
                                    elapsed_ms=0.0,
                                    error="timeout",
                                ),
                            )
                        )
        else:
            for name, view in silo_views.items():
                silo_results.append(self._call_silo(name, view))

        # Trie dans l'ordre canonique
        order = {"INFRA": 0, "LOGIC": 1, "PAYLOAD": 2}
        silo_results.sort(key=lambda s: order.get(s.name, 9))

        # ── 5. Unwrap des réponses silos ──────────────────────────────────────
        if not skip_membrane and self._membrane is not None:
            for sr in silo_results:
                if sr.response:
                    try:
                        sr.response = self._membrane.unwrap(sr.response)
                    except Exception:
                        pass

        # ── 6. Réconciliation locale ──────────────────────────────────────────
        final = self._reconciler.reconcile(silo_results, self.mission_id)

        # ── 7. Comptabilité energy gate ───────────────────────────────────────
        if self._gate is not None:
            total_tokens = sum(self._gate._estimate_tokens(sr.response) for sr in silo_results if sr.response)
            self._gate._energy_used += total_tokens

        # ── 8. Score moyen ────────────────────────────────────────────────────
        valid_scores = [sr.confidence for sr in silo_results if not sr.error]
        confidence_avg = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0

        elapsed = (time.perf_counter() - t0) * 1000
        gate_summary["confidence_avg"] = round(confidence_avg, 3)

        result = OrchestratorResult(
            final=final,
            silos=silo_results,
            confidence_avg=confidence_avg,
            gate_summary=gate_summary,
            mission_id=self.mission_id,
            elapsed_ms=elapsed,
        )

        if self.on_result:
            try:
                self.on_result(result)
            except Exception:
                pass

        logger.info(f"[Orch] Done — silos={len(silo_results)} conf_avg={confidence_avg:.2f} elapsed={elapsed:.0f}ms")
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_mcp_tools(self) -> list[dict]:
        """
        [DIRECTIVE 2026-03-22] Définitions d'outils obligatoires pour appels cloud.
        Une pensée sans capacité d'action validée est une hallucination.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "apply_structural_mutation",
                    "description": "Applique une mutation sur l'AST du fichier cible.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "diff": {"type": "string", "description": "Patch unifié"},
                            "justification": {"type": "string", "description": "Raison technique"},
                            "risk_level": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                        },
                        "required": ["diff", "justification"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "emit_security_finding",
                    "description": "Émet un finding de sécurité structuré vers le RAG.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "severity": {"type": "string", "enum": ["info", "low", "medium", "high", "critical"]},
                            "cve": {"type": "string"},
                            "detail": {"type": "string"},
                        },
                        "required": ["title", "severity"],
                    },
                },
            },
        ]

    def status(self) -> dict:
        gate_energy = self._gate.energy_status() if self._gate else {}
        return {
            "mission_id": self.mission_id,
            "gate_ready": self._gate is not None,
            "membrane_ready": self._membrane is not None,
            "silos": list(SILO_CONFIGS.keys()),
            "parallel": self.parallel,
            "gate_energy": gate_energy,
        }


# ============================================================================
# Compat retro : alias pour Nokido.py qui a un import lie a une ancienne
# nomenclature (refacto incomplete). Ne pas casser la TUI pour si peu.
# ============================================================================
# OrchestratorManager = alias vers la classe reelle ForgeOrchestrator.
OrchestratorManager = ForgeOrchestrator

# Singleton paresseux pour get_orchestrator()
_orchestrator_singleton = None


def get_orchestrator(*args, **kwargs):
    """Retourne un ForgeOrchestrator singleton (lazy init)."""
    global _orchestrator_singleton
    if _orchestrator_singleton is None:
        _orchestrator_singleton = ForgeOrchestrator(*args, **kwargs)
    return _orchestrator_singleton


__all__ = [
    "ForgeOrchestrator",
    "OrchestratorManager",
    "get_orchestrator",
    "LatencyMetric",
    "SiloResult",
    "OrchestratorResult",
    "PromptSegmenter",
    "Reconciler",
]
