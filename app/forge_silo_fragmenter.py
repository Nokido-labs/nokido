"""
app/forge_silo_fragmenter.py — Siloed Fragmentation Engine + Noise Guardian v1.0
==================================================================================
Pipeline de souveraineté numérique :

    Rapport brut (complet, sensible)
              │
    ┌─────────▼──────────┐
    │   NOISE GUARDIAN   │  IPs → GENERIC_IP_ADDR_882
    │   Magic constants  │  CVE-2017-0143 → VULN-SIG-7
    │   Signatures tools │  Mimikatz → CRED-TOOL-3
    │   Entropie inject  │  Lignes log banales ajoutées
    └─────────┬──────────┘
              │ 3 contextes anonymisés distincts
    ┌─────────┴───────────────────────────────────┐
    │  SILO INFRA      SILO LOGIC    SILO PAYLOAD  │
    │  "config réseau" "audit CWE"   "fuzzing QA"  │
    │  qwen2.5-7b      deepseek-6.7b laforge-qwen  │
    │  voit: ports     voit: patterns voit: types   │
    └─────────┬───────────────────────────────────┘
              │ sorties partielles anodines
    ┌─────────▼──────────┐
    │  RÉCONCILIATEUR    │  Seul le Ryzen a la clé
    │  local (Ryzen)     │  Dé-anonymise + fusionne
    │  RAG local only    │  Rien ne sort
    └────────────────────┘
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# NOISE GUARDIAN
# ══════════════════════════════════════════════════════════════════════════════


class NoiseGuardian:
    """
    Dernière ligne de défense avant envoi à un LLM.

    1. Magic constants  : 0xDEADBEEF → GENERIC_HEX_452
    2. CVEs/signatures  : CVE-2017-0143 → VULN-SIG-7 (persistant par session)
    3. IPs              : localhost → GENERIC_IP_ADDR_882 (persistant)
    4. Entropie         : lignes de log banales si fragment trop "pur"
    5. Score sensibilité: bloque si > seuil avant envoi cloud
    """

    SIGNATURE_PATTERNS = [
        (r"CVE-\d{4}-\d{4,7}", "VULN-SIG"),
        (r"MS\d{2}-\d{3,4}", "MSADV"),
        # (r'EternalBlue|EternalRomance',        'EXPLOIT-SIG-A'),  # disabled: faux positif
        (r"BlueKeep", "EXPLOIT-SIG-B"),
        (r"WannaCry|NotPetya", "MALWARE-SIG"),
        (r"Mimikatz|mimikatz", "CRED-TOOL"),
        (r"Metasploit|msfconsole|msfvenom", "EXPLOIT-FRAMEWORK"),
        (r"Impacket|impacket", "NET-TOOLKIT"),
        (r"secretsdump(?:\.py)?", "CRED-DUMP-TOOL"),
        (r"psexec|PsExec", "REMOTE-EXEC-TOOL"),
        (r"ntlmrelayx(?:\.py)?", "RELAY-TOOL"),
        (r"crackmapexec|cme\b", "NET-AUDIT-TOOL"),
        (r"[Bb]lood[Hh]ound", "GRAPH-ENUM-TOOL"),
        (r"Responder(?:\.py)?", "POISON-TOOL"),
        (r"hashcat|john(?:\s+the\s+ripper)?", "CRACK-TOOL"),
    ]

    ENTROPY_LINES = [
        "[DEBUG] Connection pool initialized (idle=2, active=0)",
        "[INFO]  Cache flush completed in 12ms",
        "[TRACE] GC cycle: freed 847KB, 23ms pause",
        "[DEBUG] Thread pool resize: 4->6 workers",
        "[INFO]  Config reload: no changes detected",
        "[TRACE] Heartbeat sent (seq=1847, rtt=3ms)",
        "[DEBUG] Buffer compact: 1024->512 bytes",
        "[INFO]  Metrics snapshot persisted",
        "[TRACE] Socket backlog cleared (q=0)",
        "[DEBUG] Auth token refresh scheduled",
    ]

    SENSITIVITY_CHECKS = [
        (r"CVE-\d{4}", 0.30),
        (r"exploit|pwn|shell(?:code)?", 0.20),
        (r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", 0.20),
        (r"password|credential|hash|ntlm", 0.15),
        (r"0x[0-9a-f]{4,}", 0.10),
        (r"metasploit|mimikatz|impacket", 0.25),
        (r"backdoor|rootkit|malware", 0.20),
        (r"reverse.shell|bind.shell", 0.25),
    ]

    def __init__(self):
        self._aliases: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._rng_seed = int(time.time()) % 10000

    def _counter(self, key: str) -> int:
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    def _alias(self, value: str, prefix: str) -> str:
        """Alias persistant — même valeur → même alias dans toute la session."""
        if value in self._aliases:
            return self._aliases[value]
        h = int(hashlib.md5(value.encode()).hexdigest()[:4], 16) % 900 + 100
        alias = f"{prefix}_{h}"
        # MESURE 2026-09-25 : 900 alias par prefixe, AUCUN controle -- 2 000 IP donnaient 806
        # alias : deux valeurs sous un meme alias ne se restituent plus. Suffixe sur collision.
        pris = self.__dict__.setdefault("_alias_pris", set(self._aliases.values()))
        k = 1
        while alias in pris:
            k += 1
            alias = f"{prefix}_{h}_{k}"
        pris.add(alias)
        self._aliases[value] = alias
        return alias

    def neutralize_ips(self, text: str) -> tuple[str, int]:
        count = 0

        def repl(m):
            nonlocal count
            ip = m.group(0)
            if ip.startswith("127.") or ip == "0.0.0.0":
                return ip
            count += 1
            return self._alias(ip, "GENERIC_IP_ADDR")

        result = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", repl, text)
        return result, count

    def neutralize_signatures(self, text: str) -> tuple[str, int]:
        count = 0
        result = text
        for pattern, prefix in self.SIGNATURE_PATTERNS:

            def make_repl(pfx):
                def r(m):
                    nonlocal count
                    count += 1
                    return self._alias(m.group(0), pfx)

                return r

            new, n = re.subn(pattern, make_repl(prefix), result, flags=re.IGNORECASE)
            result, count = new, count
        return result, count

    def neutralize_magic(self, text: str) -> tuple[str, int]:
        count = 0

        def repl_hex(m):
            nonlocal count
            count += 1
            return f"GENERIC_HEX_{self._counter('hex'):03d}"

        def repl_port(m):
            nonlocal count
            count += 1
            return f"GENERIC_PORT_{self._counter('port'):03d}"

        result, n1 = re.subn(r"\b0x[0-9A-Fa-f]{4,16}\b", repl_hex, text)
        result, n2 = re.subn(r"\b(?:4444|31337|6666|55553)\b", repl_port, result)

        # MACs : xx:xx:xx:xx:xx:xx ou xx-xx-xx-xx-xx-xx
        def repl_mac(m):
            nonlocal count
            count += 1
            return self._alias(m.group(0), "GENERIC_MAC")

        result, n3 = re.subn(r"\b(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}\b", repl_mac, result)
        return result, n1 + n2 + n3

    def inject_entropy(self, text: str, min_density: int = 3) -> str:
        """Ajoute des lignes de log banales si le fragment est trop "pur"."""
        lines = [l for l in text.splitlines() if l.strip()]
        if len(lines) >= min_density * 4:
            return text
        import random

        rng = random.Random(self._rng_seed)
        n = max(1, min_density - len(lines) // 4)
        noise = rng.sample(self.ENTROPY_LINES, min(n, len(self.ENTROPY_LINES)))
        result = lines[:]
        for nl in noise:
            result.insert(rng.randint(0, len(result)), nl)
        return "\n".join(result)

    def sensitivity_score(self, text: str) -> float:
        score = 0.0
        for pattern, weight in self.SENSITIVITY_CHECKS:
            if re.search(pattern, text, re.IGNORECASE):
                score += weight
        return min(1.0, score)

    def sanitize(self, text: str, max_sensitivity: float = 0.5, add_entropy: bool = True) -> tuple[str, dict]:
        """Pipeline complet : neutralise + valide + entropie."""
        rpt = {
            "original_len": len(text),
            "neutralized_ips": 0,
            "neutralized_sigs": 0,
            "neutralized_magic": 0,
            "entropy_injected": False,
            "sensitivity_before": self.sensitivity_score(text),
            "sensitivity_after": 0.0,
            "blocked": False,
            "block_reason": "",
        }
        # Détection injections/jailbreak — bloque avant de passer au LLM
        import re as _re_san

        _INJECT = [
            (r"ignore previous instructions", "prompt injection"),
            (r"ignore all (?:previous|prior)", "prompt injection"),
            (r"you are now\s+(?:a |an |DAN)", "jailbreak role switch"),
            (r"do anything now", "jailbreak DAN"),
            (r"(?i)system:\s*override", "override système"),
            (r"disregard (?:all |your )", "injection disregard"),
            (r"\[INST\]|\[/INST\]", "format Llama inject"),
            (r"<\|.*?\|>", "token spécial LLM"),
        ]
        for _pat, _reason in _INJECT:
            if _re_san.search(_pat, text, _re_san.IGNORECASE):
                rpt["blocked"] = True
                rpt["block_reason"] = f"Injection détectée: {_reason}"
                return "", rpt
        result, rpt["neutralized_ips"] = self.neutralize_ips(text)
        result, rpt["neutralized_sigs"] = self.neutralize_signatures(result)
        result, rpt["neutralized_magic"] = self.neutralize_magic(result)
        if add_entropy:
            result = self.inject_entropy(result)
            rpt["entropy_injected"] = True
        rpt["sensitivity_after"] = self.sensitivity_score(result)
        if rpt["sensitivity_after"] > max_sensitivity:
            rpt["blocked"] = True
            rpt["block_reason"] = (
                f"Sensibilité {rpt['sensitivity_after']:.2f} > seuil {max_sensitivity}. "
                "Segmenter davantage ou réduire le contexte."
            )
        return result, rpt

    def deanonymize(self, text: str) -> str:
        """Restaure les vraies valeurs dans une réponse LLM.

        `_aliases` est {valeur: alias}. MESURE 2026-09-25 : la boucle le lisait A L'ENVERS
        (`for alias, real in ...`) -- elle cherchait la VALEUR dans le texte pour la remplacer
        par l'ALIAS : rien n'etait jamais restitue. Alias les plus longs d'abord.
        """
        result = text
        for real, alias in sorted(self._aliases.items(), key=lambda x: -len(x[1])):
            result = result.replace(alias, real)
        return result

    def export_key(self) -> dict:
        return {"aliases": dict(self._aliases), "counters": dict(self._counters)}

    def import_key(self, key: dict):
        self._aliases = key.get("aliases", {})
        self._counters = key.get("counters", {})


# ══════════════════════════════════════════════════════════════════════════════
# Dataclasses
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class Fragment:
    id: str
    silo: str
    prompt: str
    model: str
    output: str = ""
    duration: float = 0.0
    tokens: int = 0
    guardian_rpt: dict = field(default_factory=dict)
    blocked: bool = False


@dataclass
class FragmentedReport:
    id: str
    source: str
    fragments: list[Fragment] = field(default_factory=list)
    synthesis: str = ""
    alias_key: dict = field(default_factory=dict)
    duration: float = 0.0
    rag_indexed: bool = False
    stats: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


# ══════════════════════════════════════════════════════════════════════════════
# FRAGMENTATION ENGINE
# ══════════════════════════════════════════════════════════════════════════════


class FragmentationEngine:
    """
    Orchestrateur de fragmentation cognitive.
    3 silos indépendants → réconciliation locale → RAG.
    """

    SILO_MODELS = {
        "infra": "qwen2.5-coder:7b-instruct-q4_K_M",
        "logic": "deepseek-coder:6.7b",
        "payload": "laforge-qwen:latest",
    }

    def __init__(self, max_sensitivity: float = 0.5):
        self._guardian = NoiseGuardian()
        self._max_sens = max_sensitivity

    # ── Extraction ────────────────────────────────────────────────────────────

    def _extract(self, report: str, keywords: list[str], limit: int = 40) -> str:
        lines = [l for l in report.splitlines() if any(k in l.lower() for k in keywords)]
        return "\n".join(lines[:limit]) if lines else report[:600]

    def _ctx_infra(self, r: str) -> str:
        return self._extract(
            r,
            [
                "port",
                "service",
                "protocol",
                "tcp",
                "udp",
                "open",
                "firewall",
                "signing",
                "version",
                "banner",
                "network",
                "gateway",
            ],
        )

    def _ctx_logic(self, r: str) -> str:
        return self._extract(
            r,
            [
                "vuln",
                "weak",
                "deprecated",
                "unauthenticated",
                "bypass",
                "overflow",
                "injection",
                "disclosure",
                "privilege",
                "default",
                "unsigned",
                "cleartext",
                "exposed",
                "misconfigured",
            ],
        )

    def _ctx_payload(self, r: str) -> str:
        return self._extract(
            r,
            [
                "input",
                "parameter",
                "field",
                "form",
                "api",
                "endpoint",
                "login",
                "auth",
                "credential",
                "user",
                "password",
                "token",
                "upload",
                "request",
                "header",
                "cookie",
            ],
            limit=30,
        )

    # ── Prompts ───────────────────────────────────────────────────────────────

    def _prompt_infra(self, ctx: str) -> str:
        return (
            "Tu es expert en configuration réseau et hardening.\n"
            "Analyse cette configuration (données anonymisées) :\n"
            "1. Services exposés avec niveau de risque CVSS\n"
            "2. Protocoles obsolètes ou non sécurisés\n"
            "3. Bonnes pratiques manquantes\n"
            "4. Vecteurs d'exposition réseau\n\n"
            f"Configuration :\n{ctx}\n\n"
            'Réponds en JSON : {"services":[{"name":...,"risk":...,"issues":[...]}],'
            '"hardening_gaps":[...],"vectors":[...]}'
        )

    def _prompt_logic(self, ctx: str) -> str:
        return (
            "Tu es expert en sécurité applicative.\n"
            "Analyse ce comportement applicatif (données anonymisées) :\n"
            "1. Patterns de vulnérabilité CWE/OWASP\n"
            "2. Vecteurs d'exploitation théoriques (complexité 1-10)\n"
            "3. Conditions préalables\n"
            "4. Contre-mesures et mitigations\n\n"
            f"Comportement :\n{ctx}\n\n"
            'Réponds en JSON : {"vulns":[{"cwe":...,"desc":...,"complexity":...}],'
            '"mitigations":[...],"exploitation_path":"..."}'
        )

    def _prompt_payload(self, ctx: str) -> str:
        return (
            "Tu es expert en tests de robustesse et QA sécurité.\n"
            "Pour ces surfaces d'entrée (données anonymisées), génère :\n"
            "1. Cas de test limites (edge cases)\n"
            "2. Patterns de fuzzing adaptés\n"
            "3. Séquences d'authentification à valider\n\n"
            f"Surfaces :\n{ctx}\n\n"
            'Réponds en JSON : {"test_vectors":[{"type":...,"pattern":...}],'
            '"auth_tests":[...],"fuzzing":[...]}'
        )

    # ── LLM ───────────────────────────────────────────────────────────────────

    async def _call(self, model: str, prompt: str, max_tokens: int = 400, timeout: int = 180) -> tuple[str, int]:
        import urllib.request

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": max_tokens},
        }
        if "qwen3" in model:
            payload["think"] = False
        loop = asyncio.get_event_loop()

        def _run():
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                "http://127.0.0.1:11434/api/generate", data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                d = json.loads(resp.read())
            return d.get("response", ""), d.get("eval_count", 0)

        try:
            return await asyncio.wait_for(loop.run_in_executor(None, _run), timeout=timeout)
        except asyncio.TimeoutError:
            return f"[TIMEOUT {timeout}s]", 0
        except Exception as e:
            if model != "laforge-qwen:latest":
                logger.warning(f"[Frag] {model} err: {e} → fallback")
                return await self._call("laforge-qwen:latest", prompt, max_tokens)
            return f"[ERR: {e}]", 0

    # ── Pipeline ──────────────────────────────────────────────────────────────

    async def fragment(
        self,
        report: str,
        target_hint: str = "",
        on_fragment_done: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
    ) -> FragmentedReport:
        t0 = time.time()
        fid = f"frag_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        result = FragmentedReport(id=fid, source=report)

        def prog(step, msg):
            logger.info(f"[Frag] {step}: {msg}")
            if on_progress:
                on_progress(step, msg)

        prog("extract", "Extraction 3 contextes...")
        raw = {
            "infra": self._ctx_infra(report),
            "logic": self._ctx_logic(report),
            "payload": self._ctx_payload(report),
        }

        prog("guardian", "Noise Guardian — neutralisation...")
        sanitized, grpts = {}, {}
        for silo, ctx in raw.items():
            clean, grpt = self._guardian.sanitize(ctx, self._max_sens)
            sanitized[silo] = clean
            grpts[silo] = grpt
            status = "BLOQUÉ" if grpt["blocked"] else "OK"
            prog(
                "guardian",
                (
                    f"Silo {silo}: {status} | "
                    f"IPs={grpt['neutralized_ips']} "
                    f"Sigs={grpt['neutralized_sigs']} "
                    f"Magic={grpt['neutralized_magic']} "
                    f"Sens={grpt['sensitivity_after']:.2f}"
                ),
            )

        result.alias_key = self._guardian.export_key()

        prog("silos_ready", "3 silos prêts — envoi parallèle...")

        prompts = {
            "infra": self._prompt_infra(sanitized["infra"]),
            "logic": self._prompt_logic(sanitized["logic"]),
            "payload": self._prompt_payload(sanitized["payload"]),
        }

        async def run_silo(silo: str) -> Fragment:
            f = Fragment(
                id=f"{fid}_{silo}",
                silo=silo,
                prompt=prompts[silo],
                model=self.SILO_MODELS[silo],
                guardian_rpt=grpts[silo],
                blocked=grpts[silo]["blocked"],
            )
            if f.blocked:
                f.output = "[BLOQUÉ par NoiseGuardian]"
                return f
            t1 = time.time()
            f.output, f.tokens = await self._call(f.model, prompts[silo])
            f.duration = round(time.time() - t1, 2)
            if on_fragment_done:
                on_fragment_done(f)
            return f

        frags = await asyncio.gather(*[run_silo(s) for s in ["infra", "logic", "payload"]])
        result.fragments = list(frags)

        prog("reconcile", "Réconciliation locale...")
        result.synthesis = await self._reconcile(result)
        result.duration = round(time.time() - t0, 2)

        await self._index_rag(result)

        n_neutral = sum(g["neutralized_sigs"] + g["neutralized_ips"] + g["neutralized_magic"] for g in grpts.values())
        result.stats = {
            "total_tokens": sum(f.tokens for f in result.fragments),
            "total_neutralized": n_neutral,
            "blocked_silos": sum(1 for f in result.fragments if f.blocked),
            "sensitivity_max": max(g["sensitivity_before"] for g in grpts.values()),
            "sensitivity_after": max(g["sensitivity_after"] for g in grpts.values()),
        }
        prog("done", (f"{result.duration}s | {result.stats['total_tokens']} tokens | {n_neutral} éléments neutralisés"))
        return result

    async def _reconcile(self, result: FragmentedReport) -> str:
        """Réconciliation LOCALE — dé-anonymise + synthèse via laforge-qwen."""
        parts = []
        for f in result.fragments:
            if f.output and "[BLOQUÉ" not in f.output and "[TIMEOUT" not in f.output:
                clean = self._guardian.deanonymize(f.output)
                parts.append(f"[SILO {f.silo.upper()} — {f.model}]\n{clean[:500]}")
        if not parts:
            return "Aucune sortie disponible des silos."

        prompt = (
            "Réponds EN FRANÇAIS UNIQUEMENT. Tu es un analyste pentest.\n"
            "Voici 3 analyses partielles d un même réseau. Synthèse opérationnelle :\n\n"
            "## VULNÉRABILITÉS (par sévérité)\n"
            "Liste chaque vulnérabilité avec sa cible, son service et son impact.\n\n"
            "## EXPLOITATION\n"
            "Pour chaque vulnérabilité : commande concrète prête à exécuter.\n\n"
            "## REMÉDIATION\n"
            "Action prioritaire par service exposé.\n\n"
            "## SCORE GLOBAL\n"
            "Note de risque 0-100 avec justification.\n\n"
            "Analyses :\n" + "\n\n".join(parts) + "\n\nRéponds UNIQUEMENT en texte structuré, PAS de code Python."
        )
        output, _ = await self._call("laforge-qwen:latest", prompt, max_tokens=600, timeout=60)
        return output

    async def _index_rag(self, result: FragmentedReport):
        try:
            import sys

            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from nokido_agent.app.forge_ingest_pipeline import get_session_sink

            rag = get_session_sink()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            text = (
                f"[FRAG-REPORT {ts}] {result.id}\n"
                f"Durée: {result.duration}s | "
                f"Tokens: {result.stats.get('total_tokens', 0)} | "
                f"Neutralisés: {result.stats.get('total_neutralized', 0)}\n"
                f"{result.synthesis[:1500]}"
            )
            await rag.add_session_message(result.id, "fragmented_pentest", text)
            result.rag_indexed = True
        except Exception as e:
            logger.debug(f"[Frag] RAG: {e}")

    # ── API sync ──────────────────────────────────────────────────────────────

    def fragment_sync(
        self,
        report: str,
        target_hint: str = "",
        on_fragment_done: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
    ) -> FragmentedReport:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.fragment(report, target_hint, on_fragment_done, on_progress))
        finally:
            loop.close()

    def validate_only(self, text: str) -> dict:
        """Test NoiseGuardian sans fragmentation."""
        _, rpt = self._guardian.sanitize(text)
        return rpt


# ── Singleton ──────────────────────────────────────────────────────────────────
_FRAGMENTER: Optional[FragmentationEngine] = None


def get_fragmenter() -> FragmentationEngine:
    global _FRAGMENTER
    if _FRAGMENTER is None:
        _FRAGMENTER = FragmentationEngine()
    return _FRAGMENTER
