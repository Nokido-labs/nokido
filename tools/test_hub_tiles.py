"""Test E2E LIVE des tuiles du Hub : GET /api/hub/modules (ce que le navigateur recoit)
puis GET chaque href resolue. Login admin_token -> cookie serveur. Trusted_script.
SOURCE (import SERVICES) vs LIVE (endpoint) -> dit si un restart :7400 est requis."""
import sys
import json
import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar

ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from app.web_hub.auth import AuthConfig  # noqa: E402
from app.web_hub.app import SERVICES  # noqa: E402

cfg = AuthConfig.from_env()
BASE = "http://127.0.0.1:7400"
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
if cfg.enabled:
    try:
        data = urllib.parse.urlencode({"admin_token": cfg.admin_token or "", "redirect_to": "/"}).encode()
        op.open(BASE + "/auth/login", data=data, timeout=6)
    except Exception as e:
        print("login FAIL:", type(e).__name__, str(e)[:80])
print("logged:", any(c.name == "lf_session" for c in cj))


def hit(u):
    try:
        r = op.open(urllib.request.Request(u), timeout=6)
        return str(r.status)
    except urllib.error.HTTPError as e:
        return f"HTTP{e.code}"
    except Exception as e:
        return f"ERR:{type(e).__name__}"


raw = op.open(BASE + "/api/hub/modules", timeout=6).read()
live = json.loads(raw)
match = "(RESTART OK)" if len(live) == len(SERVICES) else "<<< RESTART :7400 REQUIS"
print(f"SOURCE SERVICES={len(SERVICES)}  LIVE /api/hub/modules={len(live)}  {match}")
print(f"{'slug':<14}{'status':<8}{'href':<30}{'GET'}")
nb_ok = nb_bad = 0
for m in live:
    href = m["href"]
    full = href if href.startswith("http") else BASE + href
    if m["status"] == "up":
        st = hit(full)
        if st.startswith(("2", "3")):
            nb_ok += 1
        else:
            nb_bad += 1
    else:
        st = f"({m['status']})"
    print(f"{m['slug']:<14}{m['status']:<8}{href[:29]:<30}{st}")
print(f"\nup&clickable: {nb_ok} OK / {nb_bad} BROKEN")

print("\n--- ASSETS /design (polish restyle) ---")
for a in ("/design/ui_kits/hub/index.html",
          "/design/ui_kits/hub/hub-compiled.js",
          "/design/ui_kits/hub/hub-polish.css"):
    print(f"{a:<46}{hit(BASE + a)}")

print("\n--- ENDPOINTS temps-reel (donnees des vues) ---")
import json as _json
for a in ("/api/hub/overview", "/api/hub/federation", "/api/hub/persona", "/api/hub/provenance"):
    try:
        body = op.open(BASE + a, timeout=6).read().decode("utf-8", "replace")
        d = _json.loads(body)
        n = len(d) if isinstance(d, (list, dict)) else 0
        print(f"{a:<24}200 ({n} {'items' if isinstance(d, list) else 'champs'}) {body[:80]}")
    except Exception as e:
        print(f"{a:<24}{type(e).__name__}: {str(e)[:50]}")
