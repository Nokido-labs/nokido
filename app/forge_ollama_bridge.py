"""
FORGE INTELLIGENCE v3 [BLUE]
DATE:2026-03-25 | VER:v_batch_forge_ollama_bridge
#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]
CONTRAINTE: header HD batch — statut initial
"""
from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)
__FORGE_COLOR__ = "BLUE"
__FORGE_TAGS__ = (
    "#FORGE:[score:75|agent:batch-hd-injector|temp:0.00|risk:0.30|ast:KO|test:KO|lint:KO|color:BLUE|attempt:1]"
)

"""
forge_ollama_bridge.py — Agent Ollama avec Tool-Router Bunker-Grade
====================================================================
Architecture :
  1. Manifeste compact — liste les capacités MCP sans les schémas JSON
  2. Late-binding      — outils injectés à la demande, pas par défaut
  3. /api/chat first   — structure system/user/assistant pour Qwen
  4. Tool-Router       — intercepte CALL: tool_name {args} → exécute → réinjecte

Flux complet :
  Nokido → OllamaBridge.propose(task)
    → build_capability_string()        # manifeste compact (~30 tokens)
    → POST /api/chat (system+user)     # Qwen répond
    → _tool_router(response)           # intercepte CALL: si présent
        → exécute via MCP ring=0       # résultat local
        → réinjecte SYSTEM: résultat   # 2e appel Qwen avec contexte
    → retour réponse finale
"""


import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_ROOT_DIR = Path(__file__).resolve().parent.parent
_TIMEOUT = 35.0
_MAX_TOKENS = 400
_INGEST_MIN_CHARS = 80

# Pattern Proxy-Trigger principal : [NEED: web_search]
_NEED_PATTERN = re.compile(r"\[NEED:\s*([\w_]+)(?:\s*\|\s*(.+?))?\]", re.IGNORECASE)
# Rétrocompatibilité syntaxe CALL: (sessions précédentes)
_CALL_PATTERN = re.compile(r'CALL:\s*(\w+)\s*(\{.*?\}|\[.*?\]|"[^"]*")?', re.IGNORECASE | re.DOTALL)

# Outils MCP disponibles pour Qwen (via Nokido ring=0)
_MCP_TOOLS = [
    {"name": "rag_search", "desc": "chercher dans la base de connaissances RAG", "args": "q"},
    {"name": "rag_ingest", "desc": "ajouter une information dans le RAG", "args": "text, source"},
    {"name": "read_file", "desc": "lire un fichier du projet", "args": "path"},
    {"name": "read_list", "desc": "lister les fichiers d'un dossier", "args": "path"},
    {"name": "sql_query", "desc": "interroger la base SQLite du projet", "args": "q"},
    {"name": "task_create", "desc": "créer une tâche dans le bus Nokido", "args": "title, description"},
    {"name": "task_list", "desc": "lister les tâches en cours", "args": ""},
    {"name": "run_python", "desc": "exécuter du code Python en sandbox ring=0", "args": "code"},
]


def _read_model_from_env() -> str:
    """Read model from env."""
    try:
        for line in (_ROOT_DIR / "Nokido.env").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("OLLAMA_MODEL_DEFAULT") and "=" in line:
                val = line.split("=", 1)[1].strip()
                if val:
                    return val
    except Exception:
        pass
    return "qwen2.5-coder:latest"


def _read_url_from_env() -> str:
    """Read url from env."""
    try:
        for line in (_ROOT_DIR / "Nokido.env").read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("OLLAMA_URL") and "=" in line:
                val = line.split("=", 1)[1].strip()
                if val:
                    m = re.match(r"(https?://[^/]+)", val)
                    return m.group(1) if m else "http://localhost:11434"
    except Exception:
        pass
    return "http://localhost:11434"


_DEFAULT_MODEL = _read_model_from_env()
_DEFAULT_URL = _read_url_from_env()


# =============================================================================
# MANIFESTE COMPACT
# =============================================================================


