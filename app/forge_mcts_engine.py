#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_mcts_engine.py — Moteur de réflexion délibérée (System 2 / LLM-MCTS).

Évolution v2 : Consensus Darwinien.
Intègre une cour d'arbitrage multi-modèles (Gemini, Claude, Local) pour évaluer
la fitness des transients et converger vers une solution validée par consensus.
"""

from __future__ import annotations

__FORGE_COLOR__ = "cognition/reasoning : deliberation System 2, LLM-MCTS, consensus darwinien"  # organe declare le 2026-09-06 (audit de raccordement)

import math
import time
import random
import logging
import asyncio
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass, field

# Intégration organique
try:
    from app.forge_lane_admission import acquire, release
    from app.forge_llm_router import route_query
    from app.forge_swarm_bus import publish
    from app.forge_docker_transient import TransientEnv
except ImportError:
    def acquire(*args, **kwargs): return True
    def release(*args, **kwargs): pass
    async def route_query(msg, provider="groq", **kwargs): return {"text": "print('dummy')"}
    def publish(*args, **kwargs): pass
    class TransientEnv:
        def __init__(self, *args, **kwargs): pass
        def boot(self): return True
        def put_file(self, *args, **kwargs): pass
        def fast_exec(self, *args, **kwargs): return {"ok": True, "timed_out": False, "stdout": "", "stderr": ""}
        def terminate(self, *args, **kwargs): pass

@dataclass
class ThoughtNode:
    """Un nœud de l'arbre de réflexion (un 'transient')."""
    prompt: str
    parent: Optional[ThoughtNode] = None
    children: List[ThoughtNode] = field(default_factory=list)
    visits: int = 0
    value: float = 0.0
    depth: int = 0
    model_origin: str = "unknown"

    @property
    def score(self) -> float:
        return self.value / self.visits if self.visits > 0 else 0.0

class ConsensusEvaluator:
    """Gère l'arbitrage entre modèles forts (Claude, Gemini, Local Oracle)."""
    
    def __init__(self, evaluators: List[Dict[str, Any]]):
        # Format: {"provider": "claude", "weight": 1.0, "role": "code_expert"}
        self.evaluators = evaluators

    async def get_consensus_score(self, thought: str) -> float:
        """Calcule un score de fitness basé sur le consensus multi-modèles."""
        tasks = []
        for ev in self.evaluators:
            prompt = f"Évalue la pertinence de cette réflexion technique (Note de 0 à 10) :\n\n{thought}"
            tasks.append(route_query(prompt, provider=ev["provider"]))
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        scores = []
        for i, res in enumerate(responses):
            if isinstance(res, dict) and "text" in res:
                try:
                    # Extraction naïve du score numérique (à affiner avec regex)
                    score_str = "".join(filter(str.isdigit, res["text"][:10]))
                    val = float(score_str) if score_str else 5.0
                    scores.append(val * self.evaluators[i]["weight"])
                except Exception:
                    scores.append(5.0)
        
        if not scores:
            return 0.0
        
        consensus = sum(scores) / len(scores)
        publish(kind="CONSENSUS_REACHED", data={"thought": thought[:100], "score": consensus})
        return consensus


class TransientCodeEvaluator:
    """Évaluateur darwinien empirique (System 2 d'Exécution).
    Utilise le Transient Daemon (Docker) pour scorer la fitness d'un snippet
    de code. Si ça compile/passe les tests = note maximale, sinon pénalité."""
    
    def __init__(self, transient_env):
        self.env = transient_env
        self.booted = False

    async def get_consensus_score(self, thought: str) -> float:
        if not self.booted:
            if not self.env.boot():
                return 0.0
            self.booted = True
            
        # Extrait le code Python des blocs markdown si présent
        code = thought
        if "```python" in thought:
            code = thought.split("```python")[1].split("```")[0].strip()
            
        # Injecte le mutant dans le conteneur
        self.env.put_file(code, "mutant.py")
        
        # Test 1 : Compile ? (Syntaxe)
        res_syntax = self.env.fast_exec("python -m py_compile mutant.py", timeout_s=3)
        if not res_syntax["ok"]:
            publish(kind="MCTS_EVAL_FAILED", data={"reason": "SyntaxError", "output": res_syntax["stderr"]})
            return 0.0  # Mort subite darwinienne
            
        # Test 2 : Exécution/Tests
        # Dans un vrai workflow, on lancerait `pytest`. Ici on l'exécute juste.
        res_exec = self.env.fast_exec("python mutant.py", timeout_s=5)
        if res_exec["timed_out"]:
            publish(kind="MCTS_EVAL_FAILED", data={"reason": "Timeout (Infinite Loop)"})
            return -5.0  # Pénalité sévère pour les fork-bombs/boucles inf
            
        if not res_exec["ok"]:
            publish(kind="MCTS_EVAL_FAILED", data={"reason": "RuntimeError", "output": res_exec["stderr"]})
            return 2.0  # Récompense de consolation (ça compile, mais plante à l'exécution)
            
        publish(kind="MCTS_EVAL_SUCCESS", data={"output": res_exec["stdout"]})
        return 10.0  # Survie du mutant (fitness maximale)


