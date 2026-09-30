"""forge_handoff_compress.py — context compression entre agents.

Wang multi-agent survey + Anthropic cookbooks pattern. Quand chain longue,
chaque handoff inter-agent doit compress le context precedent en TLDR
(preserve key facts + decisions) sans exploser le context window.

Workflow :
  1. Handoff source -> target avec full conversation history
  2. compress_context_for_handoff(history, target_persona) via Cerebras
  3. Target recoit TLDR + last 2 turns full + transferred state vars

Format TLDR :
    {
      "summary": "1-3 sentences",
      "key_facts": ["fact1", "fact2", ...],
      "decisions": ["decision1", ...],
      "open_questions": ["q1", ...],
      "context_state": {...},  # named variables transferred
      "estimated_tokens_saved": int
    }

API :
    compress_for_handoff(messages, target_agent, target_persona)
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("handoff_compress")

CEREBRAS_URL = "https://api.cerebras.ai/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


COMPRESS_PROMPT = """You are compressing a multi-agent conversation history before handoff.
The next agent is: {target_agent} (role: {target_persona})

History to compress:
{history}

Compress into JSON output (strict format):
{{
  "summary": "1-3 sentences of what happened",
  "key_facts": ["fact 1", "fact 2", ...] (max 8 items, concrete and reusable),
  "decisions": ["decision 1", ...] (max 5),
  "open_questions": ["q1", ...] (max 5),
  "context_state": {{}} (key-value pairs of variables/state the next agent needs),
  "next_action_hint": "what {target_agent} should do next (1 sentence)"
}}

Rules:
- DROP verbose preambles, greetings, redundant repetitions
- KEEP all unique facts, decisions, errors encountered
- KEEP variables/IDs/URLs/file paths mentioned
- Be terse. Target ~300 tokens output for ~3000 tokens input.

Output STRICT JSON only."""


def _llm_call(url: str, model: str, key: str, prompt: str, max_tokens: int = 600, timeout: int = 20) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    # response_format json_object seulement pour models qui le supportent
    if "gpt-oss" not in model:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key.strip()}",
            "User-Agent": "Mozilla/5.0 LaForge-Agent",  # eviter filtre Python-urllib
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    msg = data["choices"][0]["message"]
    # gpt-oss-120b utilise 'reasoning' au lieu de 'content' parfois
    return msg.get("content") or msg.get("reasoning", "")


def compress_for_handoff(
    messages: list[dict], target_agent: str, target_persona: str = "", keep_last_turns: int = 2
) -> dict:
    """Compress history pour handoff vers target_agent.

    Args:
        messages: liste {role, content} (chronologique)
        target_agent: nom du prochain agent
        target_persona: description courte du role cible
        keep_last_turns: nombre de dernieres interactions a preserver intactes

    Returns:
        dict TLDR + last_messages + estimated_savings
    """
    if not messages:
        return {
            "summary": "",
            "key_facts": [],
            "decisions": [],
            "open_questions": [],
            "context_state": {},
            "last_messages": [],
        }

    # Split : history a compresser vs derniers turns a preserver
    if len(messages) <= keep_last_turns + 1:
        return {
            "summary": "Conversation courte, pas de compression necessaire",
            "key_facts": [],
            "decisions": [],
            "open_questions": [],
            "context_state": {},
            "last_messages": messages,
            "estimated_tokens_saved": 0,
        }

    to_compress = messages[:-keep_last_turns]
    preserved = messages[-keep_last_turns:]

    history_text = "\n".join(f"[{m.get('role', '?')}] {m.get('content', '')[:1500]}" for m in to_compress)
    original_chars = sum(len(m.get("content", "")) for m in to_compress)

    try:
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        cerebras_key = get_secret("CEREBRAS_API_KEY")
        groq_key = get_secret("GROQ_API_KEY")
    except Exception:
        cerebras_key = groq_key = None

    prompt = COMPRESS_PROMPT.format(
        target_agent=target_agent,
        target_persona=target_persona or "general assistant",
        history=history_text[:8000],
    )

    # Cerebras primary, Groq fallback
    raw = None
    for url, model, key in [
        (CEREBRAS_URL, "gpt-oss-120b", cerebras_key),
        (GROQ_URL, "llama-3.3-70b-versatile", groq_key),
    ]:
        if not key:
            continue
        try:
            raw = _llm_call(url, model, key, prompt)
            break
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.warning(f"compress via {url} KO: {e}")
            continue

    if not raw:
        logger.warning("compression LLM unavailable - fallback truncation")
        return _fallback_truncate(messages, target_agent)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning(f"parse compress JSON KO: {e}")
        return _fallback_truncate(messages, target_agent)

    compressed_chars = len(raw)
    parsed["last_messages"] = preserved
    parsed["estimated_tokens_saved"] = max(0, (original_chars - compressed_chars) // 4)
    return parsed


def _fallback_truncate(messages: list[dict], target_agent: str) -> dict:
    """Si LLM compression KO, juste tronquer le history aux 10 derniers."""
    last_10 = messages[-10:]
    return {
        "summary": f"Conversation de {len(messages)} messages (compression LLM KO, tronquee).",
        "key_facts": [],
        "decisions": [],
        "open_questions": [],
        "context_state": {},
        "last_messages": last_10,
        "estimated_tokens_saved": 0,
    }


def format_compressed_for_prompt(compressed: dict, target_agent: str) -> str:
    """Format compressed TLDR + last_messages en bloc prompt-injectable."""
    lines = [f"### Handoff TLDR (transferred to {target_agent})"]
    if compressed.get("summary"):
        lines.append(f"**Summary:** {compressed['summary']}")

    facts = compressed.get("key_facts", [])
    if facts:
        lines.append("**Key facts:**")
        for f in facts[:8]:
            lines.append(f"  - {f}")

    decisions = compressed.get("decisions", [])
    if decisions:
        lines.append("**Decisions made:**")
        for d in decisions[:5]:
            lines.append(f"  - {d}")

    questions = compressed.get("open_questions", [])
    if questions:
        lines.append("**Open questions:**")
        for q in questions[:5]:
            lines.append(f"  - {q}")

    state = compressed.get("context_state", {})
    if state:
        lines.append(f"**Transferred state:** {json.dumps(state, ensure_ascii=False)}")

    hint = compressed.get("next_action_hint")
    if hint:
        lines.append(f"**Next action hint:** {hint}")

    last = compressed.get("last_messages", [])
    if last:
        lines.append("\n### Recent conversation (full, preserved)")
        for m in last:
            lines.append(f"[{m.get('role', '?')}] {m.get('content', '')[:500]}")

    return "\n".join(lines)


# --- CLI demo ---


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="EXECUTOR")
    ap.add_argument("--persona", default="agent code execution")
    args = ap.parse_args()

    # Demo conversation
    msgs = [
        {"role": "user", "content": "Aide-moi a deboguer ce bug NSSM crash loop."},
        {"role": "assistant", "content": "Investigation... le pid file traine."},
        {"role": "user", "content": "GC stale PIDs ?"},
        {"role": "assistant", "content": "Oui, j'ai patche supervisor.ts ligne 1234..."},
        {"role": "user", "content": "Test deploy ?"},
        {"role": "assistant", "content": "Pre-deploy review puis schtasks /Create..."},
    ]

    result = compress_for_handoff(msgs, target_agent=args.target, target_persona=args.persona)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\n---- Formatted for prompt injection ----\n")
    print(format_compressed_for_prompt(result, args.target))


if __name__ == "__main__":
    main()
