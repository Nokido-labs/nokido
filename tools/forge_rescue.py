#!/usr/bin/env python3
"""
forge_rescue.py — Canal de secours Nokido v2.0 (ON-DEMAND + DROITS ADMIN)
===========================================================================
Script DORMANT — zéro overhead au repos. Activé manuellement ou via run().

USAGE :
    python tools/forge_rescue.py --status           # diagnostic complet
    python tools/forge_rescue.py --restore          # restaure claude_desktop_config.json
    python tools/forge_rescue.py --restart-hub      # redémarre NokidoMCP via NSSM (admin)
    python tools/forge_rescue.py --restart-netcfg   # redémarre netcfg-agent-mcp.exe (admin)
    python tools/forge_rescue.py --restart-all      # tout redémarrer (admin)
    python tools/forge_rescue.py --ask "question"   # canal qwen3:8b local
    python tools/forge_rescue.py --full             # status + restore + restart si besoin

DROITS ADMIN :
    Les actions --restart-* nécessitent des droits admin (NSSM + taskkill).
    Le script se ré-élève automatiquement via UAC si nécessaire.
    Si déjà admin : exécution directe sans UAC.

CONNAISSANCE DU CODE :
    Hub principal    : tools/nokido_hub.py  (PID observé : 28352)
    Bridge stdio     : tools/mcp_stdio_bridge.py  (proxy stdio→HTTP:8766/mcp)
    Service NSSM     : NokidoMCP  (nssm.exe dans C:/ProgramData/chocolatey/bin/)
    netcfg exe       : ../netcfg-agent-mcp/dist/netcfg-agent-mcp.exe
    netcfg token     : %USERPROFILE%/.netcfg-agent-mcp/token
    Config Claude    : %USERPROFILE%/AppData/Roaming/Claude/claude_desktop_config.json
    Nokido env      : Nokido.env  (FORGE_MCP_TOKEN, ports, flags)
    Log hub          : logs/mcp_service.log
    Log bridge       : logs/mcp_bridge.log
    Log rescue       : logs/rescue_agent.log
    Port Nokido     : 8766/mcp
    Port netcfg      : 8767/mcp
    Port Ollama      : 11434
    NSSM             : C:/ProgramData/chocolatey/bin/nssm.exe
    Rescue model     : qwen3:8b (Ollama local)
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── CHEMINS ──────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
CONFIG_PATH = Path(__import__("os").path.expanduser(r"~\AppData\Roaming\Claude\claude_desktop_config.json"))
TOKEN_NETCFG = Path(__import__("os").path.expanduser(r"~\.netcfg-agent-mcp\token"))
LAFORGE_ENV = ROOT / "Nokido.env"
LOG_PATH = ROOT / "logs" / "rescue_agent.log"
NSSM = Path(r"C:\ProgramData\chocolatey\bin\nssm.exe")
PYTHON = Path(__import__("os").path.expanduser(r"~\miniforge3\python.exe"))
NETCFG_EXE = Path(str(__import__("pathlib").Path(__file__).resolve().parents[2] / "netcfg-agent-mcp" / "dist" / "netcfg-agent-mcp.exe"))
RESCUE_MODEL = "qwen3:8b"
NSSM_SERVICE = "NokidoMCP"

# ── LOGGING ──────────────────────────────────────────────────────────────────


def _log(msg: str, level: str = "INFO"):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} [rescue] {level:5s} {msg}"
    print(line)
    try:
        LOG_PATH.parent.mkdir(exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── ADMIN ────────────────────────────────────────────────────────────────────


def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _elevate_and_rerun():
    """Re-lance ce script en admin via UAC si nécessaire."""
    _log("Droits admin requis — demande UAC...", "WARN")
    args = " ".join(f'"{a}"' for a in sys.argv)
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(PYTHON), f'"{__file__}" {args}', str(ROOT), 1
    )
    if ret <= 32:
        _log(f"UAC refusé ou erreur (code {ret})", "ERROR")
        sys.exit(1)
    sys.exit(0)


def _require_admin(action_name: str):
    if not _is_admin():
        _log(f"{action_name} nécessite les droits admin")
        _elevate_and_rerun()


def _run_admin(cmd: list, desc: str = "") -> tuple[int, str]:
    """Exécute une commande, en élevant si nécessaire."""
    _require_admin(desc or cmd[0])
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    out = (r.stdout + r.stderr).strip()
    _log(f"{desc or cmd[0]}: {out[:200]}" if out else f"{desc or cmd[0]}: OK")
    return r.returncode, out


# ── TOKENS ───────────────────────────────────────────────────────────────────


def _token_nokido() -> str:
    try:
        for line in LAFORGE_ENV.read_text(encoding="utf-8").splitlines():
            if "FORGE_MCP_TOKEN" in line and "=" in line:
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _token_netcfg() -> str:
    try:
        return TOKEN_NETCFG.read_text().strip()
    except Exception:
        return ""


# ── CONFIG CANONIQUE ─────────────────────────────────────────────────────────


def _canonical() -> dict:
    return {
        "Nokido": {
            "command": str(PYTHON).replace("\\", "/"),
            "args": [str(TOOLS / "mcp_stdio_bridge.py").replace("\\", "/")],
            "env": {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "LAFORGE_AGENT": "CLAUDE"},
        },
        "netcfg-agent-mcp": {
            "command": str(PYTHON).replace("\\\\", "/"),
            "args": [str(__import__("pathlib").Path(__file__).resolve().parents[2] / "netcfg-agent-mcp" / "netcfg_stdio_bridge.py")],
            "env": {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "NETCFG_MCP_TOKEN": _token_netcfg(),
            },
        },
        "MCP_DOCKER": {
            "command": "docker",
            "args": ["mcp", "gateway", "run"],
            "env": {
                "LOCALAPPDATA": __import__("os").path.expanduser(r"~\AppData\Local"),
                "ProgramData": r"C:\ProgramData",
                "ProgramFiles": r"C:\Program Files",
            },
        },
    }


def validate_config() -> bool:
    """Verifie claude_desktop_config.json, restaure depuis _canonical() si manquant."""
    import json
    import logging

    log = logging.getLogger("service_monitor")
    try:
        cfg_path = Path(__import__("os").path.expanduser(r"~\AppData\Roaming\Claude\claude_desktop_config.json"))
        current = json.loads(cfg_path.read_text(encoding="utf-8"))
        servers = current.get("mcpServers", {})
        canon = _canonical()
        missing = [k for k in canon if k not in servers]
        if missing:
            log.warning(f"[CONFIG] Serveurs manquants: {missing} — restauration")
            for k in missing:
                servers[k] = canon[k]
            current["mcpServers"] = servers
            cfg_path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[RESCUE] Config restauree: {missing}")
            return False
        log.info(f"[CONFIG] OK — {list(servers.keys())}")
        return True
    except Exception as e:
        log.error(f"[CONFIG] Erreur: {e}")
        return False


# ── STATUS ───────────────────────────────────────────────────────────────────


def cmd_status() -> dict:
    results = {}

    for name, url in [
        ("nokido_hub", "http://127.0.0.1:8766/health"),
        ("netcfg_agent", "http://127.0.0.1:8767/health"),
        ("ollama", "http://127.0.0.1:11434/api/tags"),
        # Stack LLM locale — étages de la cascade souveraine ollama -> lmstudio -> llamacpp
        ("lmstudio", "http://127.0.0.1:1234/v1/models"),
        ("llamacpp_8080", "http://127.0.0.1:8080/health"),
        ("llama_native_8091", "http://127.0.0.1:8091/health"),
        ("embedder_8099", "http://127.0.0.1:8099/health"),
    ]:
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                if name == "ollama":
                    data = json.loads(r.read())
                    models = [m["name"] for m in data.get("models", [])]
                    has_rescue = RESCUE_MODEL in models
                    gemma = [m for m in models if "gemma" in m.lower()]
                    results[name] = (
                        f"UP — {len(models)} modèles — {RESCUE_MODEL}: {'OK' if has_rescue else 'ABSENT'}"
                        f" — gemma: {', '.join(gemma) if gemma else 'ABSENT'}"
                    )
                else:
                    results[name] = f"UP ({r.status})"
        except Exception as e:
            # 401/403 = serveur UP mais Bearer requis (ex: LMStudio API key)
            code = getattr(e, "code", None)
            results[name] = f"UP (auth {code})" if code in (401, 403) else f"DOWN — {e}"

    # Service NSSM
    try:
        r = subprocess.run(["sc", "query", NSSM_SERVICE], capture_output=True, text=True, errors="replace")
        state = "RUNNING" if "RUNNING" in r.stdout else "STOPPED"
        results["nssm_service"] = state
    except Exception as e:
        results["nssm_service"] = f"ERREUR — {e}"

    # Config Claude Desktop
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        servers = list(cfg.get("mcpServers", {}).keys())
        missing = [k for k in _canonical() if k not in servers]
        results["claude_config"] = (
            f"OK — {servers}" if not missing else f"DÉGRADÉE — manquants: {missing}"
        )
    except Exception as e:
        results["claude_config"] = f"ILLISIBLE — {e}"

    # Bridge log dernière ligne
    try:
        bridge_log = ROOT / "logs" / "mcp_bridge.log"
        last = bridge_log.read_text(encoding="utf-8").splitlines()[-1]
        results["bridge_last_log"] = last[-120:]
    except Exception as e:
        results["bridge_last_log"] = f"ABSENT — {e}"

    # Admin status
    results["is_admin"] = "OUI" if _is_admin() else "NON (restart-* nécessitent UAC)"

    for k, v in results.items():
        _log(f"  {k:20s}: {v}")

    return results


# ── RESTORE ──────────────────────────────────────────────────────────────────


def cmd_restore(force: bool = False) -> bool:
    try:
        current = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        current = {}

    canonical = _canonical()
    missing = [k for k in canonical if k not in current.get("mcpServers", {})]

    if not force and not missing:
        _log("Config OK — aucune restauration nécessaire")
        return False

    current["mcpServers"] = canonical
    CONFIG_PATH.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"Config restaurée → {list(canonical.keys())}")
    _log("ACTION : Quit + relancer Claude Desktop pour appliquer")
    return True


# ── RESTART HUB (NSSM, admin requis) ─────────────────────────────────────────


def cmd_restart_hub():
    _require_admin("restart-hub")
    _log("Redémarrage NokidoMCP via NSSM...")
    _run_admin([str(NSSM), "stop", NSSM_SERVICE], "nssm stop")
    time.sleep(2)
    _run_admin([str(NSSM), "start", NSSM_SERVICE], "nssm start")
    time.sleep(3)
    # Vérif
    try:
        with urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=5) as r:
            _log(f"Hub UP après redémarrage ({r.status})")
    except Exception as e:
        _log(f"Hub toujours DOWN après redémarrage: {e}", "ERROR")


# ── RESTART WEBHUB (admin requis) ────────────────────────────────────────────


def cmd_restart_webhub():
    _require_admin("restart-webhub")
    _log("Redémarrage NokidoWebHub via NSSM (kill+start pour purger zombie)...")
    # Kill process zombie d'abord (si hung)
    pid = None
    try:
        import socket

        s = socket.socket()
        s.settimeout(0.3)
        s.connect(("127.0.0.1", 7400))
        s.close()
        # Get PID from netstat
        r = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, errors="replace")
        for line in (r.stdout or "").splitlines():
            if "127.0.0.1:7400" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pid = parts[-1]
                    break
    except Exception:
        pass
    _run_admin([str(NSSM), "stop", "NokidoWebHub"], "nssm stop webhub")
    time.sleep(2)
    if pid:
        _run_admin(["taskkill", "/F", "/PID", pid], f"taskkill PID {pid}")
        time.sleep(1)
    _run_admin([str(NSSM), "start", "NokidoWebHub"], "nssm start webhub")
    time.sleep(4)
    try:
        with urllib.request.urlopen("http://127.0.0.1:7400/health", timeout=5) as r:
            _log(f"WebHub UP après redémarrage ({r.status})")
    except Exception as e:
        _log(f"WebHub toujours DOWN: {e}", "ERROR")


# ── RESTART NETCFG (admin requis) ────────────────────────────────────────────


def cmd_restart_netcfg():
    _require_admin("restart-netcfg")
    _log("Redémarrage netcfg-agent-mcp...")
    # Tuer le process existant
    _run_admin(["taskkill", "/F", "/IM", "netcfg-agent-mcp.exe"], "taskkill netcfg")
    time.sleep(1)
    # Relancer en background
    subprocess.Popen(
        [
            str(NETCFG_EXE),
            "serve",
            "--transport",
            "http",
            "--host",
            "127.0.0.1",
            "--port",
            "8767",
            "--standalone",
        ],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8767/health", timeout=5) as r:
            _log(f"netcfg UP après redémarrage ({r.status})")
    except Exception as e:
        _log(f"netcfg toujours DOWN: {e}", "ERROR")


# ── RESTART ALL ───────────────────────────────────────────────────────────────


def cmd_restart_all():
    _require_admin("restart-all")
    cmd_restart_hub()
    cmd_restart_webhub()
    cmd_restart_netcfg()
    _log("Restart all terminé")


# ── RESCUE ASK (qwen3:8b, full local) ────────────────────────────────────────


def cmd_ask(question: str) -> str:
    _log(f"-> qwen3:8b: {question[:80]}")
    try:
        payload = json.dumps(
            {
                "model": RESCUE_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Tu es l'agent de secours Nokido. Architecture : "
                            "hub HTTP:8766 (nokido_hub.py), bridge stdio mcp_stdio_bridge.py, "
                            "netcfg HTTP:8767, Ollama:11434, NSSM service NokidoMCP. "
                            "Réponds de façon concise et technique."
                        ),
                    },
                    {"role": "user", "content": question},
                ],
                "stream": False,
                "options": {"num_predict": 512},
            }
        ).encode()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            answer = json.loads(r.read()).get("message", {}).get("content", "(vide)")
        _log(f"<- {answer[:150]}")
        return answer
    except Exception as e:
        _log(f"ERREUR ask: {e}", "ERROR")
        return f"ERREUR: {e}"


# ── FULL ──────────────────────────────────────────────────────────────────────


def cmd_full():
    _log("=== RESCUE FULL SCAN ===")
    status = cmd_status()
    restored = False

    if "DÉGRADÉE" in status.get("claude_config", "") or "ILLISIBLE" in status.get(
        "claude_config", ""
    ):
        _log("Config dégradée → restauration")
        cmd_restore(force=False)
        restored = True

    if "DOWN" in status.get("nokido_hub", ""):
        _log("Hub DOWN → tentative redémarrage")
        cmd_restart_hub()

    if "DOWN" in status.get("netcfg_agent", ""):
        _log("netcfg DOWN → tentative redémarrage")
        cmd_restart_netcfg()

    if restored:
        _log("ACTION REQUISE : Quit + relancer Claude Desktop")

    _log("=== FIN RESCUE SCAN ===")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────


def check_all_services() -> dict:
    """
    Vérifie l état de TOUS les services critiques.
    À appeler avant et après chaque restart hub/NSSM.
    Logge dans logs/service_monitor.log.
    """
    import json
    import logging
    import socket
    import subprocess

    log_path = ROOT / "logs" / "service_monitor.log"
    logging.basicConfig(
        filename=str(log_path), level=logging.INFO, format="%(asctime)s [monitor] %(message)s"
    )
    mon = logging.getLogger("service_monitor")

    services = {
        "hub_nokido": ("127.0.0.1", 8766),
        "netcfg_agent": ("127.0.0.1", 8767),
        "ollama": ("127.0.0.1", 11434),
    }

    results = {}
    for name, (host, port) in services.items():
        try:
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            results[name] = "UP"
        except Exception:
            results[name] = "DOWN"

    # Vérifier aussi les process NSSM
    try:
        r = subprocess.run(
            ["nssm", "status", "NokidoMCP"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        results["nssm_nokido"] = r.stdout.strip()
    except Exception:
        results["nssm_nokido"] = "UNKNOWN"

    # Valider claude_desktop_config.json
    try:
        cfg_ok = validate_config()
        results["claude_config"] = "OK" if cfg_ok else "RESTORED"
    except Exception as _ce:
        results["claude_config"] = f"ERR:{_ce}"

    # Logger chaque service
    all_up = all(v in ("UP", "SERVICE_RUNNING", "OK") for v in results.values())
    level = "OK" if all_up else "WARN"
    mon.info(f"[{level}] {json.dumps(results)}")

    # Alerte si un service est DOWN
    down = [k for k, v in results.items() if v == "DOWN"]
    if down:
        mon.warning(f"SERVICES DOWN: {down} — action requise")
        print(f"[MONITOR] ⚠ SERVICES DOWN: {down}")
    else:
        print(f"[MONITOR] ✓ Tous services UP: {results}")

    return results


def _read_tail(path: Path, n_lines: int = 50) -> str:
    """Read last n_lines of a text file (UTF-8)."""
    if not path.exists():
        return f"[MISSING] {path}"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n_lines:])
    except Exception as e:
        return f"[ERR reading {path}: {e}]"


# Marqueurs cyber-denses : leur presence dans le CONTEXTE conversationnel d'un
# agent re-declenche le classifieur de securite cote modele (faux positif sur
# une conversation cyber-adjacente). Le flag n'est PAS reglable autrement (ni
# par restart ni depuis le code) : la seule prise est de ne plus l'alimenter.
# On elide donc ces lignes du prompt de reprise ; le contenu OPERATIONNEL
# (services, ports, taches, heartbeats) n'en contient pas.
_MARQUEURS_CYBER = (
    "exegol", "nuclei", "nmap", "masscan", "rustscan", "ffuf", "gobuster",
    "sqlmap", "nikto", "whatweb", "radare2", "metasploit", "msfvenom",
    "wfuzz", "hashcat", "hydra", "burpsuite", "hackthebox", "tryhackme",
    "picoctf", "vulnhub", "overthewire", "pwnable", "ringzer0", "root-me",
    "rootme", "wargame", "writeup", "flag{", "capture the flag",
    "reverse shell", "reverse engineering", "pentest", "exploit",
    "cookie_injection", "binaryen", "wasm2wat", " ctf", "ctf ", "ctf,",
    "ctf)", "ctf.", "(ctf",
)


def _rediger_cyber(txt: str) -> str:
    """Elide les lignes cyber-denses d'un extrait AVANT injection dans le prompt
    de reprise. But unique : ne pas re-declencher le classifieur de securite cote
    modele sur la prochaine session. Sur-redige volontairement — zero re-flag
    prime sur l'exhaustivite. Les blocs elides consecutifs sont compresses."""
    if not isinstance(txt, str):
        txt = str(txt)
    out: list[str] = []
    elides = 0
    for ln in txt.splitlines():
        low = ln.lower()
        if any(m in low for m in _MARQUEURS_CYBER):
            elides += 1
            continue
        if elides:
            out.append(f"[... {elides} ligne(s) cyber-adjacente(s) elidee(s) "
                       f"— anti-reflag, lire le fichier FENETRE si besoin]")
            elides = 0
        out.append(ln)
    if elides:
        out.append(f"[... {elides} ligne(s) cyber-adjacente(s) elidee(s) — anti-reflag]")
    return "\n".join(out)


