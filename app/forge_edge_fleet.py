"""forge_edge_fleet.py — Edge Inference Fleet POC.

Source roadmap_edge_inference_fleet : web-llm + transformers.js + Ollama sur
parc Linux/Android/Xbox. Fleet horizontal (pas sharding), coordinator
route REQUESTS pas WEIGHTS.

Phase 1+2 dans ce POC : Discovery LAN + Heartbeat + Registry.

API :
- register_edge(name, url, capabilities) -> id
- list_edges() -> list of {name, url, status, last_seen, capabilities}
- pick_best_edge(use_case) -> dict (load balance + RAM + model match)
- heartbeat_loop() : daemon registering self periodically
- dispatch_request(prompt, use_case='general') -> response

Discovery : registry SQLite local + heartbeat HTTP. Pas de mDNS pour POC.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `recoit_le_world_vector` — LISTE BLANCHE du broadcast : un noeud ne recoit l'etat-monde que s'il DECLARE la capacite.
- `sert_le_chat` — LISTE BLANCHE : un noeud ne recoit une requete LLM que s'il est PROUVE capable de la servir.
- `sonder_noeuds_http` — Heartbeat TIRE : un noeud edge (`forge_edge_node`) est passif, il ne pousse rien.
"""

from __future__ import annotations
import argparse, json, logging, sqlite3, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("edge_fleet")

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "sandbox" / "edge_fleet.db"

HEARTBEAT_STALE_S = 300  # 5 min


# New MDM columns to add via ALTER TABLE (SQLite has no IF NOT EXISTS for ALTER)
_MDM_COLUMNS = [
    ("battery", "INTEGER"),
    ("temperature", "REAL"),
    ("disk_used_gb", "REAL"),
    ("disk_total_gb", "REAL"),
    ("os_version", "TEXT"),
    ("ai_model", "TEXT"),
    ("device_type", "TEXT DEFAULT 'unknown'"),
    ("uptime_s", "INTEGER"),
    ("mem_used_mb", "INTEGER"),
    ("mem_total_mb", "INTEGER"),
]


