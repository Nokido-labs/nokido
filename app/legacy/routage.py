"""
routage.py — Moteur de routage et d'orchestration multi-agents pour OctoDevOps
===============================================================================
OctoDevOps v5

Ce module remplace modeplanner.py et l'ancienne logique de routage.
Il est conçu pour s'intégrer directement dans Nokido.py via import.

Architecture :
  ┌─────────────────────────────────────────────────────┐
  │  PromptClassifier (LLM Ollama local, non-streaming) │
  │  → catégorie : terminal / web / infra / code / chat │
  └─────────────────┬───────────────────────────────────┘
                    │
  ┌─────────────────▼───────────────────────────────────┐
  │  OllamaParallelRunner                               │
  │  → appels ollama run en parallèle asyncio           │
  │  → semaphore configurable (défaut 4 concurrent)     │
  └─────────────────┬───────────────────────────────────┘
                    │
  ┌─────────────────▼───────────────────────────────────┐
  │  AgentPlanner (12 rôles DevOps)                     │
  │  → score chaque agent pour la tâche via LLM         │
  │  → sélectionne les top-N agents                     │
  │  → exécution parallèle : autonome/collab/comité     │
  └─────────────────────────────────────────────────────┘

Usage depuis Nokido.py :
    from routage import (
        PromptClassifier, OllamaParallelRunner, AgentPlanner,
        SmartRouter, PromptCategory, AgentContrib,
    )

    runner = OllamaParallelRunner(ollama_url, max_concurrent=4)
    classifier = PromptClassifier(runner)
    planner = AgentPlanner(runner)
    router = SmartRouter(runner, classifier, planner, web_engine, rag_engine)

    result = await router.route(user_input, mode="autonome")
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any

import aiohttp

logger = logging.getLogger(__name__)


# =============================================================================
# CATÉGORIES DE ROUTAGE
# =============================================================================


class PromptCategory(Enum):
    TERMINAL = "terminal"  # commande SSH directe
    WEB = "web"  # recherche web nécessaire
    INFRA = "infra"  # orchestration multi-agents complexe
    CODE = "code"  # code Python, scripts, debugging
    SECURITY = "security"  # audit, CVE, durcissement
    NETWORK = "network"  # réseau, firewall, DNS
    LOG = "log"  # analyse de logs
    CHAT = "chat"  # conversation, explication, doc

    @classmethod
    def from_str(cls, s: str) -> "PromptCategory":
        s = s.strip().lower()
        mapping = {
            "terminal": cls.TERMINAL,
            "shell": cls.TERMINAL,
            "ssh": cls.TERMINAL,
            "web": cls.WEB,
            "internet": cls.WEB,
            "search": cls.WEB,
            "infra": cls.INFRA,
            "infrastructure": cls.INFRA,
            "devops": cls.INFRA,
            "code": cls.CODE,
            "python": cls.CODE,
            "script": cls.CODE,
            "security": cls.SECURITY,
            "secu": cls.SECURITY,
            "pentest": cls.SECURITY,
            "network": cls.NETWORK,
            "réseau": cls.NETWORK,
            "firewall": cls.NETWORK,
            "log": cls.LOG,
            "logs": cls.LOG,
            "journal": cls.LOG,
            "chat": cls.CHAT,
            "doc": cls.CHAT,
            "help": cls.CHAT,
        }
        for key, cat in mapping.items():
            if key in s:
                return cat
        return cls.CHAT


# =============================================================================
# DÉFINITION DES 12 RÔLES AGENTS
# =============================================================================

AGENT_ROLES: List[Dict[str, Any]] = [
    {
        "key": "planner",
        "name": "Planner Agent",
        "role": "Planning et décomposition de tâches complexes en étapes atomiques",
        "categories": [PromptCategory.INFRA, PromptCategory.CODE],
        "icon": "📋",
    },
    {
        "key": "discovery",
        "name": "Discovery Agent",
        "role": "Inventaire système, cartographie réseau, scan de services et ports",
        "categories": [PromptCategory.INFRA, PromptCategory.NETWORK],
        "icon": "🗺",
    },
    {
        "key": "devops",
        "name": "DevOps Agent",
        "role": "CI/CD, Docker, Kubernetes, Ansible, Terraform, pipelines de déploiement",
        "categories": [PromptCategory.INFRA, PromptCategory.CODE],
        "icon": "⚙",
    },
    {
        "key": "network",
        "name": "Network Agent",
        "role": "Réseau TCP/IP, firewall iptables/nftables, VPN, VLAN, DNS, diagnostic",
        "categories": [PromptCategory.NETWORK, PromptCategory.INFRA],
        "icon": "🌐",
    },
    {
        "key": "security",
        "name": "Security Agent",
        "role": "Cybersécurité, CVE, durcissement CIS/NIST, pentest, audit de sécurité",
        "categories": [PromptCategory.SECURITY, PromptCategory.INFRA],
        "icon": "🔐",
    },
    {
        "key": "log_analysis",
        "name": "Log Analysis Agent",
        "role": "Analyse de logs système, applicatifs, sécurité, corrélation d'événements",
        "categories": [PromptCategory.LOG, PromptCategory.SECURITY],
        "icon": "📊",
    },
    {
        "key": "rag",
        "name": "RAG / Knowledge Agent",
        "role": "Base de connaissances, documentation, procédures, runbooks",
        "categories": [PromptCategory.CHAT, PromptCategory.WEB],
        "icon": "🗄",
    },
    {
        "key": "action_exec",
        "name": "Action / Execution Agent",
        "role": "Exécution de commandes, scripts, automatisation de tâches système",
        "categories": [PromptCategory.TERMINAL, PromptCategory.INFRA],
        "icon": "⚡",
    },
    {
        "key": "memory",
        "name": "Memory Agent",
        "role": "Contexte long terme, historique des décisions, patterns récurrents",
        "categories": [PromptCategory.CHAT, PromptCategory.INFRA],
        "icon": "🧠",
    },
    {
        "key": "monitoring",
        "name": "Monitoring Agent",
        "role": "Métriques CPU/RAM/disque/réseau, alertes Prometheus/Grafana, SLA",
        "categories": [PromptCategory.INFRA, PromptCategory.LOG],
        "icon": "📈",
    },
    {
        "key": "patch_mgmt",
        "name": "Patch Management Agent",
        "role": "Inventaire des patchs, CVE applicables, planification mises à jour",
        "categories": [PromptCategory.SECURITY, PromptCategory.INFRA],
        "icon": "🩹",
    },
    {
        "key": "compliance",
        "name": "Compliance Agent",
        "role": "Audit de conformité CIS/NIST/ISO27001, rapports réglementaires",
        "categories": [PromptCategory.SECURITY, PromptCategory.INFRA],
        "icon": "✅",
    },
]

# Index par clé
AGENT_BY_KEY: Dict[str, Dict] = {a["key"]: a for a in AGENT_ROLES}


# =============================================================================
# RÉSULTAT DE CONTRIBUTION D'AGENT
# =============================================================================


@dataclass
class AgentContrib:
    agent_key: str
    agent_name: str
    icon: str
    response: str
    score: float = 0.0
    error: bool = False
    elapsed_s: float = 0.0


# =============================================================================
# RUNNER OLLAMA PARALLÈLE (ollama run natif)
# =============================================================================


class OllamaParallelRunner:
    """
    Exécute des appels Ollama en parallèle via l'API HTTP /api/chat.
    Utilise asyncio.Semaphore pour limiter la concurrence.

    Deux modes :
      - stream=False : retourne le texte complet (idéal pour scoring, classification)
      - stream=True  : callback token par token (idéal pour affichage UI)
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434/api/chat",
        max_concurrent: int = 4,
        timeout: float = 120.0,
    ):
        self.ollama_url = ollama_url
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.timeout = timeout
        self._model_cache: List[str] = []

    async def call(
        self,
        model: str,
        messages: List[Dict],
        system: Optional[str] = None,
        stream: bool = False,
        on_token: Optional[Any] = None,  # Callable[[str], None]
        max_tokens: int = 512,
    ) -> str:
        """
        Appel Ollama non-bloquant.
        - stream=False : attend la réponse complète
        - stream=True  : appelle on_token(tok) à chaque token
        """
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)

        payload = {
            "model": model,
            "messages": msgs,
            "stream": stream,
            "options": {"num_predict": max_tokens},
        }

        async with self.semaphore:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.post(
                        self.ollama_url,
                        json=payload,
                        timeout=aiohttp.ClientTimeout(total=self.timeout, connect=8),
                    ) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            raise RuntimeError(f"Ollama HTTP {resp.status}: {body[:200]}")

                        if not stream:
                            data = await resp.json()
                            return data.get("message", {}).get("content", "")

                        # Streaming
                        full = []
                        async for raw in resp.content:
                            if not raw:
                                continue
                            line = raw.decode("utf-8", errors="replace").strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            tok = data.get("message", {}).get("content", "")
                            if tok:
                                full.append(tok)
                                if on_token:
                                    on_token(tok)
                            if data.get("done"):
                                break
                        return "".join(full)

            except asyncio.TimeoutError:
                raise RuntimeError(f"Timeout Ollama ({model}) après {self.timeout}s")
            except aiohttp.ClientConnectorError as e:
                raise RuntimeError(f"Ollama inaccessible ({self.ollama_url}): {e}") from e

    async def call_parallel(
        self,
        calls: List[Dict],  # List of {model, messages, system?, max_tokens?}
    ) -> List[str]:
        """
        Lance plusieurs appels Ollama en parallèle.
        Retourne les réponses dans le même ordre.

        calls = [
            {"model": "qwen2.5-coder:7b", "messages": [...], "system": "..."},
            {"model": "llama3.1",          "messages": [...], "system": "..."},
        ]
        """
        tasks = [
            self.call(
                model=c["model"],
                messages=c["messages"],
                system=c.get("system"),
                max_tokens=c.get("max_tokens", 512),
            )
            for c in calls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [r if isinstance(r, str) else f"[Erreur: {r}]" for r in results]

    async def discover_models(self, tags_url: Optional[str] = None) -> List[str]:
        """Découvre les modèles Ollama disponibles."""
        if self._model_cache:
            return self._model_cache
        url = tags_url or self.ollama_url.replace("/api/chat", "/api/tags")
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json()
                    models = [m["name"] for m in data.get("models", []) if "embed" not in m["name"].lower()]
                    self._model_cache = models
                    return models
        except Exception as e:
            logger.warning(f"discover_models: {e}")
            return []


# =============================================================================
# CLASSIFIEUR DE PROMPT (LLM local)
# =============================================================================


class PromptClassifier:
    """
    Classifie le prompt dans une catégorie via LLM local.
    Priorité : heuristique rapide → LLM si ambiguïté.
    """

    # Heuristiques rapides (regex + mots-clés)
    _SHELL_CMDS = frozenset(
        {
            "ls",
            "cat",
            "grep",
            "ps",
            "kill",
            "systemctl",
            "docker",
            "kubectl",
            "apt",
            "dnf",
            "yum",
            "ip",
            "ss",
            "netstat",
            "ping",
            "curl",
            "wget",
            "chmod",
            "chown",
            "rm",
            "mv",
            "cp",
            "tar",
            "sed",
            "awk",
            "find",
            "journalctl",
            "tail",
            "head",
            "df",
            "du",
            "top",
            "htop",
            "nmap",
            "ssh",
            "scp",
            "rsync",
            "git",
            "python",
            "python3",
            "bash",
        }
    )
    _SHELL_CHARS = frozenset({"|", ">", "<", "&", ";", "$", "`"})
    _CHAT_PAT = re.compile(
        r"^(quel|quelle|quand|pourquoi|comment|est.ce|qu[''']est|c[''']est|"
        r"peux.tu|pourrais|explique|raconte|dis.moi|sais.tu|connais)\b",
        re.I,
    )
    _WEB_PAT = re.compile(
        r"\b(cve-\d{4}|exploit|vuln|actualité|news|dernier|récent|"
        r"changelog|release note|2024|2025|2026)\b",
        re.I,
    )
    _LOG_PAT = re.compile(
        r"\b(log[s]?|journald?|syslog|/var/log|erreur dans|event|"
        r"grep.*log|tail.*log)\b",
        re.I,
    )
    _SECURITY_PAT = re.compile(
        r"\b(cve|pentest|audit|exploit|vulnérabilité|hardening|durcissement|"
        r"fail2ban|iptables|selinux|apparmor|firewall|ids|ips)\b",
        re.I,
    )
    _NETWORK_PAT = re.compile(
        r"\b(réseau|routage|vlan|vpn|dns|dhcp|ping|traceroute|mtu|"
        r"interface|ip route|bgp|ospf|firewall)\b",
        re.I,
    )
    _CODE_PAT = re.compile(
        r"\b(python|script|code|fonction|classe|debug|bug|erreur python|"
        r"traceback|import|asyncio|def |class |pip )\b",
        re.I,
    )
    _INFRA_PAT = re.compile(
        r"\b(docker|kubernetes|k8s|helm|terraform|ansible|ci/cd|pipeline|"
        r"déploie|deploy|cluster|pod|container|bios|gpo|active directory)\b",
        re.I,
    )

    def __init__(self, runner: OllamaParallelRunner, model: Optional[str] = None):
        self.runner = runner
        self.model = model  # None = auto-sélectionné depuis modèles disponibles

    async def _get_model(self) -> str:
        if self.model:
            return self.model
        models = await self.runner.discover_models()
        # Préférer un modèle rapide pour la classification
        for m in models:
            ml = m.lower()
            if any(k in ml for k in ("phi4", "qwen", "llama3.1:8", "mistral", "gemma")):
                self.model = m
                return m
        self.model = models[0] if models else "llama3"
        return self.model

    def heuristic(self, text: str) -> Optional[PromptCategory]:
        """Classification heuristique rapide (< 1ms)."""
        lower = text.strip().lower()
        words = lower.split()
        first = words[0] if words else ""

        # Commande shell directe
        if first in self._SHELL_CMDS:
            return PromptCategory.TERMINAL
        if any(c in text for c in self._SHELL_CHARS):
            return PromptCategory.TERMINAL

        # Question conversationnelle sans mot-clé système
        if self._CHAT_PAT.match(lower):
            has_sys = any(
                w in words
                for w in ("log", "logs", "docker", "service", "réseau", "ssh", "ping", "top", "ps", "df", "free", "cve")
            )
            if not has_sys:
                return PromptCategory.CHAT

        # Patterns spécifiques
        if self._WEB_PAT.search(text):
            return PromptCategory.WEB
        if self._SECURITY_PAT.search(text):
            return PromptCategory.SECURITY
        if self._NETWORK_PAT.search(text):
            return PromptCategory.NETWORK
        if self._LOG_PAT.search(text):
            return PromptCategory.LOG
        if self._CODE_PAT.search(text):
            return PromptCategory.CODE
        if self._INFRA_PAT.search(text):
            return PromptCategory.INFRA

        return None  # ambiguïté → LLM

    async def classify(self, text: str) -> Tuple[PromptCategory, float]:
        """
        Retourne (catégorie, confidence).
        Utilise l'heuristique en premier, LLM si nécessaire.
        """
        # Heuristique
        cat = self.heuristic(text)
        if cat is not None:
            return cat, 0.9

        # LLM local pour les cas ambigus
        try:
            model = await self._get_model()
            prompt = (
                f"Classe ce prompt dans UNE SEULE catégorie parmi : "
                f"terminal, web, infra, code, security, network, log, chat\n"
                f'Prompt: "{text[:300]}"\n'
                f"Réponds UNIQUEMENT par le mot-clé exact, sans ponctuation ni explication."
            )
            resp = await self.runner.call(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=10,
            )
            cat = PromptCategory.from_str(resp.strip())
            return cat, 0.75
        except Exception as e:
            logger.debug(f"LLM classify: {e}")
            return PromptCategory.CHAT, 0.5


# =============================================================================
# SCORING DES AGENTS (Ollama en parallèle)
# =============================================================================


class AgentPlanner:
    """
    Score les 12 agents pour une tâche via des appels Ollama parallèles.
    Chaque agent reçoit un score flottant [0.0–1.0].
    """

    # Prompt de scoring par agent
    _SCORE_PROMPT_TMPL = (
        "Tu es un évaluateur d'agents IA DevOps.\n"
        'Tâche demandée : "{task}"\n'
        "Rôle de l'agent à évaluer : {role}\n"
        "Donne un score de pertinence entre 0.0 et 1.0 pour cet agent sur cette tâche.\n"
        "Réponds UNIQUEMENT par un nombre flottant (ex: 0.85), sans texte ni explication."
    )

    # Prompt pour la contribution de chaque agent
    _AGENT_PROMPT_TMPL = (
        "Tu es {name}, un expert DevOps.\n"
        "Ton rôle : {role}\n\n"
        "Tâche : {task}\n"
        "{context}"
        "Réponds en français de façon technique et précise en 3-8 lignes maximum."
    )

    def __init__(self, runner: OllamaParallelRunner):
        self.runner = runner

    async def score_agents(
        self,
        task: str,
        models: List[str],
        agents: Optional[List[Dict]] = None,
    ) -> Dict[str, float]:
        """
        Score tous les agents en parallèle.
        Chaque agent est évalué par le modèle le plus rapide disponible.

        Retourne {agent_key: score}
        """
        agents = agents or AGENT_ROLES
        if not models:
            return {a["key"]: 0.5 for a in agents}

        # Choisir le modèle le plus rapide pour le scoring
        fast_model = self._pick_fast_model(models)

        # Préparer les appels parallèles
        calls = [
            {
                "model": fast_model,
                "messages": [
                    {"role": "user", "content": self._SCORE_PROMPT_TMPL.format(task=task[:200], role=a["role"])}
                ],
                "max_tokens": 8,
            }
            for a in agents
        ]

        responses = await self.runner.call_parallel(calls)

        scores: Dict[str, float] = {}
        for agent, resp in zip(agents, responses):
            try:
                score = float(re.search(r"\d+\.?\d*", resp).group())
                score = max(0.0, min(1.0, score))
            except Exception:
                # Fallback : score basé sur la catégorie de l'agent
                score = 0.4
            scores[agent["key"]] = score

        return scores

    async def select_agents(
        self,
        scores: Dict[str, float],
        top_n: int = 3,
        min_score: float = 0.3,
    ) -> List[Dict]:
        """
        Sélectionne les top-N agents par score.
        Filtre les agents sous min_score.
        """
        ranked = sorted(
            [(k, v) for k, v in scores.items() if v >= min_score],
            key=lambda x: x[1],
            reverse=True,
        )
        selected_keys = [k for k, _ in ranked[:top_n]]
        return [AGENT_BY_KEY[k] for k in selected_keys if k in AGENT_BY_KEY]

    async def run_agents(
        self,
        task: str,
        agents: List[Dict],
        models: List[str],
        context: str = "",
        scores: Optional[Dict[str, float]] = None,
    ) -> List[AgentContrib]:
        """
        Exécute tous les agents sélectionnés en parallèle.
        Chaque agent utilise le modèle qui lui correspond le mieux.
        """
        if not agents or not models:
            return []

        calls = []
        for agent in agents:
            model = self._pick_model_for_agent(agent["key"], models)
            ctx_str = f"\nContexte disponible :\n{context[:500]}\n\n" if context else ""
            prompt = self._AGENT_PROMPT_TMPL.format(
                name=agent["name"],
                role=agent["role"],
                task=task[:300],
                context=ctx_str,
            )
            calls.append(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 400,
                    "agent": agent,
                }
            )

        # Appels parallèles
        t0 = time.monotonic()
        raw_calls = [
            {
                "model": c["model"],
                "messages": c["messages"],
                "max_tokens": c["max_tokens"],
            }
            for c in calls
        ]
        responses = await self.runner.call_parallel(raw_calls)
        elapsed = time.monotonic() - t0

        contribs: List[AgentContrib] = []
        for c, resp in zip(calls, responses):
            agent = c["agent"]
            error = resp.startswith("[Erreur:")
            contribs.append(
                AgentContrib(
                    agent_key=agent["key"],
                    agent_name=agent["name"],
                    icon=agent.get("icon", "?"),
                    response=resp if not error else "",
                    score=scores.get(agent["key"], 0.5) if scores else 0.5,
                    error=error,
                    elapsed_s=elapsed,
                )
            )
        return contribs

    def _pick_fast_model(self, models: List[str]) -> str:
        """Choisit le modèle le plus rapide pour le scoring."""
        for m in models:
            ml = m.lower()
            if any(k in ml for k in (":7b", ":8b", "phi4", "gemma", "mistral")):
                return m
        return models[0]

    def _pick_model_for_agent(self, agent_key: str, models: List[str]) -> str:
        """
        Choisit le modèle optimal pour un rôle agent spécifique.
        Logique : spécialistes code → coder, sécurité → modèles de raisonnement, etc.
        """
        if not models:
            return "llama3"

        ml = [m.lower() for m in models]

        preferences: Dict[str, List[str]] = {
            "security": ["deepseek-r1", "phi4", "llama3.3", "qwen3"],
            "compliance": ["deepseek-r1", "phi4", "llama3.3"],
            "log_analysis": ["mistral", "qwen", "llama3"],
            "network": ["mistral", "qwen", "llama3"],
            "devops": ["qwen2.5-coder", "deepseek-coder", "llama3"],
            "action_exec": ["qwen2.5-coder", "deepseek-coder", "llama3"],
            "planner": ["deepseek-r1", "qwen3", "phi4", "llama3.3"],
            "memory": ["llama3.3", "llama3.1", "qwen3"],
            "rag": ["llama3.3", "llama3.1", "mistral"],
            "monitoring": ["qwen", "llama3", "mistral"],
            "patch_mgmt": ["qwen", "llama3", "mistral"],
            "discovery": ["qwen", "llama3", "mistral"],
        }

        prefs = preferences.get(agent_key, [])
        for pref in prefs:
            for i, m in enumerate(ml):
                if pref in m:
                    return models[i]

        return models[0]  # fallback


