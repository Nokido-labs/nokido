"""
tools/forge_tui.py — Nokido terminal dashboard (stdlib only, no curses/rich/textual).
Polls every 3s: services, heartbeats, RAG status, git info.
"""

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path

try:
    import requests as _req
except ImportError:
    _req = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = lambda x, **kw: x

LAFORGE_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = LAFORGE_ROOT / "RAG" / "embeddings.db"
HEARTBEAT_DIR = LAFORGE_ROOT / "sandbox"

SERVICES = {
    "hub    :8766": "http://localhost:8766/health",
    "ollama :11434": "http://localhost:11434/api/tags",
    "netcfg :7500": "http://localhost:7500/health",
    "brain  :5557": None,
}

W = 56


def _box(title: str, lines: list) -> str:
    top = f"┌─ {title} " + "─" * max(0, W - len(title) - 4) + "┐"
    bot = "└" + "─" * (W - 1) + "┘"
    body = "\n".join(f"│ {l:<{W - 3}}│" for l in lines)
    return f"{top}\n{body}\n{bot}"


def check_services() -> list:
    out = []
    # Plus de tqdm ici : hors terminal ses barres partent sur stderr et se melent
    # au rapport (mesure 2026-08-29 sur `--once`), pour quatre services.
    for name, url in SERVICES.items():
        if url is None:
            out.append(f"  {name:<20} [ZMQ/skip]")
            continue
        if _req is None:
            out.append(f"  {name:<20} [requests missing]")
            continue
        try:
            r = _req.get(url, timeout=1)
            ok = "+" if r.status_code < 400 else "-"
            out.append(f"{ok} {name:<20} HTTP {r.status_code}")
        except Exception:
            out.append(f"- {name:<20} DOWN")
    return out


def _age_heartbeat(data: dict, fp) -> tuple:
    """(age_en_secondes, source) — ou (None, 'inconnu').

    Mesure 2026-08-29 : le champ s'appelle `ts` (43 fichiers sur 45), pas
    `timestamp`. En lisant l'ancien nom on obtenait 0, donc un age egal a l'epoch
    entier, donc QUARANTE daemons marques en retard alors qu'ils battaient. Un
    capteur qui lit le mauvais champ ne rend pas « rien » : il rend une alarme.

    `ts` existe sous TROIS formes, toutes vues sur disque le meme jour :
    epoch flottant, ISO naif, ISO avec decalage. Le naif est en heure LOCALE — le
    supposer UTC ajouterait deux heures d'age ici (verifie : un ts naif a 17:09
    pour 17:25 local, quand la forme `+00:00` du meme instant dit 15:25)."""
    brut = data.get("ts", data.get("timestamp"))
    if isinstance(brut, (int, float)) and brut > 0:
        return time.time() - float(brut), "ts"
    if isinstance(brut, str) and brut.strip():
        try:
            d = datetime.fromisoformat(brut)
        except ValueError:
            d = None
        if d is not None:
            maintenant = datetime.now() if d.tzinfo is None else datetime.now(d.tzinfo)
            return (maintenant - d).total_seconds(), "ts"
    try:
        return time.time() - fp.stat().st_mtime, "mtime"
    except OSError:
        return None, "inconnu"


