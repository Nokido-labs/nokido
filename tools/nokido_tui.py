"""
nokido_tui.py v2 — TUI multi-CLI user (ring 0)

Phases 1-6 complètes de docs/roadmap_tui_multi_cli.md.
v2 ajoute : OPSEC indicator (Phase 6 cognitive), RAG pane toggle,
filter unread, persistence bind mount, help modal.

Lance :
  LAFORGE_PYTHON tools/nokido_tui.py

Layout :
  STATUS │ CLAUDE │ GEMINI │ CODEX
         │ CLINE  │ MASTER │ RAG (toggle Ctrl+K)
  Compose box (input @target msg)

Bindings :
  Tab          : focus next pane
  Ctrl+B       : broadcast (@all)
  Ctrl+K       : toggle RAG pane (anchor récents)
  Ctrl+U       : filter unread (panes sans new msg cachés)
  Ctrl+R       : refresh
  Ctrl+L       : OPSEC lock toggle (humain → bouclier)
  Ctrl+Q       : quit
  F1           : help modal
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

# app/ dans le path AVANT forge_secrets (import ligne < definition de ROOT).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nokido_agent.app.forge_secrets import get_secret

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "RAG" / "embeddings.db"
from nokido_agent.app.forge_db_path import m2m_path  # noqa: E402
M2M = Path(m2m_path())   # scission M2M : agent_messages suit l'interrupteur sandbox/m2m.switch
# v2 : persistence dans bind mount Phase 6 (compatible VSS Windows + cross-conteneur)
_PERSIST_DIR = Path(os.environ.get("LAFORGE_PERSIST_DIR") or str(ROOT / "nokido_persist"))
SESSION_FILE = _PERSIST_DIR / "tui_session.json"
# Fallback legacy :
_LEGACY_SESSION = ROOT / "sandbox" / "tui_session.json"
HUB_URL = os.environ.get("FORGE_HUB_URL", "http://127.0.0.1:8766/mcp")

sys.path.insert(0, str(ROOT))

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.widgets import Footer, Header, Input, RichLog

# v3 adapters — services / tasks / health. Importés via package app/tui_adapters.
# MESURE 2026-09-25 : lancee comme en production (`python tools/nokido_tui.py`), app/ n'etait
# PAS dans sys.path (le commentaire plus haut le pretend) -> ModuleNotFoundError AVALE, les 8
# adaptateurs a None : fenetre SSH en PTY, slash v13.6, vues services/taches/sante/RBAC mortes
# sans un mot. app/ est ajoute EN FIN de chemin (jamais devant : il ne doit masquer aucun paquet
# installe) et une absence est gardee dans _ADAPTERS_ERREUR pour etre DITE a l'ecran.
_APP_DIR = str(Path(__file__).resolve().parent.parent / "app")
if _APP_DIR not in sys.path:
    sys.path.append(_APP_DIR)
_ADAPTERS_ERREUR = ""
try:
    from tui_adapters import commands_adapter as _cmd_a
    from tui_adapters import events_adapter as _evt_a
    from tui_adapters import forge_adapter as _fge_a
    from tui_adapters import health_adapter as _hlt_a
    from tui_adapters import pty_adapter as _pty_a
    from tui_adapters import rbac_adapter as _rbac_a
    from tui_adapters import services_adapter as _svc_a
    from tui_adapters import tasks_adapter as _tsk_a
except Exception as _exc_adapt:  # noqa: BLE001 - une absence se DIT (montage, /ssh, /cmd)
    _svc_a = _tsk_a = _hlt_a = _evt_a = _fge_a = _rbac_a = _pty_a = _cmd_a = None
    _ADAPTERS_ERREUR = "%s: %s" % (type(_exc_adapt).__name__, _exc_adapt)


# Mapping label TUI → agent_id DB → token env
AGENTS = [
    {"id": "agt_claude", "label": "CLAUDE", "color": "#5B9BD5", "tag": "[CLAUDE]"},
    {"id": "agt_gemini", "label": "GEMINI", "color": "#9C27B0", "tag": "[GEMINI]"},
    {"id": "agt_codex", "label": "CODEX", "color": "#FF9800", "tag": "[CODEX]"},
    {"id": "agt_cline", "label": "CLINE", "color": "#4CAF50", "tag": "[CLINE]"},
    {"id": "agt_master_llamacpp", "label": "MASTER", "color": "#FFC107", "tag": "[MASTER]"},
]


# Identite annoncee au hub (en-tete + jeton propre). Neutre : le nom de l'owner ne
# figure pas dans le code distribue.
_IDENTITE_HUB = "OWNER_TUI"


def load_token() -> str:
    """Jeton du hub pour l'identite de la TUI (`_IDENTITE_HUB`, l'en-tete qu'elle annonce).

    2b-5 (2026-09-28) : par `forge_agent_credential.jeton_hub` -- son jeton propre des
    qu'il est provisionne, le MAITRE en transition dite d'ici la. Voir la note jumelle
    dans `app/forge_llm_format_bridge.py` (meme fonction d'origine).
    """
    try:
        from nokido_agent.app.forge_agent_credential import jeton_hub

        return jeton_hub(_IDENTITE_HUB)
    except Exception:  # noqa: BLE001 -- brique illisible : pas de jeton, le hub dira 401
        return ""


_TOKEN = load_token()


def hub_notify(message: str) -> bool:
    """POST hub action=notify avec préfixe [TARGET] pour routing agent_messages."""
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "hub", "arguments": {"action": "notify", "message": message}},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        HUB_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_TOKEN}",
            "X-Agent-Name": _IDENTITE_HUB,
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
        return True
    except Exception:
        return False


def fetch_recent(agent_id: str, since_ts: float, limit: int = 20) -> list[dict]:
    """SELECT messages OÙ to_agent OU from_agent matche, depuis since_ts."""
    if not DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(M2M))
        rows = conn.execute(
            "SELECT id, from_agent, to_agent, status, created_at, payload "
            "FROM agent_messages "
            "WHERE (to_agent=? OR from_agent=?) "
            "AND datetime(created_at) > datetime(?, 'unixepoch') "
            "ORDER BY created_at ASC LIMIT ?",
            (agent_id, agent_id, since_ts, limit),
        ).fetchall()
        conn.close()
        return [
            {"id": r[0], "from": r[1], "to": r[2], "status": r[3], "ts": r[4], "payload": r[5]}
            for r in rows
        ]
    except Exception:
        return []


def status_services() -> dict:
    """Ping ports critiques."""
    import socket

    out = {}
    for label, port in [
        ("hub", 8766),
        ("netcfg", 8767),
        ("ollama", 11434),
        ("llamacpp", 8080),
        ("webhub", 7400),
        ("deno", 8000),
    ]:
        try:
            s = socket.socket()
            s.settimeout(0.5)
            s.connect(("127.0.0.1", port))
            s.close()
            out[label] = "🟢"
        except Exception:
            out[label] = "🔴"
    return out


def opsec_state() -> dict:
    """Lit miroir state.json pour afficher OPSEC level + lock dans STATUS."""
    persist = ROOT / "nokido_persist" / "state.json"
    if persist.exists():
        try:
            data = json.loads(persist.read_text(encoding="utf-8"))
            return {
                "level": data.get("opsec_level", "?"),
                "locked": bool(data.get("human_locked", False)),
                "by": data.get("last_change_by", "")[:12],
            }
        except Exception:
            pass
    # Fallback SQLite direct
    try:
        conn = sqlite3.connect(str(DB))
        row = conn.execute("SELECT value FROM opsec_state WHERE key='current_level'").fetchone()
        lock_row = conn.execute("SELECT value FROM opsec_state WHERE key='human_locked'").fetchone()
        conn.close()
        if row:
            level_map = {"0": "CTF", "1": "STANDARD", "2": "PARANOID"}
            return {
                "level": level_map.get(row[0], "?"),
                "locked": bool(lock_row and lock_row[0] == "1"),
                "by": "sqlite",
            }
    except Exception:
        pass
    return {"level": "?", "locked": False, "by": ""}


def fetch_evolution_tree(limit_commits: int = 15) -> list[dict]:
    """Phase I — Evolution tree v13.6-inspired.

    Source : git commits évolution + forged_tools/ + RAG anchors
    domain=tool_smithing. Statuts inspirés skilltree.SkillNode :
    unknown(..) | searching(>>) | learning(~~) | verified(ok) | mastered(**).
    """
    import subprocess

    items: list[dict] = []
    # 1. Commits évolution récents (Phase markers)
    try:
        r = subprocess.run(
            ["git", "log", f"-{limit_commits}", "--pretty=format:%h\x1f%s\x1f%ct"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        evolution_kw = [
            "phase",
            "deno",
            "forge",
            "tool_smith",
            "kill_switch",
            "anatomy",
            "py314",
            "autonomous",
            "evolve",
        ]
        for line in r.stdout.splitlines():
            parts = line.split("\x1f", 2)
            if len(parts) != 3:
                continue
            sha, subject, _ = parts
            kw_match = next((k for k in evolution_kw if k in subject.lower()), None)
            status = "verified" if kw_match else "learning"
            items.append(
                {
                    "type": "commit",
                    "sha": sha,
                    "label": subject[:60],
                    "status": status,
                    "depth": 0,
                }
            )
    except Exception:
        pass
    # 2. Tools forgés Phase G
    try:
        forged_dir = ROOT / "nokido_persist" / "forged_tools"
        if forged_dir.exists():
            for meta in sorted(forged_dir.glob("*.meta.json"), reverse=True)[:5]:
                try:
                    d = json.loads(meta.read_text(encoding="utf-8"))
                    spec = d.get("spec", {})
                    audit = d.get("audit", {})
                    status = (
                        "mastered"
                        if audit.get("score", 0) >= 90
                        else "verified"
                        if audit.get("approved")
                        else "learning"
                    )
                    items.append(
                        {
                            "type": "forged_tool",
                            "label": f"🛠 {spec.get('name', '?')} ({spec.get('language', '?')})",
                            "status": status,
                            "depth": 1,
                            "score": audit.get("score", 0),
                        }
                    )
                except Exception:
                    pass
    except Exception:
        pass
    return items


def fetch_recent_anchors(limit: int = 8) -> list[dict]:
    """Lit logs/lessons_learned.md pour les N derniers anchors (RAG pane)."""
    lessons = ROOT / "logs" / "lessons_learned.md"
    if not lessons.exists():
        return []
    try:
        content = lessons.read_text(encoding="utf-8", errors="replace")
        # Split par sections markdown ## ou ###
        import re as _re

        blocks = _re.split(r"\n## ", content)
        out = []
        for b in blocks[-limit:]:
            head = b.splitlines()[0][:80] if b else ""
            preview = " ".join(b.splitlines()[1:6])[:200] if len(b.splitlines()) > 1 else ""
            out.append({"head": head.strip("# "), "preview": preview})
        return out
    except Exception:
        return []


def toggle_human_lock_via_webhub(locked: bool) -> dict:
    """POST /api/opsec/lock → lock/unlock OPSEC humain via WebHub :7400."""
    try:
        body = json.dumps({"locked": locked, "reason": "TUI keystroke Ctrl+L"}).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:7400/api/opsec/lock",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return json.loads(urllib.request.urlopen(req, timeout=2).read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}


@dataclass
class PaneState:
    last_seen_id: str = ""
    last_ts: float = field(default_factory=lambda: time.time() - 3600)


class AgentPaneWidget(RichLog):
    DEFAULT_CSS = """
    AgentPaneWidget {
        border: solid $primary;
        height: 100%;
    }
    """


class NokidoTUI(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #panes_grid {
        grid-size: 3 2;
        grid-gutter: 1;
        height: 1fr;
    }
    #status_pane {
        border: solid yellow;
        height: 100%;
    }
    .agent_pane {
        border: solid blue;
        height: 100%;
    }
    #compose {
        dock: bottom;
        height: 3;
        border: solid green;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("tab", "focus_next", "Next pane"),
        Binding("ctrl+b", "broadcast", "Broadcast"),
        # ctrl+k / ctrl+d et non ctrl+m / ctrl+h (mesure 2026-09-25, Textual 8.2.5) : un
        # terminal envoie `\r` pour Ctrl+M comme pour Entree, `\x08` pour Ctrl+H, decodes
        # `enter` / `backspace` -- ces deux raccourcis ne se declenchaient JAMAIS.
        # NR : test_tui_raccourcis_atteignables_nr.
        Binding("ctrl+k", "toggle_rag", "RAG"),
        Binding("ctrl+e", "toggle_evolution", "Tree"),
        Binding("ctrl+s", "toggle_services", "Svcs"),
        Binding("ctrl+t", "toggle_tasks", "Tasks"),
        Binding("ctrl+d", "toggle_health", "Health"),
        Binding("ctrl+v", "toggle_events", "Events"),
        Binding("ctrl+f", "toggle_forge", "Forge"),
        Binding("ctrl+g", "toggle_rbac", "RBAC"),
        Binding("ctrl+p", "toggle_pty", "PTY"),
        Binding("0", "view_none", "0=Master"),
        Binding("1", "view_services", "1=Svc"),
        Binding("2", "view_tasks", "2=Tasks"),
        Binding("3", "view_health", "3=Health"),
        Binding("4", "view_events", "4=Events"),
        Binding("5", "view_forge", "5=Forge"),
        Binding("6", "view_rag", "6=RAG"),
        Binding("7", "view_evolution", "7=Evol"),
        Binding("8", "view_rbac", "8=RBAC"),
        Binding("9", "view_pty", "9=PTY"),
        Binding("f3", "view_cycle", "Cycle"),
        Binding("ctrl+u", "toggle_unread_filter", "Filter"),
        Binding("ctrl+l", "toggle_opsec_lock", "Lock"),
        Binding("ctrl+r", "refresh_all", "Refresh"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("f1", "help", "Help"),
    ]

    def __init__(self):
        super().__init__()
        self.panes: dict[str, PaneState] = {a["id"]: PaneState() for a in AGENTS}
        self._poll_task: asyncio.Task | None = None
        self._rag_visible: bool = False
        self._evolution_visible: bool = False
        # v3 : nouvelles vues swappables sur pane MASTER (exclusives)
        self._services_visible: bool = False
        self._tasks_visible: bool = False
        self._health_visible: bool = False
        self._events_visible: bool = False
        self._forge_visible: bool = False
        self._rbac_visible: bool = False
        self._pty_visible: bool = False
        self._unread_filter: bool = False
        self._unread_count: dict[str, int] = {a["id"]: 0 for a in AGENTS}
        self._load_session()

    # v3 : registry des vues swappables — index numérique <→ flag + renderer.
    _MASTER_VIEWS = [
        ("none", None, None),
        ("services", "_services_visible", "_render_services"),
        ("tasks", "_tasks_visible", "_render_tasks"),
        ("health", "_health_visible", "_render_health"),
        ("events", "_events_visible", "_render_events"),
        ("forge", "_forge_visible", "_render_forge"),
        ("rag", "_rag_visible", "_render_rag"),
        ("evolution", "_evolution_visible", "_render_evolution"),
        ("rbac", "_rbac_visible", "_render_rbac"),
        ("pty", "_pty_visible", "_render_pty"),
    ]

    def _clear_master_views(self) -> None:
        """v3 : reset toutes les vues swappables avant d'en activer une."""
        for _, attr, _ in self._MASTER_VIEWS:
            if attr:
                setattr(self, attr, False)

    def _active_master_view(self) -> str:
        for name, attr, _ in self._MASTER_VIEWS:
            if attr and getattr(self, attr, False):
                return name
        return "none"

    def _set_master_view(self, name: str) -> None:
        """Active la vue MASTER nommée. 'none' restaure pane MASTER vide."""
        self._clear_master_views()
        for vname, attr, render in self._MASTER_VIEWS:
            if vname == name and attr:
                setattr(self, attr, True)
                if render:
                    getattr(self, render)()
                return
        # fallback : restore master
        self._restore_master_pane()

    def _restore_master_pane(self) -> None:
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold #FFC107]── MASTER ──[/]")
        except Exception:
            pass

    def _load_session(self) -> None:
        # v2 : try bind mount d'abord, puis legacy sandbox/
        for src in (SESSION_FILE, _LEGACY_SESSION):
            if src.exists():
                try:
                    data = json.loads(src.read_text(encoding="utf-8"))
                    age = time.time() - data.get("saved_at", 0)
                    if age > 7 * 86400:  # roadmap C6 : 7 jours
                        return
                    for aid, state in data.get("panes", {}).items():
                        if aid in self.panes:
                            self.panes[aid].last_seen_id = state.get("last_seen_id", "")
                            self.panes[aid].last_ts = state.get("last_ts", time.time() - 3600)
                    self._rag_visible = bool(data.get("rag_visible", False))
                    self._evolution_visible = bool(data.get("evolution_visible", False))
                    self._services_visible = bool(data.get("services_visible", False))
                    self._tasks_visible = bool(data.get("tasks_visible", False))
                    self._health_visible = bool(data.get("health_visible", False))
                    self._events_visible = bool(data.get("events_visible", False))
                    self._forge_visible = bool(data.get("forge_visible", False))
                    self._rbac_visible = bool(data.get("rbac_visible", False))
                    self._pty_visible = bool(data.get("pty_visible", False))
                    self._unread_filter = bool(data.get("unread_filter", False))
                    return
                except Exception:
                    pass

    def _save_session(self) -> None:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = {
                "panes": {
                    aid: {"last_seen_id": p.last_seen_id, "last_ts": p.last_ts}
                    for aid, p in self.panes.items()
                },
                "rag_visible": self._rag_visible,
                "evolution_visible": self._evolution_visible,
                "services_visible": self._services_visible,
                "tasks_visible": self._tasks_visible,
                "health_visible": self._health_visible,
                "events_visible": self._events_visible,
                "forge_visible": self._forge_visible,
                "rbac_visible": self._rbac_visible,
                "pty_visible": self._pty_visible,
                "unread_filter": self._unread_filter,
                "saved_at": time.time(),
                "schema": "nokido.tui.session.v3",
            }
            SESSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    # Jusqu'a quand #status_pane montre un message VOULU (aide, usage d'une commande) :
    # la boucle de 2 s ne l'ecrase pas avant. Mesure 2026-09-24 (Pilot headless) : l'aide
    # F1 / /help etait effacee en moins d'1 s par `_render_status` -- elle existait, et
    # personne ne pouvait la lire. Ctrl+R rend la main au statut sans attendre.
    _statut_fige_jusqua: float = 0.0
    AIDE_VISIBLE_S = 30.0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Grid(id="panes_grid"):
            yield RichLog(id="status_pane", highlight=False, markup=True, wrap=True)
            for a in AGENTS:
                w = AgentPaneWidget(
                    id=f"pane_{a['id']}",
                    classes="agent_pane",
                    highlight=False,
                    markup=True,
                    wrap=True,
                )
                w.border_title = a["label"]
                yield w
        yield Input(placeholder="@target msg | @all msg | /help", id="compose")
        yield Footer()

    def _dire_adaptateur_absent(self, fonction: str) -> None:
        """Une fonction sans adaptateur le DIT (avant : `return` muet, `/ssh` ne repondait rien)."""
        try:
            pane = self.query_one("#status_pane", RichLog)
            self._statut_fige_jusqua = time.time() + 10.0
            pane.write("[red]%s indisponible : %s[/]"
                       % (fonction, _ADAPTERS_ERREUR or "adaptateur non charge"))
        except Exception:  # muet-ok : l'affichage d'une panne ne doit pas en creer une autre
            pass

    async def on_mount(self) -> None:
        self._render_status()
        if _ADAPTERS_ERREUR:
            self._dire_adaptateur_absent("Adaptateurs (PTY SSH, slash v13.6, vues)")
        for a in AGENTS:
            pane = self.query_one(f"#pane_{a['id']}", RichLog)
            pane.write(f"[bold {a['color']}]── {a['label']} ──[/]")
            # Charger derniers 10 msgs historiques
            msgs = fetch_recent(a["id"], time.time() - 86400, limit=10)
            for m in msgs:
                self._render_msg(pane, m, a)
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        while True:
            try:
                for a in AGENTS:
                    pane = self.query_one(f"#pane_{a['id']}", RichLog)
                    # skip render messages si pane MASTER affiche une vue swappable
                    if a["id"] == "agt_master_llamacpp" and (self._active_master_view() != "none"):
                        continue
                    msgs = fetch_recent(a["id"], self.panes[a["id"]].last_ts)
                    new_count = 0
                    for m in msgs:
                        if m["id"] == self.panes[a["id"]].last_seen_id:
                            continue
                        self._render_msg(pane, m, a)
                        self.panes[a["id"]].last_seen_id = m["id"]
                        new_count += 1
                        # Beep si destinataire = user
                        if m["to"] == "agt_naarob":
                            self.bell()
                    if new_count > 0:
                        self._unread_count[a["id"]] += new_count
                    if msgs:
                        self.panes[a["id"]].last_ts = time.time()
                # Refresh vues swappables MASTER selon cadences propres
                now_i = int(time.time())
                if self._rag_visible and now_i % 30 == 0:
                    self._render_rag()
                if self._evolution_visible and now_i % 30 == 0:
                    self._render_evolution()
                if self._services_visible and now_i % 5 == 0:
                    self._render_services()
                if self._tasks_visible and now_i % 8 == 0:
                    self._render_tasks()
                if self._health_visible and now_i % 30 == 0:
                    self._render_health()
                if self._events_visible and now_i % 5 == 0:
                    self._render_events()
                if self._forge_visible and now_i % 15 == 0:
                    self._render_forge()
                if self._rbac_visible and now_i % 30 == 0:
                    self._render_rbac()
                if self._pty_visible and now_i % 1 == 0:
                    self._render_pty()
                self._render_status()
            except Exception:
                pass
            await asyncio.sleep(2.0)

    def _render_msg(self, pane: RichLog, m: dict, agent: dict) -> None:
        try:
            payload = json.loads(m["payload"])
            text = payload.get("text", "")[:200]
        except Exception:
            text = (m["payload"] or "")[:200]
        direction = "→" if m["from"] == agent["id"] else "←"
        peer = m["to"] if m["from"] == agent["id"] else m["from"]
        ts_short = (m["ts"] or "")[-8:]
        pane.write(f"[dim]{ts_short}[/] [{agent['color']}]{direction} {peer}[/] {text}")

    def _render_status(self) -> None:
        if time.time() < self._statut_fige_jusqua:
            return  # un message voulu occupe le panneau (aide, usage) : ne pas l'ecraser
        try:
            pane = self.query_one("#status_pane", RichLog)
            pane.clear()
            pane.write("[bold yellow]── STATUS ──[/]")
            services = status_services()
            for label, state in services.items():
                pane.write(f"  {state} {label:14}")
            # OPSEC indicator (Phase 6 cognitive)
            ops = opsec_state()
            color_map = {"CTF": "yellow", "STANDARD": "cyan", "PARANOID": "green", "?": "white"}
            color = color_map.get(ops["level"], "white")
            lock_icon = "🔒" if ops["locked"] else "🔓"
            pane.write("")
            pane.write(f"[bold]OPSEC:[/] [{color}]{ops['level']}[/] {lock_icon}")
            if ops["locked"]:
                pane.write(f"  [dim]locked by {ops['by']}[/]")
            # Unread count
            try:
                conn = sqlite3.connect(str(M2M))
                unread = conn.execute(
                    "SELECT COUNT(*) FROM agent_messages WHERE to_agent='agt_naarob' AND status='unread'"
                ).fetchone()[0]
                conn.close()
                pane.write("")
                pane.write(f"[bold]unread user:[/] {unread}")
            except Exception:
                pass
            # Filter mode
            if self._unread_filter:
                pane.write("[bold magenta]FILTER: unread only[/]")
        except Exception:
            pass

    def _render_evolution(self) -> None:
        """Phase I — EVOLUTION_TREE pane (skilltree v13.6 inspired).

        Statuts ASCII : .. unknown | >> searching | ~~ learning | ok verified | ** mastered
        """
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold yellow]── EVOLUTION TREE (v13.6) ──[/]")
            items = fetch_evolution_tree(limit_commits=15)
            if not items:
                pane.write("[dim]aucune évolution détectée[/]")
                return
            ICONS = {
                "unknown": "..",
                "searching": ">>",
                "learning": "~~",
                "verified": "ok",
                "mastered": "**",
            }
            COLORS = {
                "unknown": "dim",
                "searching": "blue",
                "learning": "yellow",
                "verified": "green",
                "mastered": "bold green",
            }
            commit_count = sum(1 for i in items if i["type"] == "commit")
            forged_count = sum(1 for i in items if i["type"] == "forged_tool")
            pane.write(f"[dim]commits {commit_count} · forged {forged_count}[/]")
            pane.write("")
            for item in items:
                indent = "  " * item.get("depth", 0)
                icon = ICONS.get(item["status"], "..")
                color = COLORS.get(item["status"], "dim")
                tag = item.get("sha", "") + " " if item.get("sha") else ""
                score = f" ({item.get('score', 0)})" if item["type"] == "forged_tool" else ""
                pane.write(f"[{color}]{indent}{icon} {tag}{item['label']}{score}[/]")
        except Exception as e:
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.write(f"[red]evolution err: {e}[/]")
            except Exception:
                pass

    def _render_rag(self) -> None:
        """Affiche les derniers anchors dans pane RAG (toggle Ctrl+K)."""
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold yellow]── RAG ANCHORS ──[/]")
            anchors = fetch_recent_anchors(limit=8)
            if not anchors:
                pane.write("[dim]aucun anchor (logs/lessons_learned.md vide)[/]")
                return
            for a in anchors:
                pane.write(f"[bold cyan]› {a['head']}[/]")
                pane.write(f"  [dim]{a['preview']}[/]")
                pane.write("")
        except Exception:
            pass

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        text = message.value.strip()
        message.input.value = ""
        if not text:
            return
        # Slash commands
        if text == "/help":
            self.action_help()
            return
        if text.startswith("/clear"):
            for a in AGENTS:
                pane = self.query_one(f"#pane_{a['id']}", RichLog)
                pane.clear()
            return
        # /ssh <host> <port> <user> — ouvre PTY pane
        if text.startswith("/ssh"):
            parts = text.split()
            if len(parts) < 4:
                try:
                    pane = self.query_one("#status_pane", RichLog)
                    self._statut_fige_jusqua = time.time() + 10.0
                    pane.write("[red]/ssh <host> <port> <user>[/]")
                except Exception:
                    pass
                return
            host, port, user = parts[1], parts[2], parts[3]
            if _pty_a is None:
                self._dire_adaptateur_absent("PTY")
                return
            self._clear_master_views()
            self._pty_visible = True
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.clear()
                pane.write(f"[yellow]connecting {user}@{host}:{port}...[/]")
            except Exception:
                pass
            # Auth interactive — pas dans le compose (DLP). Pour MVP : password
            # vide (clé SSH/auth pubkey). Étendre via vault plus tard.
            asyncio.create_task(self._pty_open(host, int(port), user))
            return
        # /ssh-send <text> — injecte commande dans PTY actif
        if text.startswith("/ssh-send "):
            cmd = text[len("/ssh-send ") :]
            if _pty_a is not None:
                asyncio.create_task(_pty_a.inject_async(cmd))
            return
        # /ssh-close — ferme PTY
        if text.startswith("/ssh-close"):
            if _pty_a is not None:
                asyncio.create_task(_pty_a.close_async())
            return
        # Commandes slash héritées v13.6 (commands_adapter) — sauf /ssh* qui restent ci-dessus
        if text.startswith("/") and _cmd_a is not None:
            asyncio.create_task(self._run_slash_command(text))
            return
        # Parse @target1,@target2 message
        m = re.match(r"^(@\w+(?:,@\w+)*)\s+(.+)$", text)
        if not m:
            return
        targets_str = m.group(1)
        body = m.group(2)
        targets = [t.strip("@") for t in targets_str.split(",")]
        if "all" in targets:
            targets = [a["label"].lower() for a in AGENTS]
        # Send chaque target
        for t in targets:
            tag_match = next((a for a in AGENTS if a["label"].lower() == t.lower()), None)
            if not tag_match:
                continue
            full = f"{tag_match['tag']} [user-TUI {time.strftime('%H:%M:%S')}] {body}"
            ok = hub_notify(full)
            pane = self.query_one(f"#pane_{tag_match['id']}", RichLog)
            arrow = "[green]→[/]" if ok else "[red]✗[/]"
            pane.write(f"[dim]{time.strftime('%H:%M:%S')}[/] {arrow} [bold]user[/] {body}")

    def action_broadcast(self) -> None:
        inp = self.query_one("#compose", Input)
        if inp.value and not inp.value.startswith("@"):
            inp.value = f"@all {inp.value}"
            inp.cursor_position = len(inp.value)

    def action_refresh_all(self) -> None:
        for aid in self.panes:
            self.panes[aid].last_ts = time.time() - 86400
            self.panes[aid].last_seen_id = ""
        self._statut_fige_jusqua = 0.0
        self._render_status()

    def action_help(self) -> None:
        """Affiche aide dans pane STATUS (overlay propre, pas spam panes agents)."""
        try:
            pane = self.query_one("#status_pane", RichLog)
            self._statut_fige_jusqua = time.time() + self.AIDE_VISIBLE_S
            pane.clear()
            pane.write("[bold yellow]── HELP ──[/]")
            pane.write("[bold]Compose:[/]")
            pane.write("  [cyan]@claude msg[/]    direct")
            pane.write("  [cyan]@gemini,@codex[/] multi-target")
            pane.write("  [cyan]@all msg[/]       broadcast")
            pane.write("  [cyan]/clear[/]         vide panes")
            pane.write("  [cyan]/help[/]          cette aide")
            pane.write("")
            pane.write("[bold]Bindings:[/]")
            pane.write("  Tab     next pane")
            pane.write("  Ctrl+B  broadcast prefix")
            pane.write("  Ctrl+K  toggle RAG anchors")
            pane.write("  Ctrl+E  toggle EVOLUTION TREE")
            pane.write("  Ctrl+S  toggle SERVICES (supervisor :8765)")
            pane.write("  Ctrl+T  toggle TASKS (agent_tasks queue)")
            pane.write("  Ctrl+D  toggle HEALTH (forge_health_diagnostic)")
            pane.write("  Ctrl+V  toggle EVENTS (EventBus tail)")
            pane.write("  Ctrl+F  toggle FORGE (AMI/skills/GOAP)")
            pane.write("")
            pane.write("[bold]Dispatcher MASTER (Phase 3) :[/]")
            pane.write("  0=Master  1=Services  2=Tasks  3=Health")
            pane.write("  4=Events  5=Forge  6=RAG  7=Evolution  8=RBAC  9=PTY")
            pane.write("  Ctrl+G  toggle RBAC (read-only ; édition :7400/rbac)")
            pane.write("  Ctrl+P  toggle PTY (SSH live)")
            pane.write("  F3      cycle vue suivante")
            pane.write("")
            pane.write("[bold]Slash :[/]")
            pane.write("  /ssh <host> <port> <user>  ouvre session PTY")
            pane.write("  /ssh-send <cmd>            envoie au PTY actif")
            pane.write("  /ssh-close                 ferme la session PTY")
            pane.write("")
            pane.write("[bold]Slash héritées v13.6 :[/] [dim](/cmds pour la liste)[/]")
            pane.write("  /run /rag /mem /agentic /evolve /role /model")
            pane.write("  /ollama /audit /code /test /sandbox /nlu /estim")
            pane.write("  /chain /scan /cmds")
            pane.write("")
            pane.write("  Ctrl+U  filter unread")
            pane.write("  Ctrl+L  toggle OPSEC lock")
            pane.write("  Ctrl+R  refresh all")
            pane.write("  Ctrl+Q  quit (save session)")
            pane.write("  F1      this help")
            pane.write("")
            pane.write("[dim]Press Ctrl+R to restore status[/]")
        except Exception:
            pass

    def action_toggle_rag(self) -> None:
        """Ctrl+K : toggle pane MASTER ↔ RAG anchors view."""
        want = not self._rag_visible
        self._clear_master_views()
        if want:
            self._rag_visible = True
            self._render_rag()
        else:
            self._restore_master_pane()

    def action_toggle_evolution(self) -> None:
        """Ctrl+E : toggle pane MASTER ↔ EVOLUTION TREE (v13.6 inspired)."""
        want = not self._evolution_visible
        self._clear_master_views()
        if want:
            self._evolution_visible = True
            self._render_evolution()
        else:
            self._restore_master_pane()

    def action_toggle_services(self) -> None:
        """Ctrl+S : toggle pane MASTER ↔ SERVICES (supervisor :8765)."""
        want = not self._services_visible
        self._clear_master_views()
        if want:
            self._services_visible = True
            self._render_services()
        else:
            self._restore_master_pane()

    def action_toggle_tasks(self) -> None:
        """Ctrl+T : toggle pane MASTER ↔ TASKS (agent_tasks queue)."""
        want = not self._tasks_visible
        self._clear_master_views()
        if want:
            self._tasks_visible = True
            self._render_tasks()
        else:
            self._restore_master_pane()

    def action_toggle_health(self) -> None:
        """Ctrl+D : toggle pane MASTER ↔ HEALTH (forge_health_diagnostic)."""
        want = not self._health_visible
        self._clear_master_views()
        if want:
            self._health_visible = True
            self._render_health()
        else:
            self._restore_master_pane()

    def action_toggle_events(self) -> None:
        """Ctrl+V : toggle pane MASTER ↔ EVENTS (EventBus tail)."""
        want = not self._events_visible
        self._clear_master_views()
        if want:
            self._events_visible = True
            self._render_events()
        else:
            self._restore_master_pane()

    def action_toggle_forge(self) -> None:
        """Ctrl+F : toggle pane MASTER ↔ FORGE (AMI/skills/GOAP)."""
        want = not self._forge_visible
        self._clear_master_views()
        if want:
            self._forge_visible = True
            self._render_forge()
        else:
            self._restore_master_pane()

    # ── Bindings numériques (Phase 3) ────────────────────────────────────
    def action_view_none(self) -> None:
        self._set_master_view("none")

    def action_view_services(self) -> None:
        self._set_master_view("services")

    def action_view_tasks(self) -> None:
        self._set_master_view("tasks")

    def action_view_health(self) -> None:
        self._set_master_view("health")

    def action_view_events(self) -> None:
        self._set_master_view("events")

    def action_view_forge(self) -> None:
        self._set_master_view("forge")

    def action_view_rag(self) -> None:
        self._set_master_view("rag")

    def action_view_evolution(self) -> None:
        self._set_master_view("evolution")

    def action_view_rbac(self) -> None:
        self._set_master_view("rbac")

    def action_view_pty(self) -> None:
        self._set_master_view("pty")

    async def _run_slash_command(self, text: str) -> None:
        """Dispatch /cmd via commands_adapter ; affiche résultat dans STATUS."""
        if _cmd_a is None:
            self._dire_adaptateur_absent("Commandes slash v13.6")
            return
        result = await _cmd_a.dispatch(text)
        try:
            pane = self.query_one("#status_pane", RichLog)
            if result is None:
                pane.write(f"[red]commande inconnue : {text.split()[0]}[/]")
                pane.write("[dim]/cmds pour la liste[/]")
            else:
                pane.write(f"[bold cyan]{text.split()[0]}[/]")
                for line in str(result).splitlines()[:20]:
                    pane.write(f"  {line}")
        except Exception:
            pass

    async def _pty_open(self, host: str, port: int, user: str) -> None:
        if _pty_a is None:
            return
        # auth interactive prévue plus tard ; MVP password vide (pubkey)
        ok, reason = await _pty_a.open_async(host, port, user, entity_id="usr_naarob")
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            if ok:
                pane.write(f"[green]✓ connected {user}@{host}:{port}[/]")
            else:
                pane.write(f"[red]✗ {reason}[/]")
        except Exception:
            pass

    def action_toggle_pty(self) -> None:
        """Ctrl+P : toggle pane MASTER ↔ PTY (live SSH terminal)."""
        want = not self._pty_visible
        self._clear_master_views()
        if want:
            self._pty_visible = True
            self._render_pty()
        else:
            self._restore_master_pane()

    def _render_pty(self) -> None:
        if _pty_a is None:
            self._dire_adaptateur_absent("PTY")
            return
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold yellow]── PTY (SSH terminal live) ──[/]")
            info = _pty_a.session_info()
            if not info.get("open"):
                pane.write("[dim]aucune session — tape :[/]")
                pane.write("  [cyan]/ssh <host> <port> <user>[/]")
                pane.write("  [cyan]/ssh 127.0.0.1 22 user[/]   (exemple)")
                err = info.get("error")
                if err:
                    pane.write(f"[red]dernière erreur : {err}[/]")
                return
            pane.write(
                f"[green]● {info['user']}@{info['host']}:{info['port']}[/]  "
                f"[dim]{info.get('bytes', 0)} bytes reçus[/]"
            )
            pane.write("")
            for line in _pty_a.snapshot():
                pane.write(line.rstrip() or " ")
        except Exception as e:
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.write(f"[red]pty err: {e}[/]")
            except Exception:
                pass

    def action_toggle_rbac(self) -> None:
        """Ctrl+G : toggle pane MASTER ↔ RBAC (read-only — édition web :7400/rbac)."""
        want = not self._rbac_visible
        self._clear_master_views()
        if want:
            self._rbac_visible = True
            self._render_rbac()
        else:
            self._restore_master_pane()

    def _render_rbac(self) -> None:
        if _rbac_a is None:
            return
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold yellow]── RBAC (forge_rbac_mapping) ──[/]")
            pane.write("[dim]édition : http://127.0.0.1:7400/rbac[/]")
            pane.write("")
            rows = _rbac_a.list_mappings_safe()
            if not rows:
                pane.write("[dim]aucun mapping (DB absente ou table vide)[/]")
                return
            ring_col = {-1: "magenta", 0: "red", 1: "orange3", 2: "yellow", 3: "cyan", 4: "dim"}
            for m in rows:
                acc = m.get("os_account", {})
                col = ring_col.get(m.get("ring_level"), "white")
                ring_lbl = {
                    -1: "MASTER",
                    0: "SYSTEM",
                    1: "DEV",
                    2: "TRUSTED",
                    3: "COLLAB",
                    4: "UNTRUSTED",
                }.get(m.get("ring_level"), "?")
                pane.write(
                    f"[{col}]R{m.get('ring_level'):>2} {ring_lbl:9}[/] "
                    f"[bold]{m.get('entity_id', '?'):22}[/] "
                    f"{m.get('entity_type', '?'):8} → "
                    f"[green]{acc.get('zone', '?'):16}[/] "
                    f"user={acc.get('os_user') or '-'}"
                )
        except Exception as e:
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.write(f"[red]rbac err: {e}[/]")
            except Exception:
                pass

    def action_view_cycle(self) -> None:
        """F3 : cycle vue suivante dans le registry."""
        names = [v[0] for v in self._MASTER_VIEWS]
        cur = self._active_master_view()
        try:
            idx = names.index(cur)
        except ValueError:
            idx = 0
        nxt = names[(idx + 1) % len(names)]
        self._set_master_view(nxt)

    def _render_events(self) -> None:
        if _evt_a is None:
            return
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold yellow]── EVENTS (EventBus :7400) ──[/]")
            stats = _evt_a.event_stats()
            if stats:
                tot = stats.get("total_events", 0)
                err = stats.get("errors", 0)
                top = sorted((stats.get("by_prefix") or {}).items(), key=lambda x: -x[1])[:5]
                pane.write(
                    f"[dim]total={tot}  err={err}  top={','.join(f'{k}:{v}' for k, v in top)}[/]"
                )
                pane.write("")
            evts = _evt_a.fetch_events(limit=18)
            if not evts:
                pane.write("[dim]aucun event ou web_hub :7400 DOWN[/]")
                return
            color_by_pref = {
                "tool": "red",
                "rpc": "blue",
                "silo": "green",
                "skill": "yellow",
                "debate": "magenta",
                "agent": "cyan",
                "system": "dim",
            }
            for e in evts[-15:]:
                topic = e.get("topic", "?")
                pref = topic.split(".")[0] if "." in topic else topic
                col = color_by_pref.get(pref, "white")
                ts = (e.get("ts", "") or "")[-12:]
                agt = (e.get("agent") or "-")[:10]
                data = e.get("data") or {}
                hint = ""
                if isinstance(data, dict):
                    for k in ("name", "tool", "method", "status", "error"):
                        v = data.get(k)
                        if v:
                            hint = f"{k}={str(v)[:30]}"
                            break
                pane.write(f"[dim]{ts}[/] [{col}]{topic[:28]:28}[/] [bold]{agt:10}[/] {hint}")
        except Exception as e:
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.write(f"[red]events err: {e}[/]")
            except Exception:
                pass

    def _render_forge(self) -> None:
        if _fge_a is None:
            return
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold yellow]── FORGE (AMI / Skills / GOAP) ──[/]")

            ami = _fge_a.ami_traces_summary()
            if ami.get("present"):
                pane.write(
                    f"[bold cyan]AMI traces[/] : total={ami['total']:,} "
                    f"succ={ami['successes']:,} rate={ami['rate']} "
                    f"24h={ami['last_24h']}"
                )
            else:
                pane.write("[dim]AMI traces : DB absente[/]")

            nt = _fge_a.night_trainer_state()
            for k in ("night", "offline"):
                v = nt.get(k, {})
                if v.get("present") and "data" in v:
                    d = v["data"]
                    line = " ".join(
                        f"{kk}={vv}"
                        for kk, vv in list(d.items())[:4]
                        if not isinstance(vv, (dict, list))
                    )
                    pane.write(f"[dim]{k}_trainer:[/] {line}")

            goap = _fge_a.goap_state()
            if goap.get("present") and "data" in goap:
                d = goap["data"]
                if isinstance(d, dict):
                    pane.write(
                        "[dim]GOAP:[/] "
                        + " ".join(
                            f"{k}={v}"
                            for k, v in list(d.items())[:4]
                            if not isinstance(v, (dict, list))
                        )
                    )

            pane.write("")
            pane.write("[bold]Top curated_skills :[/]")
            top = _fge_a.top_curated_skills(limit=8)
            if not top:
                pane.write("[dim]aucun (lance forge_skill_curator --once)[/]")
            else:
                for s in top:
                    pane.write(
                        f"  [green]{s['score']:.3f}[/] "
                        f"[bold]{s['task']:18}[/]/{s['action']:18} "
                        f"n={s['uses']:>5} rate={s['rate']:.2f}"
                    )
        except Exception as e:
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.write(f"[red]forge err: {e}[/]")
            except Exception:
                pass

    def _render_services(self) -> None:
        if _svc_a is None:
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.clear()
                pane.write("[red]services_adapter indisponible[/]")
            except Exception:
                pass
            return
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold yellow]── SERVICES (supervisor :8765) ──[/]")
            services = _svc_a.list_services()
            if not services:
                pane.write("[dim]supervisor DOWN ou liste vide[/]")
                return
            color_map = {
                "running": "green",
                "starting": "yellow",
                "restarting": "yellow",
                "sleeping": "blue",
                "stopped": "red",
                "disabled": "dim",
            }
            for s in services:
                col = color_map.get(s["status"], "white")
                star = "*" if s["essential"] else " "
                pid = s.get("pid") or "-"
                up = s.get("uptime_s") or 0
                up_s = f"{int(up)}s" if up and up < 3600 else (f"{up // 3600}h" if up else "-")
                port = s.get("port") or ""
                port_s = f":{port}" if port else ""
                pane.write(
                    f"{star} [{col}]{s['status']:10}[/] "
                    f"[bold]{s['name']:24}[/] pid={pid!s:>5} up={up_s:>4} "
                    f"r={s['restarts']} {port_s}"
                )
        except Exception as e:
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.write(f"[red]services err: {e}[/]")
            except Exception:
                pass

    def _render_tasks(self) -> None:
        if _tsk_a is None:
            return
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold yellow]── TASKS (agent_tasks) ──[/]")
            counts = _tsk_a.task_counts()
            if counts:
                summary = " ".join(f"{k}={v}" for k, v in counts.items())
                pane.write(f"[dim]{summary}[/]")
                pane.write("")
            for t in _tsk_a.recent_tasks(limit=20):
                col = {
                    "done": "green",
                    "in_progress": "cyan",
                    "queued": "yellow",
                    "failed": "red",
                }.get(t["status"], "white")
                pane.write(f"[{col}]{t['status']:11}[/] [bold]#{t['id']}[/] {t['title']:60}")
                pane.write(
                    f"  [dim]exec={t['executor']:14} type={t['task_type']:10} "
                    f"at={t['created_at'][-19:] if t['created_at'] else '-'}[/]"
                )
        except Exception as e:
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.write(f"[red]tasks err: {e}[/]")
            except Exception:
                pass

    def _render_health(self) -> None:
        if _hlt_a is None:
            return
        try:
            pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
            pane.clear()
            pane.write("[bold yellow]── HEALTH (forge_health_diagnostic) ──[/]")
            r = _hlt_a.load_report()
            score = r.get("score")
            if score is None:
                pane.write(f"[dim]rapport absent — {r.get('error', '?')}[/]")
                pane.write("[dim]Run : LAFORGE_PYTHON app/forge_health_diagnostic.py --once[/]")
                return
            col = "green" if score >= 80 else "yellow" if score >= 50 else "red"
            pane.write(f"[bold {col}]Score {score}/100[/]  [dim]{r.get('ts', '')}[/]")
            pane.write(
                f"RAG vec : {r.get('rag_pct_vec', '?')}%   "
                f"imports morts : {r.get('imports_broken', 0)}   "
                f"keys broken : {r.get('provider_keys_broken', 0)}"
            )
            hor = r.get("hormones") or []
            if hor:
                pane.write(f"[bold cyan]hormones :[/] {', '.join(hor)}")
            pane.write("")
            gaps = r.get("gaps") or []
            pane.write(f"[bold]Lacunes ({len(gaps)}) :[/]")
            for g in gaps[:12]:
                pane.write(f"  {g}")
        except Exception as e:
            try:
                pane = self.query_one("#pane_agt_master_llamacpp", RichLog)
                pane.write(f"[red]health err: {e}[/]")
            except Exception:
                pass

    def action_toggle_unread_filter(self) -> None:
        """Ctrl+U : cache panes sans nouveaux msgs."""
        self._unread_filter = not self._unread_filter
        for a in AGENTS:
            try:
                pane = self.query_one(f"#pane_{a['id']}", RichLog)
                if self._unread_filter and self._unread_count.get(a["id"], 0) == 0:
                    pane.styles.display = "none"
                else:
                    pane.styles.display = "block"
            except Exception:
                pass
        self._render_status()

    def action_toggle_opsec_lock(self) -> None:
        """Ctrl+L : pose ou retire verrou humain OPSEC via WebHub."""
        current = opsec_state()
        new_lock = not current["locked"]
        result = toggle_human_lock_via_webhub(new_lock)
        try:
            pane = self.query_one("#status_pane", RichLog)
            if result.get("ok"):
                pane.write(f"[bold green]OPSEC lock {'SET' if new_lock else 'RELEASED'}[/]")
            else:
                pane.write(f"[bold red]OPSEC toggle FAIL: {result.get('error', '?')[:60]}[/]")
        except Exception:
            pass
        self._render_status()

    async def on_unmount(self) -> None:
        self._save_session()
        if self._poll_task:
            self._poll_task.cancel()


