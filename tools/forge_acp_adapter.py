#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_acp_adapter.py — PoC : Nokido comme backend AGENT via ACP (Agent
Client Protocol), à côté du serveur MCP.

ACP (origine Zed, adopté par microsoft/intelligent-terminal) = JSON-RPC 2.0 sur
stdio où un HOST (terminal/éditeur) PILOTE un agent-CLI. C'est le dual de MCP :
MCP = Nokido sert des tools ; ACP = Nokido EST l'agent piloté. Ce PoC permet
de brancher Nokido dans intelligent-terminal / Zed / tout host ACP comme
backend SOUVERAIN (la data passe par le pipeline Nokido : firewall + router).

Transport : JSON-RPC newline-delimited sur stdin/stdout (comme mcp_stdio_bridge).
Le HOST spawn ce script ; il dialogue initialize → session/new → session/prompt.
Sur session/prompt, on route le texte via le hub Nokido (tool `ask`, POST :8766
/mcp — proxy stateless, token FORGE_MCP_TOKEN optionnel en local) et on stream
la réponse en notification `session/update` (agent_message_chunk).

PoC = phase 1 : initialize / session/new / session/prompt / session/cancel.
Hors PoC (phase 2) : auth, permissions, fs/*, token-streaming réel (ask renvoie
le texte complet → 1 seul chunk ici), tool_call updates, mcpServers passthrough.

Config host ACP (ex) :
  command = %USERPROFILE%/miniforge3/python.exe
  args    = [".../LaForge/tools/forge_acp_adapter.py"]
  env     = { LAFORGE_ACP_PROVIDER = "ollama" }   # local-first par défaut
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

PROTOCOL_VERSION = "1.0"
HUB_MCP = "http://127.0.0.1:8766/mcp"
PROVIDER = os.environ.get("LAFORGE_ACP_PROVIDER", "ollama")  # sovereign default


def _get_token() -> str:
    """Token hub : env (FORGE_TOKEN_BRIDGE prioritaire, FORGE_MCP_TOKEN) puis
    vault DPAPI machine. Hub /mcp attend `Authorization: Bearer <token>`."""
    for k in ("FORGE_TOKEN_BRIDGE", "FORGE_MCP_TOKEN"):
        v = os.environ.get(k)
        if v:
            return v
    try:
        _app = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
        if _app not in sys.path:
            sys.path.insert(0, _app)
        # 2b-6 (2026-09-28) : par la brique `jeton_hub` -- jeton propre du pont, le maitre
        # seulement en transition dite ; plus de lecture directe du coffre machine.
        from nokido_agent.app.forge_agent_credential import jeton_hub  # type: ignore
        return jeton_hub("BRIDGE") or ""
    except Exception:
        return ""

_rpc_id = 1000
_SESSIONS: dict = {}  # sessionId -> {provider, rag_context} : config par session (phase 2)


def _chunk(text, size: int = 280, maxn: int = 40):
    """Découpe pour un rendu PROGRESSIF côté host (pattern ACP = N session/update,
    coupé sur espace). NB : `ask` est single-shot -> chunking d'AFFICHAGE, pas un
    vrai token-stream (= phase 3, via hub orchestrate/SSE)."""
    text = text or ""
    chunks, i = [], 0
    while i < len(text) and len(chunks) < maxn:
        j = min(i + size, len(text))
        if j < len(text):
            sp = text.rfind(" ", i, j)
            if sp > i:
                j = sp
        chunks.append(text[i:j])
        i = j
    if i < len(text) and chunks:
        chunks[-1] += text[i:]
    return chunks or ([text] if text else [])


def _emit(obj: dict) -> None:
    """Écrit un message JSON-RPC (réponse ou notification) sur stdout."""
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(req_id, result) -> None:
    _emit({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error(req_id, code: int, message: str) -> None:
    _emit({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


def _notify(method: str, params: dict) -> None:
    _emit({"jsonrpc": "2.0", "method": method, "params": params})


def _extract_prompt_text(params: dict) -> str:
    """Tolérant : ACP `prompt` (liste de content blocks) OU `messages` (Anthropic-
    like). Concatène les blocs type=text du dernier message utilisateur."""
    blocks = params.get("prompt")
    if blocks is None:
        msgs = params.get("messages") or []
        blocks = msgs[-1].get("content") if msgs else []
    if isinstance(blocks, str):
        return blocks
    out = []
    for b in blocks or []:
        if isinstance(b, dict) and b.get("type") in (None, "text"):
            out.append(b.get("text", ""))
        elif isinstance(b, str):
            out.append(b)
    return "\n".join(t for t in out if t).strip()


def _route_to_nokido(text: str, provider: str = "", rag_context: bool = False) -> str:
    """Route le prompt via le pipeline Nokido (hub tool `ask`). Souverain :
    firewall pre/post + router local-first côté hub. Fail-soft. provider/
    rag_context = config par session (phase 2 : host choisit local/cloud + RAG)."""
    global _rpc_id
    _rpc_id += 1
    _args = {"provider": provider or PROVIDER, "message": text}
    if rag_context:
        _args["rag_context"] = True
    body = json.dumps({
        "jsonrpc": "2.0", "id": _rpc_id, "method": "tools/call",
        "params": {"name": "ask", "arguments": _args},
    }).encode("utf-8")
    headers = {"content-type": "application/json"}
    tok = _get_token()
    if tok:
        headers["authorization"] = "Bearer " + tok
    try:
        req = urllib.request.Request(HUB_MCP, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        return f"[Nokido ACP] hub injoignable: {exc}"
    if "error" in resp:
        return f"[Nokido ACP] hub error: {resp['error']}"
    res = resp.get("result", resp)
    # Format MCP : result.content = [{type:text, text:...}]
    if isinstance(res, dict) and isinstance(res.get("content"), list):
        parts = [c.get("text", "") for c in res["content"] if isinstance(c, dict)]
        raw = "\n".join(p for p in parts if p) or json.dumps(res, ensure_ascii=False)
    else:
        raw = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
    # Le tool `ask` renvoie un JSON {ok, text, provider, ...} -> ne garder que
    # .text pour un rendu propre côté host ACP (sinon le host affiche le JSON).
    try:
        inner = json.loads(raw)
        if isinstance(inner, dict) and isinstance(inner.get("text"), str):
            return inner["text"]
    except Exception:
        pass
    return raw


def _route_cowork(text: str) -> str:
    """Expose cowork via ACP (P4a) : un hote (Zed/terminal) pilote le collegue IA. Commandes :
    'cowork new: <goal>' | 'cowork list' | 'cowork status <pid>' | 'cowork run <pid>' |
    'cowork propose <pid>' | 'cowork approve <pid> <tid>' | 'cowork reject <pid> <tid>'. Local souverain."""
    try:
        _app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
        if _app not in sys.path:
            sys.path.insert(0, _app)
        from nokido_agent.app import forge_cowork as cw  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return f"[cowork] indispo: {exc}"
    parts = text.split()
    sub = parts[1].lower() if len(parts) > 1 else ""
    try:
        if sub.startswith("new") or "new:" in text.lower():
            goal = text.split(":", 1)[1].strip() if ":" in text else " ".join(parts[2:])
            if not goal:
                return "[cowork] usage: cowork new: <goal>"
            pid = cw.create_project(goal, [{"description": goal, "type": "doc", "reversible": True}])
            return f"[cowork] projet cree: {pid} (goal: {goal})"
        if sub == "list":
            return "[cowork] projets idle: " + (", ".join(cw.list_active()) or "(aucun)")
        if sub == "status" and len(parts) > 2:
            p = cw.get_project(parts[2])
            return json.dumps(p, ensure_ascii=False) if p else "[cowork] projet inconnu"
        if sub == "run" and len(parts) > 2:
            return json.dumps(cw.run_once(parts[2]), ensure_ascii=False)
        if sub == "propose" and len(parts) > 2:
            return json.dumps(cw.propose_next(parts[2]), ensure_ascii=False)
        if sub == "approve" and len(parts) > 3:
            return json.dumps(cw.approve(parts[2], parts[3], ring=4), ensure_ascii=False)  # ACP=untrusted -> trust-ring refuse
        if sub == "reject" and len(parts) > 3:
            return json.dumps(cw.reject(parts[2], parts[3], ring=4), ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return f"[cowork] erreur: {exc}"
    return ("[cowork] commandes: new: <goal> | list | status <pid> | run <pid> | "
            "propose <pid> | approve <pid> <tid> | reject <pid> <tid>")


def handle(obj: dict) -> None:
    method = obj.get("method")
    req_id = obj.get("id")
    params = obj.get("params") or {}

    if method == "initialize":
        _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "agentCapabilities": {
                "loadSession": False,
                "promptCapabilities": {"image": False, "embeddedContext": True},
            },
            "authMethods": [],  # backend local souverain : pas d'auth requise
            "agentInfo": {"name": "Nokido", "version": "poc-2"},
        })
    elif method == "authenticate":
        _result(req_id, {})  # no-op (local souverain)
    elif method == "session/new":
        import secrets
        sid = "nokido-" + secrets.token_hex(8)
        # Extensions Nokido : le host peut choisir provider (local/cloud) + RAG.
        _SESSIONS[sid] = {
            "provider": params.get("provider") or PROVIDER,
            "rag_context": bool(params.get("rag_context", False)),
        }
        _result(req_id, {"sessionId": sid})
    elif method == "session/prompt":
        sid = params.get("sessionId", "")
        cfg = _SESSIONS.get(sid, {})
        text = _extract_prompt_text(params)
        if text.lower().startswith("cowork"):
            answer = _route_cowork(text)  # P4a : l'hote pilote le collegue cowork
        elif text:
            answer = _route_to_nokido(text, cfg.get("provider", ""), cfg.get("rag_context", False))
        else:
            answer = "[Nokido ACP] prompt vide"
        for piece in _chunk(answer):  # rendu progressif (N session/update)
            _notify("session/update", {
                "sessionId": sid,
                "sessionUpdate": {
                    "type": "agent_message_chunk",
                    "role": "agent",
                    "content": [{"type": "text", "text": piece}],
                },
            })
        _result(req_id, {"stopReason": "end_turn"})
    elif method == "session/cancel":
        # Best-effort : le route sync n'est pas interruptible (cancel vrai = async,
        # phase 3). On nettoie au moins la session.
        _SESSIONS.pop(params.get("sessionId", ""), None)
    elif req_id is not None:
        _error(req_id, -32601, f"method not found: {method}")


def _selftest() -> int:
    """Joue le flux ACP in-process (capture _emit) — pas de subprocess/stdin.
    Via trusted_script = teste protocole + ROUTE réelle (loopback hub)."""
    global _emit
    captured: list = []
    real = _emit
    _emit = lambda o: captured.append(o)  # noqa: E731
    try:
        handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "1.0"}})
        handle({"jsonrpc": "2.0", "id": 2, "method": "session/new",
                "params": {"provider": PROVIDER, "rag_context": False}})
        sid = "s"
        for o in captured:
            if o.get("id") == 2 and isinstance(o.get("result"), dict):
                sid = o["result"].get("sessionId", "s")
        handle({"jsonrpc": "2.0", "id": 3, "method": "session/prompt",
                "params": {"sessionId": sid, "prompt": [
                    {"type": "text", "text": "explique en une phrase ce qu'est Nokido"}]}})
        handle({"jsonrpc": "2.0", "id": 4, "method": "session/prompt",
                "params": {"sessionId": sid, "prompt": [{"type": "text", "text": "cowork list"}]}})
        assert any("[cowork]" in json.dumps(o, ensure_ascii=False) for o in captured), "ACP cowork routing KO"
    finally:
        _emit = real
    for o in captured:
        real(o)
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if "--selftest" in sys.argv:
        return _selftest()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            handle(obj)
        except Exception as exc:  # noqa: BLE001 - ne jamais tuer la boucle
            if obj.get("id") is not None:
                _error(obj.get("id"), -32603, f"internal: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
