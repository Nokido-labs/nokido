#!/usr/bin/env python3
"""_patch_ensure_service.py — enregistre le Bouton Rouge nokido_ensure_service dans
forge_mcp_registry : catalogue + _TOOL_MIN_RING + _TOOLS_PUBLIC + dispatch + handler.
(forge_tools DB + _ALLOWED_TOOLS = gérés par _grant_ensure_service.py). Idempotent."""
import sys
import pathlib

F = pathlib.Path(__file__).resolve().parent.parent / "app" / "forge_mcp_registry.py"
src = F.read_text(encoding="utf-8")

if "nokido_ensure_service" in src:
    print("SKIP: déjà présent")
    sys.exit(0)

EDITS = []

# 1) _TOOL_MIN_RING
EDITS.append((
'''    _TOOL_MIN_RING: dict = {
        "forge_deep_explore": 4,
        "forge_call_dynamic": 2,''',
'''    _TOOL_MIN_RING: dict = {
        "nokido_ensure_service": 4,
        "forge_deep_explore": 4,
        "forge_call_dynamic": 2,'''))

# 2) _TOOLS_PUBLIC
EDITS.append((
'''    _TOOLS_PUBLIC: set = {"web_search", "ask", "hub", "forge_deep_explore"}''',
'''    _TOOLS_PUBLIC: set = {"web_search", "ask", "hub", "forge_deep_explore", "nokido_ensure_service"}'''))

# 3) catalogue (avant forge_deep_explore)
EDITS.append((
'''    def _raw_tool_catalog(self) -> List[Dict[str, Any]]:
        """Catalogue brut (sans injection de `explanation`)."""
        return [
            {
                "name": "forge_deep_explore",''',
'''    def _raw_tool_catalog(self) -> List[Dict[str, Any]]:
        """Catalogue brut (sans injection de `explanation`)."""
        return [
            {
                "name": "nokido_ensure_service",
                "description": (
                    "USE THIS to guarantee a Nokido service is in a desired state "
                    "(docker, searxng, hub, ollama, netcfg, webhub, graph, embed, lmstudio). "
                    "Do NOT write keeper/diagnostic scripts, do NOT run docker commands, do "
                    "NOT diagnose manually. The Hub owns the privileges (SeTcbPrivilege), "
                    "daemons and containers. You are a CLIENT: declare the intent, the Hub "
                    "makes it true."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "docker | searxng | hub | ollama | netcfg | webhub | graph | embed | lmstudio (or a Nokido<Name>)."},
                        "desired_state": {"type": "string", "enum": ["running", "stopped", "restarted"], "description": "Desired state (default running)."},
                    },
                    "required": ["service"],
                },
            },
            {
                "name": "forge_deep_explore",'''))

# 4) dispatch
EDITS.append((
'''        if name == "forge_deep_explore":
            return await self._handle_deep_explore(args, agent, ring)''',
'''        if name == "nokido_ensure_service":
            return await self._handle_ensure_service(args, agent, ring)

        if name == "forge_deep_explore":
            return await self._handle_deep_explore(args, agent, ring)'''))

# 5) handler method (avant _handle_deep_explore)
EDITS.append((
'''    async def _handle_deep_explore(self, args: Dict[str, Any], agent: str, ring: int) -> Dict[str, Any]:''',
'''    async def _handle_ensure_service(self, args: Dict[str, Any], agent: str, ring: int) -> Dict[str, Any]:
        """Bouton rouge declaratif : {service, desired_state} -> orchestration SERVIE
        (LaForgeTrusted: forge_docker_agent/keeper/forge_supervisor_ctl). Le client
        DECLARE ; l'imperatif (privileges/daemons/conteneurs) reste cote hub."""
        import asyncio as _aio
        import json as _json
        import re as _re
        from pathlib import Path as _P
        svc = str(args.get("service") or "").strip()
        state = str(args.get("desired_state") or "running").strip()
        if not svc:
            return {"error": "service requis", "hint": "nokido_ensure_service{service, desired_state}"}
        if not _re.match(r"^[A-Za-z0-9_\\-]{1,40}$", svc) or not _re.match(r"^[A-Za-z]{1,16}$", state):
            return {"error": "service/desired_state invalides (alphanum)"}
        script = str(_P(__file__).resolve().parent.parent / "tools" / "forge_ensure_service.py")
        try:
            from forge_python_bin import LAFORGE_PYTHON as _PY
        except Exception:
            _PY = __import__("os").path.expanduser(r"~/miniforge3/python.exe")
        cmd = f'"{_PY}" "{script}" --service {svc} --state {state}'
        try:
            from forge_sandbox_exec import spawn_as_trusted
            r = await _aio.to_thread(lambda: spawn_as_trusted(cmd, timeout=200))
        except Exception as e:  # noqa: BLE001
            return {"error": f"ensure_service: {type(e).__name__}: {str(e)[:120]}"}
        out = (r.get("stdout") or "").strip() if isinstance(r, dict) else str(r)
        try:
            return _json.loads(out.splitlines()[-1])
        except Exception:
            return {"success": False, "detail": (out[-300:] or "no output"),
                    "exit": (r.get("exit_code") if isinstance(r, dict) else None)}

    async def _handle_deep_explore(self, args: Dict[str, Any], agent: str, ring: int) -> Dict[str, Any]:'''))

for i, (old, new) in enumerate(EDITS, 1):
    c = src.count(old)
    if c != 1:
        print(f"ABORT E{i}: {c} matches (need 1)")
        sys.exit(1)
    src = src.replace(old, new)

try:
    compile(src, str(F), "exec")
except SyntaxError as e:
    print(f"ABORT SyntaxError: {e}")
    sys.exit(2)

F.write_text(src, encoding="utf-8")
print(f"OK: nokido_ensure_service registered ({len(EDITS)} edits, compile OK)")
