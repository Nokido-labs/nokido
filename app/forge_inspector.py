# -*- coding: utf-8 -*-
"""
forge_inspector.py — Monitoring autonome Nokido v1.0
======================================================
Branché sur forge_network_logger.net_log() — bus centralisé existant.
Ajoute : CPU/RAM/disque (psutil), réseau, zombie killer, snapshot état sain.

FONCTIONS :
  1. SYSTEM MONITOR  — CPU, RAM, disque, réseau via psutil (si dispo)
  2. PROCESS GUARDIAN — kill zombies Python/Node en doublon
  3. PORT SENTINEL   — ports critiques, doublon = kill + alerte
  4. LOG AGGREGATOR  — parse tous les logs, détecte patterns d erreur
  5. SNAPSHOT SAVER  — état connu-bon sauvegardé quand tout est OK
  6. ACTION BROKER   — actions correctives automatiques

Démarrage : forge_inspector.start() dans nokido_hub.py boot
Intervalle : 30s
Logs       : via net_log(channel=INTERNAL) → network_log SQLite + mcp_audit.log
"""

from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"

# ── Bus de logging centralisé — verbosité contrôlée ─────────────────────────
# Règles de verbosité :
#   INFO  → silencieux (cycles OK, scans normaux) — pas de valeur répétée
#   WARN  → loggué : zombie tué, port DOWN, erreur détectée dans logs
#   ERR   → loggué : service DOWN, OOM, action corrective
#   CYCLE → loggué 1 fois sur 10 si OK, toujours si WARN/ERR
_cycle_count = 0


def _log(direction: str, tool: str, status: str, detail: str = "", agent: str = "INSPECTOR"):
    """Émet via net_log() — filtre verbosité : WARN/ERR only sauf cycle summary."""
    # Filtrer les INFO répétitifs sans valeur
    if status == "INFO" and tool in ("inspector", "inspector.cycle"):
        return  # silencieux — cycle OK pas d intérêt technique
    try:
        import sys as _s

        if str(ROOT / "app") not in _s.path:
            _s.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_network_logger import net_log, NetworkChannel, Direction

        net_log(
            channel=NetworkChannel.INTERNAL,
            direction=Direction.OUT if direction == "OUT" else Direction.IN,
            method=tool,
            tool=tool,
            agent=agent,
            status=status,
            payload_out=detail[:400] if detail else None,
        )
    except Exception as e:  # noqa: BLE001
        import logging as _lg

        _lg.getLogger(__name__).warning(
            "[inspector] evenement NON journalise (%s: %s) | consequence: l'inspection "
            "aura des trous, et un trou dans une inspection se lit comme une periode "
            "sans anomalie", type(e).__name__, str(e)[:90])


# ── Configuration ─────────────────────────────────────────────────────────────
CRITICAL_PORTS = {
    8765: "LaForge-Master",
    8766: "Nokido Hub",
    8767: "netcfg-agent-mcp",
    11434: "Ollama",
}

SINGLETON_LIMITS = {
    "nokido_hub.py": 1,
    # Bridges stdio : Claude Desktop lance TOUJOURS 2 copies légitimes par
    # serveur (fenêtre principale + pool partagé Cowork/Code « they run their
    # own copy »). Limite 1 = l'inspector abattait la copie principale en
    # « ZOMBIE KILLED pattern=netcfg » (incident 2026-08-23, netcfg failed
    # en boucle dans Desktop). 3 = 2 copies + marge de relance.
    "mcp_stdio_bridge.py": 3,
    "forge_collab_broker.py": 1,
    "forge_python_worker.py": 1,  # Mutualisation forcée via ZeroMQ/IPC (v14.0)
    "netcfg_stdio_bridge.py": 3,
    "netcfg-agent-mcp.exe": 1,
    "llama-server.exe": 1,       # Unification : 1 seul serveur concurrent requis (Continuous Batching)
    "ollama.exe": 1,
}

MAX_NODE_PROCS = 3  # cmd + 2 node pour searxng

