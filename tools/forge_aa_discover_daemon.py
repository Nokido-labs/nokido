"""
forge_aa_discover_daemon.py - Daemon hebdomadaire ArtificialAnalysis discover
==============================================================================
Tous les 7 jours :
  1. Refresh cache AA (fetch_llms force=True)
  2. discover_new_only(min_quality=40) -> nouveaux candidats absents PROVIDER_AA_MAP
  3. Filtre candidats jamais vus auparavant (state file)
  4. Notify mailbox user via hub si nouveau candidat trouve

Service NSSM (mode loop continu) :
    nssm install NokidoAADiscoverDaemon ^
        __import__("os").path.expanduser("~\\miniforge3\\python.exe") ^
        __import__("os").path.expanduser("~\\Script python IA\\Nokido\\tools\\forge_aa_discover_daemon.py")

OU schtasks Windows hebdomadaire (mode --once) :
    schtasks /create /tn "LaForge-AA-Discover" /sc weekly /d MON /st 06:00 ^
        /tr "\\__import__("os").path.expanduser("~\\miniforge3\\python.exe\\") ^
             \\__import__("os").path.expanduser("~\\Script python IA\\Nokido\\tools\\forge_aa_discover_daemon.py\\") --once"

State persistent : sandbox/aa_discover_seen.json
  {slugs_notified: [...], last_run_utc: "..."}

Notifs evitent re-spam meme candidat sur plusieurs semaines.
"""

from __future__ import annotations

import datetime
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STATE_FILE = ROOT / "sandbox" / "aa_discover_seen.json"
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

CHECK_INTERVAL_SEC = 7 * 24 * 3600  # 1 semaine
HUB_NOTIFY_URL = "http://127.0.0.1:8766/api/notify"
MAILBOX_RECIPIENT = "user"
DEFAULT_MIN_QUALITY = 40.0


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"slugs_notified": [], "last_run_utc": None}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"slugs_notified": [], "last_run_utc": None}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[aa-discover] save_state failed: {e}", flush=True)


