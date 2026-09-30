# -*- coding: utf-8 -*-
"""One-shot patcher: Sprint 2 anti context-bomb sur app/forge_mcp_registry.py.

Greffe le verbe MCP `tool_scope` (scope dynamique du catalogue par agent,
delegue a app/forge_tool_scope.py) :
  A. handler async handle_tool_scope (to_thread, fail-safe M2M codes) ;
  B. filtre de VISIBILITE dans get_tool_list (scope ∪ CORE, best-effort,
     insere AVANT la vue compacte Sprint 1 — les deux composent) ;
  C. entree catalogue `tool_scope` dans _raw_tool_catalog ;
  E. `tool_scope: 3` dans _TOOL_MIN_RING (visibilite ring<=3).

Le dispatch n'est PAS filtre : un outil hors scope reste appelable (fallback).

CRITICAL_FILE -> applique via owner trusted_script (chemin officiel), memes
garanties que forge_patch_mcpsec_fix3 : exact-match (count==1), idempotence,
compile() AVANT ecriture, newline preserve. Abort sans ecrire au moindre
mismatch. Re-runnable (idempotent).

Run : run action=trusted_script path=tools/forge_patch_registry_toolscope.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "app", "forge_mcp_registry.py")

# ── A : handler, insere avant le bloc compact (Sprint 1) ────────────────────
A_OLD = "    # ── Mode compact negocie par client (Sprint 1 anti context-bomb) ────────\n"
A_NEW = (
    '    async def handle_tool_scope(self, args: Dict[str, Any], agent: str, ring: int):\n'
    '        """Sprint 2 anti context-bomb : scope dynamique du catalogue par agent.\n'
    '        Delegue a forge_tool_scope (classifieur semantique LOCAL + etat +\n'
    '        push list_changed). Sync -> to_thread (embeddings = I/O, anti-wedge)."""\n'
    '        try:\n'
    '            import sys as _s, os as _o\n'
    '            _app = _o.path.dirname(_o.path.abspath(__file__))\n'
    '            if _app not in _s.path:\n'
    '                _s.path.insert(0, _app)\n'
    '            from forge_tool_scope import handle as _ts_handle\n'
    '            return await asyncio.to_thread(_ts_handle, dict(args or {}), agent, ring)\n'
    '        except Exception as e:  # noqa: BLE001 - jamais casser le dispatch\n'
    '            return {"intent_code": "ERR_SCOPE_INTERNAL", "error": str(e)[:200]}\n'
    '\n'
) + A_OLD

# ── B : filtre de visibilite dans get_tool_list, avant la vue compacte ──────
B_OLD = (
    '        # Sprint 1 anti context-bomb : vue telegraphique NEGOCIEE par client.\n'
    '        ca = self._compact_agents()\n'
)
B_NEW = (
    '        # Sprint 2 : scope dynamique par agent (tool_scope). VISIBILITE seule —\n'
    '        # le dispatch reste ouvert (un outil hors scope demeure appelable).\n'
    '        try:\n'
    '            from forge_tool_scope import active_tools_for as _ts_active\n'
    '            _scope = _ts_active(agent)\n'
    '            if _scope:\n'
    '                visible = [t for t in visible if t["name"] in _scope]\n'
    '        except Exception:\n'
    '            pass  # scope best-effort : jamais casser tools/list\n'
) + B_OLD

# ── C : entree catalogue (avant agy_run, 1re entree du catalogue statique) ──
C_OLD = (
    '            {\n'
    '                "name": "agy_run",\n'
)
C_NEW = (
    '            {\n'
    '                "name": "tool_scope",\n'
    '                "description": "Scope dynamique du catalogue MCP (anti context-bomb). action=set|clear|status. set: intent -> classifieur semantique LOCAL -> tools/list reduit au groupe pertinent + CORE (push list_changed). Reponses M2M intent codes.",\n'
    '                "inputSchema": {\n'
    '                    "type": "object",\n'
    '                    "properties": {\n'
    '                        "action": {"type": "string", "enum": ["set", "clear", "status"]},\n'
    '                        "intent": {"type": "string", "description": "But de la session (action=set)"},\n'
    '                        "target_agent": {"type": "string", "description": "Agent vise (defaut: appelant ; autre = ring<=1)"},\n'
    '                    },\n'
    '                    "required": ["action"],\n'
    '                },\n'
    '            },\n'
) + C_OLD

# ── E : ring de visibilite ───────────────────────────────────────────────────
E_OLD = (
    '        "forge_deep_explore": 4,\n'
    '        "forge_call_dynamic": 2,\n'
)
E_NEW = '        "tool_scope": 3,\n' + E_OLD

raw = open(TARGET, "rb").read().decode("utf-8")
nl = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

if "handle_tool_scope" in text:
    print("ABORT: already patched (idempotent no-op)")
    sys.exit(3)

for label, old in (("A", A_OLD), ("B", B_OLD), ("C", C_OLD), ("E", E_OLD)):
    n = text.count(old)
    if n != 1:
        print(f"ABORT: block {label} found {n} times (expected exactly 1) -> no write")
        sys.exit(2)

text = text.replace(A_OLD, A_NEW, 1)
text = text.replace(B_OLD, B_NEW, 1)
text = text.replace(C_OLD, C_NEW, 1)
text = text.replace(E_OLD, E_NEW, 1)

try:
    compile(text, TARGET, "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch -> no write: {e}")
    sys.exit(4)

open(TARGET, "wb").write(text.replace("\n", nl).encode("utf-8"))
print(f"OK: tool_scope grafted (A handler, B filter, C catalog, E ring) + AST valid. newline={nl!r}")