ERROR_PATTERNS = {
    r"WinError 10048": "port_conflict",
    r"ConnectionRefusedError": "service_down",
    r"No such file or directory": "path_broken",
    r"out of memory|OOM": "oom",
    r"SyntaxError": "syntax_error",
    r"ModuleNotFoundError": "import_error",
    r"Traceback": "traceback",
    r"NSSM.*FAIL|FAIL.*NSSM": "nssm_fail",
}

WATCHED_LOGS = [
    "logs/mcp_service_err.log",
    "logs/mcp_bridge.log",
    "logs/inspector.log",
    "logs/service_monitor.log",
    "logs/post_commit.log",
]

_running = False
_thread: Optional[threading.Thread] = None


# ── 1. SYSTEM MONITOR (psutil) ────────────────────────────────────────────────
def _sys_metrics() -> dict:
    """CPU/RAM/disque/réseau via psutil. Graceful si absent."""
    metrics = {}
    try:
        import psutil

        metrics["cpu_pct"] = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory()
        metrics["ram_pct"] = mem.percent
        metrics["ram_used_gb"] = round(mem.used / 1e9, 2)
        disk = psutil.disk_usage(str(ROOT))
        metrics["disk_pct"] = disk.percent
        net = psutil.net_io_counters()
        metrics["net_sent_mb"] = round(net.bytes_sent / 1e6, 1)
        metrics["net_recv_mb"] = round(net.bytes_recv / 1e6, 1)
        # Connexions actives sur ports critiques
        conns = psutil.net_connections(kind="inet")
        for port, name in CRITICAL_PORTS.items():
            listening = [c for c in conns if c.laddr.port == port and c.status == "LISTEN"]
            metrics[f"port_{port}"] = "OK" if listening else "DOWN"
    except ImportError:
        # psutil absent — fallback netstat minimal
        try:
            # errors="replace" OBLIGATOIRE : netstat n'ecrit pas de l'UTF-8 sur un
            # Windows localise (cp1252/cp850). Sans lui, UnicodeDecodeError dans le
            # thread lecteur -> l'except ci-dessous avale TOUT et le capteur devient
            # aveugle en silence (anti-regression incident 47 Go).
            r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=5)
            for port, name in CRITICAL_PORTS.items():
                metrics[f"port_{port}"] = "OK" if f":{port} " in r.stdout else "DOWN"
        except Exception:
            pass
    except Exception as e:
        metrics["error"] = str(e)[:80]
    return metrics


