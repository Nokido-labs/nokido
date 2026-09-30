#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""forge_health_ui.py — dashboard de santé Nokido, souverain + sans build.

Rend `sandbox/health.json` (écrit par le supervisor toutes les 20s, chantier
P1.3 observabilité) : pouls du hub, grille des services colorée par statut,
alerte essentiels dégradés. Vanilla HTML + CSS inline + auto-refresh fetch —
ZÉRO framework / build / dépendance (direction A de [[roadmap_generative_ui]]),
rapide. Complète le dashboard hub (laid+lent, [[roadmap_ui_dashboard_unified]]).
Lit la MÊME surface hub-indépendante -> marche même hub down.

Usage :
    forge_health_ui.py --html               # imprime le HTML (test)
    forge_health_ui.py --json               # health.json brut
    forge_health_ui.py --serve [--port 7610]  # serveur live (http.server)
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEALTH = os.path.join(ROOT, "sandbox", "health.json")

_COLORS = {
    "running": "#3fb950", "sleeping": "#58a6ff", "stopped": "#d29922",
    "quarantine": "#f85149", "starting": "#a371f7", "restarting": "#a371f7",
}


def load() -> dict:
    try:
        with open(HEALTH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def render_html(h: dict) -> str:
    svc = h.get("services", {})
    hub_ok = h.get("hub_healthy", False)
    degc = h.get("degraded_count", "?")
    degess = h.get("degraded_essential", []) or []
    banner = "#3fb950" if hub_ok and not degess else ("#f85149" if degess else "#d29922")
    cards = []
    for name, s in sorted(svc.items(), key=lambda kv: (kv[1].get("wave", 9), kv[0])):
        st = s.get("status", "?")
        col = _COLORS.get(st, "#8b949e")
        port = s.get("port")
        ess = "★" if s.get("essential") else ""
        rst = s.get("restarts", 0)
        cards.append(
            f'<div class="c" style="border-left:4px solid {col}">'
            f'<div class="n">{_html.escape(name)} <span class="e">{ess}</span></div>'
            f'<div class="m"><span class="b" style="background:{col}">{_html.escape(st)}</span>'
            f' w{s.get("wave","?")}{f" :{port}" if port else ""}'
            f'{f" ↻{rst}" if rst else ""}</div></div>'
        )
    alert = (f'<div class="alert">⚠ ESSENTIELS DÉGRADÉS : {", ".join(_html.escape(x) for x in degess)}</div>'
             if degess else "")
    nrun = sum(1 for s in svc.values() if s.get("status") == "running")
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nokido — santé</title><style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:#0d1117;color:#c9d1d9;font:14px/1.5 ui-monospace,Consolas,monospace}}
header{{padding:18px 22px;border-bottom:1px solid #21262d;display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
.pulse{{width:14px;height:14px;border-radius:50%;background:{banner};box-shadow:0 0 12px {banner};animation:p 2s infinite}}
@keyframes p{{50%{{opacity:.4}}}}
h1{{font-size:17px;margin:0;font-weight:600}}
.stat{{color:#8b949e}}.stat b{{color:#c9d1d9}}
.alert{{margin:14px 22px;padding:10px 14px;background:#3d1417;border:1px solid #f85149;border-radius:8px;color:#ff7b72}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px;padding:18px 22px}}
.c{{background:#161b22;border:1px solid #21262d;border-radius:8px;padding:10px 12px}}
.n{{font-weight:600;font-size:13px;word-break:break-all}}.e{{color:#d29922}}
.m{{margin-top:6px;color:#8b949e;font-size:12px}}
.b{{color:#0d1117;padding:1px 7px;border-radius:10px;font-size:11px;font-weight:700}}
footer{{padding:10px 22px;color:#484f58;font-size:11px}}
</style></head><body>
<header><span class="pulse"></span><h1>Nokido — santé</h1>
<span class="stat">hub <b>{"OK" if hub_ok else "KO"}</b></span>
<span class="stat">running <b>{nrun}</b>/{len(svc)}</span>
<span class="stat">dégradés <b>{degc}</b></span>
<span class="stat" id="ts">ts {h.get("ts","?")}</span></header>
{alert}
<div class="grid" id="g">{"".join(cards)}</div>
<footer>auto-refresh 5s · source sandbox/health.json (supervisor P1.3) · souverain, sans build</footer>
<script>setTimeout(function(){{location.reload()}},5000)</script>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Dashboard santé Nokido (health.json)")
    ap.add_argument("--html", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--serve", action="store_true")
    ap.add_argument("--port", type=int, default=7610)
    a = ap.parse_args()
    h = load()
    if a.json:
        print(json.dumps(h, ensure_ascii=False, indent=2))
        return 0
    if a.serve:
        import http.server

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path.startswith("/data"):
                    body = json.dumps(load()).encode("utf-8")
                    ct = "application/json"
                else:
                    body = render_html(load()).encode("utf-8")
                    ct = "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("content-type", ct)
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = http.server.HTTPServer(("127.0.0.1", a.port), H)
        print(f"[health-ui] http://127.0.0.1:{a.port}  (Ctrl-C pour stop)")
        srv.serve_forever()
        return 0
    # défaut : --html
    print(render_html(h))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
