"""forge_llm_format_bridge.py — moteur partagé des ingress LLM-API multi-format.

__FORGE_COLOR__ = "metabolisme-llm"

POURQUOI (anti-dup CLAUDE.md §3, vérifié Explore 2026-06-10) :
  forge_openai_proxy.py (:7777) sert DÉJÀ l'ingress OpenAI /v1/chat/completions
  (firewall + hub_call + cascade). Pour intercepter Claude Code (Anthropic
  /v1/messages) et Gemini CLI (generateContent), il faut 2 ingress de PLUS qui
  PARTAGENT le même moteur. Ce module = ce moteur (DRY) ; les 2 ingress
  (forge_anthropic_ingress, forge_gemini_ingress) = adaptateurs de FORMAT minces.

LE SWITCHBOARD N'EST PAS RÉÉCRIT : le déport local (micro-tâche) vs passthrough
cloud (tâche lourde, OAuth Max/Ultra) vit dans forge_cognitive_router.route_task
+ forge_llm_router.call_cascade, atteints via le tool hub `ask` (provider="auto").
L'ingress reste DUMB : convertit le format -> appelle `ask` -> reconvertit.
Préserve les quotas (cloud = claude_cli/gemini_cli OAuth, PAS l'API payante,
cf feedback_no_anthropic_api_direct). Cf docs/biblio_cli_unification_2026-06-10.md.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from nokido_agent.app.forge_secrets import get_secret

ROOT = Path(__file__).resolve().parent.parent
HUB_URL = os.environ.get("FORGE_HUB_URL", "http://127.0.0.1:8766/mcp")
HUB_TIMEOUT_DEFAULT = int(os.environ.get("FORGE_PROXY_HUB_TIMEOUT", "180"))
HUB_CONCURRENCY = int(os.environ.get("FORGE_PROXY_HUB_CONCURRENCY", "8"))


def load_token() -> str:
    """Jeton du hub, par le COFFRE.

    Le repli manuel sur `Nokido.env` qui suivait est REDONDANT : `get_secret`
    resout deja coffre > WCM > Nokido.env > os.environ. Le garder revenait a
    reimplementer a la main son troisieme maillon.
    Une fois ce module et `tools/nokido_tui.py` migres, les deux
    reimplementations sont devenues identiques et ont fait mordre le detecteur
    de clones -- qui groupe par STRUCTURE AST, pas par nom de variable. Le clone
    n'etait pas le probleme : il en etait le symptome.
    """
    return get_secret("FORGE_MCP_TOKEN") or ""


_TOKEN = load_token()

import httpx

_HTTPX: "httpx.AsyncClient | None" = None
_SEM: "asyncio.Semaphore | None" = None


def _runtime() -> "tuple[httpx.AsyncClient, asyncio.Semaphore]":
    """Lazy init httpx singleton + semaphore (dans l'event loop)."""
    global _HTTPX, _SEM
    if _HTTPX is None:
        limits = httpx.Limits(
            max_connections=HUB_CONCURRENCY * 2, max_keepalive_connections=HUB_CONCURRENCY
        )
        _HTTPX = httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(HUB_TIMEOUT_DEFAULT, connect=5.0))
    if _SEM is None:
        _SEM = asyncio.Semaphore(HUB_CONCURRENCY)
    return _HTTPX, _SEM


_FW = None
_FW_TRIED = False


def _fw():
    """SemanticFirewall best-effort (Golden Rule #4). Dégrade si indispo, ne brick pas."""
    global _FW, _FW_TRIED
    if not _FW_TRIED:
        _FW_TRIED = True
        try:
            import sys as _s

            _s.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_semantic_firewall import get_firewall

            _FW = get_firewall()
        except Exception as e:  # noqa: BLE001
            print(f"[bridge] SemanticFirewall indispo — ingress DEGRADE: {e}", flush=True)
            _FW = None
    return _FW


async def hub_call(name: str, args: dict, agent: str, timeout: "int | None" = None) -> dict:
    """Appel MCP hub async (httpx singleton borné)."""
    client, sem = _runtime()
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {_TOKEN}", "X-Agent-Name": agent}
    t = timeout if timeout is not None else HUB_TIMEOUT_DEFAULT
    async with sem:
        r = await client.post(HUB_URL, json=body, headers=headers, timeout=t)
        r.raise_for_status()
        return r.json()