# ── 2. PROCESS GUARDIAN ───────────────────────────────────────────────────────
def _scan_procs() -> dict:
    """Inventaire PID→cmd des process Python/Node/cmd."""
    result: dict[str, dict] = {"python": {}, "node": {}, "exe": {}}
    try:
        r = subprocess.run(
            [
                "powershell",
                "-Command",
                "Get-WmiObject Win32_Process | "
                "Where-Object {$_.Name -in ('python.exe','node.exe','cmd.exe','netcfg-agent-mcp.exe')} | "
                "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        procs = json.loads(r.stdout or "[]")
        if isinstance(procs, dict):
            procs = [procs]
        for p in procs:
            pid = str(p.get("ProcessId", ""))
            name = (p.get("Name", "") or "").lower()
            cmd = p.get("CommandLine", "") or ""
            if "python" in name:
                result["python"][pid] = cmd
            elif "node" in name:
                result["node"][pid] = cmd
            elif "netcfg" in name:
                result["exe"][pid] = cmd
    except Exception as e:
        _log("OUT", "inspector", "WARN", f"scan_procs: {e}")
    return result


_pid_first_seen: dict[str, float] = {}  # pid → first time seen as duplicate
_KILL_GRACE_S = 90  # grace period before killing a duplicate hub/core process
_KILL_GRACE_PATTERNS = {"nokido_hub.py", "mcp_stdio_bridge.py", "netcfg_stdio_bridge.py"}


def _kill_zombies(procs: dict) -> list:
    """Tue les process en doublon au-delà de leur limite."""
    killed = []
    now = time.time()

    # Python — par pattern de script
    for pattern, max_n in SINGLETON_LIMITS.items():
        matches = [(pid, cmd) for pid, cmd in procs["python"].items() if pattern in cmd]
        if len(matches) > max_n:
            # Garder les max_n plus récents (PIDs les plus hauts)
            to_kill = sorted(matches, key=lambda x: int(x[0]))[:-max_n]
            for pid, cmd in to_kill:
                # Grace period for hub/bridge — don't kill within _KILL_GRACE_S of first sight
                if pattern in _KILL_GRACE_PATTERNS:
                    first = _pid_first_seen.setdefault(pid, now)
                    if now - first < _KILL_GRACE_S:
                        _log(
                            "OUT",
                            "inspector.kill",
                            "INFO",
                            f"GRACE: {pattern[:30]} pid={pid} ({int(now - first)}s < {_KILL_GRACE_S}s)",
                        )
                        continue
                try:
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
                    killed.append({"pid": pid, "reason": f"zombie:{pattern}"})
                    _pid_first_seen.pop(pid, None)
                    _log("OUT", "inspector.kill", "WARN", f"ZOMBIE KILLED pid={pid} pattern={pattern[:40]}")
                except Exception as e:
                    _log("OUT", "inspector.kill", "ERR", f"kill {pid}: {e}")
        else:
            # Clean up stale PIDs no longer duplicates
            for pid in list(_pid_first_seen):
                if pid not in {p for p, _ in matches}:
                    _pid_first_seen.pop(pid, None)

    # Node.exe — max MAX_NODE_PROCS
    node_pids = sorted(procs["node"].keys(), key=int)
    if len(node_pids) > MAX_NODE_PROCS:
        for pid in node_pids[:-MAX_NODE_PROCS]:
            try:
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
                killed.append({"pid": pid, "reason": "zombie:node"})
                _log("OUT", "inspector.kill", "WARN", f"NODE ZOMBIE pid={pid}")
            except Exception:
                pass

    return killed


# ── 3. PORT SENTINEL ─────────────────────────────────────────────────────────
def _check_ports() -> dict:
    """Vérifie les ports critiques depuis netstat."""
    result = {}
    try:
        # errors="replace" : cf. _sys_metrics. Ici l'enjeu est plus grave — sans lui,
        # une seule ligne non decodable fait echouer TOUTE la sentinelle de ports,
        # et un capteur qui ne peut pas voir se lit comme « aucun port DOWN ».
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=8)
        listeners: dict[int, list] = {}
        for line in (r.stdout or "").splitlines():
            if "LISTENING" not in line:
                continue
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                port = int(parts[1].split(":")[-1])
                pid = parts[-1]
                if port in CRITICAL_PORTS:
                    listeners.setdefault(port, []).append(pid)
            except ValueError:
                pass

        for port, name in CRITICAL_PORTS.items():
            pids = list(set(listeners.get(port, [])))
            if not pids:
                result[port] = "DOWN"
                _log("OUT", "inspector.port", "ERR", f"PORT DOWN :{port} {name}")
            elif len(pids) > 1:
                result[port] = "DUPLICATE"
                _log("OUT", "inspector.port", "WARN", f"DUPLICATE :{port} PIDs={pids}")
                # Tuer les doublons — garder le PID le plus bas (le plus ancien = le bon)
                for pid in sorted(pids, key=int)[1:]:
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=5)
            else:
                result[port] = "OK"
    except Exception as e:
        _log("OUT", "inspector.port", "ERR", f"check_ports: {e}")
    # Si résultat vide (race condition boot ou netstat timeout) — fallback socket
    if not result:
        for port, name in CRITICAL_PORTS.items():
            try:
                s = socket.socket()
                s.settimeout(1)
                s.connect(("127.0.0.1", port))
                s.close()
                result[port] = "OK"
            except Exception:
                result[port] = "DOWN"
    return result