def _ensure_db():
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(str(DB), timeout=5)
    con.execute("""
    CREATE TABLE IF NOT EXISTS edges (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        capabilities TEXT,
        last_seen TEXT NOT NULL,
        ram_free_mb INTEGER,
        cpu_pct REAL,
        models_loaded TEXT,
        registered_at TEXT
    )
    """)
    # Migrate: add MDM columns if missing
    for col_name, col_type in _MDM_COLUMNS:
        try:
            con.execute(f"ALTER TABLE edges ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists
    con.commit()
    con.close()


def register_edge(name: str, url: str, capabilities: dict | None = None, metrics: dict | None = None) -> str:
    """Register or update edge in registry."""
    _ensure_db()
    import hashlib

    eid = hashlib.md5(f"{name}:{url}".encode()).hexdigest()[:12]
    now = datetime.now(timezone.utc).isoformat()
    caps_json = json.dumps(capabilities or {})
    metrics = metrics or {}
    con = sqlite3.connect(str(DB), timeout=5)
    con.execute(
        """
    INSERT INTO edges (
        id, name, url, capabilities, last_seen, ram_free_mb, cpu_pct,
        models_loaded, registered_at, battery, temperature, disk_used_gb,
        disk_total_gb, os_version, ai_model, device_type, uptime_s,
        mem_used_mb, mem_total_mb
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(id) DO UPDATE SET
        last_seen=excluded.last_seen,
        ram_free_mb=excluded.ram_free_mb,
        cpu_pct=excluded.cpu_pct,
        models_loaded=excluded.models_loaded,
        battery=excluded.battery,
        temperature=excluded.temperature,
        disk_used_gb=excluded.disk_used_gb,
        disk_total_gb=excluded.disk_total_gb,
        os_version=excluded.os_version,
        ai_model=excluded.ai_model,
        device_type=excluded.device_type,
        uptime_s=excluded.uptime_s,
        mem_used_mb=excluded.mem_used_mb,
        mem_total_mb=excluded.mem_total_mb
    """,
        (
            eid,
            name,
            url,
            caps_json,
            now,
            metrics.get("ram_free_mb"),
            metrics.get("cpu_pct"),
            json.dumps(metrics.get("models_loaded", [])),
            now,
            metrics.get("battery"),
            metrics.get("temperature"),
            metrics.get("disk_used_gb"),
            metrics.get("disk_total_gb"),
            metrics.get("os_version"),
            metrics.get("ai_model"),
            metrics.get("device_type", "unknown"),
            metrics.get("uptime_s"),
            metrics.get("mem_used_mb"),
            metrics.get("mem_total_mb"),
        ),
    )
    con.commit()
    con.close()
    return eid


def list_edges() -> list[dict]:
    _ensure_db()
    con = sqlite3.connect(str(DB), timeout=5)
    rows = con.execute(
        """SELECT id, name, url, capabilities, last_seen, ram_free_mb, cpu_pct,
                  models_loaded, battery, temperature, disk_used_gb, disk_total_gb,
                  os_version, ai_model, device_type, uptime_s, mem_used_mb, mem_total_mb
           FROM edges"""
    ).fetchall()
    con.close()
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        last_seen_dt = datetime.fromisoformat(r[4])
        age_s = (now - last_seen_dt).total_seconds()
        status = "online" if age_s < HEARTBEAT_STALE_S else "stale"
        try:
            caps = json.loads(r[3] or "{}")
        except Exception:
            caps = {}
        try:
            models = json.loads(r[7] or "[]")
        except Exception:
            models = []
        mem_used = r[16]
        mem_total = r[17]
        mem_pct = round(mem_used / mem_total * 100, 1) if mem_used and mem_total else None
        out.append(
            {
                "id": r[0],
                "name": r[1],
                "url": r[2],
                "status": status,
                "age_s": round(age_s, 1),
                "ram_free_mb": r[5],
                "cpu_pct": r[6],
                "models_loaded": models,
                "capabilities": caps,
                "battery": r[8],
                "temperature": r[9],
                "disk_used_gb": r[10],
                "disk_total_gb": r[11],
                "os_version": r[12],
                "ai_model": r[13],
                "device_type": r[14],
                "uptime_s": r[15],
                "mem_used_mb": mem_used,
                "mem_total_mb": mem_total,
                "mem_pct": mem_pct,
            }
        )
    return out


# Runtimes qui servent /v1/chat/completions (OpenAI-compat) sur l'URL http du noeud.
_RUNTIMES_CHAT = frozenset({"ollama", "llamacpp", "llama.cpp", "vllm", "openai"})


def sert_le_chat(edge: dict) -> bool:
    """LISTE BLANCHE : un noeud ne recoit une requete LLM que s'il est PROUVE capable de la servir --
    en ligne, URL http(s), et runtime d'inference declare OU capacite `chat` explicite.

    Avant (27/09), `pick_best_edge` et `forge_contract_net` prenaient tout noeud (le premier meme
    STALE via contract_net) : le recepteur world-vector de la VM DNS, ou un Android joint par adb,
    aurait gagne l'election et recu des requetes LLM qu'il ne sait pas servir."""
    if edge.get("status") != "online":
        return False
    if not str(edge.get("url") or "").startswith(("http://", "https://")):
        return False
    caps = edge.get("capabilities") or {}
    if not isinstance(caps, dict):
        return False
    return caps.get("chat") is True or caps.get("runtime") in _RUNTIMES_CHAT


def recoit_le_world_vector(edge: dict) -> bool:
    """LISTE BLANCHE du broadcast : un noeud ne recoit l'etat-monde que s'il DECLARE la capacite
    `world_vector` (forge_edge_node s'inscrit avec) et une URL http(s).

    Avant (28/09), `broadcast_world_vector` POSTait a tout noeud inscrit : l'hote ollama
    (`heartbeat_self`, runtime ollama) rendait 404 a chaque diffusion, un Android adb n'a pas
    d'URL http. Le statut n'est PAS filtre : un noeud passif tombe STALE 5 min apres son
    inscription sans etre mort (STALE != DEAD) -- l'ecarter couperait la VM reelle."""
    if not str(edge.get("url") or "").startswith(("http://", "https://")):
        return False
    caps = edge.get("capabilities") or {}
    return isinstance(caps, dict) and caps.get("world_vector") is True


def sonder_noeuds_http(timeout: float = 3.0) -> dict:
    """Heartbeat TIRE : un noeud edge (`forge_edge_node`) est passif, il ne pousse rien. On lit son
    /health ; une reponse `ok` rafraichit last_seen et ses metriques (capacites inchangees). Un
    noeud muet n'est PAS declare mort : il vieillit jusqu'a STALE, et le rapport dit pourquoi."""
    out = {}
    for e in list_edges():
        url = str(e.get("url") or "")
        if not url.startswith(("http://", "https://")) or e.get("device_type") != "edge-node":
            continue
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=timeout) as r:
                h = json.loads(r.read())
        except Exception as ex:  # noqa: BLE001
            out[e["name"]] = {"rafraichi": False, "motif": f"{type(ex).__name__}: {str(ex)[:80]}"}
            continue
        if not (isinstance(h, dict) and h.get("ok") is True):
            out[e["name"]] = {"rafraichi": False, "motif": "health sans ok=true"}
            continue
        total, used = h.get("mem_total_mb"), h.get("mem_used_mb")
        register_edge(e["name"], url, capabilities=e.get("capabilities") or {}, metrics={
            "ram_free_mb": (total - used) if total and used is not None else None,
            "mem_used_mb": used, "mem_total_mb": total, "uptime_s": h.get("uptime_s"),
            "os_version": h.get("os_version"), "device_type": h.get("device_type", "edge-node")})
        out[e["name"]] = {"rafraichi": True}
    return out


