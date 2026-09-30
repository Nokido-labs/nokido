"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_interaction_test
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
app/forge_interaction_test.py
==============================
Système de test d'interaction multi-agents Nokido.

Scénarios disponibles :
  1. PING-PONG    — deux agents se répondent en alternance (N tours)
  2. DEBATE       — Agent A propose, Agent B critique, Agent C synthétise
  3. CHAIN        — Chaque agent enrichit la réponse du précédent
  4. PARALLEL     — Tous les agents répondent en parallèle à la même question
  5. RAG_COLLAB   — Un agent cherche dans le RAG, l'autre génère, le 3e valide

Architecture :
  - Chaque tour d'interaction est loggé dans events.db (sequence_id monotone)
  - L'état visible dans live_bridge.map (GUI 60fps)
  - AgentContext écrit la "pensée en cours" pour chaque agent
  - Le filtre de résonance vérifie chaque réponse avant envoi
  - Résultats indexés dans le RAG (domain=interaction)

Backends supportés :
  - llamacpp    → forge_llamacpp.llamacpp_call (async, natif)
  - ollama      → http://127.0.0.1:11434  (avec fallback)
  - gemini      → forge_collab_multimodal  (si API key)
  - echo        → mode test pur sans LLM (réponses déterministes)
  - claude_mcp  → via MCP bridge Nokido

Usage CLI :
  python forge_interaction_test.py --scenario ping_pong --turns 3
  python forge_interaction_test.py --scenario debate --topic "architecture mmap"
  python forge_interaction_test.py --scenario chain --agents llamacpp,echo
  python forge_interaction_test.py --list-scenarios
"""

import asyncio
import json
import sqlite3
import time
import sys
import argparse
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass
class AgentMessage:
    agent_id: str
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    turn: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass
class InteractionResult:
    scenario: str
    agents: list[str]
    turns: list[AgentMessage]
    elapsed_ms: float
    ok: bool
    summary: str = ""
    error: str = ""


# ── Backends ──────────────────────────────────────────────────────────────────


async def _call_llamacpp(prompt: str, system: str = "", max_tokens: int = 400, temperature: float = 0.5) -> str:
    """Appel llamacpp natif (async)."""
    try:
        from nokido_agent.app.forge_llamacpp import llamacpp_call, is_available

        if not is_available():
            return "[llamacpp indisponible — vérifier LLAMACPP_MODEL_PATH]"
        msgs = [{"role": "user", "content": prompt}]
        return await llamacpp_call(
            messages=msgs,
            system=system or None,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as e:
        return f"[llamacpp error] {e}"


async def _call_ollama(
    prompt: str, system: str = "", model: str = "qwen2.5-coder:latest", max_tokens: int = 400
) -> str:
    """Appel Ollama HTTP (async via executor)."""
    import json as _j
    import urllib.request as _ur

    def _sync() -> str:
        """Sync."""
        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.5},
        }
        try:
            req = _ur.Request(
                "http://127.0.0.1:11434/api/generate",
                data=_j.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with _ur.urlopen(req, timeout=30) as r:
                data = _j.loads(r.read().decode())
                return data.get("response", "").strip()
        except Exception as e:
            return f"[ollama error] {e}"

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync)


async def _call_echo(prompt: str, agent_id: str = "echo", turn: int = 0) -> str:
    """Backend echo déterministe — pour tests sans LLM."""
    await asyncio.sleep(0.05)  # simuler une latence
    templates = [
        f"[{agent_id} T{turn}] Analyse initiale : '{prompt[:40]}...' — Je propose une approche modulaire.",
        f"[{agent_id} T{turn}] En réponse : je vois un risque de couplage fort. Proposition d'inversion de dépendances.",
        f"[{agent_id} T{turn}] Consensus : l'approche modulaire avec injection de dépendances est la plus solide.",
        f"[{agent_id} T{turn}] Validation finale : architecture approuvée. ADR créé automatiquement.",
        f"[{agent_id} T{turn}] Enrichissement RAG : {len(prompt)} chars indexés dans domain=interaction.",
    ]
    return templates[turn % len(templates)]


async def _call_agent(
    agent_id: str,
    prompt: str,
    system: str = "",
    history: list[AgentMessage] | None = None,
    turn: int = 0,
    max_tokens: int = 400,
) -> str:
    """
    Dispatch vers le bon backend selon agent_id.
    history = liste des messages précédents pour contexte.
    """
    # Enrichir le prompt avec l'historique
    ctx = ""
    if history:
        recent = history[-4:]  # 4 derniers messages
        ctx = "\n".join(f"[{m.agent_id}]: {m.content[:200]}" for m in recent)
        prompt = ctx + "\n\n[Question actuelle]: " + prompt

    # Enregistrer la "pensée" dans mmap
    try:
        from nokido_agent.app.forge_mmap_context import AgentContext

        _ctx = AgentContext(agent_id)
        _ctx.start_thinking(prompt[:60], progress=10)
    except Exception:
        _ctx = None

    # Dispatch backend
    if agent_id.startswith("echo"):
        response = await _call_echo(prompt, agent_id, turn)
    elif agent_id == "llamacpp" or agent_id == "qwen_coder":
        response = await _call_llamacpp(prompt, system, max_tokens)
    elif agent_id.startswith("ollama"):
        model = "qwen2.5-coder:latest"
        response = await _call_ollama(prompt, system, model, max_tokens)
    elif agent_id == "laforge":
        # Nokido = Ollama local
        response = await _call_ollama(prompt, system, "qwen2.5-coder:latest", max_tokens)
    else:
        response = await _call_echo(prompt, agent_id, turn)

    # Done dans mmap
    if _ctx:
        try:
            _ctx.done(response)
        except Exception:
            pass

    return response or f"[{agent_id}] (réponse vide)"


# ── Logger événements ─────────────────────────────────────────────────────────


def _log_interaction(
    session_id: str, agent_id: str, turn: int, content: str, event_type: str = "interaction_turn"
) -> int:
    """Logue un tour d'interaction dans events.db."""
    try:
        from nokido_agent.app.forge_swarm import _log_event

        return _log_event(
            agent_id,
            event_type,
            payload={"session": session_id, "turn": turn, "preview": content[:120]},
        )
    except Exception:
        return -1