def build_capability_string(tools: list = _MCP_TOOLS) -> str:
    """
    Génère une ligne de capacités compacte (~30 tokens).
    Ne décrit pas les schémas JSON — liste seulement les noms.
    Qwen utilise : CALL: tool_name {"arg": "val"}
    """
    names = [t["name"] for t in tools]
    return (
        f"CAPABILITIES [MCP-TOOLS via Nokido]: {', '.join(names)}. "
        "Syntaxe : [NEED: tool_name | query]. "
        'Pour utiliser un outil réponds UNIQUEMENT avec : CALL: tool_name {"arg": "val"}. '
        "Tu n'as PAS accès à internet ni à web_search. "
        'Pour toute recherche utilise CALL: rag_search {"q": "ta question"}.'
    )


def build_late_binding_doc(tool_name: str) -> str:
    """
    Doc complète d'un outil spécifique — injectée à la demande (late-binding).
    Économise ~500 tokens quand l'outil n'est pas utilisé.
    """
    docs = {
        "rag_search": 'CALL: rag_search {"q": "nginx config ssl"} — recherche sémantique dans le RAG',
        "rag_ingest": 'CALL: rag_ingest {"text": "...", "source": "nom"} — ajoute dans le RAG',
        "read_file": 'CALL: read_file {"path": "app/forge_settings.py"} — lit un fichier',
        "read_list": 'CALL: read_list {"path": "app/"} — liste un dossier',
        "sql_query": 'CALL: sql_query {"q": "SELECT * FROM event_log LIMIT 5"}',
        "task_create": 'CALL: task_create {"title": "...", "description": "..."}',
        "task_list": "CALL: task_list {}",
        "run_python": 'CALL: run_python {"code": "import sys; print(sys.version)"}',
    }
    return docs.get(tool_name, f'CALL: {tool_name} {{"q": "..."}}')


# =============================================================================
# TOOL-ROUTER (L'Arbitre)
# =============================================================================

# ── Tool-caching sémantique : doc injectée une fois par session ────────────────
_SESSION_TOOL_CACHE: dict[str, bool] = {}  # {session_id+tool_name: True}


def _cache_tool_doc(session_id: str, tool_name: str, doc: str) -> None:
    """Enregistre dans shared_prompt_log qu'un outil a été documenté cette session."""
    key = f"{session_id}:{tool_name}"
    if key not in _SESSION_TOOL_CACHE:
        _SESSION_TOOL_CACHE[key] = True
        try:
            from nokido_agent.app.forge_task_bus import log_shared_prompt

            log_shared_prompt(
                session_id=session_id,
                agent_id="nokido:tool-cache",
                content=f"[TOOL-DOC] {tool_name} : {doc}",
                role="system",
                mode="dev:tool_cache",
            )
        except Exception:
            pass


# =============================================================================
# SENTINEL WEB-SEARCH — 3 VERROUS BUNKER-GRADE
# =============================================================================

# Verrou 1 — Ring-Fencing : web_search interdit si session ring=0 active
# Verrou 2 — Query Redaction : _redact() avant envoi DDG (anti-exfiltration)
# Verrou 3 — Strict Output : 1000 chars max + DLP post-search + anti-injection

_WEB_SEARCH_RING = 3  # ring maximum autorisé pour web_search
_WEB_OUTPUT_MAX = 1000  # chars max retournés à Qwen