def pick_best_edge(use_case: str = "general", min_ram_mb: int = 2000) -> dict | None:
    """Select online edge with most RAM free + lowest CPU -- parmi ceux qui SERVENT le chat."""
    edges = [e for e in list_edges() if sert_le_chat(e)]
    if not edges:
        return None
    # Filter min RAM
    eligible = [e for e in edges if (e.get("ram_free_mb") or 0) >= min_ram_mb]
    if not eligible:
        eligible = edges
    # Sort by RAM free desc, CPU asc
    eligible.sort(key=lambda e: ((e.get("ram_free_mb") or 0), -(e.get("cpu_pct") or 100)), reverse=True)
    return eligible[0]


def heartbeat_self(self_name: str = "laforge-host", self_url: str = "http://127.0.0.1:11434"):
    """Register self as edge (Ollama probable host). Collects real system metrics."""
    ram_free_mb = None
    cpu_pct = None
    battery = None
    temperature = None
    disk_used_gb = None
    disk_total_gb = None
    mem_used_mb = None
    mem_total_mb = None
    uptime_s = None
    os_version = None

    try:
        import psutil

        ram = psutil.virtual_memory()
        ram_free_mb = int(ram.available / 1024 / 1024)
        mem_used_mb = int(ram.used / 1024 / 1024)
        mem_total_mb = int(ram.total / 1024 / 1024)
        cpu_pct = psutil.cpu_percent(interval=0.1)

        # Battery (laptops / tablets, None on desktops)
        bat = psutil.sensors_battery()
        if bat is not None:
            battery = int(bat.percent)

        # Temperature (may not be available on all platforms)
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Take the first available sensor's current value
                for _name, entries in temps.items():
                    if entries:
                        temperature = round(entries[0].current, 1)
                        break
        except (AttributeError, NotImplementedError):
            pass  # sensors_temperatures not available on this OS

        # Disk
        disk = psutil.disk_usage("/" if __import__("os").name != "nt" else "C:\\")
        disk_used_gb = round(disk.used / 1024 / 1024 / 1024, 2)
        disk_total_gb = round(disk.total / 1024 / 1024 / 1024, 2)

        # Uptime
        uptime_s = int(time.time() - psutil.boot_time())
    except Exception:
        pass

    # OS version
    try:
        import platform as _platform
        os_version = f"{_platform.system()} {_platform.release()}"
    except Exception:
        pass

    # Probe Ollama for loaded models
    models = []
    try:
        with urllib.request.urlopen(f"{self_url}/api/tags", timeout=3) as r:
            data = json.loads(r.read())
            models = [m.get("name") for m in data.get("models", [])]
    except Exception:
        pass

    eid = register_edge(
        self_name,
        self_url,
        capabilities={"runtime": "ollama", "platform": "self"},
        metrics={
            "ram_free_mb": ram_free_mb,
            "cpu_pct": cpu_pct,
            "models_loaded": models,
            "battery": battery,
            "temperature": temperature,
            "disk_used_gb": disk_used_gb,
            "disk_total_gb": disk_total_gb,
            "mem_used_mb": mem_used_mb,
            "mem_total_mb": mem_total_mb,
            "uptime_s": uptime_s,
            "os_version": os_version,
            "device_type": "host",
        },
    )
    return eid