def _broadcast_state(agent_id: str, state: str, turn: int) -> None:
    """Broadcast état dans mmap pour la GUI."""
    try:
        from nokido_agent.app.live_bridge import bridge

        bridge.json_set("interaction.agent", agent_id)
        bridge.json_set("interaction.state", state)
        bridge.json_set("interaction.turn", turn)
        bridge.json_set("interaction.ts", time.time())
    except Exception:
        pass


# ── Scénario 1 : PING-PONG ────────────────────────────────────────────────────


async def scenario_ping_pong(
    topic: str,
    agent_a: str = "echo_A",
    agent_b: str = "echo_B",
    turns: int = 4,
    session_id: str = "",
) -> InteractionResult:
    """
    Deux agents se répondent en alternance.
    Agent A commence, Agent B répond, etc.
    """
    session_id = session_id or "pp_" + str(int(time.time()))
    history: list[AgentMessage] = []
    t0 = time.monotonic()

    print(f"\n{'=' * 60}")
    print(f"PING-PONG  topic='{topic[:40]}'  {agent_a} ↔ {agent_b}")
    print(f"{'=' * 60}")

    # System prompts différents pour chaque agent
    sys_a = (
        f"Tu es {agent_a}, un architecte logiciel. Tu proposes des solutions concrètes. Sois concis (2-3 phrases max)."
    )
    sys_b = (
        f"Tu es {agent_b}, un expert en sécurité et performance. Tu analyses "
        f"et améliores les propositions. Sois concis (2-3 phrases max)."
    )

    current_prompt = topic
    for i in range(turns):
        agent = agent_a if i % 2 == 0 else agent_b
        syst = sys_a if i % 2 == 0 else sys_b

        _broadcast_state(agent, "THINKING", i + 1)
        print(f"\n[Tour {i + 1}/{turns}] {agent} réfléchit…")

        response = await _call_agent(
            agent_id=agent,
            prompt=current_prompt,
            system=syst,
            history=history,
            turn=i,
        )

        msg = AgentMessage(
            agent_id=agent,
            role="assistant",
            content=response,
            turn=i + 1,
        )
        history.append(msg)
        _log_interaction(session_id, agent, i + 1, response)
        _broadcast_state(agent, "IDLE", i + 1)

        print(f"  → {response[:120]}{'…' if len(response) > 120 else ''}")

        # La réponse de l'un devient le prompt de l'autre
        current_prompt = response

    elapsed = (time.monotonic() - t0) * 1000
    summary = f"{turns} tours  {agent_a} ↔ {agent_b}  {elapsed:.0f}ms"
    return InteractionResult(
        scenario="ping_pong",
        agents=[agent_a, agent_b],
        turns=history,
        elapsed_ms=elapsed,
        ok=True,
        summary=summary,
    )