# =============================================================================
# SYNTHÈSE MULTI-AGENTS
# =============================================================================


class AgentSynthesizer:
    """
    Synthétise les contributions de plusieurs agents en une réponse finale.
    Utilisé pour les modes collaboration et comité.
    """

    _SYNTH_PROMPT_TMPL = (
        "Tu es OctoDevOps, un assistant DevOps senior.\n"
        "Voici les contributions de {n} agents experts sur la tâche :\n"
        "Tâche : {task}\n\n"
        "{contributions}\n\n"
        "Synthétise ces contributions en une réponse claire, technique et actionnable.\n"
        "Évite les redondances. Garde les commandes concrètes si présentes.\n"
        "Réponds en français, maximum 15 lignes."
    )

    _JURY_PROMPT_TMPL = (
        "Tu es le Juge DevOps.\n"
        "Tâche : {task}\n\n"
        "Propositions de {n} experts :\n"
        "{contributions}\n\n"
        "Analyse chaque proposition et désigne la meilleure.\n"
        "Format obligatoire :\n"
        "VERDICT : [nom de l'agent]\n"
        "JUSTIFICATION : [2 phrases]\n"
        "SYNTHÈSE FINALE : [réponse complète à appliquer]"
    )

    def __init__(self, runner: OllamaParallelRunner):
        self.runner = runner

    async def synthesize(
        self,
        task: str,
        contribs: List[AgentContrib],
        model: str,
        mode: str = "collaboration",
    ) -> str:
        """
        Synthèse selon le mode :
          - collaboration : fusion équilibrée
          - comite        : vote + justification
        """
        valid = [c for c in contribs if not c.error and c.response]
        if not valid:
            return "Aucune contribution valide des agents."
        if len(valid) == 1:
            return valid[0].response

        contrib_text = "\n\n---\n\n".join(
            f"{c.icon} [{c.agent_name}] (score={c.score:.2f})\n{c.response}" for c in valid
        )

        if mode == "comite":
            prompt = self._JURY_PROMPT_TMPL.format(
                task=task[:200],
                n=len(valid),
                contributions=contrib_text[:3000],
            )
        else:
            prompt = self._SYNTH_PROMPT_TMPL.format(
                task=task[:200],
                n=len(valid),
                contributions=contrib_text[:3000],
            )

        try:
            return await self.runner.call(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
            )
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            return valid[0].response  # fallback : meilleur agent seul