def _heal_ports(ports: dict):
    """Actions correctives sur les ports DOWN."""
    if ports.get(8766) == "DOWN":
        # LaForge-Master :8765 owns NokidoMCP — skip nssm if master is UP
        master_up = ports.get(8765) == "OK"
        if master_up:
            _log(
                "OUT",
                "inspector.heal",
                "INFO",
                "Hub 8766 DOWN but LaForge-Master :8765 UP — skip nssm, master owns hub",
            )
        else:
            _now = time.time()
            if _now - _last_action.get("hub_nssm_start", 0) > 120:
                _last_action["hub_nssm_start"] = _now
                _log("OUT", "inspector.heal", "WARN", "Hub 8766 DOWN + Master DOWN → nssm start NokidoMCP")
                subprocess.run(["nssm", "start", "NokidoMCP"], capture_output=True)
    if ports.get(8767) == "DOWN":
        # Vérifier via MCP avant d alerter — netcfg écoute en mode standalone pas TCP direct
        try:
            import urllib.request as _ur

            _body = json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "netcfg_ping", "arguments": {}}}
            ).encode()
            _env = ROOT / "Nokido.env"
            _tok = ""
            try:
                for _ln in _env.read_text(errors="ignore").splitlines():
                    if _ln.startswith("FORGE_MCP_TOKEN="):
                        _tok = _ln.split("=", 1)[1].strip()
                        break
            except:
                pass
            _req = _ur.Request(
                "http://127.0.0.1:8766/mcp",
                data=_body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {_tok}",
                    "X-Agent-Name": "INSPECTOR",
                },
                method="POST",
            )
            _r = _ur.urlopen(_req, timeout=3)
            _res = json.loads(_r.read())
            _txt = _res.get("result", {}).get("content", [{}])[0].get("text", "")
            if '"ok": true' in _txt or '"ok":true' in _txt:
                # netcfg répond via MCP — faux positif TCP, pas d alerte
                ports[8767] = "OK_MCP"
                return
        except Exception:
            pass
        # Vrai DOWN — alerter une seule fois (cooldown via _last_action)
        _now = time.time()
        if _now - _last_action.get("netcfg_down", 0) > 300:
            _last_action["netcfg_down"] = _now
            _log("OUT", "inspector.heal", "WARN", "netcfg 8767 DOWN confirmé MCP — restart manuel requis")
            try:
                import urllib.request as _ur2, os as _os2

                _tok2 = _os2.environ.get("FORGE_MCP_TOKEN", "")
                _body2 = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "hub",
                            "arguments": {
                                "action": "notify",
                                "message": "⚠ netcfg-agent-mcp DOWN (confirmé MCP) — restart manuel requis",
                            },
                        },
                    }
                ).encode()
                _req2 = _ur2.Request(
                    "http://127.0.0.1:8766/mcp",
                    data=_body2,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {_tok2}",
                        "X-Agent-Name": "INSPECTOR",
                    },
                    method="POST",
                )
                _ur2.urlopen(_req2, timeout=3)
            except Exception:
                pass


# ── 4. LOG AGGREGATOR — offset tracking (pas de faux positifs sur lignes anciennes)
_log_offsets: dict[str, int] = {}  # chemin → dernier offset lu


def _parse_logs(lines_each: int = 30) -> list:
    """Lit uniquement les NOUVELLES lignes depuis le dernier scan."""
    events = []
    for rel in WATCHED_LOGS:
        p = ROOT / rel
        if not p.exists():
            continue
        try:
            size = p.stat().st_size
            offset = _log_offsets.get(rel, size)  # premier run = skip ancien
            if size <= offset:
                _log_offsets[rel] = size
                continue  # pas de nouvelles lignes
            with open(str(p), encoding="utf-8", errors="replace") as fh:
                fh.seek(offset)
                new_content = fh.read()
            _log_offsets[rel] = size
            lines = new_content.splitlines()
            for line in lines[-lines_each:]:
                for pattern, action in ERROR_PATTERNS.items():
                    if re.search(pattern, line, re.IGNORECASE):
                        events.append({"source": rel, "line": line.strip()[:150], "action": action, "ts": time.time()})
        except Exception as e:  # noqa: BLE001
            import logging as _lg

            # Un fichier de log non analyse ne remonte AUCUNE erreur : son silence
            # ressemble alors a un organe sain. C'est le defaut le plus couteux d'un
            # scanner — surestimer sa propre couverture.
            _lg.getLogger(__name__).warning(
                "[inspector] journal %s NON analyse (%s: %s) — ecarte | consequence: "
                "aucune erreur ne remontera de cette source, et son silence passera "
                "pour de la sante", rel, type(e).__name__, str(e)[:80])
    return events