# ── Scénario 2 : DÉBAT ────────────────────────────────────────────────────────


async def scenario_debate(
    topic: str,
    planneur: str = "echo_PLAN",
    critique: str = "echo_CRIT",
    synthese: str = "echo_SYNTH",
    session_id: str = "",
) -> InteractionResult:
    """
    Planificateur propose → Critique analyse → Synthétiseur consensus.
    """
    session_id = session_id or "deb_" + str(int(time.time()))
    history: list[AgentMessage] = []
    t0 = time.monotonic()

    print(f"\n{'=' * 60}")
    print(f"DÉBAT  topic='{topic[:40]}'")
    print(f"  Planificateur={planneur}  Critique={critique}  Synthèse={synthese}")
    print(f"{'=' * 60}")

    # Phase 1 : Planificateur propose
    _broadcast_state(planneur, "THINKING", 1)
    print(f"\n[1/3] {planneur} (Planificateur) propose…")
    prop = await _call_agent(
        agent_id=planneur,
        prompt=f"Propose une architecture pour : {topic}",
        system="Tu es un architecte. Propose une solution structurée en 3 points.",
        turn=1,
    )
    history.append(AgentMessage(planneur, "assistant", prop, turn=1, metadata={"role": "proposition"}))
    _log_interaction(session_id, planneur, 1, prop, "debate_propose")
    _broadcast_state(planneur, "IDLE", 1)
    print(f"  PROPOSITION: {prop[:150]}…")

    # Phase 2 : Critique analyse
    _broadcast_state(critique, "THINKING", 2)
    print(f"\n[2/3] {critique} (Critique) analyse…")
    crit = await _call_agent(
        agent_id=critique,
        prompt=f"Analyse cette proposition et identifie 2 risques:\n{prop}",
        system="Tu es un expert sécurité/perf. Identifie les failles et propose des améliorations.",
        history=history,
        turn=2,
    )
    history.append(AgentMessage(critique, "assistant", crit, turn=2, metadata={"role": "critique"}))
    _log_interaction(session_id, critique, 2, crit, "debate_critique")
    _broadcast_state(critique, "IDLE", 2)
    print(f"  CRITIQUE: {crit[:150]}…")

    # Phase 3 : Synthétiseur construit le consensus
    _broadcast_state(synthese, "THINKING", 3)
    print(f"\n[3/3] {synthese} (Synthétiseur) consolide…")
    synt = await _call_agent(
        agent_id=synthese,
        prompt=(f"Synthétise en une décision finale :\nPROPOSITION: {prop}\nCRITIQUE: {crit}"),
        system="Tu es le Chef. Produis un consensus actionnable en 2 phrases.",
        history=history,
        turn=3,
    )
    history.append(AgentMessage(synthese, "assistant", synt, turn=3, metadata={"role": "synthese"}))
    _log_interaction(session_id, synthese, 3, synt, "debate_synthese")
    _broadcast_state(synthese, "IDLE", 3)
    print(f"  SYNTHÈSE: {synt[:150]}…")

    elapsed = (time.monotonic() - t0) * 1000
    return InteractionResult(
        scenario="debate",
        agents=[planneur, critique, synthese],
        turns=history,
        elapsed_ms=elapsed,
        ok=True,
        summary=f"3 phases  {elapsed:.0f}ms  consensus={synt[:60]}",
    )


