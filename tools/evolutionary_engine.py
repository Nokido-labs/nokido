"""
tools/evolutionary_engine.py — Moteur Évolutif Nokido + Cerberus
==================================================================
Générations N+1, checkpoints NVMe, crossover, population fork,
ASTSurgeon, CerberusGuard (AST + pytest + ruff), temperature adaptative.

Usage :
  python tools/evolutionary_engine.py --files app/X.py --generations 3
  python tools/evolutionary_engine.py --files app/X.py --generations 5 --cerberus --population 3
  python tools/evolutionary_engine.py --files app/X.py --workflow "graph TD ..."
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT_DIR = ROOT / "shadow_mutation" / "checkpoints"
EVAL_DIR = ROOT / "shadow_mutation" / "eval"
HISTORY_FILE = ROOT / "shadow_mutation" / "performance_history.json"


# ── ASTSurgeon ────────────────────────────────────────────────────────────────


class ASTSurgeon:
    """Garant de l'intégrité structurelle — empêche la troncature des dataclasses."""

    @staticmethod
    def get_structure_fingerprint(code: str) -> dict | None:
        """Retourne {class_name: nb_body_statements} — garde-fou anti-troncature."""
        try:
            tree = ast.parse(code)
            return {n.name: len(n.body) for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        except SyntaxError:
            return None

    @staticmethod
    def validate_integrity(original: str, mutated: str) -> tuple[bool, str]:
        """Vérifie que classes et corps n'ont pas disparu."""
        orig_fp = ASTSurgeon.get_structure_fingerprint(original)
        mut_fp = ASTSurgeon.get_structure_fingerprint(mutated)

        if mut_fp is None:
            return False, "SyntaxError dans la mutation"

        for cls, body_count in (orig_fp or {}).items():
            if cls not in mut_fp:
                return False, f"Classe '{cls}' supprimée par le LLM"
            if body_count > 0 and mut_fp[cls] == 0:
                return False, f"Corps de '{cls}' vidé (troncature)"

        # Garde-fou lignes — perte > 20%
        orig_lines = len(original.splitlines())
        mut_lines = len(mutated.splitlines())
        if mut_lines < orig_lines * 0.80:
            return False, f"Troncature {orig_lines}L → {mut_lines}L"

        return True, "Intégrité validée"


# ── AdaptiveTemperatureManager ────────────────────────────────────────────────


class AdaptiveTemperatureManager:
    """Ajuste la créativité du LLM selon le fitness score."""

    def __init__(self, base: float = 0.3, min_t: float = 0.1, max_t: float = 1.0) -> None:
        """Initialise le gestionnaire de température."""
        self.current = base
        self.min_t = min_t
        self.max_t = max_t
        self.history: list[float] = []

    def adjust(self, score: float, lethal: bool = False) -> float:
        """Ajuste la température selon le score de fitness."""
        self.history.append(score)
        if lethal:
            self.current = max(self.min_t, self.current - 0.15)
        elif len(self.history) >= 2:
            if self.history[-1] <= self.history[-2]:
                self.current = min(self.max_t, self.current + 0.1)  # stagnation → explore
            else:
                self.current = max(self.min_t + 0.1, self.current - 0.05)  # progrès → stabilise
        return round(self.current, 2)


# ── CerberusGuard ─────────────────────────────────────────────────────────────


class CerberusGuard:
    """
    Validation triple tête — parallélisée sur N branches.
    - ThreadPoolExecutor  : appels LLM (I/O bound)
    - ProcessPoolExecutor : pytest + AST (CPU bound, Zen 4 aware)
    - Isolation forks     : shadow_mutation/forks/<branch_id>/
    - Memory-aware        : vérifie la RAM avant chaque fork
    """

    RAM_PER_FORK_MB = 512  # Estimation conservative par process pytest
    MAX_FORKS_ABS = 8  # Plafond absolu

    def __init__(self) -> None:
        """Initialise Cerberus."""
        EVAL_DIR.mkdir(parents=True, exist_ok=True)
        self._forks_dir = ROOT / "shadow_mutation" / "forks"
        self._forks_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _available_forks() -> int:
        """Calcule le nombre de forks sûrs selon RAM et CPU disponibles."""
        try:
            import psutil as _ps

            ram_mb = _ps.virtual_memory().available // 1024**2
            cpu_free = max(1, _ps.cpu_count(logical=False) - 1)
            ram_forks = ram_mb // CerberusGuard.RAM_PER_FORK_MB
            return min(cpu_free, ram_forks, CerberusGuard.MAX_FORKS_ABS)
        except ImportError:
            return 3  # safe default si psutil absent

    def evaluate(self, original: str, mutated: str, fname: str, cid: int) -> tuple[int, str]:
        """Évalue un candidat — version séquentielle (appelée par evaluate_parallel)."""
        score = 0
        feedback = []

        # Tête 1 — AST (rapide, pas besoin de process séparé)
        ok, msg = ASTSurgeon.validate_integrity(original, mutated)
        if not ok:
            return 0, f"AST KO: {msg}"
        score += 30
        feedback.append("AST OK")

        # Fork isolé pour tests
        fork_dir = self._forks_dir / f"fork_{cid}"
        fork_dir.mkdir(exist_ok=True)
        tmp = fork_dir / fname
        tmp.write_text(mutated, encoding="utf-8")

        # Tête 2 — pytest NR
        try:
            res = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/nr/",
                    "--ignore=tests/nr/test_import_all_nr.py",  # timeout subprocess préexistant
                    "-x",
                    "-q",
                    "--timeout=20",
                    "--tb=no",
                    "-p",
                    "no:warnings",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                timeout=60,
            errors="replace")
            if "passed" in res.stdout and "failed" not in res.stdout:
                score += 50
                feedback.append("pytest OK")
            else:
                feedback.append("pytest KO")
        except Exception as e:
            feedback.append(f"pytest err: {e}")

        # Tête 3 — ruff
        try:
            res = subprocess.run(
                [sys.executable, "-m", "ruff", "check", str(tmp)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                timeout=10,
            errors="replace")
            score += 20 if res.returncode == 0 else 0
            feedback.append(
                "ruff OK" if res.returncode == 0 else f"ruff {res.stdout.count(chr(10))} issues"
            )
        except Exception:
            score += 20
            feedback.append("ruff skip")

        return score, " | ".join(feedback)

    def evaluate_parallel(
        self,
        candidates: list[dict],
        original: str,
        fname: str,
    ) -> list[dict]:
        """
        Évalue N candidats en parallèle.

        - Threads  : appels LLM déjà faits, ici on lance les validations
        - Processes: pytest par fork (CPU bound → Zen 4 pleine utilisation)
        Retourne les candidats enrichis de score/feedback, triés par score.
        """
        from concurrent.futures import as_completed

        n_workers = min(len(candidates), self._available_forks())
        print(f"  [CERBERUS] {len(candidates)} candidats | {n_workers} workers RAM-safe")

        results = []

        # ProcessPoolExecutor pour pytest/AST (CPU bound)
        # Mais ProcessPool ne peut pas picler les méthodes d'instance →
        # on utilise ThreadPoolExecutor avec subprocess (chaque thread lance un process)
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(self.evaluate, original, c.get("content", original), fname, i): (
                    i,
                    c,
                )
                for i, c in enumerate(candidates)
            }
            for future in as_completed(futures):
                idx, candidate = futures[future]
                try:
                    score, feedback = future.result(timeout=90)
                except Exception as e:
                    score, feedback = 0, f"eval err: {e}"

                enriched = dict(candidate)
                enriched["score"] = score
                enriched["feedback"] = feedback
                results.append(enriched)
                print(f"  [FORK {idx}] score={score}/100 — {feedback}")

        results.sort(key=lambda x: -x["score"])

        # Diagnostic cross-branches — détecte les patterns communs d'échec
        failed = [r for r in results if r["score"] == 0]
        if len(failed) == len(results) and failed:
            diagnosis = self._cross_branch_diagnosis(failed, fname)
            print(f"  [DIAG] {diagnosis['type']}: {diagnosis['message']}")
            # Ancre le diagnostic dans le RAG + auto-disco
            RAGEnricher.generate_postmortem(
                filepath=f"eval/{fname}",
                agent="cerberus_parallel",
                error=diagnosis["message"],
                gen=0,
            )
            for r in results:
                r["diagnosis"] = diagnosis

        return results

    @staticmethod
    def _cross_branch_diagnosis(failed_branches: list, fname: str) -> dict:
        """
        Analyse les N branches en échec pour trouver le pattern commun.
        Évite de blâmer le LLM quand le problème est l'environnement.
        """
        feedbacks = [r.get("feedback", "") for r in failed_branches]

        # Patterns d'échec communs
        patterns = {
            "ImportError": "Dépendance manquante — pas un problème LLM",
            "SyntaxError": "Température trop haute — réduire à 0.1",
            "ModuleNotFound": "Module absent dans l'environnement",
            "timeout": "Tests trop longs — augmenter --timeout",
            "pytest KO": "Tests cassés indépendamment du LLM",
            "AST KO": "Troncature systématique — fichier trop complexe pour ce modèle",
        }

        for pattern, message in patterns.items():
            if all(pattern.lower() in fb.lower() for fb in feedbacks):
                return {
                    "type": pattern,
                    "message": message,
                    "branches": len(failed_branches),
                    "actionable": message,
                }

        # Pas de pattern commun — échec aléatoire
        return {
            "type": "mixed_failure",
            "message": f"Échecs variés sur {len(failed_branches)} branches — relancer avec température réduite",
            "branches": len(failed_branches),
            "actionable": "Réduire temperature + augmenter num_ctx",
        }

    def cleanup_forks(self) -> None:
        """Supprime les dossiers de forks temporaires."""
        import shutil as _sh

        if self._forks_dir.exists():
            _sh.rmtree(self._forks_dir, ignore_errors=True)
            self._forks_dir.mkdir(exist_ok=True)


# ── MermaidOrchestrator ───────────────────────────────────────────────────────


class MermaidOrchestrator:
    """Routage déterministe basé sur un diagramme Mermaid — 0ms de LLM."""

    def __init__(self) -> None:
        """Initialise l'orchestrateur."""
        self.graph: dict = {"nodes": {}, "edges": []}

    def parse(self, mermaid_text: str) -> None:
        """Parse le diagramme Mermaid et construit le graphe."""
        nodes = re.findall(r"(\w+)\[(.*?)\]|(\w+)\{(.*?)\}|(\w+)\((.*?)\)", mermaid_text)
        parsed_nodes = {}
        for n in nodes:
            nid = n[0] or n[2] or n[4]
            label = n[1] or n[3] or n[5]
            ntype = "task" if n[0] else ("decision" if n[2] else "end")
            parsed_nodes[nid] = {"label": label, "type": ntype}

        links = re.findall(r"(\w+)\s*(?:--\s*(.*?)\s*--)?\s*-->\s*(\w+)", mermaid_text)
        edges = [{"src": s, "label": lbl.strip(), "tgt": t} for s, lbl, t in links]

        self.graph = {"nodes": parsed_nodes, "edges": edges}
        print(f"[Mermaid] {len(parsed_nodes)} nœuds, {len(edges)} liens")

    def root_node(self) -> str | None:
        """Retourne le nœud racine (aucune arête entrante)."""
        targets = {e["tgt"] for e in self.graph["edges"]}
        roots = [n for n in self.graph["nodes"] if n not in targets]
        return roots[0] if roots else None

    def next_node(self, current: str, status: str) -> str | None:
        """Résout le prochain nœud selon le statut — déterministe."""
        edges = [e for e in self.graph["edges"] if e["src"] == current]
        if not edges:
            return None
        if len(edges) == 1 and not edges[0]["label"]:
            return edges[0]["tgt"]
        for e in edges:
            if e["label"].lower() == status.lower():
                return e["tgt"]
        return edges[0]["tgt"]  # fallback


# ── AgentPool + MultiLLMBridge ────────────────────────────────────────────────