# =============================================================================
# ROUTEUR PRINCIPAL
# =============================================================================


@dataclass
class RouteResult:
    category: PromptCategory
    confidence: float
    mode: str
    response: str
    agents_used: List[str] = field(default_factory=list)
    contribs: List[AgentContrib] = field(default_factory=list)
    web_used: bool = False
    rag_used: bool = False
    elapsed_s: float = 0.0


class SmartRouter:
    """
    Point d'entrée unique du moteur de routage.
    Orchestre : classification → web → RAG → agents → synthèse.

    Intégration Nokido :
        router = SmartRouter(
            runner     = OllamaParallelRunner(settings.ollama_url),
            classifier = PromptClassifier(runner),
            planner    = AgentPlanner(runner),
            web_engine = get_web_engine(ollama_url),
            rag_engine = rag_engine,
        )
        result = await router.route(user_input, mode=self._collab_mode)
    """

    def __init__(
        self,
        runner: OllamaParallelRunner,
        classifier: PromptClassifier,
        planner: AgentPlanner,
        web_engine=None,  # WebSearchEngine
        rag_engine=None,  # RAGEngine (Nokido)
        scorer=None,  # ModelScorer (scoring.py)
    ):
        self.runner = runner
        self.classifier = classifier
        self.planner = planner
        self.web_engine = web_engine
        self.rag_engine = rag_engine
        self.scorer = scorer
        self.synth = AgentSynthesizer(runner)
        self._models: List[str] = []

    async def _ensure_models(self) -> List[str]:
        if not self._models:
            if self.scorer and self.scorer.is_ready:
                self._models = self.scorer.models
            else:
                self._models = await self.runner.discover_models()
        return self._models

    async def route(
        self,
        user_input: str,
        mode: str = "autonome",  # autonome / collaboration / comite
        arch=None,  # ArchitectureProfile
        on_role_light=None,  # Callable[[str], None] — allume les LEDs UI
    ) -> RouteResult:
        """
        Pipeline complet :
          1. Classifie le prompt
          2. Enrichit via web si nécessaire
          3. Enrichit via RAG
          4. Score et sélectionne les agents
          5. Exécute en parallèle
          6. Synthétise si multi-agents
        """
        t0 = time.monotonic()
        models = await self._ensure_models()
        cat, conf = await self.classifier.classify(user_input)

        logger.debug(f"Routage → {cat.value} (conf={conf:.0%}) mode={mode}")

        # ── Contexte architecture ──────────────────────────────────────────────
        arch_ctx = arch.context_hint() if arch else ""

        # ── Enrichissement Web ────────────────────────────────────────────────
        web_text = ""
        web_used = False
        if self.web_engine and (
            cat in (PromptCategory.WEB, PromptCategory.SECURITY) or self.web_engine.should_search(user_input)
        ):
            if on_role_light:
                on_role_light("discovery")
            try:
                results = await self.web_engine.search(user_input, max_results=4, fetch_content=True, rerank=True)
                if results:
                    web_text = self.web_engine.format_for_prompt(results)
                    web_used = True
                    if self.rag_engine:
                        await self.web_engine.enrich_rag(self.rag_engine, results)
            except Exception as e:
                logger.warning(f"Web search: {e}")

        # ── Enrichissement RAG ────────────────────────────────────────────────
        rag_text = ""
        rag_used = False
        if self.rag_engine:
            if on_role_light:
                on_role_light("rag")
            try:
                docs = await self.rag_engine.search(user_input, k=4, include_sessions=True)
                if docs:
                    rag_text = "\n".join(f"[{d.get('source', '')}] {d.get('content', '')[:300]}" for d in docs[:3])
                    rag_used = True
            except Exception as e:
                logger.debug(f"RAG search: {e}")

        # Contexte consolidé
        context = "\n\n".join(filter(None, [arch_ctx, rag_text, web_text]))

        # ── Mode TERMINAL : pas d'agents, exécution directe ───────────────────
        if cat == PromptCategory.TERMINAL:
            if on_role_light:
                on_role_light("action_exec")
            return RouteResult(
                category=cat,
                confidence=conf,
                mode=mode,
                response="[TERMINAL]",  # signale à Nokido d'injecter dans PTY
                agents_used=["action_exec"],
                web_used=web_used,
                rag_used=rag_used,
                elapsed_s=time.monotonic() - t0,
            )

        # ── Mode CHAT simple : un seul modèle ─────────────────────────────────
        if cat == PromptCategory.CHAT and mode == "autonome":
            if on_role_light:
                on_role_light("memory")
            model = self._pick_chat_model(models)
            msgs = [{"role": "user", "content": user_input}]
            sys = (
                "Tu es OctoDevOps, un assistant DevOps expert. "
                "Réponds en français, de façon concise et technique." + (f"\n\n{arch_ctx}" if arch_ctx else "")
            )
            if rag_text:
                sys += f"\n\nBase de connaissances :\n{rag_text[:800]}"
            try:
                response = await self.runner.call(model=model, messages=msgs, system=sys, max_tokens=600)
            except Exception as e:
                response = f"Erreur : {e}"
            return RouteResult(
                category=cat,
                confidence=conf,
                mode=mode,
                response=response,
                agents_used=["memory"],
                rag_used=rag_used,
                elapsed_s=time.monotonic() - t0,
            )

        # ── Scoring agents ────────────────────────────────────────────────────
        if on_role_light:
            on_role_light("planner")
        scores = await self.planner.score_agents(user_input, models)

        top_n = {"autonome": 1, "collaboration": 4, "comite": 3}.get(mode, 2)
        selected = await self.planner.select_agents(scores, top_n=top_n)

        if on_role_light:
            for a in selected:
                on_role_light(a["key"])

        # ── Exécution parallèle ───────────────────────────────────────────────
        contribs = await self.planner.run_agents(
            task=user_input,
            agents=selected,
            models=models,
            context=context,
            scores=scores,
        )

        # ── Synthèse ─────────────────────────────────────────────────────────
        if len(contribs) == 1:
            response = contribs[0].response if not contribs[0].error else "Erreur agent."
        else:
            synth_model = self._pick_synth_model(models)
            response = await self.synth.synthesize(
                task=user_input,
                contribs=contribs,
                model=synth_model,
                mode=mode,
            )

        # ── Enrichissement RAG post-réponse ───────────────────────────────────
        if self.rag_engine:
            try:
                doc = (
                    f"[Échange {time.strftime('%H:%M:%S')}]\n"
                    f"Prompt : {user_input[:300]}\n"
                    f"Réponse : {response[:500]}\n"
                    f"Agents : {[a['key'] for a in selected]}"
                )
                await self.rag_engine.add_session_message("exchange", "system", doc)
            except Exception:
                pass

        return RouteResult(
            category=cat,
            confidence=conf,
            mode=mode,
            response=response,
            agents_used=[a["key"] for a in selected],
            contribs=contribs,
            web_used=web_used,
            rag_used=rag_used,
            elapsed_s=time.monotonic() - t0,
        )

    def _pick_chat_model(self, models: List[str]) -> str:
        for m in models:
            ml = m.lower()
            if any(k in ml for k in ("llama3.3", "qwen3", "llama3.1", "mistral")):
                return m
        return models[0] if models else "llama3"

    def _pick_synth_model(self, models: List[str]) -> str:
        for m in models:
            ml = m.lower()
            if any(k in ml for k in ("llama3.3", "deepseek-r1", "qwen3", "phi4")):
                return m
        return models[0] if models else "llama3"


# =============================================================================
# SINGLETON GLOBAL (utilisé par Nokido)
# =============================================================================
_global_runner: Optional[OllamaParallelRunner] = None
_global_classifier: Optional[PromptClassifier] = None
_global_planner: Optional[AgentPlanner] = None
_global_router: Optional[SmartRouter] = None


def init_router(
    ollama_url: str = "http://localhost:11434/api/chat",
    max_concurrent: int = 4,
    web_engine=None,
    rag_engine=None,
    scorer=None,
) -> SmartRouter:
    """Initialise ou retourne le SmartRouter singleton."""
    global _global_runner, _global_classifier, _global_planner, _global_router

    if _global_router is not None:
        return _global_router

    _global_runner = OllamaParallelRunner(ollama_url, max_concurrent=max_concurrent)
    _global_classifier = PromptClassifier(_global_runner)
    _global_planner = AgentPlanner(_global_runner)
    _global_router = SmartRouter(
        runner=_global_runner,
        classifier=_global_classifier,
        planner=_global_planner,
        web_engine=web_engine,
        rag_engine=rag_engine,
        scorer=scorer,
    )
    return _global_router


def get_router() -> Optional[SmartRouter]:
    return _global_router