def heartbeat_from_http(data: dict) -> str:
    """Receive a heartbeat from an external edge device via HTTP POST.

    Expected data keys: name, url, and optional metrics (battery, temperature,
    disk_used_gb, disk_total_gb, cpu_pct, ram_free_mb, mem_used_mb, mem_total_mb,
    models_loaded, os_version, ai_model, device_type, uptime_s).

    Returns the edge id.
    """
    name = data.get("name")
    url = data.get("url")
    if not name or not url:
        raise ValueError("heartbeat_from_http requires 'name' and 'url'")

    metrics_keys = [
        "battery", "temperature", "disk_used_gb", "disk_total_gb",
        "cpu_pct", "ram_free_mb", "mem_used_mb", "mem_total_mb",
        "models_loaded", "os_version", "ai_model", "device_type", "uptime_s",
    ]
    metrics = {k: data[k] for k in metrics_keys if k in data}
    capabilities = data.get("capabilities")
    if isinstance(capabilities, str):
        try:
            capabilities = json.loads(capabilities)
        except Exception:
            capabilities = {}
    return register_edge(name, url, capabilities=capabilities, metrics=metrics)


def fleet_stats() -> dict:
    """Aggregate fleet statistics from all registered edges.

    Returns dict with: total, online, offline, avg_battery, avg_cpu, avg_mem_pct.
    """
    edges = list_edges()
    total = len(edges)
    online = sum(1 for e in edges if e["status"] == "online")
    offline = total - online

    batteries = [e["battery"] for e in edges if e.get("battery") is not None]
    cpus = [e["cpu_pct"] for e in edges if e.get("cpu_pct") is not None]
    mem_pcts = [e["mem_pct"] for e in edges if e.get("mem_pct") is not None]

    return {
        "total": total,
        "online": online,
        "offline": offline,
        "avg_battery": round(sum(batteries) / len(batteries), 1) if batteries else None,
        "avg_cpu": round(sum(cpus) / len(cpus), 1) if cpus else None,
        "avg_mem_pct": round(sum(mem_pcts) / len(mem_pcts), 1) if mem_pcts else None,
    }


# ── ADB integration : real Android devices → fleet (Phase 1, lecture seule) ──
_ADB_READONLY = {
    "getprop", "dumpsys", "wm", "df", "uptime", "top", "cat",
    "settings", "ls", "ps", "whoami", "id", "free", "printenv",
}


def _adb():
    """Lazy-import forge_adb (tools/). Returns module or None."""
    import sys as _sys
    from pathlib import Path as _P
    tools = str(_P(__file__).resolve().parent.parent / "tools")
    if tools not in _sys.path:
        _sys.path.insert(0, tools)
    try:
        from nokido_agent.tools import forge_adb
        return forge_adb
    except Exception:
        return None


def scan_adb_into_fleet() -> list[dict]:
    """Enumerate connected ADB devices, register each as a REAL edge.

    Reads real props (model, Android version, battery, temperature) via adb.
    Returns [{serial, model, battery}] for devices found. No demo/seed.
    """
    adb = _adb()
    if adb is None:
        return []
    rc, out, err = adb._run(["devices"])
    if rc != 0:
        return []
    found = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("List of"):
            continue
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue
        serial = parts[0]

        def _prop(key):
            r, o, e = adb._run(["-s", serial, "shell", "getprop", key])
            return o.strip() if r == 0 and o.strip() else None

        model = _prop("ro.product.model") or serial
        osv = _prop("ro.build.version.release")
        battery = temperature = None
        rb, ob, eb = adb._run(["-s", serial, "shell", "dumpsys", "battery"])
        if rb == 0:
            for bl in ob.splitlines():
                bl = bl.strip()
                if bl.startswith("level:"):
                    try:
                        battery = int(bl.split(":", 1)[1])
                    except Exception:
                        pass
                elif bl.startswith("temperature:"):
                    try:
                        temperature = round(int(bl.split(":", 1)[1]) / 10.0, 1)
                    except Exception:
                        pass
        register_edge(
            model,
            f"adb://{serial}",
            capabilities={"runtime": "android", "adb_serial": serial},
            metrics={
                "battery": battery,
                "temperature": temperature,
                "os_version": f"Android {osv}" if osv else None,
                "device_type": "android",
            },
        )
        found.append({"serial": serial, "model": model, "battery": battery})
    return found