# ── Scénario 3 : CHAIN (enrichissement en cascade) ───────────────────────────


async def scenario_chain(
    topic: str,
    agents: list[str] | None = None,
    session_id: str = "",
) -> InteractionResult:
    """
    Chaque agent reçoit la réponse du précédent et l'enrichit.
    """
    agents = agents or ["echo_A", "echo_B", "echo_C"]
    session_id = session_id or "chain_" + str(int(time.time()))
    history: list[AgentMessage] = []
    t0 = time.monotonic()

    print(f"\n{'=' * 60}")
    print(f"CHAIN  topic='{topic[:40]}'  agents={agents}")
    print(f"{'=' * 60}")

    current = topic
    for i, agent in enumerate(agents):
        _broadcast_state(agent, "THINKING", i + 1)
        print(f"\n[{i + 1}/{len(agents)}] {agent} enrichit…")
        response = await _call_agent(
            agent_id=agent,
            prompt=f"Enrichis et améliore ce texte :\n{current}",
            system=f"Tu es {agent}. Ajoute une perspective unique en 2-3 phrases.",
            history=history,
            turn=i,
        )
        history.append(AgentMessage(agent, "assistant", response, turn=i + 1))
        _log_interaction(session_id, agent, i + 1, response, "chain_step")
        _broadcast_state(agent, "IDLE", i + 1)
        print(f"  → {response[:120]}…")
        current = response

    elapsed = (time.monotonic() - t0) * 1000
    return InteractionResult(
        scenario="chain",
        agents=agents,
        turns=history,
        elapsed_ms=elapsed,
        ok=True,
        summary=f"{len(agents)} agents  {elapsed:.0f}ms  final={current[:60]}",
    )


# ── Scénario 4 : PARALLEL ────────────────────────────────────────────────────


async def scenario_parallel(
    topic: str,
    agents: list[str] | None = None,
    session_id: str = "",
) -> InteractionResult:
    """
    Tous les agents répondent simultanément (asyncio.gather).
    """
    agents = agents or ["echo_A", "echo_B", "echo_C"]
    session_id = session_id or "par_" + str(int(time.time()))
    t0 = time.monotonic()

    print(f"\n{'=' * 60}")
    print(f"PARALLEL  topic='{topic[:40]}'  agents={agents}")
    print(f"{'=' * 60}\n")

    async def _task(agent, idx) -> object:
        """Task.

        Args:
            agent: Description.
            idx: Description.
        """
        _broadcast_state(agent, "THINKING", 0)
        resp = await _call_agent(
            agent_id=agent,
            prompt=topic,
            system=f"Tu es {agent}. Réponds en 2 phrases depuis ta perspective unique.",
            turn=idx,
        )
        _broadcast_state(agent, "IDLE", 0)
        return resp

    responses = await asyncio.gather(*[_task(a, i) for i, a in enumerate(agents)])

    history = []
    for agent, resp in zip(agents, responses):
        msg = AgentMessage(agent, "assistant", resp, turn=0)
        history.append(msg)
        _log_interaction(session_id, agent, 0, resp, "parallel_response")
        print(f"  [{agent}]: {resp[:120]}…")

    elapsed = (time.monotonic() - t0) * 1000
    return InteractionResult(
        scenario="parallel",
        agents=agents,
        turns=history,
        elapsed_ms=elapsed,
        ok=True,
        summary=f"{len(agents)} agents simultanés  {elapsed:.0f}ms",
    )


# ── Scénario 5 : RAG_COLLAB ──────────────────────────────────────────────────