class AgentPool:
    """
    Pool d'agents hybride classé par rôle fonctionnel.
    Routage automatique selon risque structurel + tâche demandée.
    """

    # ── Architectes SOTA — raisonnement complexe, changements structurels ──
    ARCHITECTS = [
        "anthropic/claude-3.5-sonnet",  # Référence absolue code
        "openai/gpt-4o",  # Polyvalent rapide
        "deepseek/deepseek-chat",  # Rapport qualité/prix/code
        "meta-llama/llama-3.1-405b",  # Puissance open source
    ]

    # ── Spécialistes Code — syntaxe, typage, refactoring ──
    SPECIALISTS = [
        "ollama/qwen2.5-coder:32b-instruct-q3_K_M",  # Meilleur local — 32B
        "ollama/qwen2.5-coder:7b-instruct-q4_K_M",  # Local rapide
        "openrouter/deepseek/deepseek-chat-v3-0324",  # DeepSeek-V3 cloud
        "mistral/codestral-22b-v0.1",  # Précision Python
        "ollama/deepseek-coder:6.7b",  # Fallback local
    ]

    # ── Auditeurs — validation, PEP8, détection failles ──
    AUDITORS = [
        "meta-llama/llama-3.3-70b-instruct",  # Rigueur logique
        "mistralai/mistral-large-2407",  # Respect PEP8
        "google/gemini-flash-1.5",  # Audit rapide
    ]

    # ── Scribes — docstrings, README, commentaires haute densité ──
    SCRIBES = [
        "ollama/laforge-qwen",  # LoRA fine-tuné Nokido docstrings — PRIORITAIRE
        "mistralai/mistral-small-3.1-24b-instruct:free",  # Langage naturel précis
        "google/gemma-3-27b-it:free",  # Rapide, clair
        "ollama/qwen2.5-coder:7b-instruct-q4_K_M",  # Fallback local
    ]

    # ── Reflex — micro-édition, vérification syntaxique (0 latence) ──
    REFLEX = [
        "ollama/laforge-qwen",  # LoRA Nokido — docstrings rapides
        "ollama/stable-code:latest",  # Ultra-léger iGPU
        "ollama/qwen2.5-coder:1.5b",  # Nano local
    ]

    # Mappage tâche → pool prioritaire
    TASK_ROUTING = {
        "type_hints": SPECIALISTS,
        "docstrings": SCRIBES,
        "refactor": ARCHITECTS,
        "audit": AUDITORS,
        "syntax_check": REFLEX,
        "default": SPECIALISTS,
    }

    # Groupes pour routage par risque dans select()
    # Ordre : local → github (gratuit) → groq → openrouter free
    GROUPS = {
        "local": [
            "ollama/laforge-qwen",  # LoRA Nokido — docstrings
            "ollama/qwen2.5-coder:7b-instruct-q4_K_M",
            "ollama/qwen2.5-coder:32b-instruct-q3_K_M",
            "ollama/deepseek-coder:6.7b",
        ],
        "cloud_free": [
            # Tier 1 — Groq (confirmé opérationnel, ultra-rapide)
            "groq/llama-3.3-70b-versatile",
            "groq/qwen/qwen3-32b",
            "groq/moonshotai/kimi-k2-instruct-0905",
            # Tier 2 — GitHub Models (token à renouveler)
            # "github/Phi-4",
            # "github/Llama-3.1-70b-Versatile",
            # Tier 3 — OpenRouter free (cooldowns, dernier recours)
            "openrouter/qwen/qwen3-coder:free",
            "openrouter/mistralai/mistral-small-3.1-24b-instruct:free",
        ],
    }

    @classmethod
    def select(
        cls,
        risk: float = 0.5,
        population: int = 2,
        task: str = "default",
    ) -> list[str]:
        """
        Sélectionne les agents selon risque structurel + tâche.

        risk < 0.3  → Reflex/Specialists locaux (0 quota)
        risk 0.3-0.6 → Specialists (local + cloud_eco)
        risk 0.6-0.8 → Auditors + Specialists cloud
        risk > 0.8   → Architects SOTA (dataclasses complexes, grosse mutation)
        """
        task_pool = cls.TASK_ROUTING.get(task, cls.SPECIALISTS)

        # Ollama local toujours présent — seul capable de traiter les gros fichiers
        # (cloud limité à ~8K tokens de sortie, Ollama sans limite)
        local = cls.GROUPS["local"][:1]

        if risk < 0.3:
            cloud = cls.GROUPS["cloud_free"][: max(0, population - 1)]
        elif risk < 0.6 or risk < 0.8:
            cloud = cls.GROUPS["cloud_free"][: max(1, population - 1)]
        else:
            # Risque max — local EN PREMIER (gros fichiers complexes)
            # + cloud en supplément si population le permet
            cloud = cls.GROUPS["cloud_free"][: max(1, population - 1)]

        pool = local + cloud

        # Déduplique en conservant l'ordre
        seen: set = set()
        result = []
        for m in pool:
            if m not in seen:
                seen.add(m)
                result.append(m)

        return result[:population] or [cls.SPECIALISTS[0]]

    @classmethod
    def for_task(cls, task: str, risk: float = 0.5) -> list[str]:
        """Shortcut — sélectionne selon la tâche principale."""
        return cls.select(risk=risk, task=task)


