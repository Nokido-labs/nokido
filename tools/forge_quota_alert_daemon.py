"""
forge_quota_alert_daemon.py - Daemon background quota providers
================================================================
Check toutes les 1h les quotas mensuels des providers Tier 2 (subscription)
et Tier 3 (paid_api). Envoie alertes mailbox a 50%, 80%, 100% du quota
mensuel pour permettre action preventive.

Service NSSM (ou cron equivalent) :
    nssm install NokidoQuotaAlertDaemon ^
        %USERPROFILE%\\miniforge3\\python.exe ^
        __import__("os").path.expanduser("~\\Script python IA\\LaForge\\tools\\forge_quota_alert_daemon.py")

Mailbox : POST /api/notify hub :8766 (recipient=user).

Etat alertes : file plat sandbox/quota_alerted.json (key: provider:threshold:month)
pour eviter spam re-alert tant que reset mensuel pas passe.
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

ALERTED_FILE = ROOT / "sandbox" / "quota_alerted.json"
ALERTED_FILE.parent.mkdir(parents=True, exist_ok=True)

CHECK_INTERVAL_SEC = 3600  # 1h
HUB_NOTIFY_URL = "http://127.0.0.1:8766/api/notify"
MAILBOX_RECIPIENT = "user"


def _load_alerted() -> set:
    if not ALERTED_FILE.exists():
        return set()
    try:
        return set(json.loads(ALERTED_FILE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_alerted(alerted: set) -> None:
    try:
        ALERTED_FILE.write_text(json.dumps(sorted(alerted)), encoding="utf-8")
    except Exception as e:
        print(f"[quota-alert] save_alerted failed: {e}", flush=True)


def _month_key() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m")


def _send_mailbox(message: str) -> bool:
    """POST /api/notify hub. Retourne True si succes."""
    try:
        body = json.dumps(
            {
                "to": MAILBOX_RECIPIENT,
                "from": "quota_alert_daemon",
                "message": message,
                "category": "quota_alert",
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
        print(f"[quota-alert] HTTPError {e.code}: {e.reason}", flush=True)
        return False
    except Exception as e:
        print(f"[quota-alert] notify failed: {e}", flush=True)
        return False


def _format_alert(provider: str, status: dict, threshold: float) -> str:
    pct = int(status.get("pct_max", 0) * 100)
    calls = status.get("calls", 0)
    quota_calls = status.get("quota_monthly_calls", "-")
    tokens = status.get("tokens_total", 0)
    quota_tokens = status.get("quota_monthly_tokens", "-")
    if threshold >= 1.0:
        icon = "🔴"
        verb = "EPUISE"
        action = "Cascade fallback Tier 1 (free) ou Tier 0 (local) actif. Aucun appel ne passera ce provider ce mois."
    elif threshold >= 0.8:
        icon = "⚠️"
        verb = "@ 80%"
        action = (
            "Va sauter prochainement. Verifie tasks routees ; envisage routing manuel vers Tier 1."
        )
    else:
        icon = "ℹ️"
        verb = "@ 50%"
        action = "Mi-mois quota. RAS si fin de mois proche."
    return (
        f"{icon} Provider {provider} {verb} quota mensuel ({pct}%)\n"
        f"  Calls: {calls}/{quota_calls}\n"
        f"  Tokens: {tokens}/{quota_tokens}\n"
        f"  Cost: ${status.get('cost_usd', 0):.4f}\n"
        f"  Action: {action}"
    )


def check_and_alert() -> None:
    """Une iteration : check tous providers + alerte si seuils franchis."""
    try:
        from nokido_agent.app.forge_provider_quota import all_quota_report
        from nokido_agent.app.forge_provider_specs import QUOTA_ALERT_THRESHOLDS
    except ImportError as e:
        print(f"[quota-alert] imports failed: {e}", flush=True)
        return

    alerted = _load_alerted()
    month = _month_key()
    changed = False
    reports = all_quota_report()
    print(
        f"[quota-alert] {datetime.datetime.now().isoformat()} check {len(reports)} providers",
        flush=True,
    )

    for status in reports:
        provider = status["provider"]
        pct = status.get("pct_max", 0)
        for threshold in sorted(QUOTA_ALERT_THRESHOLDS):
            if pct < threshold:
                continue
            key = f"{provider}:{int(threshold * 100)}:{month}"
            if key in alerted:
                continue
            msg = _format_alert(provider, status, threshold)
            if _send_mailbox(msg):
                alerted.add(key)
                changed = True
                print(f"[quota-alert] SENT {key}", flush=True)
            else:
                print(f"[quota-alert] FAIL send {key}", flush=True)

    # ── P2 ECONOME (2026-07-05) : SOURCE endocrinienne CORTISOL_QUOTA_CLOUD ──
    # Les efferents existent deja (orchestration_gate bloque l'escalade cloud,
    # should_throttle freine les spawns >=0.85) — il manquait la GLANDE.
    # Emission si un provider depasse 80% de son quota ; level = pct max (0..1),
    # TTL = defaut endocrine (2h). Best-effort : jamais casser l'alerte mailbox.
    try:
        _pcts = [float(s.get("pct_max", 0) or 0) for s in reports]
        _worst = max(_pcts) if _pcts else 0.0
        if _worst >= 0.8:
            from nokido_agent.app.forge_endocrine import release as _release
            _wp = next((s["provider"] for s in reports
                        if float(s.get("pct_max", 0) or 0) == _worst), "?")
            _release("CORTISOL_QUOTA_CLOUD", level=min(1.0, _worst),
                     source="quota_alert_daemon", reason=f"{_wp} pct_max={_worst:.2f}")
            print(f"[quota-alert] hormone CORTISOL_QUOTA_CLOUD level={_worst:.2f} ({_wp})", flush=True)
    except Exception as _he:  # noqa: BLE001
        print(f"[quota-alert] hormone emit skipped: {_he}", flush=True)

    # Cleanup keys mois passe (garbage collect)
    alerted_filtered = {k for k in alerted if k.endswith(f":{month}") or k.endswith(":") is False}
    # Garde aussi les 2 derniers mois pour resilience
    last_month = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=30)).strftime(
        "%Y-%m"
    )
    alerted_filtered = {k for k in alerted if k.split(":")[-1] in (month, last_month)}
    if alerted_filtered != alerted:
        changed = True
        alerted = alerted_filtered

    if changed:
        _save_alerted(alerted)


def main() -> None:
    # Le pouls suit le rythme du COEUR, le controle reste une fonction lente. Avant
    # cette bascule, l'organe ne battait qu'une fois par cycle de 3600 s pour un seuil
    # de supervision de 3600 s : il vivait exactement a la limite de sa propre mort.
    from nokido_agent.app.forge_heartbeat import Cadence

    print(f"[quota-alert] daemon start, check interval={CHECK_INTERVAL_SEC}s", flush=True)
    cad = Cadence("quota_alert_daemon", cycle_s=CHECK_INTERVAL_SEC)
    while True:
        try:
            if cad.tour():
                check_and_alert()
                cad.cycle_termine(ok=True)
        except KeyboardInterrupt:
            print("[quota-alert] interrupt, exit", flush=True)
            break
        except Exception as e:
            print(f"[quota-alert] check_and_alert error: {e}", flush=True)
            # Un cycle en ECHEC le dit, au lieu de se confondre avec un cycle absent.
            cad.cycle_termine(ok=False, erreur=type(e).__name__)
        cad.dormir()


if __name__ == "__main__":
    # Mode --once pour cron-style scheduling
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        check_and_alert()
    else:
        main()