def _sentinel_query(query: str, session_id: str = "") -> tuple[str, str]:
    """
    Verrou 2 — Sentinel pré-recherche.
    Scanne la query pour détecter des secrets ou données is_private=1.
    Applique _redact() pour anonymiser avant envoi DDG.
    Retourne (query_safe, raison_blocage_ou_vide).
    """
    if not query or not query.strip():
        return "", "query vide"

    try:
        from nokido_agent.app.forge_conv_sanitizer import _redact, _REDACT_PATTERNS, _contains_ring0_data

        # Bloquer si la query contient des données ring=0
        if _contains_ring0_data(query):
            logger.warning("[sentinel:web] query bloquée — ring=0 data détectée")
            return "", "ring=0 data détectée dans la query"

        # Bloquer si la query contient des patterns de secrets
        for pattern, _ in _REDACT_PATTERNS:
            if pattern.search(query):
                logger.warning("[sentinel:web] query bloquée — secret détecté")
                return "", "secret détecté dans la query"

        # Anonymiser : redact + nettoyage générique
        safe_q = _redact(query.strip())

        # Vérification session paranoïde
        if session_id:
            try:
                from nokido_agent.app.forge_conv_sanitizer import is_paranoid

                if is_paranoid(session_id):
                    return "", "session paranoïde — web_search désactivé"
            except Exception:
                pass

        return safe_q, ""

    except Exception as e:
        logger.debug(f"[sentinel:web] erreur : {e}")
        return query.strip()[:200], ""


def _sentinel_output(raw: str) -> tuple[str, str]:
    """
    Verrou 3 — Sanitizer de contenu post-search.
    1. Tronque à 1000 chars (Strict Output)
    2. Applique _redact() sur le résultat (DLP post-search)
    3. Scanne pour patterns d'injection (15 patterns forge_prompt_guard)
    Retourne (output_safe, raison_blocage_ou_vide).
    """
    if not raw:
        return "", ""

    try:
        from nokido_agent.app.forge_conv_sanitizer import _redact
        from nokido_agent.app.forge_prompt_guard import detect_injection

        # Strict Output : 1000 chars max
        truncated = raw[:_WEB_OUTPUT_MAX]
        if len(raw) > _WEB_OUTPUT_MAX:
            truncated += f"\n[... tronqué à {_WEB_OUTPUT_MAX} chars]"

        # DLP post-search
        sanitized = _redact(truncated)

        # Anti-injection : scanner le contenu web retourné
        inj = detect_injection(sanitized)
        if inj.detected:
            logger.warning(f"[sentinel:web] injection détectée dans résultat : {inj.pattern_name} — résultat bloqué")
            return "", f"injection détectée ({inj.pattern_name})"

        return sanitized, ""

    except Exception as e:
        logger.debug(f"[sentinel:web] output sanitize erreur : {e}")
        # Fallback : retourner tronqué sans analyse
        return raw[:_WEB_OUTPUT_MAX], ""


async def _call_mcp_tool_stdio(tool_name: str, args: dict, session_id: str = "") -> str:
    """
    Facteur MCP stdio — Nokido est le seul pont entre Ollama et les outils.
    web_search passe obligatoirement par les 3 verrous Sentinel.
    """
    try:
        if tool_name == "web_search":
            q_raw = args.get("q", "").strip()
            k = min(int(args.get("k", 3)), 5)

            # Verrou 1 — Ring-Fencing : vérifier qu'aucune donnée ring=0 n'est active
            # (déjà assuré par l'Arbitre dans _tool_router, double-check ici)

            # Verrou 2 — Sentinel pré-recherche : redact + anti-exfiltration
            q_safe, blocked = _sentinel_query(q_raw, session_id=session_id)
            if blocked:
                logger.warning(f"[web_search] query bloquée : {blocked}")
                return f"[web_search] Recherche refusée : {blocked}"

            # Exécution DDG via forge_web
            from nokido_agent.app.forge_web import get_web_engine

            results = await get_web_engine().search(q_safe, max_results=k)

            if not results:
                return f"[web_search] Aucun résultat pour : {q_safe}"

            # Assembler la réponse brute
            parts = [f"[web_search] Résultats pour : {q_safe}"]
            for i, r in enumerate(results, 1):
                if isinstance(r, str):
                    parts.append(f"{i}. {r}")
                elif isinstance(r, dict):
                    title = r.get("title", r.get("url", "?"))
                    body = r.get("body", r.get("content", ""))[:300]
                    parts.append(f"{i}. {title}\n   {body}")
            raw_output = "\n".join(parts)

            # Verrou 3 — Sanitizer output : DLP + anti-injection + 1000 chars
            safe_output, blocked2 = _sentinel_output(raw_output)
            if blocked2:
                logger.warning(f"[web_search] output bloqué : {blocked2}")
                return "[web_search] Résultats filtrés (contenu suspect détecté)"

            logger.info(f"[web_search] OK query={q_safe!r} results={len(results)} output={len(safe_output)}chars")
            return safe_output

        else:
            # Autres outils → execute_tool_call local ring=0
            return await _execute_tool_call(tool_name, args)

    except Exception as e:
        logger.warning(f"[mcp_stdio:{tool_name}] erreur : {e}")
        return f"[{tool_name}] Erreur : {e}"


