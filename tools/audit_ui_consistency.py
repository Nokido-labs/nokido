"""Audit cohérence graphique : chaque page d'interface tuilée charge-t-elle le DS
unifié (nokido.css / tokens lf- / --bg-0) ? Login admin (cookie serveur). Trusted_script.

DEUX DÉFAUTS CORRIGÉS LE 2026-09-18, tous deux de la même famille (statut déclaré ≠ réel) :

1. Le script imprimait la chaîne `'200'` EN DUR pour toute réponse qui ne levait pas.
   Un code 204, 302 ou 500 non levé s'affichait donc « 200 ». Le vrai code est lu.

2. Il comptait le MUR DE LOGIN comme une page servie. Mesuré ce jour : sans session,
   `/graph/`, `/tui/`, `/providers` et `/` rendent tous **200** avec le titre
   « Nokido Hub - Login » — le portail sert le mur en 200, pas en 401, quand le client
   accepte du HTML. Un audit qui lit le code HTTP conclut donc « tout va bien » en
   n'ayant vu aucune des pages. C'est aussi ce qui m'a fait lire un faux 503 sur
   `/graph` : avec `Accept: */*` la même route rend `401 {"detail":"unauthorized"}`.
   La réponse est désormais classée MUR, qui n'est ni un succès ni une panne.
"""
import http.cookiejar
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from pathlib import Path as _P

ROOT = str(_P(__file__).resolve().parents[1])  # tools/ -> LaForge/ (robuste, indep. du user)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from app.web_hub.auth import AuthConfig  # noqa: E402

cfg = AuthConfig.from_env()
BASE = "http://127.0.0.1:7400"
HUB = "http://127.0.0.1:8766"
# En-tête d'un NAVIGATEUR : c'est lui qui décide si le portail répond en HTML ou en
# JSON. Sonder avec `*/*` mesure autre chose que ce que voit l'utilisateur.
NAV = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
if cfg.enabled:
    try:
        # form-urlencoded : la route refuse le JSON (422 « admin_token missing »,
        # `input: null`) — mesuré 2026-09-18. Le jeton ne passe JAMAIS en query.
        op.open(BASE + "/auth/login",
                data=urllib.parse.urlencode(
                    {"admin_token": cfg.admin_token or "", "redirect_to": "/"}).encode(),
                timeout=6)
    except Exception as e:
        print("login FAIL:", type(e).__name__)
if not [c for c in cj]:
    print("!! aucune session : tout ce qui suit sera un MUR, pas une mesure des pages")

PAGES = [
    (BASE, "/"), (BASE, "/vitals"), (BASE, "/launcher"), (BASE, "/anatomy"),
    (BASE, "/status"), (BASE, "/mcp_lab/"), (BASE, "/reports/"), (BASE, "/rbac"),
    (BASE, "/llm-dashboard"), (BASE, "/forge/feed"), (BASE, "/dashboard"),
    (BASE, "/redteam"), (BASE, "/providers"), (BASE, "/graph/"), (BASE, "/tui/"),
    (BASE, "/postal"), (BASE, "/epistemic"),
    (HUB, "/admin/providers"), (HUB, "/admin/mcp_clients"),
]

_TITRE = re.compile(r"<title>(.*?)</title>", re.S | re.I)

# Pages dont le HTML n'appartient PAS a Nokido : on les mandate, on ne les ecrit pas.
# Leur reprocher la feuille commune serait un reproche qu'aucun travail ne peut lever --
# et un audit qui pointe l'inameliorable finit par etre lu comme du bruit.
# Chaque exception porte sa RAISON, sinon la liste devient un tapis sous lequel balayer.
HORS_DESIGN_SYSTEM = {
    "/tui/": "HTML emis par Textual serve (backend tiers) ; le proxy en delie seulement "
             "les ressources externes bloquantes",
}


def sonde(base: str, chemin: str):
    rq = urllib.request.Request(base + chemin)
    rq.add_header("Accept", NAV)
    try:
        r = op.open(rq, timeout=9)
        code, corps = r.getcode(), r.read().decode("utf-8", "replace")
        ctype = r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        code, corps = e.code, e.read().decode("utf-8", "replace")
        ctype = e.headers.get("Content-Type", "")
    except Exception as e:
        return type(e).__name__, "", "", None, ""
    m = _TITRE.search(corps)
    titre = (m.group(1).strip() if m else "")
    # Le mur se reconnaît à son TITRE, jamais à son code : il est servi en 200.
    etat = "MUR" if "login" in titre.lower() else str(code)
    return etat, titre, corps, code, ctype


print("%-24s%-7s%-6s%-8s%-9s%s" % ("page", "etat", "DS", "tokens", "octets", "titre"))
manquants, absentes, non_html, murs, tiers = [], [], [], [], []
for base, pg in PAGES:
    etat, titre, corps, code, ctype = sonde(base, pg)
    port = "" if base == BASE else " [:8766]"
    if not corps:
        print("%-24s%-7s%-6s%-8s%-9s%s" % (pg + port, etat, "-", "-", "-", "(illisible)"))
        continue

    # DEUX FAUX POSITIFS CORRIGES le 2026-09-18 : l'audit reprochait a `/status`
    # (application/json) et a deux routes en 404 de ne pas charger la feuille commune.
    # Un endpoint JSON n'est pas une page, et une route ABSENTE n'est pas une page mal
    # stylee -- ce sont deux diagnostics differents, qui se reparent a deux endroits
    # differents. Un garde qui crie a faux se fait desarmer, et emporte les vrais avec lui.
    est_html = "text/html" in (ctype or "").lower()
    ds = "nokido.css" in corps
    tok = ("--bg-0" in corps) or ("lf-" in corps) or ("/static/nokido" in corps)
    marque = "YES" if ds else ("n/a" if not est_html else "no")
    print("%-24s%-7s%-6s%-8s%-9d%s" % (pg + port, etat, marque,
                                       "YES" if tok else ("n/a" if not est_html else "no"),
                                       len(corps), titre[:40]))
    if etat == "MUR":
        murs.append(pg + port)
    elif code and code >= 400:
        absentes.append("%s (HTTP %s)" % (pg + port, code))
    elif not est_html:
        non_html.append("%s (%s)" % (pg + port, (ctype or "?").split(";")[0]))
    elif pg in HORS_DESIGN_SYSTEM:
        tiers.append("%s — %s" % (pg + port, HORS_DESIGN_SYSTEM[pg]))
    elif not ds:
        manquants.append(pg + port)

print()
if manquants:
    print("pages HTML servies sans la feuille commune (%d) : %s"
          % (len(manquants), ", ".join(manquants)))
else:
    print("toutes les pages HTML servies chargent la feuille commune")
# Chaque categorie est NOMMEE : un total qui melange « mal style », « absent » et
# « pas une page » ne dit a personne ou aller travailler.
if absentes:
    print("routes ABSENTES (a instruire, ce n'est pas un defaut de style) : %s"
          % ", ".join(absentes))
if non_html:
    print("reponses NON-HTML (hors perimetre du design system) : %s" % ", ".join(non_html))
for t in tiers:
    print("HTML TIERS (hors perimetre, raison nommee) : %s" % t)
if murs:
    print("NON MESURE — rendu MUR (session absente ou expiree) : %s" % ", ".join(murs))
print("Un MUR n'est pas un verdict sur la page, c'est l'absence de verdict.")