def adb_readonly(cmd: str) -> dict:
    """Run an ALLOWLISTED read-only adb shell command on the active device.

    Only diagnostic verbs (_ADB_READONLY) are permitted; shell metacharacters
    are rejected. No arbitrary exec — write/control ops are Phase 2 (governed).
    """
    cmd = (cmd or "").strip()
    if not cmd:
        return {"ok": False, "error": "cmd required"}
    if any(c in cmd for c in ";|&><`$\n"):
        return {"ok": False, "error": "caractere non autorise"}
    first = cmd.split()[0]
    if first not in _ADB_READONLY:
        allowed = ", ".join(sorted(_ADB_READONLY))
        return {"ok": False, "error": f"'{first}' non autorise (lecture seule: {allowed})"}
    adb = _adb()
    if adb is None:
        return {"ok": False, "error": "forge_adb indisponible"}
    dev = adb.device()
    if not dev:
        return {"ok": False, "error": "Aucun device ADB connecte"}
    rc, out, err = adb._run(["-s", dev, "shell", *cmd.split()])
    return {"ok": rc == 0, "output": out, "error": err, "device": dev}


# Control-tier verbs (non-destructif : lancement app, input, toggles domotique).
_ADB_CONTROL = {
    "input", "am", "monkey", "screencap", "svc", "cmd", "media",
    "ime", "pm", "wm", "settings", "content", "dpm", "service",
}
# Destructifs : exigent confirm=True explicite (Phase 2 = confirmer l'irreversible).
_ADB_DESTRUCTIVE_FIRST = {"reboot", "wipe", "format", "shutdown"}
_ADB_DESTRUCTIVE_PAIRS = {
    ("pm", "uninstall"), ("pm", "clear"), ("pm", "disable"),
    ("am", "force-stop"), ("svc", "power"), ("settings", "delete"),
    ("content", "delete"),
}


def adb_control(cmd: str, confirm: bool = False) -> dict:
    """Governed ADB control on the active device (Phase 2).

    Tiers: lecture seule + control non-destructif = autorises ; verbes
    destructifs (reboot, pm uninstall, am force-stop, ...) exigent confirm=True.
    Metacaracteres shell rejetes. Reutilise forge_adb (organe toucher).
    """
    cmd = (cmd or "").strip()
    if not cmd:
        return {"ok": False, "error": "cmd required"}
    if any(c in cmd for c in ";|&><`$\n"):
        return {"ok": False, "error": "caractere non autorise"}
    toks = cmd.split()
    first = toks[0]
    pair = (toks[0], toks[1]) if len(toks) > 1 else None
    destructive = first in _ADB_DESTRUCTIVE_FIRST or (pair in _ADB_DESTRUCTIVE_PAIRS)
    if destructive and not confirm:
        return {
            "ok": False,
            "needs_confirm": True,
            "warning": f"Commande potentiellement destructive: '{cmd}'. Confirmer pour executer.",
        }
    if not (first in _ADB_READONLY or first in _ADB_CONTROL):
        return {"ok": False, "error": f"'{first}' non autorise"}
    adb = _adb()
    if adb is None:
        return {"ok": False, "error": "forge_adb indisponible"}
    dev = adb.device()
    if not dev:
        return {"ok": False, "error": "Aucun device ADB connecte"}
    rc, out, err = adb._run(["-s", dev, "shell", *toks])
    return {"ok": rc == 0, "output": out, "error": err, "device": dev, "destructive": destructive}


