"""
nokido CLI — interface terminal pour llama-server :8091 + Nokido hub :8766.

Usage:
  nokido                        chat interactif (défaut)
  nokido ask "question"         question one-shot, streaming
  nokido models                 liste les modèles chargés
  nokido status                 santé serveur + slots actifs
  nokido slots                  détail des slots d'inférence
  nokido metrics                métriques Prometheus brutes
  nokido props                  propriétés runtime (--props flag requis)
  nokido tools                  liste tous les outils hub :8766
  nokido hub <tool> [json]      appel outil hub explicite
  nokido <tool> [json]          raccourci direct — tout outil hub connu
  nokido -h / --help            ce message
"""

import argparse
import json
import os
import sys
import textwrap
import urllib.error
import urllib.request

# `forge_secrets` vit dans app/. Sans ce bootstrap, l'import ne reussit QUE si un
# appelant a deja bricole sys.path : l'entrypoint console `nokido` (tools.llama_cli:main)
# et `python tools/llama_cli.py` echouaient tous deux en ModuleNotFoundError (mesure
# 2026-08-27, forge_feature_checklist). Le CLI principal etait donc mort a l'installation.
_APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from nokido_agent.app.forge_secrets import get_secret  # noqa: E402 - apres le bootstrap de sys.path

LLAMA_BASE = "http://127.0.0.1:8091"
HUB_BASE = "http://127.0.0.1:8766"
MODEL = "laforge-coder"
MAX_TOK = 4096
OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
LMSTUDIO_BASE = "http://127.0.0.1:1234"
# État runtime mutable — bascule à chaud via /backend /model /rag (cf. cmd_chat).
#   backend "llama"  : llama-server :8091 (rapide, modèle unique).
#   backend "ollama" : :11434, switch entre tous tes modèles locaux.
#   backend "hub" (ou /rag on) : passe par le hub `ask` = RAG injecté +
#                                SemanticFirewall = VRAIE intelligence.
# Défaut rag=True : le hub (RAG + SemanticFirewall) répond aux questions système/
# Nokido au lieu du coder 7B brut (sans contexte → filler générique). Pour une
# session de code pur rapide sans roundtrip hub : `/rag off` ou `/backend llama`.
STATE = {"backend": "llama", "model": MODEL, "rag": True, "secure": False}


def _hub_token() -> str:
    """FORGE_MCP_TOKEN depuis env, fallback vault DPAPI (machine_vault)."""
    t = get_secret("FORGE_MCP_TOKEN") or get_secret("HUB_TOKEN") or ""
    if t:
        return t
    try:
        import sys as _sys

        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app"))
        from nokido_agent.app.forge_machine_vault import vault_get as _vget  # type: ignore

        return _vget("FORGE_MCP_TOKEN") or _vget("HUB_TOKEN") or ""
    except Exception:
        return ""


def _hub_headers() -> dict:
    h = {"Content-Type": "application/json", "X-Agent-Name": "LAFORGE_CLI"}
    tok = _hub_token()
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


SYSTEM = (
    "Tu es Nokido Coder, assistant expert en code et cybersécurité. "
    "Réponds de façon concise et technique."
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _get(path: str, base: str = LLAMA_BASE) -> dict | str:
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=10) as r:
            raw = r.read().decode()
        try:
            return json.loads(raw)
        except Exception:
            return raw
    except urllib.error.URLError as e:
        return {"error": str(e)}


def _post(path: str, payload: dict, base: str = LLAMA_BASE, timeout: int = 120):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout)