def register_codex_if_missing() -> None:
    """Phase 2.5 — enregistre agt_codex dans forge_entities si absent."""
    if not DB.exists():
        return
    try:
        conn = sqlite3.connect(str(DB))
        row = conn.execute("SELECT 1 FROM forge_entities WHERE entity_id='agt_codex'").fetchone()
        if not row:
            conn.execute(
                "INSERT INTO forge_entities (entity_id, entity_type, display_name, ring_level, capabilities, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (
                    "agt_codex",
                    "llm",
                    "Codex CLI",
                    2,
                    json.dumps(["read_chunk", "run_python", "task_create", "web_search"]),
                ),
            )
            conn.commit()
            print("[+] agt_codex registered in forge_entities")
        # agt_master_llamacpp aussi
        row = conn.execute(
            "SELECT 1 FROM forge_entities WHERE entity_id='agt_master_llamacpp'"
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO forge_entities (entity_id, entity_type, display_name, ring_level, capabilities, is_active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (
                    "agt_master_llamacpp",
                    "llm",
                    "llama.cpp Master Local",
                    3,
                    json.dumps(["chat", "code"]),
                ),
            )
            conn.commit()
            print("[+] agt_master_llamacpp registered")
        conn.close()
    except Exception as e:
        print(f"[!] register codex/master err: {e}")


def main() -> int:
    register_codex_if_missing()
    app = NokidoTUI()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