# ── OTA : distribuer un fichier (GGUF/config) vers un edge (Phase 3) ──────────
def _ota_source_dir() -> str:
    import os as _os
    d = _os.environ.get("LAFORGE_EDGE_OTA_DIR", str(ROOT / "sandbox" / "edge_ota"))
    _os.makedirs(d, exist_ok=True)
    return d


def list_ota_files() -> list[dict]:
    """Fichiers distribuables depuis le staging OTA (LAFORGE_EDGE_OTA_DIR)."""
    import os as _os
    d = _ota_source_dir()
    out = []
    for fn in sorted(_os.listdir(d)):
        fp = _os.path.join(d, fn)
        if _os.path.isfile(fp):
            out.append({"name": fn, "bytes": _os.path.getsize(fp)})
    return out


def _sha256_file(path: str) -> str:
    from nokido_agent.app.forge_utils import sha256_fichier  # corps partage (cliquet clones, 26/09)

    return sha256_fichier(path)


def push_to_edge(edge_id: str, filename: str, remote_path: str | None = None) -> dict:
    """Distribue un fichier du staging OTA vers un edge (Phase 3, checksum verifie).

    edge_id  : id ou nom de l'edge (list_edges).
    filename : basename d'un fichier dans le staging OTA (LAFORGE_EDGE_OTA_DIR).
    Android (url adb://serial) -> adb push + sha256sum distant compare.
    HTTP node (url http://)     -> POST <url>/ota (X-OTA-Path / X-OTA-SHA256).
    """
    import os as _os
    fn = _os.path.basename(filename or "")
    if not fn:
        return {"ok": False, "error": "filename requis"}
    local = _os.path.join(_ota_source_dir(), fn)
    if not _os.path.isfile(local):
        return {"ok": False, "error": f"fichier absent du staging OTA: {fn}"}
    sha = _sha256_file(local)
    size = _os.path.getsize(local)

    edge = None
    for e in list_edges():
        if e.get("id") == edge_id or e.get("name") == edge_id:
            edge = e
            break
    if edge is None:
        return {"ok": False, "error": f"edge inconnu: {edge_id}"}
    url = edge.get("url") or ""

    if url.startswith("adb://"):
        serial = url[len("adb://"):]
        remote = remote_path or f"/sdcard/nokido_ota/{fn}"
        adb = _adb()
        if adb is None:
            return {"ok": False, "error": "forge_adb indisponible"}
        adb._run(["-s", serial, "shell", "mkdir", "-p", _os.path.dirname(remote)])
        rc, out, err = adb._run(["-s", serial, "push", local, remote])
        if rc != 0:
            return {"ok": False, "error": f"adb push echec: {(err or out)[:200]}"}
        rc2, out2, _e2 = adb._run(["-s", serial, "shell", "sha256sum", remote])
        remote_sha = (out2.split() or [""])[0].lower() if rc2 == 0 else None
        return {"ok": True, "method": "adb", "edge": edge.get("name"), "device": serial,
                "remote": remote, "bytes": size, "sha256": sha,
                "remote_sha256": remote_sha,
                "verified": (remote_sha == sha) if remote_sha else None}

    if url.startswith("http://") or url.startswith("https://"):
        import urllib.request as _u
        import json as _json
        with open(local, "rb") as f:
            data = f.read()
        req = _u.Request(url.rstrip("/") + "/ota", data=data, method="POST",
                         headers={"X-OTA-Path": fn, "X-OTA-SHA256": sha,
                                  "Content-Type": "application/octet-stream"})
        try:
            with _u.urlopen(req, timeout=30) as r:
                resp = _json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            return {"ok": False, "error": f"POST /ota echec: {e}"}
        verified = (resp.get("sha256") == sha)
        return {"ok": bool(resp.get("ok")) and verified, "method": "http",
                "edge": edge.get("name"), "bytes": size, "sha256": sha,
                "remote": resp.get("path"), "verified": verified}

    return {"ok": False, "error": f"transport non supporte pour url: {url}"}