async def _execute_tool_call(tool_name: str, args: dict) -> str:
    """
    Exécute un outil MCP localement via ring=0 (Nokido interne).
    Retourne le résultat en string.
    """
    try:
        if tool_name == "rag_search":
            rag_engine = _g("rag_engine")
            if not rag_engine:
                return "[rag_search] RAG non initialisé"
            q = args.get("q", "")
            docs = await rag_engine.search(q, k=3)
            results = "\n".join(f"[{d.get('source', '?')}] {d.get('content', '')[:200]}" for d in docs)
            return results or "[rag_search] Aucun résultat"

        elif tool_name == "read_file":
            path = Path(_ROOT_DIR) / args.get("path", "")
            if path.exists() and path.is_file():
                content = path.read_text(encoding="utf-8", errors="ignore")
                return content[:1500]  # limiter la taille
            return f"[read_file] Fichier introuvable : {path}"

        elif tool_name == "read_list":
            path = Path(_ROOT_DIR) / args.get("path", "")
            if path.exists() and path.is_dir():
                files = [str(p.relative_to(_ROOT_DIR)) for p in path.iterdir()]
                return "\n".join(sorted(files)[:50])
            return f"[read_list] Dossier introuvable : {path}"

        elif tool_name == "sql_query":
            import sqlite3

            db_path = _ROOT_DIR / "data" / "embeddings.db"
            if not db_path.exists():
                return "[sql_query] Base de données introuvable"
            q = args.get("q", "")
            con = sqlite3.connect(str(db_path))
            try:
                rows = con.execute(q).fetchmany(20)
                return json.dumps(rows, ensure_ascii=False, default=str)
            finally:
                con.close()

        elif tool_name == "task_list":
            from nokido_agent.app.forge_task_bus import list_tasks

            tasks = list_tasks(status="pending", limit=10)
            return json.dumps(tasks, ensure_ascii=False, default=str)

        elif tool_name == "task_create":
            from nokido_agent.app.forge_task_bus import create_task

            t = create_task(
                title=args.get("title", "Tâche Ollama"),
                description=args.get("description", ""),
                executor="ollama:any",
                task_type="generic",
            )
            return f"[task_create] Tâche créée : {t['id']}"

        elif tool_name == "run_python":
            # Sandbox Python — limité, sans accès réseau
            code = args.get("code", "")
            output = []
            import io, contextlib

            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    exec(
                        code,
                        {
                            "__builtins__": {
                                "print": print,
                                "len": len,
                                "range": range,
                                "str": str,
                                "int": int,
                                "float": float,
                                "list": list,
                                "dict": dict,
                            }
                        },
                    )
                return buf.getvalue()[:500] or "[run_python] OK (pas de sortie)"
            except Exception as e:
                return f"[run_python] Erreur : {e}"

        elif tool_name == "rag_ingest":
            rag_engine = _g("rag_engine")
            if not rag_engine:
                return "[rag_ingest] RAG non initialisé"
            text = args.get("text", "")
            source = args.get("source", "ollama-contrib")
            await rag_engine.ingest_text(text, source=source, domain="collab")
            return f"[rag_ingest] {len(text)} chars ingérés depuis '{source}'"

        else:
            return f"[tool-router] Outil inconnu : {tool_name}"

    except Exception as e:
        logger.warning(f"[tool-router] {tool_name} erreur : {e}")
        return f"[{tool_name}] Erreur : {e}"