# Compteurs de confirmation — évite les faux positifs
# Règle : 3 détections consécutives = action auto
_confirm: dict[str, int] = {}
_CONFIRM_THRESHOLD = 3  # cycles consécutifs avant action

# Matrice actions auto — niveau de confiance requis
# Format: {action: {threshold, cooldown_s, safe_auto}}
ACTION_MATRIX = {
    # SAFE — action réversible, risque faible
    # cooldown 120 -> 600 (décision owner 2026-07-26 : « éviter le spam de
    # processus »). Mesure de `tools/forge_regulation_loops.py` : 120 s autorisait
    # 30 tirs/heure pour un budget de 6/h en gravité `high`. La réactivité n'est
    # PAS perdue pour autant : l'override par urgence ci-dessous laisse passer une
    # vraie montée de RAM bien avant la fin des 600 s.
    "oom": {"threshold": 2, "cooldown": 600, "safe": True, "desc": "Kill workers Python"},
    "zombie": {"threshold": 1, "cooldown": 60, "safe": True, "desc": "Kill process zombie"},
    "port_conflict": {"threshold": 2, "cooldown": 60, "safe": True, "desc": "Kill PID doublon"},
    # PRUDENT — action impactante, threshold plus haut
    "service_down": {"threshold": 3, "cooldown": 300, "safe": True, "desc": "nssm start hub"},
    "nssm_fail": {"threshold": 3, "cooldown": 600, "safe": False, "desc": "Alert only — manuel"},
    # BLOQUÉ — trop risqué pour auto
    "path_broken": {"threshold": 99, "cooldown": 0, "safe": False, "desc": "Manuel requis"},
    "syntax_error": {"threshold": 99, "cooldown": 0, "safe": False, "desc": "Manuel requis"},
}
_last_action: dict[str, float] = {}


# Effecteurs dont l'urgence est LUE sur le corps : {action: nom de boucle déclarée}
_URGENCY_LOOPS = {"oom": "inspector.oom"}


def _urgency_allows(act: str, elapsed_s: float, cooldown_s: float) -> bool:
    """Un cooldown fixe est un compromis impossible : trop court il tétanise, trop
    long l'effecteur n'agit jamais quand il faut. On garde donc le cooldown comme
    réfractaire RELATIVE et on autorise un franchissement anticipé si l'urgence
    MESURÉE le justifie — avec un plancher ABSOLU infranchissable qui couvre le
    contrecoup du remède (cf. tools/forge_regulation_loops.py, mandat owner
    2026-07-26).

    Fail-closed : toute incertitude (module absent, métrique illisible, pente non
    mesurable) répond False. Un doute ne doit jamais AUTORISER un kill.
    """
    name = _URGENCY_LOOPS.get(act)
    if not name:
        return False
    try:
        # `sys` n'est PAS importé en tête de ce module (vérifié 2026-07-26) : sans
        # cet import local, la ligne suivante lèverait NameError, l'`except` en
        # dessous l'avalerait, et l'override ne servirait JAMAIS — un no-op muet,
        # exactement le piège déjà payé aujourd'hui avec un import manquant.
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
        from nokido_agent.tools import forge_regulation_loops as _rl

        loop = next((lp for lp in _rl.LOOPS if lp.name == name), None)
        if loop is None or not loop.urgency_metric:
            return False
        urg = _rl.body_urgency(loop.urgency_metric).get("urgency")
        if urg is None:
            return False
        decision = loop.should_fire(elapsed_s, urg)
        if decision.get("fire"):
            _log("OUT", "inspector.urgency", "WARN",
                 f"{act}: franchissement anticipé — {decision.get('reason')} "
                 f"(écoulé {elapsed_s:.0f}s / cooldown {cooldown_s:.0f}s)")
            return True
        return False
    except Exception:  # noqa: BLE001
        return False