def get_heartbeats() -> list:
    out = []
    for fp in sorted(HEARTBEAT_DIR.glob("*.heartbeat")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001 — illisible n'est pas absent, on le dit
            out.append(f" {fp.stem[:28]:<28} [illisible]")
            continue
        if not isinstance(data, dict):
            # Mesure 2026-08-29 : un .heartbeat contient un flottant nu. Un seul
            # fichier hors-format faisait tomber le panneau ENTIER en erreur —
            # quarante-quatre daemons lisibles disparaissaient avec lui.
            out.append(f" {fp.stem[:26]:<26} [format {type(data).__name__}]")
            continue
        age, source = _age_heartbeat(data, fp)
        if age is None:
            out.append(f" {fp.stem[:28]:<28} [age inconnu]")
            continue
        # Un daemon qui bat toutes les 900 s n'est pas en retard a 400 s. Le seuil
        # suit l'intervalle DECLARE quand il existe ; sans lui, on garde 300 s.
        interval = data.get("interval_s")
        seuil = (max(300.0, 3.0 * float(interval))
                 if isinstance(interval, (int, float)) and interval > 0 else 300.0)
        retard = "!" if age > seuil else " "
        etat = str(data.get("health") or "")[:10]
        marque = "" if source == "ts" else "~"     # ~ = age deduit du mtime
        out.append(f"{retard}{fp.stem[:26]:<26} {int(age):>6}s{marque} {etat}")
    return out or ["(aucun fichier heartbeat)"]


def get_rag_status() -> list:
    try:
        conn = sqlite3.connect(str(DB_PATH))
        total = conn.execute("SELECT COUNT(*) FROM rag_chunks").fetchone()[0]
        null_emb = conn.execute(
            "SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL"
        ).fetchone()[0]
        null_id = conn.execute("SELECT COUNT(*) FROM rag_chunks WHERE id IS NULL").fetchone()[0]
        conn.close()
        return [
            f"Total chunks  : {total:>8,}",
            f"Null embedding: {null_emb:>8,}",
            f"Null id       : {null_id:>8,}",
        ]
    except Exception as e:
        return [f"DB error: {str(e)[:45]}"]


def get_git_info() -> list:
    try:
        commit = subprocess.check_output(
            ["git", "-C", str(LAFORGE_ROOT), "log", "-1", "--format=%h %s", "--no-walk"],
            text=True,
            stderr=subprocess.DEVNULL,
        errors="replace").strip()
        branch = subprocess.check_output(
            ["git", "-C", str(LAFORGE_ROOT), "branch", "--show-current"],
            text=True,
            stderr=subprocess.DEVNULL,
        errors="replace").strip()
        return [f"Branch : {branch}", f"Commit : {commit[: W - 12]}"]
    except Exception as e:
        return [f"git error: {e}"]


def render():
    os.system("cls" if os.name == "nt" else "clear")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"+=={'Nokido Dashboard':^{W - 6}}==+")
    print(f"  {now}")
    print(_box("SERVICES", check_services()))
    print(_box("HEARTBEATS", get_heartbeats()))
    print(_box("RAG STATUS", get_rag_status()))
    print(_box("GIT", get_git_info()))
    print("  Ctrl+C to exit")


if __name__ == "__main__":
    try:
        while True:
            render()
            time.sleep(3)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
import asyncio
import time
import urllib.request

from textual.reactive import reactive
from textual.widgets import Static


class ServiceMonitor(Static):
    """Moniteur de statut des services avec mise à jour périodique"""

    def __init__(self, url: str, interval: int = 5):
        super().__init__()
        self.url = url
        self.interval = interval
        self.status = reactive("")
        self.last_update = reactive(time.time())
        self.update_task = None

    async def on_mount(self) -> None:
        await self.update_status()
        self.update_task = asyncio.create_task(self.periodic_update())

    async def periodic_update(self):
        while True:
            await asyncio.sleep(self.interval)
            await self.update_status()

    async def update_status(self):
        try:
            with urllib.request.urlopen(self.url) as response:
                data = json.loads(response.read().decode())
                self.status = (
                    f"Status: {data.get('status', 'unknown')}\n"
                    f"Version: {data.get('version', 'N/A')}\n"
                    f"Uptime: {data.get('uptime', 'N/A')}"
                )
                self.last_update = time.time()
        except Exception as e:
            self.status = f"ERROR: {str(e)}"
            self.last_update = time.time()


class HeartbeatTail(Static):
    """Suivi des fichiers heartbeat avec défilement"""

    def __init__(self):
        super().__init__()
        self.heartbeat_files = reactive([])
        self.content = reactive("")
        self.update_task = None

    async def on_mount(self) -> None:
        await self.scan_heartbeats()
        # TODO : implement periodic re-scan loop. Placeholder no-op pour
        # garder la classe syntaxiquement valide (le fichier etait tronque).
        self.update_task = None