class MCTSEngine:
    def __init__(self, exploration_weight: float = 1.414, max_iterations: int = 10):
        self.c = exploration_weight
        self.max_iterations = max_iterations
        self.root: Optional[ThoughtNode] = None

    def uct_score(self, node: ThoughtNode, parent_visits: int) -> float:
        if node.visits == 0:
            return float('inf')
        exploitation = node.value / node.visits
        exploration = self.c * math.sqrt(math.log(parent_visits) / node.visits)
        return exploitation + exploration

    def select(self, node: ThoughtNode) -> ThoughtNode:
        while node.children:
            node = max(node.children, key=lambda n: self.uct_score(n, node.visits))
        return node

    async def expand(self, node: ThoughtNode) -> List[ThoughtNode]:
        """Expansion multi-modèles : on demande à Gemini et Claude de proposer des alternatives."""
        if not acquire("gpu_throughput", holder="mcts_expansion", heavy=True):
            return []

        try:
            # On demande des branches à 2 modèles différents pour la diversité darwinienne
            providers = ["gemini_cli", "groq"] # Exemple: Gemini Cloud + Llama Local
            tasks = []
            for p in providers:
                p_msg = f"Propose une étape de raisonnement suivante pour : {node.prompt}"
                tasks.append(route_query(p_msg, provider=p))
            
            results = await asyncio.gather(*tasks)
            
            for i, res in enumerate(results):
                if isinstance(res, dict) and "text" in res:
                    child = ThoughtNode(prompt=res["text"], parent=node, 
                                        depth=node.depth + 1, model_origin=providers[i])
                    node.children.append(child)
            return node.children
        finally:
            release("gpu_throughput", "mcts_expansion")

    def backpropagate(self, node: Optional[ThoughtNode], reward: float):
        while node:
            node.visits += 1
            node.value += reward
            node = node.parent

    async def think(self, initial_prompt: str, consensus_evaluator: ConsensusEvaluator):
        self.root = ThoughtNode(prompt=initial_prompt)
        
        for i in range(self.max_iterations):
            leaf = self.select(self.root)
            
            if leaf.visits > 0 or leaf == self.root:
                children = await self.expand(leaf)
                if children:
                    leaf = random.choice(children)
            
            reward = await consensus_evaluator.get_consensus_score(leaf.prompt)
            self.backpropagate(leaf, reward)
            
        # Le consensus final est le nœud le plus visité et le mieux noté
        best_thought = max(self.root.children, key=lambda n: n.score)
        return best_thought

if __name__ == "__main__":
    async def run_test():
        print("=== Test MCTS + Transient Code Evaluator (Nokido V16) ===")
        env = TransientEnv("transient-mcts-test", "vol_mcts_test")
        code_evaluator = TransientCodeEvaluator(env)
        
        # Surcharge de la méthode get_consensus_score pour les tests
        # (au lieu d'un simple `get_consensus_score` sur du texte, on utilise l'évaluateur Transient)
        class HybridEvaluator:
            def __init__(self, code_evaluator):
                self.code_evaluator = code_evaluator
            
            async def get_consensus_score(self, thought: str) -> float:
                return await self.code_evaluator.get_consensus_score(thought)
        
        engine = MCTSEngine(max_iterations=2)
        print("Lancement de la réflexion délibérée (Évaluation empirique par Docker)...")
        try:
            # On teste avec un prompt de code pour que l'expansion génère du Python
            best_node = await engine.think("Écris une fonction Python 'def add(a, b): return a+b'", HybridEvaluator(code_evaluator))
            print(f"\n--- CONSENSUS EMPIRIQUE FINAL ---")
            print(f"Modèle d'origine : {best_node.model_origin}")
            print(f"Score : {best_node.score:.2f} / 10.0 (basé sur l'exécution du code)")
            print(f"Contenu (Mutant Survivant) :\n{best_node.prompt[:200]}...")
        finally:
            env.terminate(force=True)

    asyncio.run(run_test())