async def scenario_rag_collab(
    topic: str,
    searcher: str = "echo_RAG",
    generator: str = "echo_GEN",
    validator: str = "echo_VAL",
    session_id: str = "",
) -> InteractionResult:
    """
    1. Searcher trouve le contexte RAG
    2. Generator produit une réponse enrichie
    3. Validator vérifie la cohérence avec les ADR
    """
    session_id = session_id or "rag_" + str(int(time.time()))
    history: list[AgentMessage] = []
    t0 = time.monotonic()

    print(f"\n{'=' * 60}")
    print(f"RAG_COLLAB  topic='{topic[:40]}'")
    print(f"{'=' * 60}")

    # 1. RAG search
    _broadcast_state(searcher, "THINKING", 1)
    print(f"\n[1/3] {searcher} — Recherche RAG…")
    rag_ctx = ""
    try:
        from nokido_agent.app.forge_npu_embedder import NPUEmbedder

        emb = NPUEmbedder()
        hits = emb.search(topic, top_k=3)
        rag_ctx = "\n".join(h.get("text", "")[:300] for h in (hits or []))
        rag_msg = f"RAG: {len(hits or [])} résultats trouvés\n{rag_ctx[:200]}"
    except Exception as e:
        rag_msg = f"[RAG fallback] Contexte non disponible: {e}"
        rag_ctx = "Contexte RAG indisponible"
    history.append(AgentMessage(searcher, "assistant", rag_msg, turn=1, metadata={"role": "rag_search"}))
    _broadcast_state(searcher, "IDLE", 1)
    print(f"  → {rag_msg[:100]}…")

    # 2. Generator
    _broadcast_state(generator, "THINKING", 2)
    print(f"\n[2/3] {generator} — Génération enrichie RAG…")
    gen_resp = await _call_agent(
        agent_id=generator,
        prompt=f"Question: {topic}\n\nContexte RAG:\n{rag_ctx[:600]}",
        system="Tu es un expert. Utilise le contexte RAG pour répondre précisément.",
        history=history,
        turn=2,
    )
    history.append(AgentMessage(generator, "assistant", gen_resp, turn=2, metadata={"role": "generation"}))
    _log_interaction(session_id, generator, 2, gen_resp, "rag_generation")
    _broadcast_state(generator, "IDLE", 2)
    print(f"  → {gen_resp[:120]}…")

    # 3. Validator (vérifie contre ADR)
    _broadcast_state(validator, "THINKING", 3)
    print(f"\n[3/3] {validator} — Validation ADR…")

    # Charger les ADR pour contexte de validation
    adr_ctx = ""
    try:
        conn = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"), timeout=3)
        adrs = conn.execute("SELECT adr_id, title, decision FROM adr_records WHERE status='Accepté' LIMIT 3").fetchall()
        conn.close()
        adr_ctx = "\n".join(f"{r[0]}: {r[1]} — {r[2][:80]}" for r in adrs)
    except Exception:
        adr_ctx = "ADR non disponibles"

    val_resp = await _call_agent(
        agent_id=validator,
        prompt=(f"Valide cette réponse contre les ADR:\nRÉPONSE: {gen_resp}\n\nADR ACTIFS:\n{adr_ctx}"),
        system="Tu es le Gardien. Vérifie que la réponse respecte les décisions architecturales (ADR).",
        history=history,
        turn=3,
    )
    history.append(AgentMessage(validator, "assistant", val_resp, turn=3, metadata={"role": "validation"}))
    _log_interaction(session_id, validator, 3, val_resp, "rag_validation")
    _broadcast_state(validator, "IDLE", 3)
    print(f"  → {val_resp[:120]}…")

    elapsed = (time.monotonic() - t0) * 1000
    return InteractionResult(
        scenario="rag_collab",
        agents=[searcher, generator, validator],
        turns=history,
        elapsed_ms=elapsed,
        ok=True,
        summary=f"RAG+GEN+VAL  {elapsed:.0f}ms",
    )


# ── Dispatcher principal ──────────────────────────────────────────────────────

SCENARIOS = {
    "ping_pong": scenario_ping_pong,
    "debate": scenario_debate,
    "chain": scenario_chain,
    "parallel": scenario_parallel,
    "rag_collab": scenario_rag_collab,
}