def _react(events: list) -> list:
    """Actions auto avec triple confirmation et cooldown."""
    actions = []
    seen = set()
    for evt in events:
        act = evt["action"]
        if act in seen:
            continue
        seen.add(act)
        cfg = ACTION_MATRIX.get(act, {"threshold": 99, "safe": False})
        # Incrémenter le compteur de confirmation
        _confirm[act] = _confirm.get(act, 0) + 1
        count = _confirm[act]
        threshold = cfg["threshold"]
        cooldown = cfg.get("cooldown", 300)
        now = time.time()
        # Vérifier cooldown — franchissable si l'urgence mesurée le justifie
        _elapsed = now - _last_action.get(act, 0)
        if _elapsed < cooldown and not _urgency_allows(act, _elapsed, cooldown):
            continue
        # Vérifier threshold
        if count < threshold:
            _log("OUT", "inspector.confirm", "WARN", f"{act}: confirmation {count}/{threshold} — attente")
            continue
        # Seuil atteint — action auto
        _confirm[act] = 0  # reset
        _last_action[act] = now
        if act == "oom":
            # Tuer les workers Python
            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "Get-WmiObject Win32_Process | Where-Object {$_.CommandLine -like '*forge_python_worker*'} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }",
                ],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            _log("OUT", "inspector.react", "WARN", "OOM → workers Python tués")
            actions.append("oom_kill_workers")
        elif act == "port_conflict":
            _log("OUT", "inspector.react", "WARN", "port_conflict → zombie scan")
            actions.append("port_conflict_scan")
        elif act == "service_down":
            _log("OUT", "inspector.react", "WARN", "service_down → heal_ports")
            actions.append("service_heal")
    return actions


# ── 5. SNAPSHOT ÉTAT SAIN ────────────────────────────────────────────────────
def _save_snapshot(ports: dict, procs: dict, metrics: dict):
    """Sauvegarde l état quand tout est OK."""
    if any(v != "OK" for v in ports.values()):
        return
    snap = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ports": ports,
        "python_count": len(procs["python"]),
        "node_count": len(procs["node"]),
        "metrics": {k: v for k, v in metrics.items() if "port_" not in k},
        "known_good": True,
    }
    path = ROOT / "sandbox" / "inspector_snapshot.json"
    path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")


def load_snapshot() -> dict:
    path = ROOT / "sandbox" / "inspector_snapshot.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


# ── 6. BOUCLE PRINCIPALE ─────────────────────────────────────────────────────


# Noeuds dont la ligne de heartbeat est MORTE : signales UNE fois par run, pas a
# chaque cycle — un avertissement repete toutes les 30 s devient du bruit qu'on ignore.
_STALE_SIGNALES: set[str] = set()