from app.core.settings import get_app_attr as _g  # centralisé


async def _tool_router(
    response: str, task: str, system: str, base_url: str, model: str, max_tokens: int, session_id: str = ""
) -> str:
    """
    Proxy-Trigger : intercepte [NEED: xxx] (priorité) ou CALL: xxx (retro).
    Exécute via MCP stdio interne (Nokido = facteur entre Ollama et MCP).
    Tool-caching : doc injectée dans shared_prompt_log la 1ère fois seulement.
    Arbitre de sécurité : outils dangereux bloqués avant exécution.
    Maximum 3 rounds anti-boucle.
    """
    for _round in range(3):
        m_need = _NEED_PATTERN.search(response)
        m_call = _CALL_PATTERN.search(response) if not m_need else None

        if not m_need and not m_call:
            break

        if m_need:
            tool_name = m_need.group(1).lower()
            hint = (m_need.group(2) or "").strip()
            args = {"q": hint} if hint else {}
            logger.info(f"[proxy-trigger] [NEED:{tool_name}] hint={hint!r}")
            doc = build_late_binding_doc(tool_name)
            if session_id:
                _cache_tool_doc(session_id, tool_name, doc)
        else:
            tool_name = m_call.group(1).lower()
            args_raw = (m_call.group(2) or "{}").strip()
            try:
                if args_raw.startswith(("{", "[")):
                    args = json.loads(args_raw)
                elif args_raw.startswith('"'):
                    args = {"q": args_raw.strip('"')}
                else:
                    args = {"q": args_raw}
            except Exception:
                args = {"q": args_raw}
            logger.info(f"[tool-router] CALL retro : {tool_name} args={args}")

        # Arbitre sécurité — outils destructeurs bloqués
        _BLOCKED = {"delete_all", "purge", "drop_db", "rm_rf", "format_disk"}
        if tool_name in _BLOCKED:
            return f"[Arbitre] Outil '{tool_name}' refusé par politique sécurité."

        # Verrou 1 — Ring-Fencing web_search
        # web_search interdit si la session contient des données ring=0 actives
        if tool_name == "web_search" and session_id:
            try:
                from nokido_agent.app.forge_conv_sanitizer import is_paranoid

                if is_paranoid(session_id):
                    logger.warning(f"[ring-fence] web_search refusé — session paranoid {session_id}")
                    return "[web_search] Refusé : session en mode paranoid (données sensibles actives)"
            except Exception:
                pass

        result = await _call_mcp_tool_stdio(tool_name, args, session_id=session_id)
        logger.info(f"[proxy-trigger] résultat {tool_name} ({len(result)} chars)")

        # Réinjection résultat + 2e appel Qwen
        reinject = f"SYSTEM: Résultat de {tool_name}:\n{result}\n\nContinue ta réponse."
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
            {"role": "assistant", "content": response},
            {"role": "user", "content": reinject},
        ]
        try:
            import aiohttp

            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    f"{base_url}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                        "options": {"num_predict": max_tokens, "temperature": 0.5},
                    },
                    timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        new_resp = data.get("message", {}).get("content", "").strip()
                        if new_resp:
                            response = new_resp
                            logger.info(f"[proxy-trigger] round {_round + 1} OK ({len(response)} chars)")
                    else:
                        break
        except Exception as e:
            logger.warning(f"[proxy-trigger] réinjection échouée : {e}")
            break

    return response