def _ensure_llama_up(timeout: int = 30) -> bool:
    """Si :8091 down, POST /supervisor/llm/activate/NokidoLlamaNative + poll health."""
    import time

    try:
        with urllib.request.urlopen(f"{LLAMA_BASE}/health", timeout=2) as _:
            return True
    except Exception:
        pass
    tok = _hub_token()
    if not tok:
        return False
    print(
        "\033[1;33m[wake] NokidoLlamaNative sleeping, activation supervisor...\033[0m", flush=True
    )
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8765/supervisor/llm/activate/NokidoLlamaNative",
            data=b"",
            method="POST",
            headers={"Authorization": f"Bearer {tok}"},
        )
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:
        print(f"\033[1;31m[wake] activate failed: {e}\033[0m")
        return False
    for _ in range(timeout):
        time.sleep(1)
        try:
            with urllib.request.urlopen(f"{LLAMA_BASE}/health", timeout=2) as _:
                print("\033[1;32m[wake] :8091 UP\033[0m", flush=True)
                return True
        except Exception:
            continue
    return False


def _stream(messages: list[dict]) -> str:
    buf = []
    _ensure_llama_up()
    try:
        with _post(
            "/v1/chat/completions",
            {
                "model": STATE["model"],
                "messages": messages,
                "max_tokens": MAX_TOK,
                "stream": True,
            },
        ) as resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content", "")
                    if delta:
                        print(delta, end="", flush=True)
                        buf.append(delta)
                except Exception:
                    pass
    except urllib.error.URLError as e:
        print(f"\033[1;31m[erreur réseau] {e}\033[0m")
        print("Vérifier NokidoLlamaNative sur :8091")
    print()
    return "".join(buf)


def _pp(obj):
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print(obj)