def _update_heartbeats(ports: dict, metrics: dict):
    """Met à jour fleet_heartbeats + compute_nodes toutes les 30s."""
    try:
        conn = sqlite3.connect(str(ROOT / "RAG" / "embeddings.db"), timeout=3)
        conn.execute("PRAGMA journal_mode=WAL")
        now = "datetime('now')"
        # Bridges et services
        for node_id, port in [("hub_nokido", 8766), ("netcfg_agent", 8767)]:
            st = ports.get(port, "DOWN")
            missed = 0 if st == "OK" else 1
            conn.execute(
                "INSERT INTO fleet_heartbeats (node_id,node_type,status,missed_count,last_ping_at) "
                "VALUES (?,?,?,?,datetime('now')) ON CONFLICT(node_id) DO UPDATE SET "
                "status=excluded.status, last_ping_at=datetime('now'), "
                "missed_count=CASE WHEN excluded.status='OK' THEN 0 "
                "ELSE missed_count+1 END",
                (node_id, "service", st, missed),
            )
        # Bridge stdio — vivant si on tourne
        conn.execute(
            "INSERT INTO fleet_heartbeats (node_id,node_type,status,missed_count,last_ping_at) "
            "VALUES ('bridge_stdio','bridge','OK',0,datetime('now')) "
            "ON CONFLICT(node_id) DO UPDATE SET status='OK',last_ping_at=datetime('now'),missed_count=0"
        )
        # Compute nodes — vérifier ollama/llamacpp via metrics
        for node_id, port_key in [("ollama_local", "port_11434"), ("llamacpp_local", "port_1234")]:
            port_val = metrics.get(port_key, "DOWN")
            st = "ready" if port_val == "OK" else "offline"
            conn.execute("UPDATE compute_nodes SET status=?,last_seen=datetime('now') WHERE node_id=?", (st, node_id))
        # Alerte si un noeud VIVANT rate ses battements. Mesure 2026-08-02 : la requete
        # ne regardait que `missed_count`, jamais la fraicheur — donc `hub_laforge`,
        # ligne laissee par le renommage LaForge->Nokido (dernier ping 2026-07-09,
        # compteur fige a 29), re-declenchait un CIRCUIT BREAK a CHAQUE cycle depuis
        # 24 jours, pendant que le hub repondait. Un garde qui crie a faux se fait
        # desarmer : « rate des battements » et « n'emet plus rien » sont deux etats
        # distincts, et le second n'est pas une panne — c'est une ligne morte.
        missed_rows = conn.execute(
            "SELECT node_id, missed_count FROM fleet_heartbeats "
            "WHERE missed_count >= 3 AND last_ping_at >= datetime('now', '-1 hour')"
        ).fetchall()
        for node_id, missed in missed_rows:
            _log("OUT", "inspector.heartbeat", "ERR", f"CIRCUIT BREAK: {node_id} a manqué {missed} heartbeats")
        # Une ligne morte ne se purge pas toute seule : la taire serait retomber dans
        # « je n'ai rien vu » = « il n'y a rien ». On la NOMME, une fois, en WARN.
        for _sid, _vu in conn.execute(
            "SELECT node_id, last_ping_at FROM fleet_heartbeats "
            "WHERE last_ping_at < datetime('now', '-1 day')"
        ).fetchall():
            if _sid not in _STALE_SIGNALES:
                _STALE_SIGNALES.add(_sid)
                _log("OUT", "inspector.heartbeat", "WARN",
                     f"ligne de heartbeat MORTE : {_sid} muet depuis {_vu} — plus aucun "
                     "emetteur (residu de renommage ?), a purger")
        conn.commit()
        conn.close()
    except Exception as e:
        _log("OUT", "inspector.heartbeat", "WARN", f"heartbeat error: {e}")