def _extract(rpc: dict) -> "tuple[str, dict]":
    """Sort le payload du wrapper MCP tools/call -> (raw_text, parsed_dict|{})."""
    text = rpc.get("result", {}).get("content", [{}])[0].get("text", "")
    try:
        inner = json.loads(text)
        if isinstance(inner, dict):
            return text, inner
    except Exception:
        pass
    return text, {}


def _block_text(content) -> str:
    """Aplati un `content` qui peut être str OU liste de blocs (Anthropic/Gemini)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict):
                out.append(c.get("text") or c.get("content") or "")
            else:
                out.append(str(c))
        return "\n".join(t for t in out if t)
    return str(content or "")


def messages_to_prompt(system, messages: list) -> str:
    """Aplati (system, messages[{role,content}]) -> prompt unique pour `ask`."""
    parts = []
    sys_txt = _block_text(system) if system else ""
    if sys_txt:
        parts.append(f"[system]\n{sys_txt}")
    for m in messages or []:
        role = m.get("role", "user")
        parts.append(f"[{role}]\n{_block_text(m.get('content', ''))}")
    return "\n\n".join(parts)


class AskResult:
    __slots__ = ("ok", "reply", "provider", "error", "input_tokens", "output_tokens")

    def __init__(self, ok: bool, reply: str = "", provider: str = "auto", error: str = "", it: int = 0, ot: int = 0):
        self.ok = ok
        self.reply = reply
        self.provider = provider
        self.error = error
        self.input_tokens = it
        self.output_tokens = ot


async def ask_via_hub(prompt: str, provider: str, max_tokens: int, thread_id: str, agent: str, ring: int = 3, cli_identity: str = "") -> AskResult:
    """firewall pre -> hub `ask` (SWITCHBOARD local/cloud) -> firewall post + restore.

    provider="auto" => forge_cognitive_router / call_cascade décident déport local
    (micro-tâche) vs passthrough cloud (lourd, OAuth Max/Ultra). L'ingress ne décide pas.
    """
    fw = _fw()
    pf = None
    if fw is not None:
        pf = fw.pre_flight(prompt, ring=ring, provider=provider)
        if not pf.ok:
            return AskResult(False, error=f"firewall blocked: {pf.reason}", provider=provider)
        prompt = pf.safe_task  # PII rédigées avant upstream

    args = {"provider": provider, "message": prompt, "max_tokens": max_tokens, "thread_id": thread_id}
    try:
        r = await hub_call("ask", args, agent=agent, timeout=180)
    except Exception as e:  # noqa: BLE001
        return AskResult(False, error=f"hub error: {e}", provider=provider)

    raw, inner = _extract(r)
    if inner and inner.get("ok") is False:
        return AskResult(False, error=inner.get("error") or "cascade ok=false", provider=inner.get("provider", provider))
    reply = (inner.get("text") if inner else None) or (inner.get("response") if inner else None) or raw
    if not reply or not str(reply).strip():
        return AskResult(False, error="empty response", provider=provider)
    actual = (inner.get("provider") if inner else None) or provider

    if fw is not None and pf is not None:
        pfr = fw.post_flight(reply, task=prompt)
        if not pfr.ok:
            return AskResult(False, error=f"firewall post: {pfr.tag} {pfr.reason}".strip(), provider=actual)
        reply = fw.restore(reply, pf.mapping)

    # Sync cross-CLI (anti zone d'ombre) : journalise l'activité dans le canal PARTAGÉ
    # forge_collab (sandbox/collab/cli_activity.md, lu par tous les CLI). RÉUTILISE le
    # canal de sync existant — ne crée PAS un nouveau bus. Best-effort + prompt déjà
    # rédigé par le firewall => aucune PII dans le log partagé.
    if cli_identity:
        try:
            from nokido_agent.app import forge_collab

            forge_collab.append(
                "cli_activity",
                sender=cli_identity,
                message=f"-> {actual} ({max_tokens}tok): {str(prompt)[:80]}",
                tags=["ingress", agent],
            )
        except Exception:
            pass

    return AskResult(True, reply=reply, provider=actual, it=len(prompt) // 4, ot=len(str(reply)) // 4)


async def list_models_via_hub(agent: str) -> list:
    """Modèles dispo = providers configurés du hub (pour /v1/models)."""
    try:
        r = await hub_call("hub", {"action": "list_providers"}, agent=agent, timeout=20)
        _, data = _extract(r)
        return data.get("configured", []) if isinstance(data, dict) else []
    except Exception:
        return []


async def shutdown() -> None:
    global _HTTPX
    if _HTTPX is not None:
        await _HTTPX.aclose()
        _HTTPX = None
