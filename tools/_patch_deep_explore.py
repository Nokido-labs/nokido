#!/usr/bin/env python3
"""_patch_deep_explore.py — migration #1+#2 : enregistre l'outil honeypot
`forge_deep_explore` + insère le coupe-circuit comportemental serveur dans
app/forge_mcp_registry.py. Idempotent-safe : ABORT si un ancrage n'est pas
trouvé exactement 1x (zéro écriture partielle) + validation compile() avant write.

Lancé via hub `run action=trusted_script` (LaForgeTrusted écrit là où le
sandbox est EPERM). Anti-fuite-tokens : cf. forge_recon_breaker + forge_tool_gate.
"""
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
F = ROOT / "app" / "forge_mcp_registry.py"
src = F.read_text(encoding="utf-8")

if "forge_deep_explore" in src:
    print("SKIP: forge_deep_explore déjà présent (idempotent)")
    sys.exit(0)

EDITS = []

EDITS.append((
'''    _TOOL_MIN_RING: dict = {
        "forge_call_dynamic": 2,''',
'''    _TOOL_MIN_RING: dict = {
        "forge_deep_explore": 4,
        "forge_call_dynamic": 2,'''))

EDITS.append((
'''    _TOOLS_PUBLIC: set = {"web_search", "ask", "hub"}''',
'''    _TOOLS_PUBLIC: set = {"web_search", "ask", "hub", "forge_deep_explore"}'''))

EDITS.append((
'''    def _raw_tool_catalog(self) -> List[Dict[str, Any]]:
        """Catalogue brut (sans injection de `explanation`)."""
        return [
            {
                "name": "exegol",''',
'''    def _raw_tool_catalog(self) -> List[Dict[str, Any]]:
        """Catalogue brut (sans injection de `explanation`)."""
        return [
            {
                "name": "forge_deep_explore",
                "description": (
                    "USE THIS FIRST for ANY codebase exploration, deep read, multi-file "
                    "recon, or 'understand how X works' on Nokido. Do NOT use native "
                    "search/read or Agent(Explore) for this. Pass your GOAL; the LOCAL "
                    "Nokido network runs the heavy reconnaissance for FREE (0 cloud "
                    "token) and returns a condensed summary with file:line references."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "intent": {"type": "string", "description": "What you want to understand (natural-language goal)."},
                        "target": {"type": "string", "description": "Optional regex/keywords (| = OR) to focus the search."},
                        "globs": {"type": "string", "description": "Optional comma globs (default app/forge_*.py,tools/*.py)."},
                        "breadth": {"type": "string", "enum": ["narrow", "medium", "wide"], "description": "Search breadth (default medium)."},
                    },
                    "required": ["intent"],
                },
            },
            {
                "name": "exegol",'''))

EDITS.append((
'''        except ImportError:
            pass  # forge_mcp_rbac absent : fallback open (compat boot)''',
'''        except ImportError:
            pass  # forge_mcp_rbac absent : fallback open (compat boot)

        # Coupe-circuit COMPORTEMENTAL (anti-fuite-tokens) : throttle la recon FINE
        # (tool `read`) sur du code Nokido, pour TOUT client MCP (agy inclus, sans
        # hook) -> force forge_deep_explore. Compteur en memoire (process hub). Fail-open.
        if name == "read":
            try:
                import sys as _sys
                from pathlib import Path as _P
                _tp = str(_P(__file__).resolve().parent.parent / "tools")
                if _tp not in _sys.path:
                    _sys.path.insert(0, _tp)
                from forge_recon_breaker import verdict_mem, is_nokido_args  # type: ignore
                _v, _why, _n = verdict_mem(agent or "UNKNOWN", "read", is_nokido_args(args))
                if _v == "deny":
                    return {"error": "recon_throttled", "reason": _why,
                            "tool": name, "delegate_to": "forge_deep_explore"}
            except Exception:
                pass'''))

EDITS.append((
'''        if name == "forge_spawn_swarm":
            return await self._handle_spawn_swarm(name, args, agent, ring)''',
'''        if name == "forge_deep_explore":
            return await self._handle_deep_explore(args, agent, ring)

        if name == "forge_spawn_swarm":
            return await self._handle_spawn_swarm(name, args, agent, ring)'''))

EDITS.append((
'''    async def dispatch(self, name: str, args: Dict[str, Any], agent: str, ring: int) -> Union[str, Dict[str, Any]]:''',
'''    async def _handle_deep_explore(self, args: Dict[str, Any], agent: str, ring: int) -> Dict[str, Any]:
        """Honeypot de delegation : recon LOCALE souveraine (0 token cloud).

        Capte les intentions d'exploration que les clients enverraient sinon en
        Agent(Explore)/reads natifs (fuite tokens). Wrappe forge_local_explore :
        recherche deterministe (regex) sur globs + synthese via modele LOCAL."""
        import asyncio as _aio
        intent = str(args.get("intent") or "").strip()
        if not intent:
            return {"error": "intent requis", "hint": "forge_deep_explore{intent, target?, globs?, breadth?}"}
        query = str(args.get("target") or intent)
        globs = str(args.get("globs") or "app/forge_*.py,tools/*.py")
        breadth = str(args.get("breadth") or "medium")
        max_hits = {"narrow": 40, "medium": 90, "wide": 180}.get(breadth, 90)

        def _run():
            import sys as _s
            from pathlib import Path as _P
            _tp = str(_P(__file__).resolve().parent.parent / "tools")
            if _tp not in _s.path:
                _s.path.insert(0, _tp)
            import forge_local_explore as fle  # type: ignore
            _globs = [g.strip() for g in globs.split(",") if g.strip()]
            _res = fle.search(query, _globs, context=2, max_hits=max_hits)
            _syn = fle.synth_local(intent, _res.get("hits", []), None)
            return _res, _syn

        try:
            res, synth = await _aio.to_thread(_run)
        except Exception as e:  # noqa: BLE001
            return {"error": f"deep_explore: {type(e).__name__}: {str(e)[:120]}"}
        hits = res.get("hits", [])
        files = sorted({h.get("file", "") for h in hits})
        return {
            "ok": True,
            "intent": intent,
            "synthesis": synth,
            "files_touched": files[:40],
            "n_hits": len(hits),
            "note": "recon LOCALE souveraine (0 token cloud). Affine via {target, globs, breadth}.",
        }

    async def dispatch(self, name: str, args: Dict[str, Any], agent: str, ring: int) -> Union[str, Dict[str, Any]]:'''))

for i, (old, new) in enumerate(EDITS, 1):
    c = src.count(old)
    if c != 1:
        print(f"ABORT E{i}: {c} matches (need exactly 1)")
        sys.exit(1)
    src = src.replace(old, new)

try:
    compile(src, str(F), "exec")
except SyntaxError as e:
    print(f"ABORT: SyntaxError after patch: {e}")
    sys.exit(2)

try:
    F.write_text(src, encoding="utf-8")
except Exception as e:
    print(f"WRITE_FAIL: {type(e).__name__}: {e}")
    sys.exit(3)

print(f"OK: forge_mcp_registry.py patched ({len(EDITS)} edits, {len(src)} bytes, compile OK)")
