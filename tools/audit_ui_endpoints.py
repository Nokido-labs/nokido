#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""audit_ui_endpoints.py — câblage RÉEL des GUIs (démo-vs-fonctionne).
Extrait les endpoints fetch()/EventSource()/'/api/...' de chaque page web_hub,
les frappe sur :7400 (loggé admin), classe :
  200=OK · 405=existe (POST/route ok, GET refusé) · 404=ROUTE MORTE · ERR=injoignable.
404 = la tuile/bouton pointe vers une route inexistante = vraie zone morte.
Trusted_script (commit avant run) OU `run python runpy`.
"""
import sys, re, json, urllib.request, urllib.parse, urllib.error, http.cookiejar
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from app.web_hub.auth import AuthConfig  # noqa: E402

cfg = AuthConfig.from_env()
BASE = "http://127.0.0.1:7400"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
if cfg.enabled:
    try:
        op.open(BASE + "/auth/login",
                data=urllib.parse.urlencode({"admin_token": cfg.admin_token or "", "redirect_to": "/"}).encode(),
                timeout=6)
    except Exception as e:
        print("login FAIL:", type(e).__name__)

WEB = Path(ROOT) / "app" / "web_hub"
RX_BASE = re.compile(r"""(?:const|let|var)\s+base\s*=\s*[`'"](/[^`'"]*)""")
RX_BASEPLUS = re.compile(r"""base\s*\+\s*[`'"](/[^`'"]+)""")
RX_CALL = re.compile(r"""(?:fetch|EventSource)\(\s*[`'"]([^`'"]+)""")
RX_API = re.compile(r"""[`'"](/(?:api|epistemic|auth|mcp_lab)/[A-Za-z0-9_\-/]+)[`'"]""")

refs = {}  # url -> set(pages)


def _add(u, page):
    u = u.split("?")[0]
    if "${" in u or "{" in u:  # templaté -> base avant 1er segment dynamique
        u = u.split("${")[0].split("{")[0].rstrip("/")
    if u.startswith("/") and not u.startswith("//") and len(u) > 3:
        refs.setdefault(u, set()).add(page)


for f in sorted(list(WEB.glob("*.html")) + list(WEB.glob("*.py")) + list(WEB.glob("forms/*.py"))):
    try:
        txt = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    bases = RX_BASE.findall(txt)
    bp = bases[0].rstrip("/") if bases else ""           # préfixe JS (ex /mcp_lab)
    baseplus = set(RX_BASEPLUS.findall(txt))             # chemins utilisés comme base + '...'
    for p in baseplus:                                   # -> URL réelle préfixée
        _add(bp + p, f.name)
    for m in set(RX_CALL.findall(txt)) | set(RX_API.findall(txt)):
        if m in baseplus:                               # forme nue d'un base+ -> déjà comptée préfixée
            continue
        _add(m, f.name)

print(f"{len(refs)} endpoints référencés par les pages\n")
dead, ok, post_only = [], 0, 0
for u in sorted(refs):
    pages = ",".join(sorted(refs[u]))
    try:
        r = op.open(BASE + u, timeout=4)
        body = r.read(1024)
        print(f"200 {len(body):>5}b  {u:<40} [{pages}]")
        ok += 1
    except urllib.error.HTTPError as e:
        tag = "ROUTE MORTE" if e.code == 404 else ("POST-only" if e.code == 405 else f"HTTP {e.code}")
        print(f"{e.code:<3} {tag:<11} {u:<40} [{pages}]")
        if e.code == 404:
            dead.append({"url": u, "pages": sorted(refs[u])})
        elif e.code == 405:
            post_only += 1
    except Exception as e:
        print(f"ERR {type(e).__name__:<11} {u:<40} [{pages}]")
print(f"\n== {ok} OK · {post_only} POST-only(câblés) · {len(dead)} MORTES ==")
print("DEAD:", json.dumps(dead, ensure_ascii=False))