def _send_mailbox(message: str) -> bool:
    """POST /api/notify hub. True si succes."""
    try:
        body = json.dumps(
            {
                "to": MAILBOX_RECIPIENT,
                "from": "aa_discover_daemon",
                "message": message,
                "category": "aa_discover",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            HUB_NOTIFY_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        print(f"[aa-discover] HTTPError {e.code}: {e.reason}", flush=True)
        return False
    except Exception as e:
        print(f"[aa-discover] notify failed: {e}", flush=True)
        return False


def _format_alert(candidates: list[dict], min_quality: float) -> str:
    """Format un seul message mailbox avec tous les nouveaux candidats."""
    lines = [
        f"🔍 AA Discover : {len(candidates)} nouveaux providers free tier (qual>={int(min_quality)})",
        "",
        f"{'Slug':<30}{'Creator':<16}{'Released':<12}{'Qual':<5}{'Code':<5}{'Math':<5}{'tok/s'}",
        "-" * 80,
    ]
    for c in candidates:
        code = c.get("coding_index")
        code_s = f"{code:.0f}" if code is not None else "-"
        math = c.get("math_index")
        math_s = f"{math:.0f}" if math is not None else "-"
        lines.append(
            f"{c['slug'][:28]:<30}{c['creator'][:14]:<16}"
            f"{c.get('release_date', '?')[:10]:<12}"
            f"{c['quality']:<5.0f}{code_s:<5}{math_s:<5}"
            f"{c.get('tokens_per_second', 0):.0f}"
        )
    lines.append("")
    lines.append("Pour integrer un candidat :")
    lines.append("1. Ajouter slug dans PROVIDER_AA_MAP (forge_artificialanalysis.py)")
    lines.append("2. Creer Provider class dans forge_agent_proxy.py")
    lines.append("3. Ajouter PROVIDER_SPECS entry dans forge_provider_specs.py")
    lines.append("4. Wire dans USE_CASE_CHAINS de forge_llm_router.py si pertinent")
    return "\n".join(lines)


def check_and_alert(min_quality: float = DEFAULT_MIN_QUALITY) -> int:
    """Une iteration : refresh AA + discover new + notify si nouveau.
    Retourne nombre de nouveaux candidats notifies."""
    try:
        from nokido_agent.app.forge_artificialanalysis import discover_new_only, fetch_llms
    except ImportError as e:
        print(f"[aa-discover] imports failed: {e}", flush=True)
        return 0

    # Step 1 : refresh cache (force=True ignore TTL)
    print(f"[aa-discover] {datetime.datetime.now().isoformat()} refresh AA cache...", flush=True)
    data = fetch_llms(force=True)
    if data.get("error"):
        print(f"[aa-discover] fetch failed: {data['error']}", flush=True)
        return 0
    n_models = len(data.get("models", []))
    print(f"[aa-discover] cached {n_models} models", flush=True)

    # Step 2 : discover new
    candidates = discover_new_only(min_quality=min_quality)
    if not candidates:
        print(f"[aa-discover] no new candidates >= {min_quality}", flush=True)
        return 0

    # Step 3 : filter only really new (jamais notifies avant)
    state = _load_state()
    already_seen = set(state.get("slugs_notified", []))
    truly_new = [c for c in candidates if c.get("slug") not in already_seen]
    if not truly_new:
        print(f"[aa-discover] {len(candidates)} candidates, tous deja notifies", flush=True)
        # Update last_run_utc quand meme
        state["last_run_utc"] = datetime.datetime.now(datetime.UTC).isoformat()
        _save_state(state)
        return 0

    # Step 4 : notify
    print(
        f"[aa-discover] {len(truly_new)} nouveaux candidats jamais notifies, envoi mailbox",
        flush=True,
    )
    msg = _format_alert(truly_new, min_quality)
    if _send_mailbox(msg):
        # Marque comme notifies
        state["slugs_notified"] = sorted(already_seen | {c["slug"] for c in truly_new})
        state["last_run_utc"] = datetime.datetime.now(datetime.UTC).isoformat()
        _save_state(state)
        print(f"[aa-discover] SENT mailbox user ({len(truly_new)} candidats)", flush=True)
        return len(truly_new)
    else:
        print("[aa-discover] FAIL send mailbox, garde candidats non-marques", flush=True)
        return 0


def main() -> None:
    print(
        f"[aa-discover] daemon start, interval={CHECK_INTERVAL_SEC}s ({CHECK_INTERVAL_SEC / 86400:.0f} jours)",
        flush=True,
    )
    while True:
        try:
            n = check_and_alert(min_quality=DEFAULT_MIN_QUALITY)
            print(
                f"[aa-discover] cycle done, {n} new notified, sleeping {CHECK_INTERVAL_SEC}s",
                flush=True,
            )
        except KeyboardInterrupt:
            print("[aa-discover] interrupt, exit", flush=True)
            break
        except Exception as e:
            print(f"[aa-discover] cycle error: {e}", flush=True)
        time.sleep(CHECK_INTERVAL_SEC)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--once" in args:
        # Mode scheduled task / cron : 1 run + exit
        n = check_and_alert(min_quality=DEFAULT_MIN_QUALITY)
        sys.exit(0)
    elif "--reset-state" in args:
        # Reset le file state pour re-notifier tous les candidats au prochain run
        if STATE_FILE.exists():
            STATE_FILE.unlink()
            print(f"[aa-discover] state reset ({STATE_FILE})")
        else:
            print("[aa-discover] no state file to reset")
    elif "--show-state" in args:
        state = _load_state()
        print(json.dumps(state, indent=2))
    elif "--help" in args or "-h" in args:
        print("Usage: forge_aa_discover_daemon.py")
        print("  (default)        loop daemon mode (sleep 7j entre cycles)")
        print("  --once           1 run + exit (pour cron/schtasks)")
        print("  --reset-state    reset state file (re-notify tous candidats)")
        print("  --show-state     affiche state file")
    else:
        main()