def dispatch_request(prompt: str, use_case: str = "general", max_tokens: int = 600) -> dict:
    """Pick best edge + forward request OpenAI-compat /v1/chat/completions.

    Fallback : if no edge available, falls back to forge_frugal_cascade.
    """
    edge = pick_best_edge(use_case)
    if not edge:
        # Fallback cloud cascade
        try:
            import sys

            sys.path.insert(0, str(ROOT))
            from nokido_agent.app.forge_frugal_cascade import cascade

            return cascade(prompt, use_case=use_case, max_tokens=max_tokens)
        except Exception as e:
            return {"error": f"no edge available + fallback fail: {e}"}

    # Forward to picked edge
    body = json.dumps(
        {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
    ).encode()
    req = urllib.request.Request(
        f"{edge['url']}/v1/chat/completions", data=body, headers={"Content-Type": "application/json"}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        choices = data.get("choices", [])
        if not choices:
            return {"error": "no choices in response", "edge": edge["name"]}
        return {
            "response": choices[0].get("message", {}).get("content", ""),
            "edge": edge["name"],
            "latency_ms": round((time.time() - t0) * 1000, 1),
        }
    except Exception as e:
        return {"error": str(e), "edge": edge["name"]}


# ── World-vector sync : soudure 4096D <-> flotte edge (codec compresse) ─────────
# Maillon manquant identifie par le debat 4096D (blackboard decision_4096d_debate_verdict) :
# transmettre l'etat-monde entre noeuds en COMPRESSE (int8 ~4x, cos>0.99), PAS 4096D brut.
def _wv_codec():
    import sys
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app import forge_world_vector_codec as c
    return c


def encode_world_vector(vec, ref=None) -> bytes:
    """Compresse un world-vector (float32) pour le wire edge (int8 + scale)."""
    c = _wv_codec()
    return c.pack(c.quantize(vec, ref=ref))


def decode_world_vector(blob: bytes, ref=None):
    """Reconstruit un world-vector recu (bytes -> float32)."""
    c = _wv_codec()
    return c.dequantize(c.unpack(blob), ref=ref)


def broadcast_world_vector(vec, ref=None, timeout: int = 10) -> dict:
    """Diffuse l'etat-monde LOCAL aux noeuds edge, COMPRESSE (POST <url>/world_vector).
    ref!=None -> transmet le delta. Borne, tient dans une trame jumbo MTU 9000.
    Liste blanche `recoit_le_world_vector` ; les noeuds ecartes sont DITS (cle `ecartes`)."""
    blob = encode_world_vector(vec, ref=ref)
    out = {"bytes_sent_each": len(blob), "delta": ref is not None, "edges": {}, "ecartes": {}}
    for e in list_edges():
        url = e.get("url")
        nm = e.get("name", url)
        if not recoit_le_world_vector(e):
            out["ecartes"][nm] = "sans capacite world_vector ou URL non http"
            continue
        try:
            req = urllib.request.Request(
                f"{url}/world_vector", data=blob,
                headers={"Content-Type": "application/octet-stream"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out["edges"][nm] = {"status": getattr(r, "status", 200)}
        except Exception as ex:  # noqa: BLE001
            out["edges"][nm] = {"error": str(ex)[:80]}  # endpoint edge a venir (POC)
    return out


def world_vector_transport_stats(dim: int = 4096) -> dict:
    """Gain de transmission codec vs 4096D brut (raw float32 vs int8) — decision edge."""
    return _wv_codec().transmit_stats(dim)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    rg = sub.add_parser("register")
    rg.add_argument("--name", required=True)
    rg.add_argument("--url", required=True)
    sub.add_parser("self-heartbeat")
    sub.add_parser("sonder")
    pk = sub.add_parser("pick")
    pk.add_argument("--use-case", default="general")
    dp = sub.add_parser("dispatch")
    dp.add_argument("--prompt", required=True)
    args = ap.parse_args()

    if args.cmd == "list":
        print(json.dumps(list_edges(), indent=2))
    elif args.cmd == "register":
        eid = register_edge(args.name, args.url)
        print(f"registered: {eid}")
    elif args.cmd == "self-heartbeat":
        eid = heartbeat_self()
        print(f"self registered: {eid}")
    elif args.cmd == "sonder":
        print(json.dumps(sonder_noeuds_http(), indent=2, ensure_ascii=False))
    elif args.cmd == "pick":
        print(json.dumps(pick_best_edge(args.use_case), indent=2))
    elif args.cmd == "dispatch":
        print(json.dumps(dispatch_request(args.prompt), indent=2))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
