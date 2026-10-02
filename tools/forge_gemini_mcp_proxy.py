"""
forge_gemini_mcp_proxy.py — Proxy Gemini ↔ MCP Nokido
=======================================================
Utilise le nouveau SDK google-genai (1.x) — plus google-generativeai.

  pip install google-genai

Architecture :
  Gemini API (gemini-2.0-flash)
    └── FunctionDeclaration × outils MCP
         └── ce proxy
              └── appel direct → fonctions mcp_server_tools.py

Usage CLI :
  python tools/forge_gemini_mcp_proxy.py
  python tools/forge_gemini_mcp_proxy.py "état du swarm ?"

Usage Python :
  from tools.forge_gemini_mcp_proxy import GeminiMCPProxy
  proxy = GeminiMCPProxy()
  print(proxy.chat("Lance les tests et montre-moi les fails"))

Prérequis :
  - GEMINI_API_KEY dans Nokido.env (compte avec crédits actifs)
  - pip install google-genai
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── Secrets : NOMS dans Nokido.env, VALEURS au coffre (decision owner 2026-10-01) ──
try:
    from nokido_agent.app.forge_secrets import injecter_env_depuis_coffre as _injecter

    _bilan_coffre = _injecter(ROOT / "Nokido.env")
    if _bilan_coffre["absentes"] or _bilan_coffre["illisibles"]:
        print("[secrets] absents du coffre : %s ; illisibles : %s -> forge_env_to_vault"
              % (_bilan_coffre["absentes"], _bilan_coffre["illisibles"]), flush=True)
except Exception as _e_coffre:  # noqa: BLE001 - dit, jamais avale
    print("[secrets] coffre indisponible (%s) : aucun secret injecte" % type(_e_coffre).__name__,
          flush=True)

# La CLE se lit par get_secret (coffre d'abord) : relire l'environnement apres l'injection
# rouvrait la couche qu'aucune rotation ne met a jour (gate « secrets hors coffre », 2026-10-02).
try:
    from nokido_agent.app.forge_secrets import get_secret as _get_secret

    GEMINI_API_KEY = _get_secret("GEMINI_API_KEY") or ""
except Exception as _e_cle:  # noqa: BLE001 - dit, jamais avale
    print("[secrets] GEMINI_API_KEY illisible (%s)" % type(_e_cle).__name__, flush=True)
    GEMINI_API_KEY = ""
# Préférer 2.5-flash-lite (10 RPM) pour le chat interactif
# Passer à 2.5-flash (3 RPM) pour les tâches complexes
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
MCP_SCRIPT = str(ROOT / "app" / "mcp_server_tools.py")

# ── Rate limiter intégré (free tier) ─────────────────────────────────────────
# gemini-2.5-flash      : 3 RPM  / 20 RPD
# gemini-2.5-flash-lite : 10 RPM / 20 RPD
import collections as _col
import threading as _thr
import time as _time_mod


class _RateLimiter:
    """Token bucket + daily counter pour Gemini free tier."""

    def __init__(self, rpm: int = 10, rpd: int = 20) -> None:
        self._rpm = rpm
        self._rpd = rpd
        self._lock = _thr.Lock()
        self._calls = _col.deque()  # timestamps des N dernières secondes
        self._today = 0
        self._day = _time_mod.strftime("%Y-%m-%d")

    def wait(self) -> None:
        """Bloque jusqu'à ce qu'un slot soit disponible."""
        with self._lock:
            # Reset journalier
            today = _time_mod.strftime("%Y-%m-%d")
            if today != self._day:
                self._today = 0
                self._day = today

            if self._today >= self._rpd:
                raise RuntimeError(
                    f"Quota journalier Gemini atteint ({self._rpd} RPD). Reset à minuit."
                )

            # RPM : garder uniquement les appels dans la dernière minute
            now = _time_mod.monotonic()
            cutoff = now - 60.0
            while self._calls and self._calls[0] < cutoff:
                self._calls.popleft()

            if len(self._calls) >= self._rpm:
                sleep_for = 60.0 - (now - self._calls[0]) + 0.5
                print(f"  ⏳ Rate limit — attente {sleep_for:.1f}s...")
                _time_mod.sleep(sleep_for)

            self._calls.append(_time_mod.monotonic())
            self._today += 1


_RATE_LIMITER = _RateLimiter(rpm=10, rpd=20)  # lite par défaut

# ── SDK ───────────────────────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:
    print("❌  pip install google-genai")
    sys.exit(1)


# ── Catalogue d'outils ────────────────────────────────────────────────────────
# (name, description, {param: (type_str, description, required)})
_CATALOG: list[dict] = [
    {
        "name": "rag_search",
        "description": "Recherche sémantique dans la base RAG de Nokido.",
        "params": {
            "query": ("STRING", "Requête de recherche", True),
            "top_k": ("INTEGER", "Nombre de résultats (défaut 5)", False),
            "domain": ("STRING", "Domaine de filtrage optionnel", False),
        },
    },
    {
        "name": "code_run_python",
        "description": "Exécute un snippet Python dans le sandbox Nokido.",
        "params": {
            "code": ("STRING", "Code Python à exécuter", True),
            "timeout": ("INTEGER", "Timeout secondes (défaut 30)", False),
        },
    },
    {
        "name": "code_py_compile",
        "description": "Vérifie la syntaxe AST d'un code Python.",
        "params": {
            "code": ("STRING", "Code Python à vérifier", True),
        },
    },
    {
        "name": "swarm_status",
        "description": "État du swarm d'agents Nokido (actifs, tâches).",
        "params": {},
    },
    {
        "name": "llm_generate",
        "description": "Génère du texte via Ollama local de Nokido.",
        "params": {
            "prompt": ("STRING", "Prompt", True),
            "max_tokens": ("INTEGER", "Tokens max", False),
        },
    },
    {
        "name": "services_status",
        "description": "État de tous les services Nokido (Ollama, RAG, etc.).",
        "params": {},
    },
    {
        "name": "events_recent",
        "description": "N événements récents du bus Nokido.",
        "params": {
            "n": ("INTEGER", "Nombre d'événements (défaut 10)", False),
        },
    },
    {
        "name": "sentinel_check",
        "description": "Vérifie la sécurité d'une instruction via le Sentinel.",
        "params": {
            "instruction": ("STRING", "Instruction à auditer", True),
        },
    },
    {
        "name": "authority_status",
        "description": "Qui détient le token d'autorité dans Nokido.",
        "params": {},
    },
    {
        "name": "github_status",
        "description": "État de la connexion GitHub du projet.",
        "params": {},
    },
    {
        "name": "llm_router_status",
        "description": "Statut du routeur LLM multi-providers.",
        "params": {},
    },
]

_TYPE_MAP = {
    "STRING": gtypes.Type.STRING,
    "INTEGER": gtypes.Type.INTEGER,
    "BOOLEAN": gtypes.Type.BOOLEAN,
    "ARRAY": gtypes.Type.ARRAY,
    "OBJECT": gtypes.Type.OBJECT,
}


def _build_tools() -> list[gtypes.Tool]:
    """Construit la liste de tools Gemini depuis le catalogue.

    Returns:
        Liste contenant un Tool avec toutes les FunctionDeclaration.
    """
    decls = []
    for tool in _CATALOG:
        props = {}
        required = []
        for pname, (ptype, pdesc, preq) in tool["params"].items():
            props[pname] = gtypes.Schema(
                type=_TYPE_MAP.get(ptype, gtypes.Type.STRING),
                description=pdesc,
            )
            if preq:
                required.append(pname)

        params = (
            gtypes.Schema(
                type=gtypes.Type.OBJECT,
                properties=props,
                required=required or None,
            )
            if props
            else None
        )
        decls.append(
            gtypes.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=params,
            )
        )
    return [gtypes.Tool(function_declarations=decls)]


# ── Exécuteur d'outils ────────────────────────────────────────────────────────


def _run_tool(tool_name: str, args: dict) -> str:
    """Exécute un outil MCP directement via import de mcp_server_tools.

    Args:
        tool_name: Nom de la fonction dans mcp_server_tools.py.
        args: Arguments à passer.

    Returns:
        Résultat textuel de l'outil.
    """
    spec = importlib.util.spec_from_file_location("_mcp_tools", MCP_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        return json.dumps({"error": f"import mcp_server_tools: {e}"})

    fn = getattr(mod, tool_name, None)
    if fn is None:
        return json.dumps({"error": f"outil '{tool_name}' introuvable"})

    try:
        if asyncio.iscoroutinefunction(fn):
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(fn(**args))
            loop.close()
        else:
            result = fn(**args)
        return str(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Proxy principal ───────────────────────────────────────────────────────────


class GeminiMCPProxy:
    """Chat interactif Gemini ↔ outils MCP Nokido."""

    def __init__(self, api_key: str = "") -> None:
        """Initialise le client Gemini et les outils MCP.

        Args:
            api_key: Clé API Gemini (fallback sur GEMINI_API_KEY env).

        Raises:
            ValueError: Si aucune clé n'est disponible.
        """
        key = api_key or GEMINI_API_KEY
        if not key:
            raise ValueError("GEMINI_API_KEY manquante dans Nokido.env")

        self._client = genai.Client(api_key=key)
        self._tools = _build_tools()
        self._config = gtypes.GenerateContentConfig(
            tools=self._tools,
            system_instruction=(
                "Tu es l'assistant de pilotage de Nokido v17, un moteur "
                "d'évolution de code multi-agents sur Ryzen 8700G. "
                "Utilise les outils MCP locaux pour répondre précisément. "
                "Réponds en français."
            ),
        )
        self._history: list[gtypes.Content] = []
        print(f"✅ GeminiMCPProxy — {GEMINI_MODEL} — {len(_CATALOG)} outils")

    def chat(self, user_message: str) -> str:
        """Envoie un message avec boucle function calling.

        Args:
            user_message: Message de l'utilisateur.

        Returns:
            Réponse textuelle finale de Gemini.
        """
        self._history.append(gtypes.Content(role="user", parts=[gtypes.Part(text=user_message)]))

        for _turn in range(6):
            _RATE_LIMITER.wait()
            response = self._client.models.generate_content(
                model=GEMINI_MODEL,
                contents=self._history,
                config=self._config,
            )
            candidate = response.candidates[0]
            parts = candidate.content.parts

            # Collecter les function calls
            fn_calls = [
                p.function_call
                for p in parts
                if getattr(p, "function_call", None) and p.function_call.name
            ]

            if not fn_calls:
                # Réponse finale texte
                text = next((p.text for p in parts if getattr(p, "text", None)), "(pas de texte)")
                self._history.append(candidate.content)
                return text

            # Exécuter les outils
            fn_response_parts = []
            for fc in fn_calls:
                name = fc.name
                args = dict(fc.args) if fc.args else {}
                print(f"  🔧 {name}({json.dumps(args, ensure_ascii=False)[:60]})")
                result = _run_tool(name, args)
                print(f"  ↳  {result[:80]}")
                fn_response_parts.append(
                    gtypes.Part(
                        function_response=gtypes.FunctionResponse(
                            name=name,
                            response={"result": result},
                        )
                    )
                )

            # Ajouter dans l'historique
            self._history.append(candidate.content)
            self._history.append(gtypes.Content(role="user", parts=fn_response_parts))

        return "⚠️ Limite de tours de function calling atteinte."

    def chat_loop(self) -> None:
        """REPL interactif dans le terminal."""
        print("\n" + "=" * 55)
        print("  Nokido × Gemini MCP — Chat interactif")
        print("  'exit' pour quitter | 'tools' pour la liste")
        print("=" * 55 + "\n")

        while True:
            try:
                msg = input("Toi > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not msg:
                continue
            if msg.lower() in ("exit", "quit"):
                break
            if msg.lower() == "tools":
                for t in _CATALOG:
                    print(f"  {t['name']:30s} {t['description'][:50]}")
                continue
            print("Gemini > ", end="", flush=True)
            try:
                print(self.chat(msg))
            except Exception as e:
                print(f"❌ {e}")
            print()


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY manquante dans Nokido.env")
        sys.exit(1)

    proxy = GeminiMCPProxy()

    if len(sys.argv) > 1:
        print(proxy.chat(" ".join(sys.argv[1:])))
    else:
        proxy.chat_loop()