def _hub_call(tool: str, params: dict, timeout: int = 60) -> dict:
    body = json.dumps(
        {
            "method": "tools/call",
            "params": {"name": tool, "arguments": params},
        }
    ).encode()
    req = urllib.request.Request(
        f"{HUB_BASE}/mcp",
        data=body,
        headers=_hub_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.URLError as e:
        return {"error": str(e)}


_TOOLS_CACHE = os.path.join(os.path.expanduser("~"), ".nokido_tools_cache.json")


def _hub_tools(timeout: int = 15) -> list[dict]:
    """Retourne la liste des outils hub depuis tools/list, avec cache disque fallback."""
    body = json.dumps({"method": "tools/list", "params": {}}).encode()
    req = urllib.request.Request(
        f"{HUB_BASE}/mcp",
        data=body,
        headers=_hub_headers(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        tools = data.get("result", {}).get("tools", [])
        if tools:
            try:
                with open(_TOOLS_CACHE, "w", encoding="utf-8") as f:
                    json.dump(tools, f)
            except Exception:
                pass
        return tools
    except Exception:
        pass
    # Cache fallback
    try:
        with open(_TOOLS_CACHE, encoding="utf-8") as f:
            cached = json.load(f)
        return cached
    except Exception:
        return []


# ── commandes ────────────────────────────────────────────────────────────────

_CHAT_HELP = """\033[1;36mCommandes chat :\033[0m
  /help            ce message
  /reset           vider l'historique
  /models          modèles locaux dispo (llama / ollama / lmstudio)
  /model <nom>     changer de modèle (ex: qwen2.5-coder:7b)
  /backend <b>     llama (:8091) | ollama (:11434) | hub (RAG+firewall)
  /rag on|off      router via hub ask = RAG injecté + firewall (intelligence)
  /secure on|off   tâches stratégiques/sécurité : cascade locale SEULE (jamais cloud)
  /tools           lister outils hub :8766
  /hub <outil> <json>  appel direct outil hub
  quit / q         quitter

\033[1;36mCLI (hors chat) :\033[0m
  nokido ask "question"    one-shot streamé
  nokido models / status / slots / metrics
  nokido tools             liste outils hub
  nokido <outil> '<json>'  appel direct outil
  nokido hub <outil> '<json>'
"""


def _list_local_models() -> dict:
    """Modèles locaux réels par backend (llama-server / ollama / lmstudio)."""
    out: dict[str, list[str]] = {}
    for key, url, parse in (
        ("llama :8091", LLAMA_BASE + "/v1/models", "openai"),
        ("lmstudio :1234", LMSTUDIO_BASE + "/v1/models", "openai"),
        ("ollama :11434", OLLAMA_BASE + "/api/tags", "ollama"),
    ):
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                d = json.loads(r.read())
            out[key] = (
                [m.get("name", "?") for m in d.get("models", [])]
                if parse == "ollama"
                else [m.get("id", "?") for m in d.get("data", [])]
            )
        except Exception:
            out[key] = ["(off)"]
    return out


def _send_ollama(history: list[dict]) -> str:
    """Stream ollama :11434 /api/chat avec le modèle courant."""
    buf: list[str] = []
    try:
        req = urllib.request.Request(
            OLLAMA_BASE + "/api/chat",
            data=json.dumps({"model": STATE["model"], "messages": history, "stream": True}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    c = json.loads(line).get("message", {}).get("content", "")
                    if c:
                        print(c, end="", flush=True)
                        buf.append(c)
                except Exception:
                    pass
    except Exception as e:
        print(f"\033[1;31m[ollama erreur] {e}\033[0m — modèle '{STATE['model']}' chargé ? (/models)")
    print()
    return "".join(buf)


def _send_smart(history: list[dict]) -> str:
    """Via hub `ask` : RAG injecté + SemanticFirewall = intelligence (pas un LLM nu)."""
    last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
    # INVARIANT : le hub = centre de l'intelligence, JAMAIS de réponse vide.
    # QUALITÉ D'ABORD : étage 1 = provider `router` (call_cascade use_case auto,
    # chains qualité, escalade anti-filler — directive user « privilégie qualité
    # réponse »). Les étages suivants = filet de DISPONIBILITÉ si le router lui-même
    # échoue. Mode /secure on : `router_local` (grille déterministe force_local,
    # meilleur slot LOCAL) + filet local seul — fin de chaîne = diagnostic interne,
    # jamais un envoi cloud.
    if STATE["backend"] == "ollama":
        chain = ["ollama"]
    elif STATE.get("secure"):
        chain = ["router_local", "ollama", "lmstudio", "llamacpp"]
    else:
        chain = ["router", "ollama", "lmstudio", "llamacpp", "groq", "cerebras"]
    errs = []
    for prov in chain:
        # Un étage qui timeout/crash NE TUE PAS le CLI : on note et on passe au
        # suivant (invariant jamais-vide — un crash est pire qu'une ligne vide).
        try:
            d = _hub_call("ask", {"provider": prov, "message": last_user, "rag_context": True})
        except Exception as e:  # noqa: BLE001
            errs.append(f"{prov}: {type(e).__name__}: {e}")
            continue
        raw = ""
        if isinstance(d, dict):
            raw = (((d.get("result") or {}).get("content") or [{}])[0]).get("text", "") or str(d.get("error", ""))
        ok, txt, err = True, raw, ""
        try:
            inner = json.loads(raw)
            if isinstance(inner, dict):
                ok = inner.get("ok", True)
                txt = str(inner.get("text") or "")
                err = str(inner.get("error") or "")
        except Exception:
            pass
        if ok and txt.strip():
            print(txt)
            return txt
        errs.append(f"{prov}: {err or 'vide'}")
    # aucun provider n'a répondu -> diagnostic EXPLICITE, jamais une ligne vide
    msg = "[hub : aucun provider n'a répondu] " + " | ".join(errs)
    print(msg)
    return msg


def _send(history: list[dict]) -> str:
    """Dispatch selon STATE (backend + rag)."""
    if STATE["rag"] or STATE["backend"] == "hub":
        return _send_smart(history)
    if STATE["backend"] == "ollama":
        return _send_ollama(history)
    return _stream(history)


def cmd_chat(_args):
    """Chat interactif multi-tour."""
    print(f"\033[1;36mNokido Coder CLI\033[0m — {LLAMA_BASE}")
    print("\033[90m/help pour aide, /reset pour réinitialiser, quit pour sortir\033[0m\n")
    history = [{"role": "system", "content": SYSTEM}]
    while True:
        try:
            user = input("\033[1;32m> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user.lower() in ("quit", "exit", "q"):
            break
        if user == "/help":
            print(_CHAT_HELP)
            continue
        if user == "/reset":
            history = [{"role": "system", "content": SYSTEM}]
            print("\033[90m[contexte réinitialisé]\033[0m")
            continue
        if user == "/tools":
            cmd_tools(None)
            continue
        if user.startswith("/hub "):
            parts = user[5:].split(None, 1)
            tool = parts[0] if parts else ""
            payload_str = parts[1] if len(parts) > 1 else "{}"
            if tool:
                try:
                    params = json.loads(payload_str)
                except json.JSONDecodeError as e:
                    print(f"[erreur JSON] {e}")
                    continue
                _pp(_hub_call(tool, params))
            continue
        if user == "/models":
            for k, v in _list_local_models().items():
                print(f"  {k}: {', '.join(v) or '—'}")
            continue
        if user.startswith("/model "):
            STATE["model"] = user[7:].strip()
            print(f"\033[90m[modèle = {STATE['model']}]\033[0m")
            continue
        if user.startswith("/backend "):
            b = user[9:].strip()
            if b in ("llama", "ollama", "hub"):
                STATE["backend"] = b
                print(f"\033[90m[backend = {b}]\033[0m")
            else:
                print("backends : llama | ollama | hub")
            continue
        if user.startswith("/rag "):
            STATE["rag"] = user[5:].strip() in ("on", "1", "true")
            print(f"\033[90m[rag = {STATE['rag']} — via hub ask]\033[0m")
            continue
        if user.startswith("/secure "):
            STATE["secure"] = user[8:].strip() in ("on", "1", "true")
            mode = "cascade locale SEULE (cloud coupé)" if STATE["secure"] else "cloud autorisé en dernier recours"
            print(f"\033[90m[secure = {STATE['secure']} — {mode}]\033[0m")
            continue
        history.append({"role": "user", "content": user})
        reply = _send(history)
        if reply:
            history.append({"role": "assistant", "content": reply})


def cmd_ask(args):
    """One-shot : pose une question, affiche la réponse, quitte."""
    question = " ".join(args.text)
    if not question:
        print('Usage: nokido ask "ta question"')
        sys.exit(1)
    _stream(
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ]
    )


def cmd_models(_args):
    """Liste les modèles chargés sur llama-server."""
    d = _get("/v1/models")
    if isinstance(d, dict) and "data" in d:
        for m in d["data"]:
            print(f"  {m['id']}")
    else:
        _pp(d)


def cmd_status(_args):
    """Santé serveur + slots actifs."""
    health = _get("/health")
    slots = _get("/slots")
    models = _get("/v1/models")
    print(
        f"health : {health.get('status', health)}"
        if isinstance(health, dict)
        else f"health : {health}"
    )
    if isinstance(models, dict) and "data" in models:
        print(f"models : {[m['id'] for m in models['data']]}")
    if isinstance(slots, list):
        busy = [s for s in slots if s.get("state", 0) != 0]
        print(f"slots  : {len(slots)} total, {len(busy)} actif(s)")
    elif isinstance(slots, dict) and "error" in slots:
        print(f"slots  : {slots['error']}")


def cmd_slots(_args):
    """Détail complet des slots d'inférence."""
    _pp(_get("/slots"))


def cmd_metrics(_args):
    """Métriques Prometheus brutes (/metrics)."""
    raw = _get("/metrics")
    if isinstance(raw, str):
        for line in raw.splitlines():
            if line and not line.startswith("#"):
                print(line)
    else:
        _pp(raw)


def cmd_props(_args):
    """Propriétés runtime du serveur (/props). Nécessite --props au lancement."""
    _pp(_get("/props"))


def cmd_tools(_args):
    """Liste tous les outils disponibles sur le hub :8766."""
    tools = _hub_tools()
    if not tools:
        print("\033[1;31m[hub hors ligne ou aucun outil]\033[0m")
        return
    print(f"\033[1;36m{len(tools)} outils hub disponibles\033[0m  ({HUB_BASE})\n")
    for t in tools:
        name = t.get("name", "?")
        desc = t.get("description", "")
        # Première ligne de description seulement
        short = desc.splitlines()[0][:72] if desc else ""
        print(f"  \033[1;32mnokido {name:<22}\033[0m {short}")
    print("\n  Usage : nokido <tool> '<json>'")
    print('  Ex    : nokido run \'{"action":"shell","code":"nssm status NokidoLlamaNative"}\'')


def cmd_hub(args):
    """
    Appel direct d'un outil Nokido hub :8766.

    Exemples:
      nokido hub run '{"action":"shell","code":"nssm status NokidoLlamaNative"}'
      nokido hub query '{"query":"forge_rag_engine","limit":3}'
      nokido hub web_search '{"query":"llama.cpp quantization"}'
    """
    tool = args.tool
    payload_str = getattr(args, "payload", None) or "{}"
    try:
        params = json.loads(payload_str)
    except json.JSONDecodeError as e:
        print(f"[erreur] JSON invalide : {e}")
        sys.exit(1)
    _pp(_hub_call(tool, params))


def cmd_ultra(args):
    """Ultra-Review LOCALE : git diff -> .py modifiés -> ForgeAudit (hub, 4 prismes, 0 API)."""
    import subprocess

    base = getattr(args, "base", None) or "origin/main"

    def _diff(rng):
        try:
            r = subprocess.run(["git", "diff", "--name-only", rng], capture_output=True, text=True, timeout=20, errors="replace")
            return [f.strip() for f in r.stdout.splitlines() if f.strip().endswith(".py")]
        except Exception:
            return []

    files = _diff(f"{base}...HEAD") or _diff("HEAD")  # fallback : changements non-committés
    if not files:
        print(f"\033[90m[ultra] aucun .py modifié (base: {base})\033[0m")
        return
    print(f"\033[1;36m[ForgeAudit]\033[0m {len(files)} fichier(s) : {', '.join(files)}")
    print("\033[90messaim read-only 4 prismes (Security/Correctness/Architecture/Style) — 1-2 min sur APU\033[0m")
    res = _hub_call("forge_trigger_audit", {"target_files": files}, timeout=600)
    txt = res
    if isinstance(res, dict):
        txt = (((res.get("result") or {}).get("content") or [{}])[0]).get("text") or json.dumps(res)[:300]
    print("\n" + str(txt))


def cmd_hub_direct(tool: str, args):
    """Dispatch dynamique : nokido <tool_hub> [json]"""
    payload_str = getattr(args, "payload", None) or "{}"
    if payload_str and not payload_str.startswith("{") and not payload_str.startswith("["):
        # Shorthand string arg → wrap en {"query": ...} ou {"code": ...}
        payload_str = json.dumps({"query": payload_str})
    try:
        params = json.loads(payload_str)
    except json.JSONDecodeError as e:
        print(f"[erreur] JSON invalide : {e}")
        sys.exit(1)
    result = _hub_call(tool, params)
    _pp(result)


# ── parser ───────────────────────────────────────────────────────────────────

# Outils hub "core" toujours présents (pour le help statique même si hub offline)
_CORE_HUB_TOOLS = [
    ("run", "Shell/Python/GitHub — action=shell|python|github, code=..."),
    ("query", "RAG FTS5 search — query=..., limit=N"),
    ("read", "Lecture fichier — path=..."),
    ("write", "Écriture fichier — path=..., content=..."),
    ("web_search", "Recherche web — query=..."),
    ("hub", "Info hub / heartbeat — action=status|list_agents"),
    ("ask", "Question LLM via hub — question=..., provider=..."),
    ("task", "Créer tâche agent — name=..., prompt=..., provider=..."),
    ("event", "Émettre événement — type=..., data=..."),
    ("orchestrate", "Orchestrer multi-agents — plan=..., agents=[...]"),
    ("rag", "RAG vectoriel — query=..., top_k=N"),
    ("skill", "Exécuter skill hub — name=..., args={}"),
    ("bundle", "Bundle contexte session — format=md|json"),
    ("crawl", "Crawler URL — url=..., depth=N"),
    ("plan", "Générer plan GOAP — goal=..., state={}"),
    ("research_agent", "Agent recherche autonome — topic=..., depth=N"),
]


def build_parser() -> argparse.ArgumentParser:
    # Parser utilise UNIQUEMENT les outils statiques (pas de requête réseau au démarrage)
    all_tools = {name: desc for name, desc in _CORE_HUB_TOOLS}

    tool_list_str = "\n".join(f"    nokido {n:<22} {d}" for n, d in sorted(all_tools.items()))
    online_marker = ""

    p = argparse.ArgumentParser(
        prog="laforge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(f"""\
            \033[1;36mNokido Coder CLI\033[0m — llama-server :8091 + hub :8766  {online_marker}

            Commandes système:
              chat      Chat interactif multi-tour (défaut si aucune commande)
              ask       Question one-shot, réponse streamée
              models    Liste modèles chargés
              status    Santé serveur + slots
              slots     Détail slots d'inférence
              metrics   Métriques Prometheus
              props     Propriétés runtime serveur
              tools     Lister tous les outils hub
              hub       Appel outil hub explicite (nokido hub <outil> '<json>')

            Outils hub (accès direct):
{tool_list_str}
        """),
    )
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("chat", help="Chat interactif multi-tour (défaut)")
    sub.add_parser("tools", help="Lister tous les outils hub :8766")
    sub.add_parser("models", help="Liste modèles chargés sur :8091")
    sub.add_parser("status", help="Santé serveur + résumé slots")
    sub.add_parser("slots", help="Détail complet des slots d'inférence")
    sub.add_parser("metrics", help="Métriques Prometheus brutes (/metrics)")
    sub.add_parser("props", help="Propriétés runtime (/props)")
    ultra_p = sub.add_parser("ultra", help="Ultra-Review locale (git diff -> ForgeAudit 4 prismes)")
    ultra_p.add_argument("--base", default="origin/main", help="ref de base du diff (défaut: origin/main)")

    ask_p = sub.add_parser("ask", help="Question one-shot streamée")
    ask_p.add_argument("text", nargs="+", help="Texte de la question")

    hub_p = sub.add_parser(
        "hub",
        help="Appel outil Nokido hub :8766",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
                                Exemples:
                                  nokido hub run '{"action":"shell","code":"nssm status NokidoLlamaNative"}'
                                  nokido hub query '{"query":"rag_engine","limit":3}'
                                  nokido hub web_search '{"query":"llama.cpp vulkan"}'
                            """),
    )
    hub_p.add_argument("tool", help="Nom de l'outil hub")
    hub_p.add_argument("payload", nargs="?", default="{}", help="Arguments JSON (défaut: {})")

    # Sous-commandes directes pour chaque outil hub connu (hors noms réservés système)
    _reserved = {"chat", "ask", "models", "status", "slots", "metrics", "props", "tools", "hub"}
    for name in sorted(all_tools):
        if name in _reserved:
            continue
        desc = all_tools[name]
        dp = sub.add_parser(name, help=f"[hub] {desc[:60]}")
        dp.add_argument("payload", nargs="?", default="{}", help="Arguments JSON")

    return p, set(all_tools.keys())


COMMANDS = {
    "chat": cmd_chat,
    "ask": cmd_ask,
    "models": cmd_models,
    "status": cmd_status,
    "slots": cmd_slots,
    "metrics": cmd_metrics,
    "props": cmd_props,
    "tools": cmd_tools,
    "hub": cmd_hub,
    "ultra": cmd_ultra,
}


def main():
    parser, hub_tool_names = build_parser()
    args = parser.parse_args()
    cmd = args.cmd

    if cmd in COMMANDS:
        COMMANDS[cmd](args)
    elif cmd in hub_tool_names:
        cmd_hub_direct(cmd, args)
    else:
        # Défaut : chat interactif
        cmd_chat(args)


if __name__ == "__main__":
    main()
