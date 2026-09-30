"""app/web_hub/dashboard_diag_htmx.py — Daemon health dashboard HTMX.

Nouvelle vue /dashboard/diag qui affiche en temps reel l'etat des heartbeats
Nokido via forge_supervisor_diag. Utilise htmx_helpers + Alpine.js pour
auto-refresh toutes les 30s sans full reload.

Pas remplacement de dashboard_html.py existant (qui sert services), mais
companion view pour observabilite daemons.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

from .htmx_helpers import htmx_layout, htmx_partial, htmx_table, htmx_alert

ROOT = Path(__file__).resolve().parent.parent.parent


def _diag_partial() -> str:
    """Render daemon health table fragment (HTMX swap target)."""
    sys.path.insert(0, str(ROOT))
    try:
        from nokido_agent.app.forge_supervisor_diag import diagnose

        d = diagnose()
    except Exception as e:
        return htmx_alert(f"diag KO: {e}", "error")

    counts = d.get("counts", {})
    total = d.get("total", 0)

    # Summary cards
    summary = f"""<div class="grid grid-cols-4 gap-3 mb-4">
  <div class="bg-green-50 border border-green-200 rounded p-3 text-center">
    <div class="text-2xl font-bold text-green-700">{counts.get("FRESH", 0)}</div>
    <div class="text-xs text-green-600">FRESH (&lt;5min)</div>
  </div>
  <div class="bg-blue-50 border border-blue-200 rounded p-3 text-center">
    <div class="text-2xl font-bold text-blue-700">{counts.get("OK", 0)}</div>
    <div class="text-xs text-blue-600">OK (&lt;1h)</div>
  </div>
  <div class="bg-yellow-50 border border-yellow-200 rounded p-3 text-center">
    <div class="text-2xl font-bold text-yellow-700">{counts.get("STALE", 0)}</div>
    <div class="text-xs text-yellow-600">STALE (&lt;1j)</div>
  </div>
  <div class="bg-red-50 border border-red-200 rounded p-3 text-center">
    <div class="text-2xl font-bold text-red-700">{counts.get("DEAD", 0)}</div>
    <div class="text-xs text-red-600">DEAD (&gt;=1j)</div>
  </div>
</div>"""

    # Table rows
    rows = []
    for name, info in sorted(d.get("heartbeats", {}).items(), key=lambda x: x[1].get("age_s", 0), reverse=True):
        age_s = info.get("age_s", 0)
        status = info.get("status", "?")
        critical = info.get("critical", False)
        optional = info.get("optional", False)
        tag = "CRITICAL" if critical else ("optional" if optional else "")
        # Format age
        if age_s < 60:
            age_str = f"{age_s:.0f}s"
        elif age_s < 3600:
            age_str = f"{age_s / 60:.1f}min"
        elif age_s < 86400:
            age_str = f"{age_s / 3600:.1f}h"
        else:
            age_str = f"{age_s / 86400:.1f}j"
        rows.append([name, status, age_str, tag])

    table = htmx_table(
        ["daemon", "status", "age", "tag"],
        rows,
    )

    alerts = ""
    for name in d.get("critical_dead", []):
        alerts += htmx_alert(f"DEAD CRITICAL: {name}", "error")
    for name in d.get("stale_critical", []):
        alerts += htmx_alert(f"STALE CRITICAL: {name}", "warning")

    return f"""<div id="diag-content">
{alerts}
{summary}
{table}
<div class="text-xs text-gray-500 mt-2">timestamp: {d.get("timestamp", "?")}</div>
</div>"""


def render_diag_page() -> str:
    """Full HTML page with auto-refresh every 30s via HTMX."""
    body = f"""<div class="max-w-6xl mx-auto p-6">
<div class="flex justify-between items-center mb-4">
  <h1 class="text-2xl font-bold">Nokido Daemon Health</h1>
  <div class="text-sm text-gray-500">
    Auto-refresh 30s
    <span class="htmx-indicator spinner ml-1"></span>
  </div>
</div>
<div hx-get="/dashboard/diag/partial"
     hx-trigger="load, every 30s"
     hx-swap="innerHTML">
{_diag_partial()}
</div>
</div>"""
    return htmx_layout("Nokido Diag", body)


def route_diag_partial() -> tuple[str, int, dict]:
    """Handler pour GET /dashboard/diag/partial. Returns (body, status, headers)."""
    return _diag_partial(), 200, {"Content-Type": "text/html; charset=utf-8"}


def route_diag_page() -> tuple[str, int, dict]:
    """Handler pour GET /dashboard/diag."""
    return render_diag_page(), 200, {"Content-Type": "text/html; charset=utf-8"}
