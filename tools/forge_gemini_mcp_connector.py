"""
forge_gemini_mcp_connector.py — Connecteur Gemini ↔ MCP Nokido (dynamique)
============================================================================
SDK : google-genai >= 1.0  (pip install google-genai)

Fonctionnement :
  1. _fetch_mcp_tools()  → GET http://localhost:9999/tools/list  (schéma live)
  2. _mcp_to_gemini()    → traduction MCP JSON Schema → gtypes.FunctionDeclaration
  3. Boucle chat         → Gemini émet functionCall → exécution via :9999 → functionResponse
  4. Thought signatures  → affiche le raisonnement interne de Gemini (si supporté)

Usage :
  # Démarrer le serveur MCP (terminal 1)
  python app/mcp_server_tools.py --transport sse --port 9999

  # Lancer le chat (terminal 2)
  python tools/forge_gemini_mcp_connector.py

  # Prompt unique
  python tools/forge_gemini_mcp_connector.py "état du swarm et derniers events ?"
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

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
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-preview-05-20")
MCP_BASE_URL = os.environ.get("MCP_BASE_URL", "http://localhost:9999")
MCP_SCRIPT = str(ROOT / "app" / "mcp_server_tools.py")

# ── SDK Gemini ────────────────────────────────────────────────────────────────
try:
    from google import genai
    from google.genai import types as gt
except ImportError:
    print("❌  pip install google-genai")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# 1 — Récupération dynamique des outils depuis le serveur MCP
# ══════════════════════════════════════════════════════════════════════════════


def _fetch_mcp_tools() -> list[dict]:
    """Récupère le schéma des outils depuis le serveur MCP SSE.

    Essaie d'abord l'endpoint HTTP REST /tools/list (FastMCP expose ça).
    Fallback : import direct de mcp_server_tools et introspection AST.

    Returns:
        Liste de dicts {name, description, inputSchema} au format MCP.
    """
    # ── Tentative HTTP ────────────────────────────────────────────────────────
    for endpoint in [
        f"{MCP_BASE_URL}/tools/list",
        f"{MCP_BASE_URL}/list_tools",
    ]:
        try:
            req = urllib.request.Request(
                endpoint,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read())
                tools = data.get("tools") or data
                if isinstance(tools, list) and tools:
                    print(f"  🌐 {len(tools)} outils récupérés depuis {endpoint}")
                    return tools
        except Exception:
            pass

    # ── Fallback : introspection des fonctions mcp_server_tools.py ───────────
    import ast

    print("  📄 Serveur MCP hors-ligne — introspection statique du fichier")
    src = Path(MCP_SCRIPT).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    tools = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Ne garder que les fonctions décorées @mcp.tool()
        is_mcp_tool = any(
            (isinstance(d, ast.Call) and getattr(getattr(d, "func", None), "attr", "") == "tool")
            or (isinstance(d, ast.Attribute) and d.attr == "tool")
            for d in node.decorator_list
        )
        if not is_mcp_tool:
            continue

        doc = ast.get_docstring(node) or f"{node.name} tool"
        params = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        for arg in node.args.args:
            if arg.arg in ("self", "cls"):
                continue
            # Deviner le type depuis l'annotation
            ann = arg.annotation
            if isinstance(ann, ast.Name):
                atype = {
                    "str": "string",
                    "int": "integer",
                    "float": "number",
                    "bool": "boolean",
                    "dict": "object",
                    "list": "array",
                }.get(ann.id, "string")
            else:
                atype = "string"
            params["properties"][arg.arg] = {
                "type": atype,
                "description": arg.arg,
            }

        # Args sans default = required
        n_defaults = len(node.args.defaults)
        n_args = len([a for a in node.args.args if a.arg not in ("self", "cls")])
        required = [
            a.arg for a in node.args.args[: n_args - n_defaults] if a.arg not in ("self", "cls")
        ]
        params["required"] = required

        tools.append(
            {
                "name": node.name,
                "description": doc.split("\n")[0][:120],
                "inputSchema": params,
            }
        )

    print(f"  📄 {len(tools)} outils extraits par introspection")
    return tools


# ══════════════════════════════════════════════════════════════════════════════
# 2 — Traduction MCP JSON Schema → FunctionDeclaration Gemini
# ══════════════════════════════════════════════════════════════════════════════

_JSON_TO_GEMINI = {
    "string": gt.Type.STRING,
    "integer": gt.Type.INTEGER,
    "number": gt.Type.NUMBER,
    "boolean": gt.Type.BOOLEAN,
    "array": gt.Type.ARRAY,
    "object": gt.Type.OBJECT,
}


def _json_schema_to_gemini(schema: dict) -> gt.Schema:
    """Convertit un JSON Schema en gtypes.Schema Gemini (récursif).

    Args:
        schema: JSON Schema dict (type, properties, items, description…).

    Returns:
        gtypes.Schema compatible Gemini Function Calling.
    """
    stype = _JSON_TO_GEMINI.get(schema.get("type", "string"), gt.Type.STRING)
    props = {}

    for pname, pschema in schema.get("properties", {}).items():
        props[pname] = _json_schema_to_gemini(pschema)

    return gt.Schema(
        type=stype,
        description=schema.get("description", ""),
        properties=props or None,
        required=schema.get("required") or None,
        items=_json_schema_to_gemini(schema["items"]) if "items" in schema else None,
        enum=schema.get("enum") or None,
    )


def _mcp_tools_to_gemini(mcp_tools: list[dict]) -> gt.Tool:
    """Traduit une liste d'outils MCP en gt.Tool pour Gemini.

    Args:
        mcp_tools: Liste de dicts {name, description, inputSchema}.

    Returns:
        gt.Tool contenant toutes les FunctionDeclaration.
    """
    decls = []
    for t in mcp_tools:
        schema = t.get("inputSchema") or t.get("input_schema") or {}
        params = _json_schema_to_gemini(schema) if schema.get("properties") else None
        decls.append(
            gt.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", t["name"]),
                parameters=params,
            )
        )
    return gt.Tool(function_declarations=decls)


# ══════════════════════════════════════════════════════════════════════════════
# 3 — Exécution d'un outil MCP
# ══════════════════════════════════════════════════════════════════════════════


def _execute_tool(tool_name: str, args: dict) -> str:
    """Exécute un outil MCP — HTTP si le serveur tourne, import direct sinon.

    Args:
        tool_name: Nom de l'outil.
        args: Arguments de l'appel.

    Returns:
        Résultat JSON ou texte de l'outil.
    """
    # ── HTTP POST vers le serveur SSE ─────────────────────────────────────────
    for endpoint in [
        f"{MCP_BASE_URL}/tools/call",
        f"{MCP_BASE_URL}/call_tool",
    ]:
        try:
            payload = json.dumps({"name": tool_name, "arguments": args}).encode()
            req = urllib.request.Request(
                endpoint,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                content = data.get("content") or data
                if isinstance(content, list) and content:
                    return content[0].get("text", str(content[0]))
                return str(data)
        except Exception:
            pass

    # ── Fallback import direct ────────────────────────────────────────────────
    import asyncio
    import importlib.util

    spec = importlib.util.spec_from_file_location("_mcp", MCP_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        return json.dumps({"error": f"import: {e}"})

    fn = getattr(mod, tool_name, None)
    if fn is None:
        return json.dumps({"error": f"'{tool_name}' introuvable"})

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


# ══════════════════════════════════════════════════════════════════════════════
# 4 — Connecteur principal
# ══════════════════════════════════════════════════════════════════════════════


class GeminiMCPConnector:
    """Connecteur Gemini ↔ MCP Nokido avec récupération dynamique des outils."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "",
        thinking: bool = True,
    ) -> None:
        """Initialise le connecteur.

        Args:
            api_key:  Clé API Gemini (défaut : GEMINI_API_KEY env).
            model:    Modèle Gemini (défaut : GEMINI_MODEL env).
            thinking: Activer les thought signatures (Gemini 2.5).

        Raises:
            ValueError: Si aucune clé API disponible.
        """
        key = api_key or GEMINI_API_KEY
        if not key:
            raise ValueError("GEMINI_API_KEY manquante dans Nokido.env")

        self._client = genai.Client(api_key=key)
        self._model = model or GEMINI_MODEL
        self._thinking = thinking
        self._history: list[gt.Content] = []

        # Récupération dynamique des outils (à chaque démarrage de session)
        print(f"🔍 Récupération des outils MCP depuis {MCP_BASE_URL}...")
        mcp_tools = _fetch_mcp_tools()
        self._tools = [_mcp_tools_to_gemini(mcp_tools)]
        self._n_tools = len(mcp_tools)

        # Config de génération
        thinking_cfg = gt.ThinkingConfig(include_thoughts=True) if thinking else None
        self._config = gt.GenerateContentConfig(
            tools=self._tools,
            thinking_config=thinking_cfg,
            system_instruction=(
                "Tu es l'assistant de pilotage de Nokido v17, moteur d'évolution "
                "de code multi-agents sur Ryzen 8700G iGPU. "
                f"Tu as accès à {self._n_tools} outils MCP locaux. "
                "Utilise-les proactivement — ne dis pas ce que tu pourrais faire, fais-le. "
                "Réponse concise et technique. Langue : français."
            ),
        )
        print(f"✅ Connecteur prêt — {self._model} — {self._n_tools} outils")

    # ── Boucle function calling ───────────────────────────────────────────────

    def _handle_response(self, response: Any) -> tuple[str, str]:
        """Extrait texte + pensées d'une réponse Gemini.

        Args:
            response: Objet GenerateContentResponse de Gemini.

        Returns:
            Tuple (texte_final, pensées) où pensées peut être vide.
        """
        parts = response.candidates[0].content.parts
        text = ""
        thoughts = ""
        for p in parts:
            if getattr(p, "thought", False):
                thoughts += getattr(p, "text", "")
            elif getattr(p, "text", None):
                text += p.text
        return text, thoughts

    def chat(self, user_message: str, show_thinking: bool = False) -> str:
        """Envoie un message à Gemini avec boucle d'appels d'outils.

        Args:
            user_message:  Message de l'utilisateur.
            show_thinking: Afficher les thought signatures si disponibles.

        Returns:
            Réponse finale de Gemini.
        """
        self._history.append(gt.Content(role="user", parts=[gt.Part(text=user_message)]))

        for _turn in range(8):
            response = self._client.models.generate_content(
                model=self._model,
                contents=self._history,
                config=self._config,
            )
            candidate = response.candidates[0]
            parts = candidate.content.parts

            # ── Thought signatures (Gemini 2.5) ──────────────────────────────
            if show_thinking and self._thinking:
                thoughts = [p.text for p in parts if getattr(p, "thought", False)]
                if thoughts:
                    print("\n💭 [Pensées de Gemini]")
                    for t in thoughts:
                        print(f"  {t[:200]}")
                    print()

            # ── Function calls ────────────────────────────────────────────────
            fn_calls = [
                p.function_call
                for p in parts
                if getattr(p, "function_call", None) and p.function_call.name
            ]

            if not fn_calls:
                # Réponse finale
                text = next(
                    (
                        p.text
                        for p in parts
                        if getattr(p, "text", None) and not getattr(p, "thought", False)
                    ),
                    "",
                )
                self._history.append(candidate.content)
                return text or "(réponse vide)"

            # ── Exécution des outils ──────────────────────────────────────────
            fn_response_parts = []
            for fc in fn_calls:
                name = fc.name
                args = dict(fc.args) if fc.args else {}
                print(f"  🔧 {name}({json.dumps(args, ensure_ascii=False)[:70]})")
                result = _execute_tool(name, args)
                print(f"  ↳  {result[:100]}")
                fn_response_parts.append(
                    gt.Part(
                        function_response=gt.FunctionResponse(
                            name=name,
                            response={"result": result},
                        )
                    )
                )

            self._history.append(candidate.content)
            self._history.append(gt.Content(role="user", parts=fn_response_parts))

        return "⚠️ Boucle tool-use trop longue."

    def refresh_tools(self) -> None:
        """Resynchronise les outils depuis le serveur MCP (appeler si changement).

        Directive sécurité [2026-03-22] : toujours re-fetch avant une nouvelle mission.
        """
        print("🔄 Resynchronisation des outils MCP...")
        mcp_tools = _fetch_mcp_tools()
        self._tools = [_mcp_tools_to_gemini(mcp_tools)]
        self._n_tools = len(mcp_tools)
        self._config = gt.GenerateContentConfig(
            tools=self._tools,
            thinking_config=gt.ThinkingConfig(include_thoughts=True) if self._thinking else None,
            system_instruction=self._config.system_instruction,
        )
        print(f"✅ {self._n_tools} outils synchronisés")

    def chat_loop(self, show_thinking: bool = False) -> None:
        """REPL interactif dans le terminal.

        Args:
            show_thinking: Afficher les thought signatures Gemini 2.5.
        """
        print("\n" + "═" * 58)
        print(f"  Nokido × Gemini MCP — {self._model}")
        print(f"  {self._n_tools} outils | 'exit' 'tools' 'think' 'refresh'")
        print("═" * 58 + "\n")

        while True:
            try:
                msg = input("Toi > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nAu revoir.")
                break
            if not msg:
                continue

            match msg.lower():
                case "exit" | "quit":
                    break
                case "tools":
                    # Ré-afficher les outils disponibles
                    tools_resp = _fetch_mcp_tools()
                    print(f"\n{len(tools_resp)} outils MCP disponibles :")
                    for t in tools_resp:
                        print(f"  {t['name']:35s} {t.get('description', '')[:50]}")
                    print()
                    continue
                case "think":
                    show_thinking = not show_thinking
                    print(f"Thought signatures : {'ON' if show_thinking else 'OFF'}\n")
                    continue
                case "refresh":
                    self.refresh_tools()
                    continue

            print("Gemini > ", end="", flush=True)
            try:
                reply = self.chat(msg, show_thinking=show_thinking)
                print(reply)
            except Exception as e:
                print(f"❌ {e}")
            print()


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gemini ↔ MCP Nokido connector")
    parser.add_argument("prompt", nargs="*", help="Prompt unique (si absent → mode chat)")
    parser.add_argument("--model", default="", help="Override modèle Gemini")
    parser.add_argument("--think", action="store_true", help="Afficher les thought signatures")
    parser.add_argument("--no-think", action="store_true", help="Désactiver le thinking")
    args = parser.parse_args()

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY manquante dans Nokido.env")
        sys.exit(1)

    connector = GeminiMCPConnector(
        model=args.model,
        thinking=not args.no_think,
    )

    if args.prompt:
        reply = connector.chat(" ".join(args.prompt), show_thinking=args.think)
        print(reply)
    else:
        connector.chat_loop(show_thinking=args.think)
