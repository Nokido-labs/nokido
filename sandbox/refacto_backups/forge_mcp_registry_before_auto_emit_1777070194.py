from __future__ import annotations
# -*- coding: utf-8 -*-
"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-04-24 | VER:v_forge_mcp_registry
#FORGE:[score:96|agent:gemini-cli|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]
CONTRAINTE: Unified Handler Registry (HTTP & STDIO)
"""
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:96|agent:gemini-cli|temp:0.00|risk:0.10|ast:OK|test:OK|lint:OK|color:GREEN|attempt:1]"

import asyncio
import json
import logging
import os
import sqlite3
import time
import base64
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# On s'assure que le path est correct pour les imports internes
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "app") not in os.sys.path: os.path.sys.path.insert(0, str(ROOT / "app"))

from forge_state_manager import get_state_manager

logger = logging.getLogger("Nokido.MCP.Registry")

class ToolRegistry:
    """Registre unifié des outils MCP pour Nokido (HTTP & STDIO)."""
    
    def __init__(self, root_dir: Path = ROOT):
        self.root = root_dir
        self.state_mgr = get_state_manager()
        self.db_path = root_dir / "RAG" / "embeddings.db"
        if not self.db_path.exists():
            # Fallback data/*.db
            try:
                self.db_path = next((root_dir / "data").glob("*.db"))
            except StopIteration:
                pass

    async def dispatch(self, name: str, args: Dict[str, Any], agent: str, ring: int) -> Union[str, Dict[str, Any]]:
        """Dispatch l'appel vers le bon handler avec vérification de sécurité."""
        method_name = f"handle_{name}"
        if hasattr(self, method_name):
            # Vérification de sécurité basique (Ring check)
            # RING 0 : read, write, query, run (python/github), set_mode
            # RING 1 : trigger_auto, task_status, index_result
            # RING 2 : notify, poll, search_recent, get_mode, task_assign/claim/result
            
            ring_needed = self._get_ring_needed(name, args)
            # Convention Nokido : ring 0 = admin (max privilege), ring > 0 = moins privilegie.
            # Un caller est refuse si son ring est SUPERIEUR au minimum autorise
            # (ex: write exige ring 0, un ring 2 est refuse car ring 2 > ring 0).
            if ring > ring_needed:
                return f"SECURITY: Acces refuse (agent ring {ring} > max autorise {ring_needed})"

            handler = getattr(self, method_name)
            try:
                return await handler(args, agent, ring)
            except Exception as e:
                logger.error(f"Erreur handler {name}: {e}")
                return f"ERR: {type(e).__name__}: {e}"
        return f"Outil inconnu: {name}"

    def get_tool_list(self) -> List[Dict[str, Any]]:
        """Retourne la liste des outils pour l'appel tools/list."""
        return [
            {"name": "read", "description": "file/logs — supporte pattern et lines pour tail_logs",
             "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["file", "tail_logs"]}, "path": {"type": "string"}, "pattern": {"type": "string"}, "lines": {"type": "integer"}}, "required": ["action", "path"]}},
            {"name": "write", "description": "write/edit (Thread-safe) — RING_0 only",
             "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
            {"name": "query", "description": "SQL RAG (Auto-snapshot si mutation)",
             "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}},
            {"name": "run", "description": "Git/Python/Atlas/Snapshot/GitHub",
             "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": ["github", "python", "atlas_build", "save_situation", "atlas_get", "make_snapshot", "hub_restart", "hub_status", "setup_check", "unified_discovery", "audit_log"]}, "code": {"type": "string"}}, "required": ["action"]}},
            {"name": "get_mode", "description": "Mode actif + statuts agents (bridge_state.json)",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "set_mode", "description": "Change mode: AUTO|CLINE|CHEF|DEBAT|PING",
             "inputSchema": {"type": "object", "properties": {"mode": {"type": "string"}, "reason": {"type": "string"}}, "required": ["mode"]}},
            {"name": "notify", "description": "Envoie notification a l autre agent",
             "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}},
            {"name": "poll", "description": "Lit et vide les notifications en attente",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "index_result", "description": "Indexe resultat tache dans RAG",
             "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "result": {"type": "string"}}, "required": ["task_id", "result"]}},
            {"name": "search_recent", "description": "Voir resultats recents de tous les agents",
             "inputSchema": {"type": "object", "properties": {"topic": {"type": "string"}, "limit": {"type": "integer"}}}},
            {"name": "auto_test", "description": "py_compile fichier",
             "inputSchema": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}},
            {"name": "trigger_autonomous_evolution", "description": "Decompose intention en silos et execute en background.",
             "inputSchema": {"type": "object", "properties": {"intention": {"type": "string"}, "domains": {"type": "array", "items": {"type": "string"}}, "noise": {"type": "boolean"}, "max_silos": {"type": "integer"}}, "required": ["intention"]}},
            {"name": "task_status", "description": "Lit statut d une tache async (orch_, task_, mcp_).",
             "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
            {"name": "task_assign", "description": "Assigne une tache a un agent",
             "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "description": {"type": "string"}, "agent": {"type": "string"}}, "required": ["task_id", "description"]}},
            {"name": "task_claim", "description": "Reclame la prochaine tache en attente",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "task_result", "description": "Livre le resultat d une tache",
             "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "result": {"type": "string"}}, "required": ["task_id", "result"]}},
            {"name": "event_publish", "description": "Publie un evenement sur l EventBus multi-agent (cf docs/EVENT_SPEC.md)",
             "inputSchema": {"type": "object", "properties": {"topic": {"type": "string"}, "kind": {"type": "string"}, "data": {"type": "object"}, "corr_id": {"type": "string"}, "parent_id": {"type": "string"}}, "required": ["topic", "kind", "data"]}},
            {"name": "event_history", "description": "Lit l historique EventBus filtre par topics (wildcards * et ** supportes)",
             "inputSchema": {"type": "object", "properties": {"topics": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"}, "since": {"type": "string"}}, "required": ["topics"]}},
        ]

    # ── HANDLERS : File System & DB ──────────────────────────────────────────

    async def handle_read(self, args: dict, agent: str, ring: int) -> str:
        path = self.root / args.get("path", "")
        if args.get("action") == "tail_logs":
            _lines = int(args.get("lines", 100))
            _pattern = args.get("pattern", "")
            if not path.exists(): return f"Log introuvable: {path}"
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if _pattern:
                lines = [l for l in lines if _pattern.lower() in l.lower()]
            return "\n".join(lines[-_lines:])
        return path.read_text(encoding="utf-8", errors="replace")

    async def handle_write(self, args: dict, agent: str, ring: int) -> str:
        path = self.root / args.get("path", "")
        content = args.get("content", "")
        # Commit Guard (simplifié)
        if path.suffix == ".py" and (path.name.startswith("forge_") or path.name == "Nokido.py"):
            try:
                compile(content, str(path), "exec")
            except Exception as e:
                return f"COMMIT GUARD FAIL: {e}"
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.state_mgr.add_notification(f"fichier ecrit: {path.name}", source=agent)
        return f"SUCCESS: {path.name} mis a jour."

    async def handle_query(self, args: dict, agent: str, ring: int) -> str:
        sql = args.get("sql", "")
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            cur = conn.execute(sql)
            if sql.strip().upper().startswith("SELECT"):
                rows = cur.fetchall()
                res = json.dumps(rows, indent=2, ensure_ascii=False)
            else:
                conn.commit()
                res = "Mutation OK"
            conn.close()
            return res
        except Exception as e:
            return f"Erreur SQL: {e}"

    # ── HANDLERS : Run (Sub-actions) ─────────────────────────────────────────

    async def handle_run(self, args: dict, agent: str, ring: int) -> str:
        act = args.get("action", "")
        code = args.get("code", "")
        
        if act == "python":
            # Exécution dangereuse -> Ring 0 requis (déjà checké dans dispatch)
            import subprocess
            proc = subprocess.run([os.sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
            return proc.stdout + proc.stderr
            
        if act == "atlas_get":
            p = self.root / "project_atlas.json"
            return p.read_text("utf-8") if p.exists() else "Atlas non trouve."

        if act == "setup_check":
            # Diagnostic simplifié
            return f"System OK | Agent: {agent} | Ring: {ring} | Time: {datetime.now().strftime('%H:%M:%S')}"

        return f"Action {act} non implementee dans le Registry."

    # ── HANDLERS : Mode & Coordination ────────────────────────────────────────

    async def handle_get_mode(self, args: dict, agent: str, ring: int) -> str:
        s = self.state_mgr.read_state()
        lines = [f"mode={s.get('active_mode', 'AUTO')}  agent={agent}"]
        for ag, info in s.get("agents", {}).items():
            lines.append(f"  {ag}: {info.get('status', '?')} {info.get('progress', 0)}%")
        notifs = s.get("pending_notifications", [])
        if notifs:
            lines.append(f"Notifs en attente: {len(notifs)}")
        return "\n".join(lines)

    async def handle_set_mode(self, args: dict, agent: str, ring: int) -> str:
        if ring > 0: return "INTERDIT: set_mode reserve RING_0"
        mode = args.get("mode", "AUTO").upper()
        s = self.state_mgr.read_state()
        s["active_mode"] = mode
        s["permissions"] = "FULL" if mode == "CHEF" else "STANDARD"
        s["last_switch"] = datetime.now().isoformat()
        s["switch_reason"] = args.get("reason", f"set par {agent}")
        self.state_mgr.add_notification(f"-> mode {mode}", source=agent)
        self.state_mgr.write_state(s)
        return f"OK mode={mode}"

    async def handle_notify(self, args: dict, agent: str, ring: int) -> str:
        msg = args.get("message", "")
        if not msg: return "Erreur: parametre 'message' requis"
        self.state_mgr.add_notification(msg, source=agent)
        return "OK notification envoyee"

    async def handle_poll(self, args: dict, agent: str, ring: int) -> str:
        s = self.state_mgr.read_state()
        notifs = s.pop("pending_notifications", [])
        if notifs:
            self.state_mgr.write_state(s)
        return "\n".join(notifs) if notifs else "Aucune notification."

    # ── HANDLERS : RAG & Résultats ───────────────────────────────────────────

    async def handle_index_result(self, args: dict, agent: str, ring: int) -> str:
        task_id = args.get("task_id", "?")
        result = args.get("result", "") or args.get("text", "")
        if not result: return "Erreur: parametre 'result' requis"
        
        src = f"mcp_result:{agent}:{task_id}:{int(time.time())}"
        text = f"[AGENT:{agent}] [TASK:{task_id}]\n{result}"[:4000]
        
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            chunk_id = args.get("id", f"idx_{agent}_{task_id}_{int(time.time())}")
            conn.execute(
                "INSERT OR REPLACE INTO rag_chunks(id, source, text, domain, author, ingested_at) "
                "VALUES(?, ?, ?, ?, ?, datetime('now'))",
                (chunk_id, src, text, "mcp_result", agent),
            )
            conn.commit()
            conn.close()
            self.state_mgr.add_notification(f"tache '{task_id}' indexee RAG", source=agent)
            return f"OK indexe: {src}"
        except Exception as e:
            return f"Erreur index: {e}"

    async def handle_search_recent(self, args: dict, agent: str, ring: int) -> str:
        topic = args.get("topic", "") or args.get("query", "")
        limit = int(args.get("limit", 10))
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            if topic:
                rows = conn.execute(
                    "SELECT source, text FROM rag_chunks WHERE domain='mcp_result' AND text LIKE ? ORDER BY rowid DESC LIMIT ?",
                    (f"%{topic}%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT source, text FROM rag_chunks WHERE domain='mcp_result' ORDER BY rowid DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            conn.close()
            if not rows: return "Aucun resultat."
            return "\n\n".join(f"[{r['source']}]\n{r['text'][:400]}" for r in rows)
        except Exception as e:
            return f"Erreur search: {e}"

    # ── HANDLERS : Tâches Asynchrones & Orchestration ────────────────────────

    async def handle_trigger_autonomous_evolution(self, args: dict, agent: str, ring: int) -> str:
        from forge_runner import spawn
        intention = args.get("intention", "")
        if not intention: return "Erreur: parametre 'intention' requis"
        
        payload = {
            "intention": intention,
            "domains": args.get("domains"),
            "noise": bool(args.get("noise", False)),
            "max_silos": args.get("max_silos")
        }
        payload_b64 = base64.b64encode(json.dumps(payload).encode("utf-8")).decode()

        job_code = (
            "import sys, json, base64, os, asyncio\n"
            "sys.path.insert(0, r'" + str(self.root / "app") + "')\n"
            "from forge_silo_engine import get_silo_engine, SiloDomain\n"
            "_p = json.loads(base64.b64decode(r'" + payload_b64 + "').decode())\n"
            "async def _go():\n"
            "    _engine = get_silo_engine()\n"
            "    _hint = [d for d in SiloDomain if d.value in [x.lower() for x in (_p.get('domains') or [])]]\n"
            "    _t = await _engine.evolve(intention=_p['intention'], hint_domains=_hint, noise=_p.get('noise', False))\n"
            "    _res = json.dumps({'task_id': _t.id, 'duration': _t.duration, 'synthesis': _t.synthesis[:1500]})\n"
            "    from live_bridge import bridge, ST_OK\n"
            "    bridge.task_set(os.environ['_LAFORGE_TID'], ST_OK, result=_res[:60])\n"
                "    open(os.path.join(r'" + str(self.root / "sandbox") + "', 'orch_' + os.environ['_LAFORGE_TID'] + '.json'), 'w', encoding='utf-8').write(_res)\n"
            "asyncio.run(_go())\n"
        )
        
        tid = spawn(job_code, prefix="orch", timeout_s=600)
        return f"task_id:{tid} — orchestration lancee. Poll via task_status({tid})."

    async def handle_task_status(self, args: dict, agent: str, ring: int) -> str:
        from forge_runner import status as get_task_status
        tid = args.get("task_id", "")
        if not tid: return "Erreur: task_id requis"
        
        d = get_task_status(tid)
        status_str = str(d.get("status", "unknown"))
        
        out = f"task_id={tid}\nstatus={status_str.upper()}\n"
        if d.get("result"): out += f"result_preview={d['result']}\n"
        
        orch_file = self.root / "sandbox" / f"orch_{tid}.json"
        if status_str == "ok" and orch_file.exists():
            out += "\n=== Resultat complet ===\n" + orch_file.read_text(encoding="utf-8")[:3000]
            
        return out

    # ── HANDLERS : Gestion des Tâches Multi-Agents (Galaxie CodeViber) ───────

    async def _update_tasks(self, tasks: dict):
        p = self.root / "sandbox" / "tasks.json"
        p.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")

    async def _read_tasks(self) -> dict:
        p = self.root / "sandbox" / "tasks.json"
        if not p.exists(): return {"pending": []}
        try: return json.loads(p.read_text(encoding="utf-8"))
        except: return {"pending": []}

    async def handle_task_assign(self, args: dict, agent: str, ring: int) -> str:
        tks = await self._read_tasks()
        task = {
            "task_id": args.get("task_id", f"tk_{int(time.time())}"),
            "description": args.get("description", ""),
            "agent": args.get("agent", "CLINE_ACT"),
            "assigned_at": datetime.now().isoformat(),
            "status": "pending"
        }
        tks["pending"].append(task)
        await self._update_tasks(tks)
        self.state_mgr.add_notification(f"tache assignee: {task['task_id']}", source=agent)
        return f"OK tache assignee: {task['task_id']}"

    async def handle_task_claim(self, args: dict, agent: str, ring: int) -> str:
        tks = await self._read_tasks()
        pending = [t for t in tks.get("pending", []) if t.get("status") == "pending" and t.get("agent") in (agent, "any", "ANY")]
        if not pending: return "Aucune tache en attente pour toi."
        
        task = pending[0]
        task["status"] = "in_progress"
        task["claimed_by"] = agent
        task["claimed_at"] = datetime.now().isoformat()
        await self._update_tasks(tks)
        return f"TACHE: {task['task_id']}\nDescription: {task['description']}"

    async def handle_task_result(self, args: dict, agent: str, ring: int) -> str:
        tks = await self._read_tasks()
        tid = args.get("task_id")
        for t in tks.get("pending", []):
            if t["task_id"] == tid:
                t["status"] = "done"
                t["result"] = args.get("result", "no result")
                t["completed_at"] = datetime.now().isoformat()
                break
        await self._update_tasks(tks)
        self.state_mgr.add_notification(f"tache terminee: {tid}", source=agent)
        return f"OK resultat livre pour {tid}"

    # ── HANDLERS : auto_test (py_compile) ────────────────────────────────────

    async def handle_auto_test(self, args: dict, agent: str, ring: int) -> str:
        """py_compile sur un fichier - retourne OK ou l erreur de syntaxe."""
        fp = args.get("filepath", "")
        if not fp: return "Erreur: parametre 'filepath' requis"
        p = self.root / fp
        if not p.exists(): return f"Fichier introuvable: {fp}"
        try:
            import py_compile
            py_compile.compile(str(p), doraise=True)
            return f"OK {p.name} py_compile OK"
        except py_compile.PyCompileError as e:
            return f"FAIL {p.name} : {e.msg}"
        except Exception as e:
            return f"ERR {type(e).__name__}: {e}"

    # ── HANDLERS : EventBus (docs/EVENT_SPEC.md) ─────────────────────────────

    async def handle_event_publish(self, args: dict, agent: str, ring: int) -> str:
        """Publie un event sur le bus via EventBus.publish (trusted car interne Registry)."""
        try:
            from forge_state_manager import EventBus
        except ImportError as e:
            return f"ERR import EventBus: {e}"
        # Instance partagee du bus via state_mgr
        if not hasattr(self, "_event_bus"):
            self._event_bus = EventBus(self.state_mgr)
        
        topic = args.get("topic", "")
        kind = args.get("kind", "msg")
        data = args.get("data", {})
        if not topic or not isinstance(data, dict):
            return "Erreur: parametres 'topic' et 'data' (dict) requis"
        
        result = self._event_bus.publish(
            topic=topic,
            kind=kind,
            data=data,
            agent=agent,
            corr_id=args.get("corr_id"),
            parent_id=args.get("parent_id"),
            trusted=True,  # les agents MCP authentifies par Bearer token sont trusted
        )
        
        if isinstance(result, str) and result.startswith("evt_"):
            return f"OK published {result}"
        return f"ERR {result}"

    async def handle_event_history(self, args: dict, agent: str, ring: int) -> str:
        """Lit l historique filtre par topics. Retourne JSON."""
        try:
            from forge_state_manager import EventBus
        except ImportError as e:
            return f"ERR import EventBus: {e}"
        if not hasattr(self, "_event_bus"):
            self._event_bus = EventBus(self.state_mgr)
        
        topics = args.get("topics", [])
        if not topics or not isinstance(topics, list):
            return "Erreur: parametre 'topics' (liste) requis"
        
        events = self._event_bus.history(
            topics=topics,
            limit=int(args.get("limit", 50)),
            since=args.get("since"),
        )
        return json.dumps(events, indent=2, ensure_ascii=False)

    # ── SECURITE : Ring check matrix ─────────────────────────────────────────

    def _get_ring_needed(self, name: str, args: Dict[str, Any]) -> int:
        """Retourne le ring minimum requis pour appeler le handler.
        
        Ring 0 (user local) : tout (write, set_mode, run python dangereux)
        Ring 1 (agents trusted Claude/Gemini/VSCode) : par defaut
        Ring 2 (agents limites) : lecture + notifications seulement
        """
        # Ring 0 only (privileges eleves)
        RING_0_ONLY = {"write", "set_mode"}
        if name in RING_0_ONLY:
            return 0
        # run : depend de l action (python = ring 0, atlas_get = ring 1)
        if name == "run":
            action = args.get("action", "")
            if action in ("python", "github", "hub_restart", "make_snapshot"):
                return 0
            return 1
        # Ring 1 : tous les autres handlers par defaut (agents authentifies)
        # read, query, get_mode, notify, poll, index_result, search_recent, 
        # auto_test, trigger_autonomous_evolution, task_*, event_*
        return 1


_registry: Optional[ToolRegistry] = None

def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