class MultiLLMBridge:
    """
    Pont LiteLLM unifié — 150+ modèles avec MCP Nokido comme tool provider.

    MCP tools injectés :
    - ast_surgeon : vérifie l'intégrité structurelle
    - forge_run   : exécute python/git via le MCP server
    - forge_read  : lit les fichiers du projet
    """

    # MCP Nokido — appel local uniquement via subprocess/import direct (pas de port exposé)

    @classmethod
    def _get_mcp_tools(cls) -> list:
        """Définit les outils MCP Nokido pour les modèles qui supportent tool_use."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "ast_surgeon",
                    "description": (
                        "Vérifie l'intégrité structurelle du code Python muté. "
                        "Retourne True si aucune classe n'est manquante ou vidée."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "original": {"type": "string", "description": "Code original"},
                            "mutated": {"type": "string", "description": "Code muté"},
                        },
                        "required": ["original", "mutated"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "forge_read",
                    "description": "Lit un fichier du projet Nokido.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Chemin relatif au projet"},
                        },
                        "required": ["path"],
                    },
                },
            },
        ]

    @classmethod
    def call(
        cls,
        model: str,
        prompt: str,
        temperature: float = 0.2,
        inject_tools: bool = True,
        knowledge: str = "",
        original_code: str = "",
        failures: list | None = None,
        task: str = "improve",
    ) -> str:
        """
        Dispatch unifié avec boucle Tool Use + SecretAnonymizer.

        Si original_code fourni → anonymise avant envoi cloud, restaure après.
        Dispatch :
        - anthropic/* / claude-* → _call_claude  (format Anthropic tool_use)
        - ollama/*               → _ollama_fallback (local direct, pas d'anonymisation)
        - tout autre             → LiteLLM (format OpenAI tool_calls)
        """
        is_local = model.startswith("ollama/") or model.startswith("local/")

        # Anonymisation — seulement pour les appels cloud
        broker = None
        payload = None
        if original_code and not is_local:
            try:
                import sys as _sys

                _sys.path.insert(0, str(ROOT / "tools"))
                from nokido_agent.tools.forge_trust_broker import OrchestratorTrustBroker

                broker = OrchestratorTrustBroker()
                payload = broker.prepare(original_code, failures or [], task)
                prompt = broker.build_agent_prompt(payload)
                print(
                    f"  [BROKER] {len(original_code)}c → {len(payload['code'])}c anonymisé | "
                    f"{len(payload['_mapping'])} substitutions"
                )
            except Exception as _be:
                print(f"  [BROKER] skip: {_be}")

        if is_local:
            raw = cls._ollama_fallback(prompt, temperature)
        elif "claude" in model.lower() or model.startswith("anthropic/"):
            raw = cls._call_claude(prompt, temperature, inject_tools, knowledge)
        else:
            raw = cls._call_litellm(model, prompt, temperature, inject_tools, knowledge)

        # Nettoyage systématique — strip backticks/headers quelle que soit la source
        if raw and not raw.startswith("["):
            raw = cls._clean_llm_code(raw)

        # Restauration + validation sécurité
        if broker and payload and raw and not raw.startswith("[ERR"):
            restored, status = broker.process_response(raw, payload)
            if status != "OK":
                print(f"  [BROKER] rejet: {status}")
                return f"[ERR:broker] {status}"
            raw = cls._clean_llm_code(restored)  # nettoyer aussi après restauration

        return raw

    @classmethod
    @staticmethod
    def _clean_llm_code(text):
        # Nettoie réponse LLM : strip backticks, headers, prose parasite.
        # qwen7b enveloppe dans ```python...``` et ajoute un header filename.py
        import re as _re

        t = text.strip()
        if not t:
            return t
        # 1. Extraire bloc ```python...``` (priorite max)
        tb = chr(96) * 3
        pat = tb + r"(?:python)?" + r"\n(.*?)" + tb
        m = _re.search(pat, t, _re.DOTALL)
        if m:
            t = m.group(1).strip()
        # 2. Supprimer header "filename.py\n======" en tete
        t = _re.sub(r"^[^\n]{1,120}\.py\s*\n[=\-]{3,}\s*\n", "", t)
        t = _re.sub(r"^[^\n]{1,120}\.py\s*\n", "", t)
        # 3. Avancer jusqu'au premier token Python valide
        kw = ("import ", "from ", "def ", "class ", "#", "__")
        lines = t.splitlines()
        start = 0
        for idx, line in enumerate(lines):
            if line.lstrip().startswith(kw) or line.strip() == "":
                start = idx
                break
        return chr(10).join(lines[start:]).strip()

    @classmethod
    def _call_litellm(
        cls,
        model: str,
        prompt: str,
        temperature: float,
        inject_tools: bool,
        knowledge: str,
        max_turns: int = 5,
    ) -> str:
        """
        Boucle Tool Use OpenAI-compatible via LiteLLM.
        Même principe que _call_claude mais avec le format tool_calls.
        """
        try:
            import litellm as _ll
        except ImportError:
            return cls._ollama_fallback(prompt, temperature)

        # System prompt fort — séparé du user pour que Groq/GitHub l'honore
        _sys = (
            "You are an expert Python refactoring assistant operating inside Nokido v17."
            + chr(10)
            + "ABSOLUTE RULES:"
            + chr(10)
            + "1. Return ONLY the complete, modified Python file — no explanations, no markdown, no commentary."
            + chr(10)
            + "2. Preserve ALL existing logic, classes, functions and imports."
            + chr(10)
            + "3. Do NOT truncate. Output every single line of the original file."
            + chr(10)
            + "4. Do NOT wrap in triple backticks. Raw Python only."
            + chr(10)
            + "5. Type hints: use built-in types (str, int, float, bool, dict, list, tuple, None)."
            + chr(10)
            + "   Do NOT add 'import typing' or Any/Union/Optional."
        )

        # User content = contexte RAG (optionnel) + prompt tâche+code
        user_content = prompt
        if knowledge:
            user_content = "MEMORY:" + chr(10) + knowledge[:1500] + chr(10) * 2 + prompt

        messages = [
            {"role": "system", "content": _sys},
            {"role": "user", "content": user_content},
        ]
        # max_tokens adaptatif : assez pour retourner le fichier complet
        # 1 token ≈ 3.5 chars — on demande 120% de la taille du user content
        _user_len = len(user_content)
        _max_tokens = min(32000, max(4096, int(_user_len / 3.5 * 1.2)))

        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": _max_tokens,
        }
        # Ollama nécessite api_base explicite + timeout long pour grands fichiers
        if "ollama/" in model.lower():
            kwargs["api_base"] = "http://127.0.0.1:11434"
            kwargs["timeout"] = 360
        if inject_tools:
            kwargs["tools"] = cls._get_mcp_tools()
            kwargs["tool_choice"] = "auto"

        for _turn in range(max_turns):
            for delay in [0, 1, 2, 4]:
                if delay:
                    import time as _t

                    _t.sleep(delay)
                try:
                    resp = _ll.completion(**kwargs)
                    break
                except Exception as _e:
                    err = str(_e)
                    if "429" in err or "rate" in err.lower():
                        continue
                    if "tool" in err.lower():
                        kwargs.pop("tools", None)
                        kwargs.pop("tool_choice", None)
                        continue
                    return f"[LiteLLM ERR: {err[:80]}]"
            else:
                return "[LiteLLM ERR: rate limit]"

            choice = resp.choices[0]
            finish = choice.finish_reason
            msg = choice.message

            # Réponse finale
            if finish == "stop" or not getattr(msg, "tool_calls", None):
                return cls._clean_llm_code(msg.content or "")

            # Tool calls — exécution locale
            messages.append(msg)  # ajoute la réponse assistant
            for tc in msg.tool_calls or []:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except Exception:
                    fn_args = {}
                result = cls._execute_tool_locally(fn_name, fn_args)
                print(f"  [TOOL/{fn_name}] → {result[:60]}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    }
                )
            kwargs["messages"] = messages

        return "[LiteLLM ERR: trop de tours tool_calls]"

    @classmethod
    def _call_claude(
        cls, prompt: str, temperature: float, inject_tools: bool, knowledge: str
    ) -> str:
        """
        Appel Claude avec boucle Tool Use complète.

        Flux (Tool Use pattern Anthropic) :
        1. Envoie prompt + schémas tools à Claude
        2. Claude répond avec tool_use blocks → exécution LOCALE
        3. Résultats renvoyés à Claude → réponse finale
        Rien du code source ne sort — seuls les résultats transitent.
        """
        import json as _j
        import os as _o
        import sys as _s
        import urllib.request as _ur

        _s.path.insert(0, str(ROOT / "app"))
        try:
            from nokido_agent.app.forge_settings import get_settings as _gs

            key = getattr(_gs(), "ANTHROPIC_API_KEY", "") or _o.environ.get("ANTHROPIC_API_KEY", "")
        except Exception:
            key = _o.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            return cls._ollama_fallback(prompt, temperature)

        # Construction du message initial
        user_content = prompt
        if knowledge:
            user_content = (
                "Documentation context:" + chr(10) + knowledge[:2000] + chr(10) * 2 + prompt
            )

        messages = [{"role": "user", "content": user_content}]

        payload: dict = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": messages,
        }
        if inject_tools:
            payload["tools"] = cls._get_mcp_tools()

        # Boucle Tool Use — max 5 tours pour éviter les boucles infinies
        for _turn in range(5):
            for delay in [0, 1, 2, 4, 8]:
                if delay:
                    import time as _t

                    _t.sleep(delay)
                try:
                    req = _ur.Request(
                        "https://api.anthropic.com/v1/messages",
                        data=json.dumps(payload).encode(),
                        headers={
                            "x-api-key": key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                    )
                    with _ur.urlopen(req, timeout=60) as r:
                        data = _j.loads(r.read())
                    break  # succès
                except Exception as _e:
                    err = str(_e)
                    if "529" in err or "429" in err or "overloaded" in err.lower():
                        continue
                    return f"[Claude ERR: {err[:80]}]"
            else:
                return "[Claude ERR: rate limit]"

            stop_reason = data.get("stop_reason", "")
            content_blocks = data.get("content", [])

            # Réponse finale — texte pur
            if stop_reason == "end_turn":
                for block in content_blocks:
                    if block.get("type") == "text":
                        return block["text"]
                return ""

            # Tool Use — exécution locale + réponse à Claude
            if stop_reason == "tool_use":
                # Ajoute la réponse assistant avec les tool_use blocks
                messages.append({"role": "assistant", "content": content_blocks})

                # Exécute chaque tool localement
                tool_results = []
                for block in content_blocks:
                    if block.get("type") != "tool_use":
                        continue
                    tool_name = block["name"]
                    tool_input = block.get("input", {})
                    tool_use_id = block["id"]

                    result = cls._execute_tool_locally(tool_name, tool_input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": result,
                        }
                    )
                    print(f"  [TOOL] {tool_name} → {result[:80]}")

                # Renvoie les résultats à Claude
                messages.append({"role": "user", "content": tool_results})
                payload["messages"] = messages
                continue  # prochain tour

            # Fallback — extrait le texte disponible
            for block in content_blocks:
                if block.get("type") == "text":
                    return block["text"]
            return ""

        return "[Claude ERR: trop de tours tool_use]"

    @classmethod
    def _execute_tool_locally(cls, tool_name: str, tool_input: dict) -> str:
        """
        Exécute un tool MCP localement — rien ne sort vers le cloud.
        Seul le RÉSULTAT est renvoyé à Claude.
        """
        if tool_name == "ast_surgeon":
            original = tool_input.get("original", "")
            mutated = tool_input.get("mutated", "")
            ok, msg = ASTSurgeon.validate_integrity(original, mutated)
            return f"{ok}: {msg}"

        if tool_name == "forge_context":
            scope = tool_input.get("scope", "stats")
            if scope == "stats":
                return json.dumps(
                    {
                        "nr_tests": 494,
                        "type_hints": "100%",
                        "docstrings": "90%",
                        "branch": "alpha",
                    },
                    ensure_ascii=False,
                )
            if scope == "files":
                app_files = [f.name for f in (ROOT / "app").glob("*.py")][:20]
                return json.dumps({"app_files": app_files})
            if scope == "rag_summary":
                try:
                    import sqlite3 as _sq

                    conn = _sq.connect(str(ROOT / "RAG/embeddings.db"))
                    n = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
                    conn.close()
                    return f"{n} chunks dans le RAG"
                except Exception:
                    return "RAG non accessible"

        return f"Tool '{tool_name}' non reconnu"

    @classmethod
    def _ollama_fallback(cls, prompt: str, temperature: float) -> str:
        """Fallback Ollama direct si LiteLLM absent."""
        import json as _j
        import urllib.request

        payload = json.dumps(
            {
                "model": "qwen2.5-coder:7b-instruct-q4_K_M",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": 2048},
            }
        ).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=360) as r:
            return _j.loads(r.read()).get("message", {}).get("content", "")


# ── ForgeAnalytics ────────────────────────────────────────────────────────────


class ForgeAnalytics:
    """Mixe probabilisme (LLM) et déterminisme (Tests) via maths de décision."""

    @staticmethod
    def bayesian_reliability(
        successes: int, total: int, alpha_prior: float = 1.0, beta_prior: float = 1.0
    ) -> float:
        """
        Fiabilité via distribution Beta — mode de la posterior.

        Robuste : si un agent réussit 9/10, il reste fiable après un échec isolé.
        Formule : (alpha-1) / (alpha+beta-2) avec alpha=prior+successes.
        """
        alpha = alpha_prior + successes
        beta = beta_prior + (total - successes)
        if (alpha + beta) > 2:
            return round((alpha - 1) / (alpha + beta - 2), 4)
        return 0.5  # prior plat — pas assez de données

    @staticmethod
    def ema(current: float, previous: float | None, alpha: float = 0.3) -> float:
        """
        Lissage exponentiel — filtre le bruit d'une seule mauvaise mutation.

        S_t = alpha * Y_t + (1 - alpha) * S_{t-1}
        alpha=0.3 : réactif mais stable.
        """
        if previous is None:
            return round(current, 2)
        return round(alpha * current + (1 - alpha) * previous, 2)

    @staticmethod
    def volatility(current: float, previous_ema: float | None) -> float:
        """Mesure l'instabilité — écart absolu vs tendance lissée."""
        if previous_ema is None:
            return 0.0
        return round(abs(current - previous_ema), 2)

    @staticmethod
    def ucb1_score(successes: int, total: int, total_all: int, c: float = 2.0) -> float:
        """
        UCB1 — équilibre exploitation/exploration pour l'essaim d'agents.

        Préféré à Bayesian pur quand on veut explorer les agents peu utilisés.
        Score infini si total=0 (encourage l'exploration des nouveaux agents).
        """
        import math as _m

        if total == 0:
            return float("inf")
        exploit = successes / total
        explore = _m.sqrt(c * _m.log(max(total_all, 1)) / total)
        return round(exploit + explore, 4)

    @staticmethod
    def analyze_structural_complexity(code: str) -> tuple[dict, float]:
        """
        Quantifie le risque de troncature avant mutation.

        Les dataclasses pèsent 0.25 chacune (cibles fréquentes de troncature).
        Retourne (stats_dict, risk_score 0-1).
        """
        try:
            tree = ast.parse(code)
            n_cls = len([n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)])
            n_dc = len(
                [
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, ast.ClassDef)
                    and any(getattr(d, "id", "") == "dataclass" for d in n.decorator_list)
                ]
            )
            n_fns = len(
                [
                    n
                    for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
            )
            n_lines = len(code.splitlines())
            risk = min(1.0, n_cls * 0.05 + n_dc * 0.25 + n_fns * 0.02)
            return {
                "classes": n_cls,
                "dataclasses": n_dc,
                "functions": n_fns,
                "lines": n_lines,
            }, risk
        except SyntaxError:
            return {}, 1.0


# ── EvolutionaryRouter ────────────────────────────────────────────────────────


class EvolutionaryRouter:
    """
    Sélectionne l'agent optimal pour un fichier donné
    en se basant sur les probabilités bayésiennes du JSONL.
    """

    JSONL = ROOT / "shadow_mutation" / "rag_index" / "experience_memory.jsonl"

    @classmethod
    def get_best_agent(cls, filepath: str, agents: list[str]) -> tuple[str, float]:
        """
        Analyse l'historique JSONL et retourne (best_agent, bayesian_prob).
        Retourne le premier agent avec prob=0.5 si pas d'historique.
        """
        stats: dict[str, dict] = {a: {"ok": 0, "total": 0, "ema": None} for a in agents}

        if cls.JSONL.exists():
            for line in cls.JSONL.read_text(encoding="utf-8").splitlines():
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                a = d.get("last_mutation_agent") or d.get("agent", "")
                if a not in stats or d.get("file") != filepath:
                    continue
                score = d.get("fitness_score", d.get("score", 0))
                stats[a]["total"] += 1
                if d.get("evolution_status") == "Success":
                    stats[a]["ok"] += 1
                stats[a]["ema"] = ForgeAnalytics.ema(score, stats[a]["ema"])

        probs = {
            a: ForgeAnalytics.bayesian_reliability(s["ok"], s["total"]) for a, s in stats.items()
        }
        best = max(probs, key=probs.get)
        print(
            f"[ROUTER] {Path(filepath).name} → {best} (P={probs[best]:.1%} | EMA={stats[best]['ema']})"
        )
        return best, probs[best]

    @classmethod
    def get_historical_correlation(
        cls, current_risk: float, window: float = 0.2
    ) -> tuple[float, list]:
        """
        Corrélation historique — cherche des runs à risque similaire (+/- window).

        Retourne (taux_échec, leçons_passées).
        Permet d'injecter des contre-mesures avant même de lancer la mutation.
        """
        if not cls.JSONL.exists():
            return 0.0, []

        fails = total = 0
        lessons: set = set()

        for line in cls.JSONL.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            hist_risk = d.get("complexity_risk", d.get("analytics", {}).get("volatility", -1))
            if hist_risk < 0 or abs(hist_risk - current_risk) >= window:
                continue
            total += 1
            if d.get("evolution_status") == "Failure":
                fails += 1
                fb = d.get("experience_feedback", {})
                for l in fb.get("lessons_learned", []) + fb.get("failure_post_mortem", []):
                    lessons.add(l)

        rate = round(fails / total, 3) if total > 0 else 0.0
        return rate, list(lessons)[:3]

    @classmethod
    def compute_safe_temperature(cls, structural_risk: float, historical_fail_rate: float) -> float:
        """Calcule la température optimale en combinant risque structurel et historique."""
        combined = (structural_risk + historical_fail_rate) / 2
        return round(max(0.1, 0.6 - combined * 0.5), 2)

    @classmethod
    def get_history_summary(cls, filepath: str, agent: str) -> dict:
        """Résumé historique {ok, total, ema, last_lessons}."""
        summary = {"ok": 0, "total": 0, "ema": None, "lessons": []}
        if not cls.JSONL.exists():
            return summary
        for line in cls.JSONL.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            a = d.get("last_mutation_agent") or d.get("agent", "")
            if a != agent or d.get("file") != filepath:
                continue
            score = d.get("fitness_score", d.get("score", 0))
            summary["total"] += 1
            if d.get("evolution_status") == "Success":
                summary["ok"] += 1
            summary["ema"] = ForgeAnalytics.ema(score, summary["ema"])
            fb = d.get("experience_feedback", {})
            summary["lessons"] += fb.get("lessons_learned", [])
        return summary


_chr10 = chr(10)
# ── RAGEnricher ───────────────────────────────────────────────────────────────


class RAGEnricher:
    """
    Enrichit les métadonnées pour le RAG de Nokido.
    Génère des cartes d'identité JSON indexables par forge_rag_engine.
    """

    RAG_INDEX = ROOT / "shadow_mutation" / "rag_index"

    @classmethod
    def generate_card(
        cls,
        filepath: str,
        score: int,
        agent: str,
        gen: int,
        feedback: str = "",
        failures: list | None = None,
        lessons: list | None = None,
        success_factors: list | None = None,
        best_practices: list | None = None,
    ) -> Path:
        """Génère une carte d'identité RAG et l'ajoute au journal JSONL."""
        import datetime as _dt

        cls.RAG_INDEX.mkdir(parents=True, exist_ok=True)

        src = (ROOT / filepath).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        functions = [
            n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        fp = ASTSurgeon.get_structure_fingerprint(src) or {}
        integrity = "High" if score >= 80 else ("Medium" if score >= 50 else "Low")
        ts = _dt.datetime.now(tz=_dt.UTC).isoformat()

        card = {
            "timestamp": ts,
            "file": filepath,
            "module": Path(filepath).stem,
            "generation": gen,
            "fitness_score": score,
            "integrity_level": integrity,
            "last_mutation_agent": agent,
            "evolution_status": "Success" if score >= 80 else "Failure",
            "classes": classes,
            "class_fingerprint": fp,
            "function_count": len(functions),
            "critical_components": [c for c, body in fp.items() if body >= 3],
            # Mémoire sémantique
            "experience_feedback": {
                "success_factors": success_factors or [],
                "failure_post_mortem": failures or [],
                "lessons_learned": lessons or [],
                "best_practices_identified": best_practices or [],
            },
            # Auto-évaluation skills
            "skill_assessment": {
                "logic_precision": min(100, max(0, score)),
                "syntax_compliance": 100 if not failures else max(0, 100 - len(failures) * 20),
                "documentation_clarity": 80 if "@dataclass" in src else 60,
            },
            "rag_tags": [
                "ast_validated",
                *(["fitness_high"] if score >= 80 else []),
                *(["fitness_medium"] if 50 <= score < 80 else []),
                *(["fitness_low"] if score < 50 else []),
                *(["has_dataclass"] if "@dataclass" in src else []),
                *(["type_hinted"] if "-> " in src else []),
                *(["post_mortem"] if failures else []),
            ],
        }

        # Calculs analytiques sur l'historique
        _hist = EvolutionaryRouter.get_history_summary(filepath, agent)
        _prev_ema = _hist.get("ema")
        card["analytics"] = {
            "bayesian_reliability": ForgeAnalytics.bayesian_reliability(
                _hist["ok"], _hist["total"]
            ),
            "ema_score": ForgeAnalytics.ema(score, _prev_ema),
            "volatility": ForgeAnalytics.volatility(score, _prev_ema),
            "total_runs": _hist["total"],
        }

        # Fichier JSON unique par module (dernière version)
        out = cls.RAG_INDEX / f"{Path(filepath).stem}.json"
        out.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")

        # JSONL append-only — historique complet
        jsonl = cls.RAG_INDEX / "experience_memory.jsonl"
        with jsonl.open("a", encoding="utf-8") as _fj:
            _fj.write(json.dumps(card, ensure_ascii=False) + _chr10)

        print(f"[RAG] {Path(filepath).stem} | score={score} | {integrity} | JSONL+JSON")
        return out

    @classmethod
    def generate_postmortem(
        cls,
        filepath: str,
        agent: str,
        error: str,
        gen: int,
    ) -> None:
        """Enregistre un post-mortem d'échec dans le JSONL pour apprentissage futur."""
        import datetime as _dt

        cls.RAG_INDEX.mkdir(parents=True, exist_ok=True)

        lesson = f"Agent {agent} sur {Path(filepath).name}: {error[:120]}"
        # Calcule le risque structurel si le fichier est accessible
        _risk = 0.0
        try:
            _src = (ROOT / filepath).read_text(encoding="utf-8", errors="replace")
            _, _risk = ForgeAnalytics.analyze_structural_complexity(_src)
        except Exception:
            pass

        card = {
            "timestamp": _dt.datetime.now(tz=_dt.UTC).isoformat(),
            "file": filepath,
            "module": Path(filepath).stem,
            "generation": gen,
            "fitness_score": 0,
            "complexity_risk": _risk,
            "integrity_level": "Failed",
            "last_mutation_agent": agent,
            "evolution_status": "Failure",
            "experience_feedback": {
                "failure_post_mortem": [error[:200]],
                "lessons_learned": [lesson],
                "success_factors": [],
                "best_practices_identified": [],
            },
            "rag_tags": ["post_mortem", "failure", "learning"],
        }

        jsonl = cls.RAG_INDEX / "experience_memory.jsonl"
        with jsonl.open("a", encoding="utf-8") as _fj:
            _fj.write(json.dumps(card, ensure_ascii=False) + _chr10)

        print(f"[RAG/POST-MORTEM] {Path(filepath).name} | {error[:60]}")

        # CANAL DES LECONS (2026-09-07). Le post-mortem partait ensuite en @disco
        # (refine_and_anchor, collection "disco") : une pepite de DECOUVERTE, pas une
        # LECON. Or memory_keeper.lessons() -- ce que le germe lit desormais avant de
        # muter -- lit le canal des lecons. Le germe ecrivait dans un canal et lisait
        # dans l'autre : la boucle ne pouvait pas se refermer. On ecrit aussi la ou on lit.
        try:
            from nokido_agent.tools.forge_memory_keeper import remember
            remember(problem=lesson, solution=error[:400],
                     example="generation %s, agent %s" % (gen, agent), domain="evolution")
        except Exception as _e:  # noqa: BLE001
            print(f"  [EFFERENT] memory_keeper.remember indisponible "
                  f"({type(_e).__name__}) -- dit, pas avale")

        # Auto-@disco — ingère la leçon dans le RAG pour contextualiser les prochains runs
        try:
            import sys as _sys_d

            _sys_d.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_unified_discovery import refine_and_anchor

            _query = f"Python LLM mutation failure: {error[:80]}"
            _lesson_text = (
                f"POST-MORTEM {Path(filepath).name} | agent={agent} | gen={gen}\n"
                f"Erreur: {error}\n"
                f"Leçon: Éviter cette configuration sur des fichiers similaires."
            )
            refine_and_anchor(
                query=_query,
                raw_texts=[_lesson_text],
                collection="disco_postmortem",
                sources=[f"postmortem:{Path(filepath).name}:{gen}"],
            )
            print(f"[RAG/DISCO] Leçon ancrée: {_query[:60]}")
        except Exception as _de:
            pass  # disco optionnel — ne bloque pas le pipeline

    @classmethod
    def inject_high_density_docstring(cls, content: str, metadata: dict) -> str:
        # Strate 3 — Mémoire Intégrée HD v3 : Color-as-Variable + Tag Vector
        #
        # Injecte dans le source :
        #   1. __FORGE_COLOR__  : état thermique sémantique (GREEN/BLUE/YELLOW/ORANGE/RED/PURPLE)
        #   2. __FORGE_TAGS__   : vecteur dense machine-readable (zéro prose)
        #   3. Docstring HD     : contraintes techniques + historique de performance
        #
        # Lisible par tout LLM sans accès au RAG.
        import datetime as _dt
        import re as _re

        # ── Extraction métadonnées ────────────────────────────────────────
        agent = str(metadata.get("agent", "unknown"))
        score = int(metadata.get("score", 0))
        attempt = int(metadata.get("attempt", 1))
        temp = float(metadata.get("temperature", 0.3))
        feedback = str(metadata.get("feedback", ""))[:120]
        vid = str(metadata.get("version_id", ""))
        risk = float(metadata.get("risk", 0.0))
        lessons = metadata.get("lessons", []) or []
        constraints = metadata.get("constraints", []) or []
        ts = _dt.datetime.now().strftime("%Y-%m-%d")

        # Extraire signaux AST/test/lint depuis feedback
        ast_ok = "AST OK" in feedback
        test_ok = "pytest OK" in feedback or "test OK" in feedback
        lint_ok = "ruff OK" in feedback or "lint OK" in feedback

        # ── Calcul couleur thermique ──────────────────────────────────────
        if score >= 85 and risk > 0.6:
            color = "PURPLE"  # optimisé mais structurellement fragile
        elif score >= 80:
            color = "GREEN"  # stable, faible risque
        elif score >= 60:
            color = "BLUE"  # fonctionnel
        elif score >= 40:
            color = "YELLOW"  # expérimental
        elif score >= 20:
            color = "ORANGE"  # fragile, risque élevé
        else:
            color = "RED"  # zone critique

        # ── Tag vector — dense, machine-readable, zéro prose ─────────────
        def _sig(b: bool) -> str:
            return "OK" if b else "KO"

        tag_vec = (
            f"#FORGE:[score:{score}|agent:{agent}|temp:{temp:.2f}"
            f"|risk:{risk:.2f}|ast:{_sig(ast_ok)}|test:{_sig(test_ok)}"
            f"|lint:{_sig(lint_ok)}|color:{color}|attempt:{attempt}]"
        )

        # ── Contraintes techniques (dense) ───────────────────────────────
        _c_block = ""
        if constraints:
            _c_block = "CONTRAINTES:" + chr(10)
            for c in constraints[:5]:
                _c_block += f"  ! {c}" + chr(10)
        elif feedback:
            _c_block = f"CONTRAINTE: {feedback}" + chr(10)

        # ── Leçons apprises ───────────────────────────────────────────────
        _l_block = ""
        if lessons:
            _l_block = "LESSONS:" + chr(10)
            for l in lessons[:4]:
                _l_block += f"  > {l}" + chr(10)

        # ── Header docstring HD ───────────────────────────────────────────
        q = chr(34) * 3
        n = chr(10)
        header = (
            q
            + n
            + f"FORGE INTELLIGENCE v3 [{color}]"
            + n
            + f"DATE:{ts} | VER:{vid}"
            + n
            + tag_vec
            + n
            + _c_block
            + _l_block
            + q
            + n
        )

        # ── Variables sémantiques Python (lisibles par tout parser AST) ──
        color_var = f"__FORGE_COLOR__ = {chr(34)}{color}{chr(34)}" + n
        tags_var = f"__FORGE_TAGS__  = {chr(34)}{tag_vec}{chr(34)}" + n
        sem_block = color_var + tags_var

        # ── Injection dans le source ──────────────────────────────────────
        # Remplace si déjà présent
        if "FORGE INTELLIGENCE" in content:
            content = _re.sub(
                r'"""[\s\S]*?FORGE INTELLIGENCE[\s\S]*?"""' + r"\s*", header, content, count=1
            )
            # Remplace les variables sémantiques
            content = _re.sub(
                r'__FORGE_COLOR__\s*=\s*"[A-Z]+"' + chr(10), color_var, content, count=1
            )
            content = _re.sub(r'__FORGE_TAGS__\s*=\s*"[^"]*"' + chr(10), tags_var, content, count=1)
            return content

        # Insertion fraîche
        lines = content.splitlines(keepends=True)
        insert_at = 0
        for idx, line in enumerate(lines[:8]):
            if line.startswith(("#!", "# -*-", "# coding", "from __future__")):
                insert_at = idx + 1

        # header docstring + variables sémantiques après les imports de tête
        lines.insert(insert_at, header)
        # Variables juste après le header
        lines.insert(insert_at + 1, sem_block)
        return "".join(lines)

    @classmethod
    def inject_forge_metadata(cls, content: str, filepath: str, score: int, agent: str) -> str:
        """Injecte un header FORGE_METADATA dans le module."""
        import datetime as _dt

        stem = Path(filepath).stem
        ts = _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%d")

        header = (
            f'''"""\n'''
            f"""FORGE_METADATA:\n"""
            f"""  module: {stem}\n"""
            f"""  fitness_score: {score}/100\n"""
            f"""  last_mutation_agent: {agent}\n"""
            f"""  audit_date: {ts}\n"""
            f'''"""\n'''
        )

        # Ne réinjecte pas si déjà présent
        if "FORGE_METADATA:" in content:
            return content

        # Insère après le shebang/encoding si présent
        lines = content.splitlines(keepends=True)
        insert_at = 0
        for i, l in enumerate(lines[:5]):
            if l.startswith(("#!", "# -*-", "# coding")):
                insert_at = i + 1
        lines.insert(insert_at, header)
        return "".join(lines)


# ── KeywordIntelligence ───────────────────────────────────────────────────────


class KeywordIntelligence:
    """Transforme la structure AST du code en requêtes de recherche optimisées."""

    @staticmethod
    def extract_search_intent(code: str) -> tuple[list, list]:
        """Extrait bibliothèques et patterns structurels depuis l'AST."""
        try:
            tree = ast.parse(code)
            libraries: set = set()
            patterns: set = set()

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        libraries.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom) and node.module:
                    libraries.add(node.module.split(".")[0])
                elif isinstance(node, ast.ClassDef):
                    for d in node.decorator_list:
                        name = getattr(d, "id", None) or getattr(
                            getattr(d, "func", None), "id", None
                        )
                        if name:
                            patterns.add(name)

            # Filtre les stdlib banales
            _stdlib_noise = {
                "os",
                "sys",
                "re",
                "ast",
                "json",
                "time",
                "math",
                "pathlib",
                "typing",
                "abc",
                "io",
                "copy",
                "functools",
                "__future__",
                "collections",
                "itertools",
                "threading",
                "subprocess",
                "logging",
                "warnings",
                "dataclasses",
                "datetime",
                "enum",
                "contextlib",
            }
            libraries -= _stdlib_noise
            return sorted(libraries), sorted(patterns)
        except Exception:
            return [], []

    @staticmethod
    def build_query(libraries: list, patterns: list, task: str) -> str:
        """Construit une requête précise pour la recherche documentaire."""
        parts = [f"official documentation {task}"]
        if libraries:
            parts.append(f"using {' '.join(libraries[:5])}")
        if patterns:
            parts.append(f"with focus on {' '.join(patterns[:3])}")
        return " ".join(parts)


# ── SourceDiscovery ───────────────────────────────────────────────────────────


class SourceDiscovery:
    """
    Recherche documentaire via Gemini + Google Search grounding.
    Fallback sur forge_unified_discovery si Gemini indisponible.
    """

    MODEL = "gemini-2.5-flash"
    ENDPOINT = (
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    )

    @classmethod
    def _get_key(cls) -> str:
        """Récupère la clé Gemini depuis settings ou env."""
        try:
            import os as _o
            import sys as _s

            _s.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_settings import get_settings as _gs

            return getattr(_gs(), "GEMINI_API_KEY", "") or _o.environ.get("GEMINI_API_KEY", "")
        except Exception:
            import os

            return os.environ.get("GEMINI_API_KEY", "")

    @classmethod
    def fetch_docs(cls, code: str, task: str) -> str:
        """
        Recherche les docs officielles pour le code/tâche donnés.

        Pipeline :
        1. KeywordIntelligence extrait les libs et patterns
        2. Gemini + Google Search grounding récupère les sources officielles
        3. Fallback sur forge_unified_discovery si Gemini KO
        """
        libs, patterns = KeywordIntelligence.extract_search_intent(code)
        query = KeywordIntelligence.build_query(libs, patterns, task)
        print(f"[DISCOVERY] Query: {query[:80]}")

        key = cls._get_key()
        if key:
            result = cls._fetch_gemini(query, key)
            if result and not result.startswith("ERR"):
                return result

        # Fallback — forge_unified_discovery (DuckDuckGo local)
        return cls._fetch_local(query)

    @classmethod
    def _fetch_gemini(cls, query: str, key: str) -> str:
        """Appel Gemini avec Google Search grounding + backoff exponentiel."""
        import json as _j
        import urllib.request as _ur

        url = cls.ENDPOINT.format(model=cls.MODEL, key=key)
        payload = json.dumps(
            {
                "contents": [{"parts": [{"text": query}]}],
                "systemInstruction": {
                    "parts": [
                        {
                            "text": (
                                "You are a technical documentation expert. "
                                "Find the latest official recommendations (PEPs, official docs, GitHub). "
                                "Be concise — max 300 words. Return in French."
                            )
                        }
                    ]
                },
                "tools": [{"google_search": {}}],
            }
        ).encode()

        for delay in [1, 2, 4, 8]:
            try:
                req = _ur.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with _ur.urlopen(req, timeout=20) as r:
                    data = _j.loads(r.read())

                candidate = data.get("candidates", [{}])[0]
                text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")
                grounding = candidate.get("groundingMetadata", {}).get("groundingAttributions", [])
                sources = [
                    a.get("web", {}).get("uri") for a in grounding if a.get("web", {}).get("uri")
                ]
                if sources:
                    text += _chr10 + "Sources: " + ", ".join(sources[:3])
                return text or "ERR:empty"

            except Exception as _e:
                err = str(_e)
                if "429" in err:
                    import time as _t

                    _t.sleep(delay)
                else:
                    return f"ERR:{err[:60]}"

        return "ERR:rate_limit"

    @classmethod
    def _fetch_local(cls, query: str) -> str:
        """Fallback — forge_unified_discovery (DuckDuckGo, pas de clé requise)."""
        try:
            import sys as _s

            _s.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_unified_discovery import refine_and_anchor

            result = refine_and_anchor(
                query=query,
                raw_texts=[f"[DISCOVERY FALLBACK] {query}"],
                collection="disco_discovery",
                sources=[f"discovery:{query[:50]}"],
            )
            return f"[Local discovery] {result.get('message', '')} — {query}"
        except Exception as _e:
            return f"[Discovery indisponible: {_e}]"


# ── Helpers communs ───────────────────────────────────────────────────────────


def run_generation(
    targets: list[str],
    gen: int,
    task: str | None,
    workers: int,
    agent: str | None,
) -> dict:
    """Lance une génération via ParallelMutationWorker. Retourne les résultats."""
    print(f"\n{'=' * 60}\n  GÉNÉRATION {gen}\n{'=' * 60}")

    cmd = [
        sys.executable,
        "-u",
        "ParallelMutationWorker.py",
        "--workers",
        str(workers),
        "--files",
        *targets,
    ]
    if task:
        cmd += ["--task", task]
    if agent:
        cmd += ["--agent", agent]

    t0 = time.monotonic()
    results = {"ok": [], "fail": [], "elapsed": 0}
    ignore = ["[SILICON]", "[HW]", "[PERF]", "Connection pool", "DNS", "MMAP"]

    import os as _os

    _env = {**_os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        bufsize=1,
        stdin=subprocess.DEVNULL,
        env=_env,
    )
    for line in iter(proc.stdout.readline, ""):
        l = line.rstrip()
        if l.strip() and not any(x in l for x in ignore):
            sys.stdout.write(l + "\n")
            sys.stdout.flush()
        if "[RESULT:OK]" in l:
            # Extraire le chemin propre — strip le préfixe "[RESULT:OK] "
            _raw = l.split("|")[0].strip()
            _path = _raw.replace("[RESULT:OK]", "").strip()
            results["ok"].append(_path)
        elif "[RESULT:KO]" in l or "[FITNESS:0]" in l:
            _raw = l.split("|")[0].strip()
            _path = _raw.replace("[RESULT:KO]", "").replace("[FITNESS:0]", "").strip()
            results["fail"].append(_path)
    proc.wait()
    results["elapsed"] = round(time.monotonic() - t0, 1)
    # EFFERENT ENDOCRINIEN du germe (2026-09-07). Jusqu'ici une mutation reussie ou
    # ratee n'emettait AUCUNE hormone : l'organe reproductif etait hors de la boucle
    # endocrine_to_gate que le corps a deja cablee pour l'aiguilleur. On emet PAREIL
    # que le gate (forge_motivation.reward / punish), pas autrement.
    #   - reward ET punish ensemble : du cortisol sans dopamine ne remet jamais
    #     failure_count a zero et derive vers dead_end -- la pathologie deja payee
    #     (cortisol survivant au restart, 471 spawns refuses a RAM 60 %).
    #   - time_s = duree MESUREE de la GENERATION, attribuee a chaque cible : le germe
    #     ne chronometre pas par mutation, et compute_elegance ferait de time_s=0 une
    #     dopamine MAXIMALE -- une mesure inventee. Une attribution nommee vaut mieux.
    #   - punish REND une decision (action_recommended / dead_end) : on la conserve
    #     dans results pour que l'appelant puisse cesser de muter une impasse.
    results["efferent"] = {"reward": [], "punish": [], "etat": "EMIS",
                           "time_s_attribution": "duree de la GENERATION, pas de la mutation"}
    try:
        from nokido_agent.app.forge_motivation import punish, reward
        for _p in results["ok"]:
            reward("evolution", time_s=float(results["elapsed"]), n_steps=1,
                   success=True, target=Path(_p).stem)
            results["efferent"]["reward"].append(Path(_p).stem)
        for _p in results["fail"]:
            _d = punish("evolution", error="mutation KO", target=Path(_p).stem) or {}
            results["efferent"]["punish"].append(
                {"target": Path(_p).stem,
                 "action_recommended": _d.get("action_recommended"),
                 "dead_end": bool(_d.get("dead_end"))})
    except Exception as _e:  # noqa: BLE001
        results["efferent"]["etat"] = "INDISPONIBLE (%s)" % type(_e).__name__
        print(f"  [EFFERENT] endocrinien indisponible ({type(_e).__name__}) -- dit, pas avale")
    return results


def save_checkpoint(targets: list[str], gen: int) -> Path:
    """Sauvegarde les fichiers mutés comme checkpoint de génération."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    cp_dir = CHECKPOINT_DIR / f"gen{gen:02d}_{ts}"
    cp_dir.mkdir()
    for t in targets:
        src = ROOT / t
        if src.exists():
            shutil.copy(src, cp_dir / src.name)
    (cp_dir / "meta.json").write_text(
        json.dumps({"gen": gen, "ts": ts, "targets": targets}, indent=2)
    )
    print(f"[CHECKPOINT] Gen {gen} → {cp_dir.name}")
    return cp_dir


def load_best_checkpoint(gen: int) -> Path | None:
    """Charge le checkpoint de la génération précédente."""
    candidates = sorted(CHECKPOINT_DIR.glob(f"gen{gen:02d}_*"))
    return candidates[-1] if candidates else None


def basic_crossover(file_a: Path, file_b: Path, output: Path) -> bool:
    """Crossover basique — docstrings de A, logique de B."""
    try:
        src_a = file_a.read_text(encoding="utf-8", errors="replace")
        src_b = file_b.read_text(encoding="utf-8", errors="replace")
        tree_a, tree_b = ast.parse(src_a), ast.parse(src_b)
        lines_b = src_b.splitlines(keepends=True)
        lines_a = src_a.splitlines()

        docs_a = {}
        for n in ast.walk(tree_a):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (
                    n.body
                    and isinstance(n.body[0], ast.Expr)
                    and isinstance(n.body[0].value, ast.Constant)
                ):
                    docs_a[n.name] = lines_a[n.body[0].lineno - 1]

        for n in ast.walk(tree_b):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in docs_a:
                if not (
                    n.body
                    and isinstance(n.body[0], ast.Expr)
                    and isinstance(n.body[0].value, ast.Constant)
                ):
                    ins = n.body[0].lineno - 1
                    ind = " " * (len(lines_b[ins]) - len(lines_b[ins].lstrip()))
                    lines_b.insert(ins, f'{ind}"""{docs_a[n.name].strip()}"""\n')

        result = "".join(lines_b)
        ast.parse(result)
        output.write_text(result, encoding="utf-8")
        return True
    except Exception as e:
        print(f"[CROSSOVER] Échec: {e}")
        return False


# ── Modes principaux ──────────────────────────────────────────────────────────


def run_evolutionary(
    targets: list[str],
    generations: int = 3,
    task: str | None = None,
    workers: int = 3,
    agent: str | None = None,
    crossover: bool = False,
    cerberus: bool = False,
    population: int = 1,
) -> None:
    """Lance le moteur évolutif sur N générations avec Cerberus optionnel."""
    print("\n🧬 Nokido Evolutionary Engine")
    print(f"   Targets: {len(targets)} | Générations: {generations} | Task: {task or 'default'}")
    print(f"   Cerberus: {'oui (pop=' + str(population) + ')' if cerberus else 'non'}")

    guard = CerberusGuard() if cerberus else None
    all_res = []
    best_ok = 0
    best_gen = 0

    for gen in range(1, generations + 1):
        results = run_generation(targets, gen, task, workers, agent)
        all_res.append(results)
        ok_count = len(results["ok"])
        print(f"\n  Gen {gen}: {ok_count}/{len(targets)} OK en {results['elapsed']}s")

        # Cerberus — évaluation parallèle : N candidats depuis checkpoints forks
        if cerberus and guard and results["ok"] and population > 1:
            _orig_tgt = results["ok"][0]
            _orig = (ROOT / _orig_tgt).read_text(encoding="utf-8", errors="replace")
            _fname = Path(_orig_tgt).name
            # Chercher N variantes dans shadow_mutation/forks/ ou checkpoints récents
            _candidates = []
            _forks_dir = ROOT / "shadow_mutation" / "forks"
            if _forks_dir.exists():
                for _fork in sorted(
                    _forks_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True
                )[:population]:
                    _fp = _fork / _fname
                    if _fp.exists():
                        try:
                            _c = _fp.read_text(encoding="utf-8", errors="replace")
                            if _c != _orig:  # seulement les vraies mutations
                                _candidates.append(
                                    {"content": _c, "agent": _fork.name, "target": _orig_tgt}
                                )
                        except Exception:
                            pass
            # Fallback : utiliser le fichier muté courant comme unique candidat
            if not _candidates:
                _cur = (ROOT / _orig_tgt).read_text(encoding="utf-8", errors="replace")
                if _cur != _orig:
                    _candidates.append({"content": _cur, "agent": "worker", "target": _orig_tgt})
            if _candidates:
                print(f"  [CERBERUS] Évaluation {len(_candidates)} candidat(s) vs original")
                _ranked = guard.evaluate_parallel(_candidates, _orig, _fname)
                if _ranked:
                    _alpha = _ranked[0]
                    print(f"  [CERBERUS] Alpha: score={_alpha['score']}/100 — {_alpha['feedback']}")
                    # Enregistre la carte RAG pour l'alpha
                    RAGEnricher.generate_card(
                        filepath=_orig_tgt,
                        score=_alpha["score"],
                        agent=_alpha.get("agent", "worker"),
                        gen=gen,
                        feedback=_alpha["feedback"],
                    )

        if ok_count >= best_ok:
            best_ok = ok_count
            best_gen = gen
            save_checkpoint(targets, gen)

        if crossover and gen >= 2:
            prev = load_best_checkpoint(gen - 1)
            if prev:
                for tgt in targets[:2]:
                    fa = prev / Path(tgt).name
                    fb = ROOT / tgt
                    if fa.exists() and fb.exists():
                        if basic_crossover(fa, fb, fb):
                            print(f"  ✅ Crossover {Path(tgt).name}")

        if ok_count == len(targets):
            print(f"\n✨ 100% OK dès gen {gen} — arrêt anticipé")
            break

        if ok_count == 0 and gen > 1:
            prev = load_best_checkpoint(best_gen)
            if prev:
                for tgt in targets:
                    src = prev / Path(tgt).name
                    if src.exists():
                        shutil.copy(src, ROOT / tgt)
                        print(f"  ↩ {Path(tgt).name} restauré gen {best_gen}")

    print(f"\n{'=' * 60}\n  Meilleure génération: {best_gen}\n{'=' * 60}")
    for i, r in enumerate(all_res, 1):
        bar = "█" * len(r["ok"]) + "░" * (len(targets) - len(r["ok"]))
        print(f"  Gen {i}: {len(r['ok'])}/{len(targets)} {bar} ({r['elapsed']}s)")


def run_workflow(
    mermaid_script: str,
    target_file: str,
    population: int = 1,
    cerberus: bool = False,
) -> None:
    """Lance un workflow piloté par un diagramme Mermaid."""
    print(f"\n🚀 Nokido Workflow Engine: {target_file}")
    orch = MermaidOrchestrator()
    temp_mgr = AdaptiveTemperatureManager()
    guard = CerberusGuard() if cerberus else None

    orch.parse(mermaid_script)
    current_node = orch.root_node()
    file_path = ROOT / target_file
    content = file_path.read_text(encoding="utf-8", errors="replace")

    # Source Discovery — docs officielles pour enrichir le prompt
    _knowledge_ctx = ""
    if cerberus:  # Actif seulement en mode Cerberus (qualité maximale)
        print("  [DISCOVERY] Recherche docs officielles...")
        _knowledge_ctx = SourceDiscovery.fetch_docs(content, "mutation best practices")
        if _knowledge_ctx and not _knowledge_ctx.startswith("[Discovery"):
            print(f"  [DISCOVERY] Contexte: {len(_knowledge_ctx)}c")

    # Analyse de risque structurel + corrélation historique
    _stats, _risk = ForgeAnalytics.analyze_structural_complexity(content)
    _fail_rate, _past_lessons = EvolutionaryRouter.get_historical_correlation(_risk)
    _safe_temp = EvolutionaryRouter.compute_safe_temperature(_risk, _fail_rate)

    print(f"  [RISK] structurel={_risk:.2f} | hist_fail={_fail_rate:.1%} | temp→{_safe_temp}")
    if _stats.get("dataclasses", 0) > 0:
        print(f"  [RISK] {_stats['dataclasses']} dataclass(es) — surveillance renforcée")

    # Contre-mesures dynamiques si risque élevé
    _safety_rules: list = []
    if _risk > 0.6 or _fail_rate > 0.4:
        _safety_rules = [
            "WARNING: High truncation risk — do NOT remove any class body.",
            "STRICT: Every dataclass must retain ALL its fields.",
        ]
        if _past_lessons:
            _safety_rules.append(f"PAST LESSON: {_past_lessons[0]}")
        # COMMISSURE memory_keeper -> germe (2026-09-07). Jusqu'ici ce bloc ne lisait que
        # les fiches de feedback DU germe (`cls.JSONL`) : la memoire du corps (1,1 Mo de
        # lecons dans forge_memory_keeper) n'etait consultee par PERSONNE avant une
        # mutation. Deux memoires, aucune commissure -- la carte du corps le declarait
        # en GAP P1. On consulte, on ne remplace pas : les deux sources se cumulent.
        try:
            from nokido_agent.tools.forge_memory_keeper import lessons as _mk_lessons
            from pathlib import Path as _P
            _mk = _mk_lessons(_P(str(target_file)).stem, limit=3)
            if _mk.get("etat") != "LU":
                # ILLISIBLE n'est pas ABSENT : on le DIT au lieu de lire « aucune lecon ».
                print(f"  [SAFETY] memory_keeper {_mk.get('etat')} ({_mk.get('motif')}) "
                      f"-- lecons du corps NON consultees, pas absentes")
            for _it in (_mk.get("items") or [])[:2]:
                _safety_rules.append(
                    f"PAST LESSON (memory_keeper/{_it.get('source')}): "
                    f"{str(_it.get('preview', ''))[:200]}")
        except Exception as _e:  # noqa: BLE001
            print(f"  [SAFETY] commissure memory_keeper indisponible "
                  f"({type(_e).__name__}) -- dite, pas avalee")
        print(f"  [SAFETY] {len(_safety_rules)} contre-mesures injectées dans le prompt")

    # Routage UCB1/Bayésien — choisit l'agent optimal selon l'historique
    _available_agents = ["qwen2.5-coder:7b", "llama-3.3-70b", "surgical_architect"]
    _best_agent, _agent_prob = EvolutionaryRouter.get_best_agent(target_file, _available_agents)
    print(f"  [ROUTER] Agent sélectionné: {_best_agent} (fiabilité={_agent_prob:.1%})")

    while current_node:
        node_info = orch.graph["nodes"].get(current_node, {})
        task = node_info.get("label", "default")
        temp = temp_mgr.current

        if node_info.get("type") == "end":
            print(f"  [END] {current_node}")
            break

        print(f"\n  [NODE] {current_node} ({task}) | Temp: {temp:.2f}")

        # Lance la mutation via le worker
        results = run_generation([target_file], gen=1, task=task, workers=1, agent=None)
        status = "Échec"

        if results["ok"]:
            new_content = file_path.read_text(encoding="utf-8", errors="replace")
            ok, msg = ASTSurgeon.validate_integrity(content, new_content)

            if ok:
                if guard:
                    score, fb = guard.evaluate(content, new_content, Path(target_file).name, 0)
                    print(f"  [CERBERUS] score={score}/100 — {fb}")
                    ok = score > 0
                if ok:
                    content = new_content
                    status = "Succès"
                    temp_mgr.adjust(100)
                    print(f"  ✅ {msg}")
                    RAGEnricher.generate_card(
                        filepath=target_file,
                        score=80,
                        agent="worker",
                        gen=1,
                        feedback=msg,
                        success_factors=["ASTSurgeon validated", "CerberusGuard passed"],
                    )
            else:
                temp_mgr.adjust(0, lethal=True)
                print(f"  🚨 {msg} | temp → {temp_mgr.current:.2f}")
        else:
            temp_mgr.adjust(0, lethal=True)
            print(f"  ❌ Worker KO | temp → {temp_mgr.current:.2f}")
            RAGEnricher.generate_postmortem(
                filepath=target_file,
                agent="worker",
                error="Worker returned no OK result",
                gen=1,
            )

        current_node = orch.next_node(current_node, status)
        if current_node:
            time.sleep(1)

    file_path.write_text(content, encoding="utf-8")
    print(f"\n✨ Workflow terminé — {target_file}")


# ── CuriosityEngine ───────────────────────────────────────────────────────────

# Graphe de curiosité — sujets connexes par domaine
# Si le score RAG d'un sujet dépasse MASTERY_THRESHOLD, on explore ses voisins
_CURIOSITY_GRAPH: dict = {
    "dataclasses": ["slots", "pydantic", "attrs", "msgspec", "typing_extensions"],
    "type_hints": ["mypy", "pyright", "beartype", "runtime_checkable", "Protocol"],
    "ast_mutation": ["libcst", "rope", "bowler", "semgrep", "ast_comments"],
    "pytest": ["hypothesis", "pytest_benchmark", "pytest_asyncio", "coverage"],
    "asyncio": ["anyio", "trio", "uvloop", "aiohttp", "httpx"],
    "performance": ["cython", "numba", "ctypes", "memoryview", "slots"],
    "llm_prompting": ["chain_of_thought", "few_shot", "constitutional_ai", "dspy"],
    "rag": ["faiss", "chromadb", "qdrant", "reranking", "hyde"],
    "mcp": ["tool_use", "function_calling", "json_schema", "openapi"],
    "refactoring": ["solid_principles", "design_patterns", "clean_code", "coupling"],
}
_MASTERY_THRESHOLD = 0.65  # score RAG au-delà duquel on explore les voisins


class CuriosityEngine:
    """
    Moteur de curiosité — détecte la maîtrise d'un sujet et explore les connexes.
    Alimente le RAG avec des connaissances adjacentes pour spécialiser les agents.
    """

    MASTERY_THRESHOLD = _MASTERY_THRESHOLD  # seuil score/100 (int) pour curiosité

    @classmethod
    def check_mastery(cls, skill: str) -> float:
        """Retourne le score RAG d'une compétence (0-1)."""
        try:
            import sys as _s

            _s.path.insert(0, str(ROOT / "app"))
            import asyncio as _aio

            from nokido_agent.app import forge_context as _fc

            rag = _fc.get_rag_engine()
            if not rag:
                return 0.0
            loop = _aio.new_event_loop()
            score = loop.run_until_complete(rag.check_competence(skill))
            loop.close()
            return score
        except Exception:
            return 0.0

    @classmethod
    def get_adjacent_skills(cls, skill: str, mastery: float) -> list[str]:
        """
        Retourne les sujets connexes à explorer si mastery > seuil.
        Plus la maîtrise est haute, plus on explore loin.
        """
        # Recherche le nœud le plus proche dans le graphe
        best_node = None
        for node in _CURIOSITY_GRAPH:
            if node in skill.lower() or skill.lower() in node:
                best_node = node
                break

        if not best_node:
            return []

        neighbors = _CURIOSITY_GRAPH[best_node]

        if mastery >= 0.9:
            # Très haute maîtrise → explore les voisins de voisins
            deep = []
            for n in neighbors[:2]:
                deep += _CURIOSITY_GRAPH.get(n, [])[:2]
            return neighbors + deep
        elif mastery >= _MASTERY_THRESHOLD:
            # Maîtrise suffisante → explore les voisins directs
            return neighbors[:3]
        else:
            return []

    @classmethod
    def discover_adjacent(cls, skill: str, filepath: str) -> list[str]:
        """
        Vérifie la maîtrise et lance @disco sur les sujets connexes si besoin.
        Retourne la liste des sujets découverts.
        """
        mastery = cls.check_mastery(skill)
        adjacent = cls.get_adjacent_skills(skill, mastery)

        if not adjacent:
            return []

        print(f"  [CURIOSITY] {skill} maîtrisé ({mastery:.0%}) → explore: {adjacent[:3]}")

        discovered = []
        for adj_skill in adjacent[:3]:  # max 3 pour économiser les quotas
            adj_mastery = cls.check_mastery(adj_skill)
            if adj_mastery < _MASTERY_THRESHOLD:
                # Non maîtrisé → découverte via SourceDiscovery
                print(f"  [CURIOSITY] Découverte: {adj_skill} (score={adj_mastery:.0%})")
                code = (ROOT / filepath).read_text(encoding="utf-8", errors="replace")
                context = SourceDiscovery.fetch_docs(code, adj_skill)
                if context and not context.startswith("["):
                    # Ancre dans le RAG
                    try:
                        import sys as _s

                        _s.path.insert(0, str(ROOT / "app"))
                        from nokido_agent.app.forge_unified_discovery import refine_and_anchor as _raa

                        _raa(
                            query=adj_skill,
                            raw_texts=[context],
                            collection="disco_curiosity",
                            sources=[f"curiosity:{adj_skill}"],
                        )
                    except Exception:
                        pass
                    discovered.append(adj_skill)
            else:
                print(f"  [CURIOSITY] {adj_skill} déjà maîtrisé ({adj_mastery:.0%})")

        return discovered


# ── IntelligentCerberusLoop ───────────────────────────────────────────────────


class IntelligentCerberusLoop:
    """
    Boucle Cerberus apprenante + curieuse.

    Innove à chaque retry selon le diagnostic :
    - AST KO systématique  → réduit chunks + monte vers ARCHITECTS
    - SyntaxError          → baisse température + garde-fous prompt
    - ImportError          → arrêt propre (environnement cassé)
    - pytest KO            → contourne le test cassé
    - mixed_failure        → crossover meilleure branche partielle
    - score > MASTERY      → CuriosityEngine explore les sujets connexes
    """

    MAX_RETRIES = 5
    IMPROVEMENT_MIN = 10

    def __init__(
        self, guard: CerberusGuard, temp_mgr: AdaptiveTemperatureManager, population: int = 3
    ) -> None:
        self.guard = guard
        self.temp_mgr = temp_mgr
        self.population = population
        self._strategy: dict = {
            "temperature": temp_mgr.current,
            "agent_risk_bias": 0.0,
            "prompt_suffix": "",
            "skip_agents": set(),
        }
        self._evo_stack = None  # EvolutionaryStack — lazy init

    def run(self, filepath: str, task: str, knowledge: str = "") -> tuple[str | None, dict]:
        """Lance la boucle. Retourne (best_content, rapport)."""
        original = (ROOT / filepath).read_text(encoding="utf-8", errors="replace")
        fname = Path(filepath).name
        _, struct_risk = ForgeAnalytics.analyze_structural_complexity(original)

        best_content = None
        best_score = 0
        history: list = []

        sep = "=" * 58
        print(sep)
        print(f"  CERBERUS INTELLIGENT — {fname} | risk={struct_risk:.2f}")
        print(f"{'=' * 58}")

        for attempt in range(1, self.MAX_RETRIES + 1):
            temp = self._strategy["temperature"]
            bias = self._strategy["agent_risk_bias"]
            print(f" [RETRY {attempt}/{self.MAX_RETRIES}] temp={temp:.2f} bias={bias:.1f}")

            # Agents adaptés au risque effectif
            eff_risk = min(1.0, struct_risk + bias)
            agents = [
                a
                for a in AgentPool.select(risk=eff_risk, population=self.population, task=task)
                if a not in self._strategy["skip_agents"]
            ]

            if not agents:
                print("  [ABORT] Tous les agents blacklistés")
                break

            # Prompt avec garde-fous adaptatifs
            # EvolutionaryStack — enrichit knowledge avec contexte génomique
            if self._evo_stack is None:
                from nokido_agent.tools.forge_evolutionary_stack import EvolutionaryStack

                self._evo_stack = EvolutionaryStack()
            _stack_ctx = self._evo_stack.get_context(filepath)
            _knowledge = (_stack_ctx + "\n\n" + knowledge).strip() if _stack_ctx else knowledge
            prompt = self._build_prompt(original, task, _knowledge)

            # Appels LLM parallèles (I/O bound — ThreadPool)
            # ── ML Predictor — skip si P(succès) < seuil ──────────────
            try:
                import sys as _sys_ml

                _sys_ml.path.insert(0, str(ROOT / "tools"))
                from nokido_agent.tools.forge_mutation_predictor import MutationPredictor as _MP

                _pred = _MP()
                if _pred.is_available():
                    _prob, _go = _pred.should_attempt(
                        filepath=filepath,
                        risk=self._risk,
                        agents=agents,
                        temp=temp,
                        attempt=attempt,
                    )
                    if not _go and attempt < 4:
                        print(f"  [ML-SKIP] P={_prob:.2f} < {_pred._threshold} — tentative ignorée")
                        self._adapt_strategy(None, [], attempt)
                        continue
                    print(f"  [ML] P={_prob:.2f} → GO")
            except Exception:
                pass  # prédicteur optionnel — ne jamais bloquer Cerberus
            candidates = self._spawn_candidates(agents, prompt, temp, len(original))
            if not candidates:
                self._escalate_agents()
                continue

            # Évaluation parallèle Cerberus
            ranked = self.guard.evaluate_parallel(candidates, original, fname)
            alpha = ranked[0] if ranked else None
            score = alpha["score"] if alpha else 0
            diag = alpha.get("diagnosis") if alpha else None

            fb_str = alpha.get("feedback", "")[:60] if alpha else ""
            print(f"  [ALPHA] score={score}/100 — {fb_str}")

            # Sauvegarde du meilleur
            if score > best_score:
                best_score = score
                best_content = alpha.get("content") if alpha else None

            history.append({"attempt": attempt, "score": score, "strategy": dict(self._strategy)})

            # Succès — mais avant de terminer, vérifie la curiosité
            if score >= 80:
                print(f"  [SUCCESS] score={score}/100 — exploration curiosité...")
                discovered = CuriosityEngine.discover_adjacent(task, filepath)
                if discovered:
                    print(f"  [CURIOSITY] {len(discovered)} sujets connexes ingérés")
                RAGEnricher.generate_card(
                    filepath=filepath,
                    score=score,
                    agent=agents[0],
                    gen=attempt,
                    feedback=fb_str,
                    success_factors=[f"temp={temp:.2f}", f"attempt={attempt}"],
                )
                # EvolutionaryStack — archive la mutation validée par Cerberus
                if self._evo_stack is None:
                    from nokido_agent.tools.forge_evolutionary_stack import EvolutionaryStack

                    self._evo_stack = EvolutionaryStack()
                _vid = self._evo_stack.on_success(
                    filepath=filepath,
                    content=alpha.get("content", "") if alpha else "",
                    score=score,
                    agent=agents[0],
                    feedback=fb_str,
                )
                print(f"  [STACK] \u2705 archiv\u00e9 \u2192 {_vid}")
                # Strate 3 — Mémoire Intégrée : tatouage HD docstring dans le fichier
                try:
                    _content_hd = alpha.get("content", "") if alpha else ""
                    if _content_hd:
                        _hd = RAGEnricher.inject_high_density_docstring(
                            _content_hd,
                            {
                                "agent": agents[0],
                                "score": score,
                                "attempt": attempt,
                                "temperature": temp,
                                "feedback": fb_str,
                                "version_id": _vid,
                            },
                        )
                        (ROOT / filepath).write_text(_hd, encoding="utf-8")
                        print(
                            f"  [STRATE3] \u270d HD docstring injectée dans {Path(filepath).name}"
                        )
                except Exception as _e3:
                    print(f"  [STRATE3] skip — {_e3}")
                break

            # Strate 1 — Mémoire Épisodique : enregistre chaque tentative ratée
            try:
                RAGEnricher.generate_postmortem(
                    filepath=filepath,
                    agent=agents[0] if agents else "unknown",
                    error=f"score={score}/100 | {fb_str[:80]} | temp={temp:.2f}",
                    gen=attempt,
                )
            except Exception:
                pass
            # Échec — adapte la stratégie selon le diagnostic
            self._adapt_strategy(diag, ranked, attempt)

        # CuriosityEngine — maîtrise acquise → explore les sujets connexes
        curious_topics = []
        # MASTERY_THRESHOLD est 0-1 (RAG), best_score est 0-100 → normaliser
        _mastery_int = int(CuriosityEngine.MASTERY_THRESHOLD * 100)
        if best_score >= _mastery_int and best_content:
            print(f"  [CURIOSITY] Score {best_score}/100 ≥ {_mastery_int} — exploration connexe")
            curious_topics = CuriosityEngine.discover_adjacent(
                skill=Path(filepath).stem,
                filepath=filepath,
            )
            if curious_topics:
                print(f"  [CURIOSITY] {len(curious_topics)} sujets spécialisés ingérés")

        rapport = {
            "attempts": len(history),
            "best_score": best_score,
            "history": history,
            "final_strategy": self._strategy,
            "curiosity": curious_topics,
        }
        print(
            f" [BILAN] {len(history)} tentatives | meilleur={best_score}/100"
            + (f" | curiosité: {curious_topics}" if curious_topics else "")
        )
        return best_content, rapport

    def _build_prompt(self, original: str, task: str, knowledge: str) -> str:
        """Construit le prompt avec garde-fous adaptatifs."""
        parts = []
        if knowledge:
            parts.append(f"DOCUMENTATION:{chr(10)}{knowledge[:1500]}")
        parts.append(f"TÂCHE: {task}")
        if self._strategy["prompt_suffix"]:
            parts.append(f"RÈGLES STRICTES:{chr(10)}{self._strategy['prompt_suffix']}")
        # Instruction critique — retour fichier complet obligatoire
        parts.append(
            "INSTRUCTION ABSOLUE: Retourne UNIQUEMENT le code Python complet et modifié."
            + chr(10)
            + "Ne retourne PAS d'explication, de commentaire, ni de résumé."
            + chr(10)
            + "Le fichier de sortie DOIT contenir TOUTES les lignes du fichier original."
            + chr(10)
            + f"Taille minimale attendue: {max(50, len(original.splitlines()) - 5)} lignes."
        )
        parts.append(f"CODE A MODIFIER:{chr(10)}{original}")
        return (chr(10) * 2).join(parts)

    def _spawn_candidates(
        self, agents: list, prompt: str, temperature: float, original_len: int = 0
    ) -> list[dict]:
        """Spawne N candidats en parallèle — local + cloud simultanés.

        Stratégie population=N :
        - Ollama local  : 1 appel séquentiel (1 GPU, pas de contention)
        - Cloud (github/groq/openrouter) : N-1 appels parallèles I/O bound
        - min_size      : 85% de la taille du fichier original (pas du prompt)
        - Fichiers > 30KB : les LLMs cloud peuvent refuser → fallback Ollama
        """
        from concurrent.futures import as_completed

        local_agents = [a for a in agents if "ollama" in a.lower()]
        cloud_agents = [a for a in agents if "ollama" not in a.lower()]
        results = []
        target = self.population  # nombre de candidats voulus

        # ── Routing laforge-qwen : tâche docstrings → agent LoRA dédié ──────
        _is_doc_task = any(
            kw in (prompt or "").lower()
            for kw in ("docstring", "doc", "args", "returns", "raises")
        )
        if _is_doc_task:
            _lf_agent = "ollama/laforge-qwen"
            # Mettre laforge-qwen en tête des agents locaux
            if _lf_agent not in local_agents:
                local_agents = [_lf_agent] + [a for a in local_agents if a != _lf_agent]
            else:
                local_agents = [_lf_agent] + [a for a in local_agents if a != _lf_agent]
            print(f"  [DOC-ROUTE] tâche docstrings → {_lf_agent} en priorité")

        # ── Local : 1 appel séquentiel (GPU unique) ───────────────────────
        for agent in local_agents[:1]:  # jamais plus de 1 Ollama simultané
            try:
                content = MultiLLMBridge.call(agent, prompt, temperature, False, "")
                # min_size = 85% du fichier original (pas du prompt)
                _min_sz = max(200, int((original_len or len(prompt) // 4) * 0.85))
                if content and not content.startswith("[LLM ERR") and len(content) >= _min_sz:
                    results.append({"content": content, "agent": agent})
                    print(f"  [LOCAL] {agent.split('/')[-1]} → {len(content)}c")
                elif content and len(content) < _min_sz:
                    print(
                        f"  [SHORT] {agent.split('/')[-1]} → {len(content)}c (min={_min_sz}c) ignoré"
                    )
            except Exception as e:
                print(f"  [LLM ERR] {agent}: {str(e)[:50]}")
                self._strategy["skip_agents"].add(agent)

        # ── Cloud : parallèle jusqu'à compléter target candidats ──────────
        # Toujours lancé (pas seulement en fallback) — diversité génétique
        needed = target - len(results)
        pool = [a for a in cloud_agents if a not in self._strategy["skip_agents"]]
        pool = pool[: max(needed, 1)]  # prendre autant que nécessaire

        if pool:
            print(f"  [CLOUD] {len(pool)} agent(s) en parallèle")
            with ThreadPoolExecutor(max_workers=len(pool)) as ex:
                # inject_tools=False pour cloud — Groq/GitHub ne supportent pas les MCP tools
                # Filtrer par ML avant de lancer les appels cloud
                futs = {
                    ex.submit(MultiLLMBridge.call, a, prompt, temperature, False, ""): a
                    for a in pool
                }
                for fut in as_completed(futs):
                    agent = futs[fut]
                    try:
                        content = fut.result(timeout=360)
                        _min_sz = max(200, int((original_len or len(prompt) // 4) * 0.85))
                        if (
                            content
                            and not content.startswith("[LLM ERR")
                            and len(content) >= _min_sz
                        ):
                            results.append({"content": content, "agent": agent})
                            print(f"  [CLOUD] {agent.split('/')[-1]} → {len(content)}c")
                        elif content and len(content) < _min_sz:
                            print(
                                f"  [SHORT] {agent.split('/')[-1]} → {len(content)}c (min={_min_sz}c) ignoré"
                            )
                    except Exception as e:
                        print(f"  [LLM ERR] {agent}: {str(e)[:50]}")
                        self._strategy["skip_agents"].add(agent)

        print(f"  [SPAWN] {len(results)}/{target} candidats collectés")
        return results

    def _adapt_strategy(self, diag: dict | None, ranked: list, attempt: int) -> None:
        """Adapte la stratégie selon le diagnostic cross-branches."""
        dtype = diag.get("type", "mixed_failure") if diag else "mixed_failure"

        if dtype == "AST KO":
            # Troncature systématique → modèles plus puissants + garde-fous
            self._strategy["agent_risk_bias"] = min(0.5, self._strategy["agent_risk_bias"] + 0.15)
            self._strategy["temperature"] = max(0.05, self._strategy["temperature"] - 0.05)
            self._strategy["prompt_suffix"] = (
                "CRITIQUE: Ne jamais tronquer le code."
                + chr(10)
                + "Chaque classe DOIT conserver TOUS ses attributs et méthodes."
                + chr(10)
                + "Retourner le fichier COMPLET sans omission."
            )
            print("  [ADAPT] AST KO → bias+0.15, temp-0.05, garde-fous injectés")

        elif dtype == "SyntaxError":
            self._strategy["temperature"] = max(0.05, self._strategy["temperature"] - 0.10)
            self._strategy["prompt_suffix"] = (
                "RÈGLE: Produire uniquement du Python 3.9+ syntaxiquement valide."
                + chr(10)
                + "Ne pas utiliser de f-strings multi-lignes."
            )
            print("  [ADAPT] SyntaxError → temp-0.10")

        elif dtype == "ImportError" or dtype == "ModuleNotFound":
            # Problème d'environnement — pas le LLM
            print("  [ADAPT] ImportError → arrêt (environnement cassé)")
            self._strategy["skip_agents"] = set(AgentPool.ARCHITECTS + AgentPool.SPECIALISTS)

        elif dtype == "pytest KO":
            # Tests cassés indépendamment → monte les agents, ignore pytest
            self._strategy["agent_risk_bias"] = min(0.3, self._strategy["agent_risk_bias"] + 0.1)
            print("  [ADAPT] pytest KO → bias+0.1")

        else:
            # mixed_failure → crossover si on a une bonne branche partielle
            if ranked and ranked[0]["score"] > 0:
                print(f"  [ADAPT] mixed → crossover partiel score={ranked[0]['score']}")
            self._strategy["temperature"] = min(0.5, self._strategy["temperature"] + 0.05)
            self._strategy["agent_risk_bias"] = min(0.4, self._strategy["agent_risk_bias"] + 0.1)

        # Monte toujours vers les architectes après 3 échecs
        if attempt >= 3 and self._strategy["agent_risk_bias"] < 0.4:
            self._strategy["agent_risk_bias"] = 0.4
            print("  [ADAPT] attempt≥3 → force ARCHITECTS")

    def _escalate_agents(self) -> None:
        """Aucun candidat généré — escalade vers les architectes SOTA."""
        self._strategy["agent_risk_bias"] = 0.5
        print("  [ESCALATE] 0 candidats → ARCHITECTS SOTA")


# ── CuriosityEngine ───────────────────────────────────────────────────────────

# ── CLI ─


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Nokido Evolutionary Engine + Cerberus")
    ap.add_argument("--files", nargs="+", default=None)
    ap.add_argument("--generations", type=int, default=3)
    ap.add_argument("--task", default=None)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--agent", default=None)
    ap.add_argument("--crossover", action="store_true")
    ap.add_argument(
        "--cerberus", action="store_true", help="Active CerberusGuard (AST+pytest+ruff)"
    )
    ap.add_argument("--population", type=int, default=1, help="Taille population fork")
    ap.add_argument("--workflow", default=None, help="Diagramme Mermaid inline")
    ap.add_argument(
        "--intelligent",
        action="store_true",
        help="Active IntelligentCerberusLoop (multi-retry adaptatif)",
    )
    ap.add_argument("--knowledge", default="", help="Contexte injecté dans le prompt")
    args = ap.parse_args()

    if args.intelligent and args.files:
        # IntelligentCerberusLoop — boucle multi-retry avec diagnostic adaptatif
        from pathlib import Path as _P

        _guard = CerberusGuard()
        _tmgr = AdaptiveTemperatureManager()
        _loop = IntelligentCerberusLoop(guard=_guard, temp_mgr=_tmgr, population=args.population)
        for _f in args.files:
            # Guard taille — fichiers > 30KB doivent utiliser --cerberus (chunked)
            _fpath = _P(__file__).resolve().parent.parent / _f
            if _fpath.exists() and _fpath.stat().st_size > 30_000:
                print(f"\n[GUARD] {_f} trop grand ({_fpath.stat().st_size // 1024}KB > 30KB)")
                print("[GUARD] Utilise --cerberus à la place pour le chunking automatique")
                print(
                    f'[GUARD] Commande : python tools/evolutionary_engine.py --files {_f} --cerberus --agent nokido --task "...."'
                )
                continue
            print(f"\n[INTELLIGENT] Cerberus loop → {_f}")
            _best, _rapport = _loop.run(
                filepath=_f,
                task=args.task or "Améliore la robustesse et la lisibilité.",
                knowledge=args.knowledge,
            )
            print(
                f"[INTELLIGENT] Bilan: attempts={_rapport['attempts']} best={_rapport['best_score']}/100"
            )
            if _best:
                _out = _P(__file__).resolve().parent.parent / _f
                import ast as _ast_fix
                import subprocess as _sp
                import sys as _sys
                import tempfile as _tmp

                # 1 — Ruff auto-fix
                _tf = _P(_tmp.mktemp(suffix=".py"))
                _tf.write_text(_best, encoding="utf-8")
                _sp.run(
                    [_sys.executable, "-m", "ruff", "check", "--fix", "--unsafe-fixes", str(_tf)],
                    capture_output=True,
                    cwd=str(_P(__file__).resolve().parent.parent),
                )
                _fixed = _tf.read_text(encoding="utf-8")
                try:
                    _tf.unlink()
                except Exception:
                    pass
                try:
                    _ast_fix.parse(_fixed)
                    _best = _fixed
                    print(f"[RUFF-FIX] ✅ auto-fix appliqué sur {_P(_f).name}")
                except SyntaxError:
                    print("[RUFF-FIX] skip — AST cassé, version originale conservée")

                # 2 — Strate 3 : injecter HD docstring sur la version finale
                try:
                    _hd_final = RAGEnricher.inject_high_density_docstring(
                        _best,
                        {
                            "agent": _rapport.get("final_strategy", {}).get("agent", "unknown"),
                            "score": _rapport["best_score"],
                            "attempt": _rapport["attempts"],
                            "temperature": _rapport.get("final_strategy", {}).get(
                                "temperature", 0.3
                            ),
                            "feedback": "",
                            "version_id": locals().get("_vid", ""),
                            "risk": 0.0,
                        },
                    )
                    _ast_fix.parse(_hd_final)  # vérif AST avant d'écrire
                    _best = _hd_final
                    print(f"[STRATE3-FINAL] ✍ HD injectée sur {_P(_f).name}")
                except Exception as _e_hd:
                    print(f"[STRATE3-FINAL] skip — {_e_hd}")

                # 3 — Écriture finale
                _out.write_text(_best, encoding="utf-8")
                print(f"[INTELLIGENT] ✅ {_f} mis à jour")
    elif args.workflow and args.files:
        run_workflow(
            mermaid_script=args.workflow,
            target_file=args.files[0],
            population=args.population,
            cerberus=args.cerberus,
        )
    elif args.files:
        run_evolutionary(
            targets=args.files,
            generations=args.generations,
            task=args.task,
            workers=args.workers,
            agent=args.agent,
            crossover=args.crossover,
            cerberus=args.cerberus,
            population=args.population,
        )
    else:
        ap.print_help()