def _loop():
    global _running
    _log("OUT", "inspector", "INFO", "Démarré — scan toutes les 30s")
    cycle = 0
    while _running:
        try:
            cycle += 1
            t0 = time.monotonic()

            metrics = _sys_metrics()
            procs = _scan_procs()
            killed = _kill_zombies(procs)
            ports = _check_ports()
            _heal_ports(ports)
            _update_heartbeats(ports, metrics)
            events = _parse_logs()
            actions = _react(events)
            _save_snapshot(ports, procs, metrics)

            elapsed = round((time.monotonic() - t0) * 1000)
            n_down = sum(1 for v in ports.values() if v != "OK")
            status = "OK" if not n_down and not killed and not events else "WARN"

            summary = (
                f"cycle={cycle} {elapsed}ms | cpu={metrics.get('cpu_pct', '?')}% "
                f"ram={metrics.get('ram_pct', '?')}% | ports_down={n_down} "
                f"zombies={len(killed)} errors={len(events)} actions={actions}"
            )
            _log("OUT", "inspector.cycle", status, summary)

            # Écrire dans inspector_log SQLite
            try:
                # Journal d'organe : retire du verrou RAG (owner 2026-09-19).
                # 1 954 prises du verrou en 33 h pour un journal que personne ne
                # joint au RAG. `journal_path` rend la base HISTORIQUE tant que
                # `sandbox/journaux.switch` est absent : ce site ne change donc
                # pas de comportement tant qu'on n'a pas bascule. ⚠ NE PAS
                # toucher le connect de `_update_heartbeats` plus haut : celui-la
                # ecrit fleet_heartbeats/compute_nodes, pas ce journal.
                try:
                    from forge_db_path import journal_path
                    _base_journal = journal_path("inspector_log")
                except ImportError:  # muet-ok: repli EXPLICITE sur le chemin historique
                    _base_journal = str(ROOT / "RAG" / "embeddings.db")
                conn = sqlite3.connect(_base_journal, timeout=3)
                conn.execute("""CREATE TABLE IF NOT EXISTS inspector_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT DEFAULT (datetime('now')),
                    status TEXT, ports_down INTEGER,
                    zombies INTEGER, errors INTEGER,
                    cpu_pct REAL, ram_pct REAL,
                    detail TEXT)""")
                conn.execute(
                    "INSERT INTO inspector_log (status,ports_down,zombies,errors,cpu_pct,ram_pct,detail) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        status,
                        n_down,
                        len(killed),
                        len(events),
                        metrics.get("cpu_pct"),
                        metrics.get("ram_pct"),
                        json.dumps({"ports": ports, "killed": killed, "actions": actions})[:800],
                    ),
                )
                conn.execute(
                    "DELETE FROM inspector_log WHERE id NOT IN "
                    "(SELECT id FROM inspector_log ORDER BY id DESC LIMIT 2000)"
                )
                conn.commit()
                conn.close()
            except Exception:
                pass

        except Exception as e:
            _log("OUT", "inspector", "ERR", f"cycle error: {e}")
        time.sleep(30)


# ── API PUBLIQUE ──────────────────────────────────────────────────────────────
def start():
    global _running, _thread
    if _running:
        return
    _running = True
    _thread = threading.Thread(target=_loop, daemon=True, name="forge_inspector")
    _thread.start()
    _log("OUT", "inspector", "INFO", "Thread démarré")


def stop():
    global _running
    _running = False


def status() -> dict:
    """État immédiat consultable depuis un tool MCP."""
    procs = _scan_procs()
    ports = _check_ports()
    metrics = _sys_metrics()
    snap = load_snapshot()
    try:
        import sys as _s, os as _o

        _app = str(ROOT.parent / "app")
        if _app not in _s.path:
            _s.path.insert(0, _app)
        from nokido_agent.app.forge_project_state_graph import scan_project

        g = scan_project(str(ROOT.parent))
        by_status: dict = {}
        for n in g.nodes.values():
            by_status[n.status] = by_status.get(n.status, 0) + 1
        blocked = g.get_blocked()
        ready = g.get_ready_to_test()
        cp = g.critical_path()
        proj_graph = {
            "total": len(g.nodes),
            "by_status": by_status,
            "blocked_count": len(blocked),
            "blocked": [n.id for n in blocked[:5]],
            "ready_to_test": [n.id for n in ready[:5]],
            "critical_path": cp[:8],
        }
    except Exception as _e:
        proj_graph = {"error": str(_e)[:120]}
    return {
        "running": _running,
        "ports": ports,
        "python_count": len(procs["python"]),
        "node_count": len(procs["node"]),
        "metrics": metrics,
        "last_good_state": snap.get("ts", "never"),
        "project_graph": proj_graph,
    }


def cleanup_now() -> dict:
    """Purge immédiate — appeler au boot du hub."""
    procs = _scan_procs()
    killed = _kill_zombies(procs)
    ports = _check_ports()
    _heal_ports(ports)
    metrics = _sys_metrics()
    _log("OUT", "inspector.cleanup", "INFO", f"Boot cleanup: killed={len(killed)} ports={ports}")
    return {"killed": killed, "ports": ports, "metrics": metrics}


if __name__ == "__main__":
    import json as _j

    print(_j.dumps(status(), indent=2, ensure_ascii=False))