class OllamaBridge:
    def __init__(self, model: str = _DEFAULT_MODEL, base_url: str = _DEFAULT_URL) -> None:
        """Init.

        Args:
            model: Description.
            base_url: Description.
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.enabled = True
        self._author = f"ollama:{model.split(':')[0]}"

    async def propose(
        self,
        task: str,
        role: str = "Expert externe (Ollama)",
        rag_ctx: str = "",
        system_extra: str = "",
        max_tokens: int = _MAX_TOKENS,
    ) -> str:
        """Propose.

        Args:
            task: Description.
            role: Description.
            rag_ctx: Description.
            system_extra: Description.
            max_tokens: Description.
        """
        if not self.enabled:
            return ""

        # ── 1. System prompt avec manifeste compact ───────────────────────────
        capability = build_capability_string()

        _canary = ""  # AB4 : lie AVANT le try — le garde ne cause jamais la panne
        try:
            from nokido_agent.app.forge_prompt_guard import build_safe_system

            system, _canary, _warns = build_safe_system(
                role=f"{role}. {capability}",
                rag_ctx=rag_ctx,
                system_extra=system_extra,
            )
            # AB4 (2026-09-12) : ces deux valeurs etaient JETEES. Le canari pose
            # dans le prompt n'etait verifie nulle part, et une injection reperee
            # dans le contexte RAG partait en silence — un garde qui tourne et
            # dont le verdict va a la poubelle ne garde rien.
            if _warns:
                logger.warning("[ollama_bridge] prompt_guard: %s", _warns)
        except Exception:
            system = f"Tu es {role}. {capability}\nRéponds en français, de façon technique et précise, max 12 lignes."
            if rag_ctx:
                system += f"\n\nContexte RAG :\n{rag_ctx[:600]}"
            if system_extra:
                system += f"\n\n{system_extra}"

        try:
            import aiohttp
            from nokido_agent.app.forge_metrics import get_collector as _gc

            _col = _gc()
            with _col.measure("ollama", self.model, mode="collab") as _m:
                answer = ""

                # ── 2. /api/chat en priorité (structure system/user) ──────────
                try:
                    chat_payload = {
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": task},
                        ],
                        "stream": False,
                        "options": {"num_predict": max_tokens, "temperature": 0.7},
                    }
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{self.base_url}/api/chat",
                            json=chat_payload,
                            timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                answer = data.get("message", {}).get("content", "").strip()
                                if answer:
                                    logger.debug(f"OllamaBridge: /api/chat OK ({len(answer)} chars)")
                            else:
                                logger.debug(f"OllamaBridge /api/chat: HTTP {resp.status}")
                except Exception as _ce:
                    logger.debug(f"OllamaBridge /api/chat failed: {_ce}")

                # ── 3. Fallback /api/generate ─────────────────────────────────
                if not answer:
                    try:
                        gen_payload = {
                            "model": self.model,
                            "prompt": f"{system}\n\nTâche : {task}",
                            "stream": False,
                            "options": {"num_predict": max_tokens, "temperature": 0.7},
                        }
                        async with aiohttp.ClientSession() as session:
                            async with session.post(
                                f"{self.base_url}/api/generate",
                                json=gen_payload,
                                timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
                            ) as resp:
                                if resp.status == 200:
                                    data = await resp.json()
                                    answer = data.get("response", "").strip()
                                    if answer:
                                        logger.debug(f"OllamaBridge: /api/generate OK ({len(answer)} chars)")
                    except Exception as _ge:
                        logger.debug(f"OllamaBridge /api/generate failed: {_ge}")

                # ── 4. Fallback stdio ─────────────────────────────────────────
                if not answer:
                    answer = await self._stdio_fallback(task, system, max_tokens)

                # ── 5. Late-binding : si Qwen dit "je ne sais pas" ou utilise web_search
                if answer and self._needs_late_binding(answer):
                    logger.info("[ollama-bridge] Late-binding déclenché")
                    answer = await self._late_binding_retry(task, system, answer, max_tokens)

                # ── 6. Tool-Router : intercepte CALL: tool_name {args} ────────
                _needs_routing = bool(answer and ("[NEED:" in answer.upper() or "CALL:" in answer.upper()))
                if _needs_routing:
                    _sid = ""
                    try:
                        for _mn in ("__main__", "Nokido"):
                            _m = sys.modules.get(_mn)
                            if _m and getattr(_m, "session_name", None):
                                _sid = str(_m.session_name)
                                break
                    except Exception:
                        pass
                    answer = await _tool_router(
                        answer,
                        task,
                        system,
                        self.base_url,
                        self.model,
                        max_tokens,
                        session_id=_sid,
                    )

                # AB4 (2026-09-12) — verification de la fuite du canari AVANT
                # l'ingestion RAG qui suit : une marque interne recopiee par le
                # modele serait sinon ECRITE EN BASE, puis reservie en contexte.
                if answer and _canary:
                    try:
                        from nokido_agent.app.forge_prompt_guard import verifier_fuite

                        answer, _fuite = verifier_fuite(answer, _canary,
                                                        source="ollama_bridge")
                        if _fuite:
                            logger.error("[ollama-bridge] fuite de prompt detectee "
                                         "— marque retiree avant ingestion")
                    except Exception as _vfe:  # noqa: BLE001
                        logger.error(f"[ollama-bridge] verification de fuite "
                                     f"ILLISIBLE: {_vfe}")

                _m.estimate_tokens(task, answer)

            # ── Ingestion RAG ─────────────────────────────────────────────────
            if answer and len(answer) >= _INGEST_MIN_CHARS:
                asyncio.create_task(self._ingest_rag(answer, source=task[:60], domain="collab"))
            # Pilier 4 : Fallback → LiteLLM si réponse vide ou entropique
            if not answer:
                try:
                    from nokido_agent.app.forge_litellm_bridge import ask as _litellm_ask

                    logger.info("[ollama-bridge] réponse vide → escalade LiteLLM")
                    answer = await _litellm_ask(
                        task,
                        context=rag_ctx,
                        role="LaForge-Worker (escalade depuis OllamaBridge)",
                        max_tokens=max_tokens,
                    )
                    if answer:
                        logger.info(f"[ollama-bridge] LiteLLM escalade OK ({len(answer)} chars)")
                except Exception as _fe:
                    logger.debug(f"[ollama-bridge] escalade LiteLLM échouée : {_fe}")

            return answer

        except asyncio.TimeoutError:
            logger.warning(f"OllamaBridge: timeout ({_TIMEOUT}s)")
            return ""
        except Exception as e:
            logger.warning(f"OllamaBridge: erreur {e}")
            return ""

    def _needs_late_binding(self, response: str) -> bool:
        """
        Détecte si Qwen a répondu "je ne sais pas" / utilisé web_search
        → déclenche le late-binding avec doc d'outil.
        """
        triggers = [
            "web_search",
            "je ne sais pas",
            "je n'ai pas accès",
            "je ne peux pas rechercher",
            "pas d'accès à internet",
            "je ne peux pas accéder",
            "search the web",
            "look it up",
        ]
        r_lower = response.lower()
        return any(t in r_lower for t in triggers)

    async def _late_binding_retry(self, task: str, system: str, bad_response: str, max_tokens: int) -> str:
        """
        Late-binding : Qwen a dit "je ne sais pas" → on lui injecte
        la doc de rag_search et on relance.
        """
        doc = build_late_binding_doc("rag_search")
        retry_msg = (
            f"Tu as répondu : '{bad_response[:100]}'\n\n"
            f"CORRECTION : tu as accès à Nokido. Voici comment chercher :\n{doc}\n\n"
            f"Réessaie maintenant avec CALL: rag_search pour répondre à : {task}"
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
            {"role": "assistant", "content": bad_response},
            {"role": "user", "content": retry_msg},
        ]
        try:
            import aiohttp

            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "options": {"num_predict": max_tokens, "temperature": 0.5},
                    },
                    timeout=aiohttp.ClientTimeout(total=_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("message", {}).get("content", "").strip() or bad_response
        except Exception as e:
            logger.debug(f"[late-binding] retry échoué : {e}")
        return bad_response

    async def _stdio_fallback(self, task: str, system: str, max_tokens: int) -> str:
        """Fallback stdio : ollama run en sous-processus."""
        try:
            import shutil

            if not shutil.which("ollama"):
                return ""
            prompt_text = f"{system}\n\nTâche : {task}"
            proc = await asyncio.create_subprocess_exec(
                "ollama",
                "run",
                self.model,
                prompt_text,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
            answer = stdout.decode("utf-8", errors="replace").strip()
            if answer:
                logger.debug(f"OllamaBridge: stdio OK ({len(answer)} chars)")
            return answer
        except Exception:
            return ""

    async def _ingest_rag(self, text: str, source: str, domain: str) -> None:
        """Ingère la réponse dans le RAG collaboratif."""
        try:
            rag_engine = _g("rag_engine")
            if rag_engine and hasattr(rag_engine, "ingest_text"):
                await rag_engine.ingest_text(
                    text,
                    source=f"ollama:{source}",
                    domain=domain,
                    metadata={"author": self._author, "ring": 3},
                )
        except Exception as e:
            logger.debug(f"OllamaBridge._ingest_rag: {e}")

    def get_available_models(self) -> list:
        """Retourne les modèles Ollama disponibles."""
        try:
            import urllib.request
            import json as _json

            url = f"{self.base_url}/api/tags"
            with urllib.request.urlopen(url, timeout=3) as r:
                data = _json.loads(r.read())
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def is_inference_alive(self, timeout: float = 8.0, ttl: float = 60.0) -> bool:
        """L'inference tourne-t-elle REELLEMENT ? Seul un POST /api/chat qui rend du
        contenu le prouve.

        `api/tags` ne fait que LISTER des manifests sur disque ; `api/ps` liste les
        modeles residents. Ni l'un ni l'autre ne prouve que le runner `llama-server`
        est present et repond -- mesure 2026-08-19 : runner MANQUANT, api/tags listait
        16 modeles, tout `api/chat` rendait 500. On teste donc 1 seul token, en cache
        (TTL 60s) pour ne pas payer une generation a chaque appel. False si down.
        """
        import time as _t

        now = _t.monotonic()
        cache = getattr(self, "_inf_alive_cache", None)
        if cache and now - cache[0] < ttl:
            return cache[1]
        ok = False
        try:
            import json as _json
            import urllib.request

            modeles = self.get_available_models()
            modele = next((m for m in modeles if "embed" not in m.lower()),
                          modeles[0] if modeles else "")
            if modele:
                corps = _json.dumps({
                    "model": modele,
                    "messages": [{"role": "user", "content": "ok"}],
                    "stream": False, "options": {"num_predict": 1},
                }).encode()
                req = urllib.request.Request(
                    f"{self.base_url}/api/chat", data=corps,
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    d = _json.loads(r.read())
                ok = (d.get("message") or {}).get("content") is not None
        except Exception:  # noqa: BLE001 - inference HS = not alive, jamais crasher
            ok = False
        self._inf_alive_cache = (now, ok)
        return ok


# =============================================================================
# SINGLETON
# =============================================================================

_bridge: Optional[OllamaBridge] = None


def get_bridge(model: str = "", url: str = "") -> OllamaBridge:
    """Get bridge.

    Args:
        model: Description.
        url: Description.
    """
    global _bridge
    if _bridge is None:
        try:
            m = sys.modules.get("__main__")
            s = getattr(m, "settings", None)
            _model = model or getattr(s, "ollama_model_default", _DEFAULT_MODEL) or _DEFAULT_MODEL
            _url = url or getattr(s, "ollama_url", _DEFAULT_URL) or _DEFAULT_URL
        except Exception:
            _model, _url = model or _DEFAULT_MODEL, url or _DEFAULT_URL
        _bridge = OllamaBridge(model=_model, base_url=_url)
    return _bridge


def reset_bridge() -> None:
    """Reset bridge."""
    global _bridge
    _bridge = None