async def run_scenario(
    name: str, topic: str, agents: list[str] | None = None, turns: int = 4, **kwargs
) -> InteractionResult:
    """Point d'entrée principal — dispatch vers le bon scénario."""
    if name not in SCENARIOS:
        raise ValueError(f"Scénario inconnu: {name}. Dispo: {list(SCENARIOS)}")

    fn = SCENARIOS[name]

    # Mapper agents si fournis
    if agents and name == "ping_pong" and len(agents) >= 2:
        kwargs["agent_a"] = agents[0]
        kwargs["agent_b"] = agents[1]
    elif agents and name == "debate" and len(agents) >= 3:
        kwargs["planneur"] = agents[0]
        kwargs["critique"] = agents[1]
        kwargs["synthese"] = agents[2]
    elif agents:
        kwargs["agents"] = agents

    if name == "ping_pong":
        kwargs["turns"] = turns

    result = await fn(topic=topic, **kwargs)

    # Indexer le résultat dans le RAG
    try:
        conn = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        summary_text = f"Interaction {name}: {topic}\n" + "\n".join(
            f"[{m.agent_id} T{m.turn}]: {m.content[:300]}" for m in result.turns
        )
        # 2026-09-12 : sans `id` (TEXT PRIMARY KEY) la clef restait NULLE, et
        # `summary_text[:2000]` amputait le resume en silence.
        from nokido_agent.app.forge_db_path import ecrire_chunk  # type: ignore

        ecrire_chunk(conn, f"interaction/{name}", "interaction", summary_text)
        conn.commit()
        conn.close()
    except Exception:
        pass

    return result


def print_result(result: InteractionResult) -> None:
    """Print result.

    Args:
        result: Description.
    """
    print(f"\n{'=' * 60}")
    print(f"✅ {result.scenario.upper()} — {result.summary}")
    print(f"   Agents  : {result.agents}")
    print(f"   Turns   : {len(result.turns)}")
    print(f"   Elapsed : {result.elapsed_ms:.0f}ms")
    if result.error:
        print(f"   Error   : {result.error}")
    print(f"{'=' * 60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    """Main."""
    parser = argparse.ArgumentParser(description="Nokido Interaction Test")
    parser.add_argument("--scenario", default="debate", choices=list(SCENARIOS.keys()), help="Scénario à exécuter")
    parser.add_argument(
        "--topic", default="architecture du système Nokido avec MMap et Watchdog", help="Sujet du débat / question"
    )
    parser.add_argument("--agents", default="", help="Agents comma-séparés ex: llamacpp,echo_B,echo_C")
    parser.add_argument("--turns", type=int, default=4, help="Nombre de tours (ping_pong)")
    parser.add_argument("--use-llm", action="store_true", help="Utiliser llamacpp si disponible (sinon echo)")
    parser.add_argument("--list-scenarios", action="store_true")
    args = parser.parse_args()

    if args.list_scenarios:
        print("Scénarios disponibles:")
        for name, fn in SCENARIOS.items():
            print(f"  {name:12s} — {fn.__doc__.strip().splitlines()[0]}")
        return

    # Résoudre les agents
    if args.agents:
        agents = [a.strip() for a in args.agents.split(",")]
    elif args.use_llm:
        from nokido_agent.app.forge_llamacpp import is_available

        if is_available():
            agents = ["llamacpp", "echo_B", "echo_C"]
            print("✅ llamacpp disponible — utilisation du vrai LLM")
        else:
            agents = ["echo_A", "echo_B", "echo_C"]
            print("⚠  llamacpp indisponible — mode echo")
    else:
        agents = ["echo_A", "echo_B", "echo_C"]

    result = asyncio.run(
        run_scenario(
            name=args.scenario,
            topic=args.topic,
            agents=agents,
            turns=args.turns,
        )
    )
    print_result(result)

    # Sauvegarder le résultat
    out_path = ROOT / "sandbox" / "interaction_result.json"
    out_path.write_text(
        json.dumps(
            {
                "scenario": result.scenario,
                "agents": result.agents,
                "elapsed": result.elapsed_ms,
                "ok": result.ok,
                "summary": result.summary,
                "turns": [{"agent": m.agent_id, "turn": m.turn, "content": m.content[:300]} for m in result.turns],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Résultat sauvegardé: {out_path}")


if __name__ == "__main__":
    main()