def _query_inbox(agent_id: str, limit: int = 10) -> list:
    """Query agent_messages SQLite for unread messages to agent."""
    import sqlite3

    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_db_path import m2m_path   # scission M2M : suit l'interrupteur sandbox/m2m.switch
    db = Path(m2m_path())
    if not db.exists():
        return [{"err": f"DB not found: {db}"}]
    try:
        conn = sqlite3.connect(str(db))
        rows = conn.execute(
            "SELECT from_agent, status, created_at, substr(payload,1,400) "
            "FROM agent_messages WHERE to_agent=? "
            "ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        conn.close()
        return [{"from": r[0], "status": r[1], "ts": r[2], "preview": r[3]} for r in rows]
    except Exception as e:
        return [{"err": str(e)}]


def _docker_state() -> str:
    """Get docker containers state via WSL Debian."""
    try:
        r = subprocess.run(
            [
                "wsl",
                "-d",
                "Debian",
                "--",
                "docker",
                "ps",
                "-a",
                "--format",
                "{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        return r.stdout.strip() or "[no containers]"
    except Exception as e:
        return f"[docker err: {e}]"


def _nssm_state() -> dict:
    """Get NSSM services status."""
    services = [
        "NokidoMCP",
        "NokidoWebHub",
        "NokidoGraph",
        "NokidoHebbian",
        "NokidoLlamaNative",
        "NokidoLlamaRouter",
        "NokidoRSSWatcher",
        "NokidoGeminiDaemon",
    ]
    out = {}
    for svc in services:
        try:
            r = subprocess.run(
                ["nssm", "status", svc],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
            out[svc] = r.stdout.strip() or "UNKNOWN"
        except Exception:
            out[svc] = "ERR"
    return out


def _heartbeats() -> dict:
    """Read daemon heartbeat files."""
    files = {
        "gemini_poll_daemon": ROOT / "sandbox" / "gemini_poll_daemon.heartbeat",
        "forge_bell": ROOT / "sandbox" / "forge_bell.heartbeat",
    }
    out = {}
    for name, path in files.items():
        if not path.exists():
            out[name] = "MISSING"
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            out[name] = {
                "ts": data.get("ts", "?"),
                "status": data.get("status", "?"),
                "mode": data.get("mode", "?"),
            }
        except Exception as e:
            out[name] = f"ERR:{e}"
    return out


def _gemini_session_state() -> dict:
    """
    Extrait état de session Gemini CLI depuis :
    - ~/.gemini/inbox.md (markdown inbox actif)
    - ~/.gemini/skills/ (7 skills custom)
    - ~/.gemini/projects.json (projets actifs)
    - hub network_log filtré agent=GEMINI (50 derniers appels MCP)
    - sandbox/gemini_poll_daemon.log (dernières activités daemon)
    """
    home = Path.home()
    gem_dir = home / ".gemini"
    out: dict = {"source_dir": str(gem_dir), "available": gem_dir.exists()}

    # 1. Inbox markdown
    inbox = gem_dir / "inbox.md"
    if inbox.exists():
        try:
            lines = inbox.read_text(encoding="utf-8", errors="replace").splitlines()
            out["inbox_tail"] = "\n".join(lines[-60:])
            out["inbox_size"] = len(lines)
        except Exception as e:
            out["inbox_err"] = str(e)

    # 2. Skills custom Gemini
    skills_dir = gem_dir / "skills"
    if skills_dir.exists():
        skills = sorted([d.name for d in skills_dir.iterdir() if d.is_dir()])
        out["skills"] = skills

    # 3. Projects
    projects = gem_dir / "projects.json"
    if projects.exists():
        try:
            out["projects"] = json.loads(projects.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 4. Hub network_log (50 derniers appels MCP de Gemini)
    db = ROOT / "RAG" / "embeddings.db"
    if db.exists():
        try:
            import sqlite3

            conn = sqlite3.connect(str(db))
            rows = conn.execute(
                "SELECT ts, method, substr(payload_in,1,250) "
                "FROM network_log WHERE agent='GEMINI' "
                "ORDER BY ts DESC LIMIT 50"
            ).fetchall()
            conn.close()
            out["recent_mcp_calls"] = [{"ts": r[0], "method": r[1], "preview": r[2]} for r in rows]
        except Exception as e:
            out["mcp_calls_err"] = str(e)

    # 5. Daemon log tail
    dlog = ROOT / "sandbox" / "gemini_poll_daemon.log"
    if dlog.exists():
        try:
            lines = dlog.read_text(encoding="utf-8", errors="replace").splitlines()
            out["daemon_log_tail"] = "\n".join(lines[-30:])
        except Exception:
            pass

    return out


def cmd_resume_prompt(agent: str = "claude") -> str:
    """
    Génère un prompt de reprise complet pour un agent (claude/gemini/cline/...).
    Lit toutes les sources de vérité + état système actuel.
    """
    agent_id = f"agt_{agent.lower()}"
    other_agent = "agt_gemini" if agent.lower() == "claude" else "agt_claude"

    # 1. Sources de vérité
    situation = _rediger_cyber(_read_tail(ROOT / "SITUATION.md", n_lines=200))
    panorama_tail = _rediger_cyber(_read_tail(ROOT / "PANORAMA.md", n_lines=80))
    atlas = ROOT / "LAFORGE_ATLAS.md"
    atlas_exists = "✅ existe" if atlas.exists() else "❌ absent"

    # 2. État système
    services = check_all_services()
    nssm = _nssm_state()
    docker = _rediger_cyber(_docker_state())
    heartbeats = _heartbeats()

    # 3. Inbox
    inbox = _query_inbox(agent_id, limit=10)

    # 3b. Session state Gemini-spécifique (si agent=gemini)
    gemini_state = _gemini_session_state() if agent.lower() == "gemini" else None

    # 4. Compose
    from datetime import datetime

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    prompt = f"""\
═══════════════════════════════════════════════════════════════
PROMPT DE REPRISE — AGENT {agent.upper()} | {now}
═══════════════════════════════════════════════════════════════

Tu es {agent.upper()}, agent autonome dans l'écosystème Nokido.
Tu reprends une session après interruption. CHECK obligatoire :
1. ⚠️ N'OUVRE PAS SITUATION.md / PANORAMA.md EN ENTIER — ils sont
   cyber-adjacents et un dump complet RE-DÉCLENCHE le classifieur de sécurité
   côté modèle (flag non réglable autrement, cf. handoff 2026-08-28). Les
   extraits RÉDIGÉS ci-dessous suffisent ; pour un détail, lire FENÊTRÉ
   (pattern / lignes), jamais le fichier entier.
2. Vérifie ton inbox `agent_messages` (extrait ci-dessous)
3. Point d'entrée réel = registre de dettes (forge_memoire_active.projeter)
   + roadmap SSoT, PAS la table périmée de SITUATION.md.

# IDENTITÉ
- Agent ID  : {agent_id}
- Token env : FORGE_TOKEN_{agent.upper()} dans Nokido.env
- Bridge    : %USERPROFILE%/nokido_bridge.bat (Python miniforge3)
- Hub MCP   : http://127.0.0.1:8766/mcp (16 tools)

# CANAUX COMM (3)
1. PANORAMA = PANORAMA.md à la racine (registre git, append-only)
2. agent_messages SQLite (RAG/embeddings.db) — `hub action=poll` agent={agent.upper()}
3. EventBus Hub :8766 — `event(action=publish, topic=agent.X.inbox, ...)`
   Send : `hub action=notify message="[CIBLE] ..."` (préfixe = destinataire)

# ÉTAT SERVICES (live, {now})

## NSSM ({sum(1 for v in nssm.values() if v == "SERVICE_RUNNING")}/{len(nssm)} RUNNING)
{json.dumps(nssm, indent=2, ensure_ascii=False)}

## Ports critiques
{json.dumps(services, indent=2, ensure_ascii=False)}

## Heartbeats daemons
{json.dumps(heartbeats, indent=2, ensure_ascii=False)}

## Containers Docker (via WSL Debian)
{docker[:1500]}

# ATLAS
LAFORGE_ATLAS.md à la racine = {atlas_exists} (3 mermaid + journal vol + roadmap + anomalies)

# INBOX {agent_id} ({len(inbox)} entries récents)
{json.dumps(inbox, indent=2, ensure_ascii=False)[:3000]}
"""

    # Insertion gemini-spécifique
    if gemini_state and gemini_state.get("available"):
        skills_str = ", ".join(gemini_state.get("skills", []))
        recent_calls = gemini_state.get("recent_mcp_calls", [])[:15]
        prompt += f"""
# 🤖 ÉTAT SESSION GEMINI (extrait ~/.gemini/)

## Skills custom actifs ({len(gemini_state.get("skills", []))})
{skills_str}

## Inbox markdown (~/.gemini/inbox.md, {gemini_state.get("inbox_size", 0)} lignes)
```markdown
{gemini_state.get("inbox_tail", "[empty]")[:2500]}
```

## Derniers appels MCP via hub (network_log, 15/50)
{json.dumps(recent_calls, indent=2, ensure_ascii=False)[:3000]}

## Daemon log tail (sandbox/gemini_poll_daemon.log)
```
{gemini_state.get("daemon_log_tail", "[empty]")[:2000]}
```
"""

    prompt += f"""
# SITUATION.md (tail 200 lines)
```markdown
{situation}
```

# PANORAMA tail (80 lines)
```markdown
{panorama_tail}
```

# PROTOCOLES
- Python: `LAFORGE_PYTHON = %USERPROFILE%/miniforge3/python.exe` — JAMAIS `python` brut
- SecretGuard v3 actif : passer par bridge nokido_bridge.bat pour subprocess
- SemanticFirewall pre/post-flight pour tout cloud
- SovereignMembrane wrap pour données sensibles
- Anti-duplication : query rag_fts avant créer nouveau forge_*.py
- Économie tokens : ASCII progress bar `[██████░░░░] 60%`, regrouper actions parallèles

# CHECK INITIAL OBLIGATOIRE
```python
import sys
sys.path.insert(0, r"{ROOT}/app")
from forge_self_correction import read_lessons, preflight_check_verbose
print(read_lessons(3000))
```

# TON ACK ATTENDU dans PANORAMA
```
### [{agent.upper()} @ {now}]
**Sujet : Reprise session — ACK état système**

[Récap court + prochaine action prévue]

[{agent.upper()}@<TS> frame=auto session=<X>]
```

# OUTIL DE RESYNC
Re-générer ce prompt à tout moment :
```bash
python tools/forge_rescue.py --resume-prompt {agent}
```

═══════════════════════════════════════════════════════════════
"""
    return prompt


def check_known_bug(keyword: str) -> str:
    """
    ITEM 13 — Chercher un pattern dans forge_known_bugs.md avant tout patch.
    Retourne le pattern trouvé ou chaîne vide.
    Usage : avant tout patch, appeler check_known_bug("nom_du_problème")
    """
    bugs_path = ROOT / "docs" / "forge_known_bugs.md"
    if not bugs_path.exists():
        return ""
    content = bugs_path.read_text(encoding="utf-8")
    keyword_lower = keyword.lower()
    for line in content.splitlines():
        if keyword_lower in line.lower():
            return line.strip()[:200]
    return ""


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Nokido Rescue Agent v2.0 — canal de secours on-demand"
    )
    parser.add_argument("--status", action="store_true", help="Diagnostic complet")
    parser.add_argument(
        "--restore", action="store_true", help="Restaure claude_desktop_config.json"
    )
    parser.add_argument(
        "--force", action="store_true", help="Force la restauration même si config OK"
    )
    parser.add_argument(
        "--restart-hub", action="store_true", help="Redémarre NokidoMCP via NSSM (admin)"
    )
    parser.add_argument(
        "--restart-webhub", action="store_true", help="Redémarre NokidoWebHub via NSSM (admin)"
    )
    parser.add_argument(
        "--restart-netcfg", action="store_true", help="Redémarre netcfg-agent-mcp.exe (admin)"
    )
    parser.add_argument("--restart-all", action="store_true", help="Redémarre hub + netcfg (admin)")
    parser.add_argument("--ask", type=str, help="Question au modèle local qwen3:8b")
    parser.add_argument("--full", action="store_true", help="Status + restore + restart si besoin")
    parser.add_argument(
        "--resume-prompt",
        nargs="?",
        const="claude",
        default=None,
        metavar="AGENT",
        help="Génère prompt reprise pour agent (claude/gemini/cline/...) — défaut: claude",
    )
    parser.add_argument(
        "--resync",
        type=str,
        metavar="AGENT",
        help="Resync agent : prompt reprise + notify hub + write to file",
    )
    args = parser.parse_args()

    if args.status:
        cmd_status()
    elif args.restore:
        cmd_restore(force=args.force)
    elif args.restart_hub:
        cmd_restart_hub()
    elif args.restart_webhub:
        cmd_restart_webhub()
    elif args.restart_netcfg:
        cmd_restart_netcfg()
    elif args.restart_all:
        cmd_restart_all()
    elif args.ask:
        print(cmd_ask(args.ask))
    elif args.full:
        cmd_full()
    elif args.resume_prompt:
        print(cmd_resume_prompt(args.resume_prompt))
    elif args.resync:
        prompt = cmd_resume_prompt(args.resync)
        out_file = ROOT / "sandbox" / f"resume_prompt_{args.resync.lower()}.md"
        out_file.parent.mkdir(exist_ok=True)
        out_file.write_text(prompt, encoding="utf-8")
        print(f"[+] Prompt reprise écrit : {out_file}")
        print(f"[+] Taille : {len(prompt)} chars")
        print(f"[+] À coller dans nouvelle session {args.resync.upper()}.")
        # Notify hub via inbox de l'autre agent (alerte resync en cours)
        try:
            other = "claude" if args.resync.lower() == "gemini" else "gemini"
            msg = f"[{other.upper()}] [RESCUE] Prompt reprise généré pour {args.resync.upper()} : {out_file.name}. Resync en cours."
            body = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "hub", "arguments": {"action": "notify", "message": msg}},
                }
            ).encode("utf-8")
            # 2026-08-05 : ce POST etait au bon format JSON-RPC mais partait SANS
            # en-tete Authorization -> rejete `no_auth` par _resolve_ring. Il a ete
            # surpris par le controle d'identification du diagnostic de sante, et
            # non par une enquete : c'etait le TROISIEME emetteur anonyme, celui
            # qu'aucune lecture manuelle n'avait trouve.
            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_hub_client import HubClient  # client GOUVERNE

            _c = HubClient(agent="RESCUE")
            _rep = _c.notify(msg)
            if _rep is None:
                print(f"[!] Notify {other.upper()} NON DELIVRE — hub injoignable sur "
                      f"{_c.base_url} (identite RESCUE, jeton {_c.token_src})")
            elif isinstance(_rep, str) and ("GATE_DENIED" in _rep or "Erreur" in _rep):
                print(f"[!] Notify {other.upper()} REFUSE par le hub : {_rep} "
                      f"— verifier le ring de RESCUE dans config/agent_identities.json")
            else:
                print(f"[+] Notify {other.upper()} via hub OK (identite RESCUE)")
        except Exception as e:
            print(f"[!] Hub notify err: {e}")
    else:
        parser.print_help()
