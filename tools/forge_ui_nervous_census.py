#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_ui_nervous_census.py — le cablage REEL des interfaces, ELEMENT par element.

Premiere brique du « systeme nerveux de la GUI » (owner, 2026-08-26) : une interface
n'est pas un tas de pixels mais une surface OBSERVABLE et ACTIONNABLE par les agents.
Avant de brancher un contrat d'UI, une telemetrie ou un UI Doctor, il faut MESURER ce
qui existe : quels elements sont reellement cables, lesquels ne sont que visuels, et
lesquels sont invisibles a un agent parce qu'ils n'ont ni role ni nom accessible.

CE QUI EXISTAIT DEJA, et qui est REUTILISE (anti-dup) :
  * tools/forge_playwright_browser.py  — moteur Firefox isole (profil dedie, binaires
    C:/nokido/ms-playwright), lunettes a11y / set-of-mark / interactifs ;
  * tools/audit_ui_endpoints.py        — endpoints fetch()/EventSource des PAGES (regex
    sur la source) sondes sur :7400 ; sa grille 200/405/404/ERR est reprise ici ;
  * tools/forge_ui_manifest.py         — le registre-contrat des surfaces et leur etat
    MESURE (live/dormant/absent) ; confronte ici a la sonde ;
  * tools/forge_ui_campaign.py         — le gate d'acceptation (captures + flags).

CE QUI MANQUAIT : la JOINTURE par element. L'audit des endpoints lit la source de la
page, pas le bouton ; l'oracle liste les interactifs sans dire s'ils menent quelque
part. Ici, pour chaque element interactif d'une page rendue :
    element -> gestionnaire (href / hx-* / form / onclick / @click / listener JS)
            -> cible HTTP -> sonde (GET SEULEMENT, jamais un POST : un bouton
               « Restart » ne doit pas etre actionne par un recensement)
            -> verdict.

VERDICTS (un par element, exclusifs) :
    CABLE       cible trouvee et route vivante (2xx/3xx, ou 405 sur une route POST)
    CABLE_AUTH  cible trouvee, 401/403 : cablee, hors de portee de cette session
    MORT        cible trouvee, 404 / 5xx / injoignable : le bouton pointe dans le vide
    JS_OPAQUE   gestionnaire present mais aucune cible HTTP lisible statiquement —
                candidat a une sonde d'EXECUTION (phase 2), pas un verdict
    VISUEL      aucun gestionnaire, aucune cible : decor
    CONTROLE    champ de saisie : cable par son formulaire, pas une action
Drapeau orthogonal `invisible_agent` : ni nom ni role accessible — present a l'ecran,
absent de l'arbre que lit un agent.

TROIS ETATS sur chaque sonde : statut lu / refus explicite / injoignable — une page qui
ne repond pas est `injoignable`, jamais « sans bouton ».

Sorties (sandbox/workspace/ui_audit/) :
    nervous_<surface>_<date>.json   detail par page et par element
    nervous_report_<date>.md        synthese lisible, comptes par verdict et par surface
    ui_contract_generated.json      squelette de contrat par surface (pages -> actions)

Usage (deporte, > 70 s) :
    run action=run_job script=tools/forge_ui_nervous_census.py
    LAFORGE_PYTHON tools/forge_ui_nervous_census.py --surfaces web_hub,graph --max-pages 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT_DIR = ROOT / "sandbox" / "workspace" / "ui_audit"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "C:/nokido/ms-playwright")
os.environ.setdefault("NOKIDO_UI_BROWSER_PROFILE", str(OUT_DIR / "profil-census"))
os.environ.setdefault("NOKIDO_UI_BROWSER_HEADED", "0")

__FORGE_COLOR__ = "interface/proprioception-ui"  # l'interface se sent elle-meme

SURFACES_DEFAUT = [
    {"surface": "web_hub", "base": "http://127.0.0.1:7400", "login": "form", "manifest": "dashboard",
     # Graines corrigees le 2026-08-29 : `/diag` n'existe pas (la route est
     # `/dashboard/diag`) et `/epistemic` est PARAMETREE (`/epistemic/{topic}`), donc
     # nue elle rend 404. Deux 404 qui se lisaient comme des pages cassees alors que
     # c'etaient nos propres graines qui etaient fausses.
     "graines": ["/dashboard", "/organs", "/postal", "/anatomy", "/swarm", "/maison",
                 "/dashboard/diag", "/launcher", "/llm_dashboard", "/rbac/"]},
    {"surface": "deno_web_hub", "base": "http://127.0.0.1:7401", "login": None, "manifest": None},
    {"surface": "graph", "base": "http://127.0.0.1:7474", "login": None, "manifest": "graph"},
    {"surface": "netcfg_ui", "base": "http://127.0.0.1:7500", "login": None, "manifest": "netcfg"},
]
MAX_PAGES = 50
ATTENTE_RENDU_MS = 1500
# Pages TIERCES : la doc OpenAPI (ReDoc / Swagger) est generee par une bibliotheque,
# elle ne dit RIEN de notre cablage. Mesure 2026-08-29 (mode navigateur) : /redoc a lui
# seul apportait l'essentiel des 139 JS_OPAQUE et des 321 invisible_agent — une dette
# qui n'est pas la notre, comptee dans notre denominateur. On l'ecarte, et on le DIT
# dans le rapport : un filtre muet surestime la couverture au lieu de l'expliquer.
TIERCES = r"/redoc($|[/?])|/docs($|[/?])|/openapi\.json"
EXCLUS = re.compile(r"(/auth/logout|/static/|/api/|" + TIERCES +
                    r"|\.(png|jpg|jpeg|gif|svg|css|js|ico|json|map)($|\?)|autofire=true)", re.I)
VERDICTS = ("CABLE", "CABLE_AUTH", "MORT", "INCERTAIN", "EXTERNE", "PRUDENCE", "JS_OPAQUE", "VISUEL", "CONTROLE")
# Un GET n'est pas sans effet quand la route s'appelle ainsi : /auth/logout accepte le
# GET et a DECONNECTE la session du recensement (mesure 2026-08-26 : toutes les pages
# suivantes en 401). Ces cibles ne sont jamais sondees — verdict PRUDENCE, dit tel quel.
DANGEREUX = re.compile(r"(logout|logoff|signout|reset|delete|purge|kill|restart|stop|shutdown|reboot|wipe|clear|evict)", re.I)
CONTROLES = {"input", "select", "textarea"}
ROLES_MUETS = {None, "", "generic", "presentation", "none", "div", "span"}

# Instrumentation AVANT tout script de page : compte les ecouteurs poses par JS sur
# chaque element (click/submit/...). Les ecouteurs DELEGUES (htmx, Alpine posent sur
# document) ne marquent pas l'element — ils sont vus par leurs attributs hx-* / @click.
INIT_JS = r"""
(() => {
  const orig = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, fn, opts) {
    try {
      if (this && this.setAttribute && /^(click|submit|change|input|keydown|keyup|pointerdown|mousedown|touchstart)$/.test(type)) {
        const n = parseInt(this.getAttribute('data-nk-listeners') || '0', 10) + 1;
        this.setAttribute('data-nk-listeners', String(n));
      }
    } catch (e) {}
    return orig.call(this, type, fn, opts);
  };
})();
"""

# Extraction : chaque element potentiellement actionnable, VISIBLE ou NON (un bouton
# cache est dit cache, pas omis), avec ses attributs de cablage et son nom accessible
# calcule comme le ferait un lecteur d'ecran (aria-label > labelledby > label > texte).
ELEMENTS_JS = r"""
() => {
  const sel = 'a[href],button,input,select,textarea,summary,form,[role=button],[role=link],[role=checkbox],[role=tab],[role=menuitem],[role=switch],[onclick],[hx-get],[hx-post],[hx-put],[hx-delete],[hx-patch],[contenteditable=true],[tabindex]:not([tabindex="-1"])';
  const implicit = {a: 'link', button: 'button', input: 'textbox', select: 'combobox', textarea: 'textbox', summary: 'button', form: 'form'};
  const out = []; let i = 0;
  for (const e of document.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect();
    const st = getComputedStyle(e);
    const visible = !(r.width <= 1 || r.height <= 1 || st.visibility === 'hidden' || st.display === 'none' || st.opacity === '0');
    const attrs = {};
    for (const a of e.attributes) {
      if (/^(hx-|x-on:|@|data-|on|aria-|href|action|method|type|name|id|role|disabled|title|placeholder)/.test(a.name)) attrs[a.name] = String(a.value).slice(0, 200);
    }
    const tag = e.tagName.toLowerCase();
    const inputType = tag === 'input' ? (e.getAttribute('type') || 'text').toLowerCase() : null;
    let role = e.getAttribute('role') || implicit[tag] || null;
    if (tag === 'input' && ['submit', 'button', 'reset', 'image'].includes(inputType)) role = 'button';
    if (tag === 'input' && inputType === 'checkbox') role = 'checkbox';
    if (tag === 'input' && inputType === 'radio') role = 'radio';
    if (tag === 'input' && inputType === 'hidden') role = null;
    const lbl = e.getAttribute('aria-labelledby');
    let name = e.getAttribute('aria-label') || '';
    if (!name && lbl) { const l = document.getElementById(lbl); if (l) name = l.innerText || ''; }
    if (!name && e.labels && e.labels.length) name = e.labels[0].innerText || '';
    if (!name) name = e.innerText || e.value || e.getAttribute('alt') || e.getAttribute('title') || e.getAttribute('placeholder') || '';
    name = String(name).trim().replace(/\s+/g, ' ').slice(0, 90);
    const form = e.closest('form');
    out.push({
      i: i++, tag, input_type: inputType, role, name, visible,
      x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
      attrs, listeners: parseInt(e.getAttribute('data-nk-listeners') || '0', 10),
      form_action: form ? (form.getAttribute('action') || '') : null,
      form_method: form ? (form.getAttribute('method') || 'get').toLowerCase() : null,
      disabled: !!e.disabled,
    });
  }
  return out;
}
"""

# Schemas d'URI qui ne menent a aucune route HTTP (ancre, script inline, courriel...).
SCHEMAS_SANS_ROUTE = ("java" + "script", "mailto", "tel", "data")


# ------------------------------------------------------------------ pur (testable)
def _cible_de(el: dict, page_url: str) -> tuple | None:
    """(METHODE, url_absolue, source) ou None. Source = htmx | href | form."""
    attrs = el.get("attrs") or {}
    for cle, meth in (("hx-get", "GET"), ("hx-post", "POST"), ("hx-put", "PUT"),
                      ("hx-delete", "DELETE"), ("hx-patch", "PATCH")):
        if attrs.get(cle):
            return meth, urljoin(page_url, attrs[cle]), "htmx"
    tag = el.get("tag")
    href = attrs.get("href")
    if tag == "a" and href:
        h = href.strip()
        if h.startswith("#") or h.lower().split(":", 1)[0] in SCHEMAS_SANS_ROUTE:
            return None
        return "GET", urljoin(page_url, h), "href"
    # Un gestionnaire inline qui NOMME sa route dans son code livre une cible lisible :
    # on la sonde en GET, methode inconnue -> un 405 vaut « la route existe ».
    for k in ("on" + "click", "on" + "submit", "on" + "change"):
        if attrs.get(k):
            m = re.search(r"""["'](/(?:api|admin|auth|supervisor)[A-Za-z0-9_\-./]*)["']""", attrs[k])
            if m:
                return "JS", urljoin(page_url, m.group(1)), k
    est_submit = (tag == "button" and (attrs.get("type") or "submit").lower() == "submit") or (
        tag == "input" and (el.get("input_type") or "") in ("submit", "image"))
    if tag == "form" or (est_submit and el.get("form_action") is not None):
        action = el.get("form_action") if tag != "form" else (attrs.get("action") or "")
        meth = (el.get("form_method") if tag != "form" else (attrs.get("method") or "get")) or "get"
        return meth.upper(), urljoin(page_url, action or page_url), "form"
    return None


def _a_un_gestionnaire(el: dict) -> bool:
    attrs = el.get("attrs") or {}
    if el.get("listeners", 0) > 0:
        return True
    for k in attrs:
        if k.startswith(("hx-", "x-on:", "@", "onclick", "onsubmit", "onchange", "oninput")):
            return True
    return False


def invisible_agent(el: dict) -> bool:
    """Present a l'ecran, absent de l'arbre qu'un agent lit : ni nom ni role."""
    return (not (el.get("name") or "").strip()) or (el.get("role") in ROLES_MUETS)


def classer(el: dict, statut_http, page_url: str = "", cible=None) -> str:
    """Un verdict exclusif par element. `statut_http` = int, ou None (injoignable),
    ou "non_sonde" (aucune cible). `cible` = (METHODE, url, source) deja resolue par
    un navigateur externe, sinon deduite des attributs. Pur : aucune I/O."""
    tag = el.get("tag")
    if tag in CONTROLES and el.get("role") not in ("button", "checkbox", "radio"):
        return "CONTROLE"
    if cible is None:
        cible = _cible_de(el, page_url or "http://127.0.0.1/")
    if cible is not None:
        meth = cible[0]
        if statut_http == "prudence":
            return "PRUDENCE"
        if statut_http == "externe":
            # Cible hors de l'origine : le sandbox du hub est HORS LIGNE, un
            # « injoignable » n'y prouve rien (mesure 2026-08-26 : 129 faux MORT sur des
            # liens openrouter/huggingface). Hors perimetre, dit tel quel.
            return "EXTERNE"
        if isinstance(statut_http, int):
            if 200 <= statut_http < 400:
                return "CABLE"
            if statut_http in (401, 403):
                return "CABLE_AUTH"
            if statut_http == 405 and meth != "GET":
                return "CABLE"  # la route existe, elle refuse juste le GET de la sonde
            if statut_http == 404 and meth != "GET":
                # Mesure 2026-08-26 : /api/opsec/set sur le hub Deno est declare POST et
                # rend 404 au GET (pas 405). Une sonde GET ne peut pas trancher une
                # route non-GET chez un serveur qui ne distingue pas les methodes.
                return "INCERTAIN"
            return "MORT"
        return "MORT"  # injoignable ou non sonde : la cible ne repond pas
    if _a_un_gestionnaire(el):
        return "JS_OPAQUE"
    return "VISUEL"


def signature_page(titre: str, elements: list) -> str:
    """Empreinte d'une page par ce qu'elle OFFRE (noms + verdicts), pas par son URL :
    `/llm_dashboard/`, `/llm_dashboard` et `/llm-dashboard` servent la meme page —
    la compter trois fois triplerait chaque defaut."""
    import hashlib

    sig = [titre] + sorted("%s|%s|%s" % (e.get("role"), e.get("name"), e.get("verdict")) for e in elements)
    return hashlib.sha256(json.dumps(sig, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def pages_uniques(pages: list) -> list:
    """Marque `doublon_de` sur les pages dont la signature a deja ete vue ; rend les
    pages uniques (les doublons restent dans le JSON, exclus des comptes)."""
    vues: dict = {}
    uniques = []
    for p in pages:
        sig = signature_page(p.get("titre", ""), p.get("elements", []))
        if sig in vues and p.get("elements"):
            p["doublon_de"] = vues[sig]
            continue
        vues.setdefault(sig, p.get("url"))
        uniques.append(p)
    return uniques


def resumer(elements: list) -> dict:
    out = {v: 0 for v in VERDICTS}
    out["invisible_agent"] = 0
    out["caches"] = 0
    for e in elements:
        out[e["verdict"]] = out.get(e["verdict"], 0) + 1
        if e.get("invisible_agent"):
            out["invisible_agent"] += 1
        if not e.get("visible", True):
            out["caches"] += 1
    out["total"] = len(elements)
    return out


# --------------------------------------------------------------------- sondes
async def _sonder(page, methode: str, url: str, cache: dict) -> tuple:
    """GET SEULEMENT, via le contexte du navigateur (cookies de session partages).
    Rend (statut|None, erreur|None). Jamais de POST : un recensement n'actionne rien."""
    cle = url.split("#", 1)[0]
    if cle in cache:
        return cache[cle]
    try:
        r = await page.request.fetch(cle, method="GET", timeout=6000, max_redirects=0)
        res = (r.status, None)
    except Exception as e:  # noqa: BLE001 — injoignable est un etat, on le nomme
        res = (None, type(e).__name__)
    cache[cle] = res
    return res


def _joignable(base: str) -> tuple:
    """Trois etats : (statut, None) / (None, erreur). Sonde brute, avant le navigateur."""
    import urllib.request

    try:
        r = urllib.request.urlopen(base + "/", timeout=4)
        return r.status, None
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None)
        return (code, None) if isinstance(code, int) else (None, type(e).__name__)


def _manifest_etats() -> dict:
    """Ce que le manifeste DECLARE, pour le confronter au mesure."""
    try:
        from nokido_agent.tools.forge_ui_manifest import manifest

        m = manifest(persist=False)
        return {s.get("surface"): s.get("etat") for s in m.get("surfaces", [])}
    except Exception as e:  # noqa: BLE001
        return {"_illisible": type(e).__name__}


async def _login_form(page, base: str) -> str:
    """web_hub :7400 : formulaire /auth/login avec le jeton du coffre (jamais un jeton
    minte). Rend ok | absent | echec | inutile."""
    try:
        from app.web_hub.auth import AuthConfig

        cfg = AuthConfig.from_env()
        if not getattr(cfg, "enabled", False):
            return "inutile"
        jeton = getattr(cfg, "admin_token", "") or ""
        if not jeton:
            return "absent"
        await page.goto(base + "/auth/login", wait_until="domcontentloaded", timeout=15000)
        champ = page.locator("input[name=admin_token]")
        if await champ.count() == 0:
            return "absent"
        await champ.first.fill(jeton)
        await champ.first.press("Enter")
        await page.wait_for_timeout(1200)
        return "echec" if "/auth/login" in page.url else "ok"
    except Exception as e:  # noqa: BLE001
        return "echec (%s)" % type(e).__name__


def _etat_socket(base: str) -> str:
    """Trois etats sur le socket lui-meme : accepte / refuse (personne n'ecoute) /
    expire (un listener existe mais n'accepte plus — service coince, PAS dormant).
    Mesure 2026-08-26 : 7474 et 7500 rendaient 200 puis, 40 min plus tard, un
    connect qui EXPIRE ; un manifeste qui lit cela « dormant » ment."""
    import socket

    u = urlparse(base)
    try:
        s = socket.create_connection((u.hostname or "127.0.0.1", u.port or 80), 1.5)
        s.close()
        return "accepte"
    except ConnectionRefusedError:
        return "refuse"
    except (TimeoutError, socket.timeout):
        return "expire"
    except OSError as e:
        return "erreur (%s)" % type(e).__name__


def _meme_origine(url: str, base: str) -> bool:
    a, b = urlparse(url), urlparse(base)
    return (a.hostname, a.port or 80) == (b.hostname, b.port or 80)


async def _page_census(page, url: str, base: str, cache: dict) -> dict:
    reseau: list = []

    def _on_response(resp):
        try:
            if _meme_origine(resp.url, base):
                reseau.append({"url": resp.url[:200], "statut": resp.status,
                               "methode": resp.request.method})
        except Exception:  # noqa: BLE001 — muet-ok : un evenement reseau illisible n'arrete pas le recensement
            pass

    page.on("response", _on_response)
    entree = {"url": url, "titre": "", "chargement": None, "elements": [], "reseau": [],
              "aria_chars": None, "liens": []}
    try:
        r = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        entree["chargement"] = r.status if r else None
        await page.wait_for_timeout(ATTENTE_RENDU_MS)
        entree["titre"] = (await page.title())[:120]
        bruts = await page.evaluate(ELEMENTS_JS)
        try:
            aria = await page.locator("body").aria_snapshot()
            entree["aria_chars"] = len(aria or "")
        except Exception:  # noqa: BLE001 — Playwright plus ancien : on le dit, on n'invente pas
            entree["aria_chars"] = None
        for el in bruts:
            cible = _cible_de(el, url)
            statut, err = ("non_sonde", None)
            if cible is not None and not _meme_origine(cible[1], base):
                statut = "externe"
            elif cible is not None and DANGEREUX.search(urlparse(cible[1]).path):
                statut = "prudence"
            elif cible is not None:
                statut, err = await _sonder(page, cible[0], cible[1], cache)
            verdict = classer(el, statut, url)
            entree["elements"].append({
                "i": el["i"], "tag": el["tag"], "role": el.get("role"), "name": el.get("name"),
                "visible": el.get("visible", True), "disabled": el.get("disabled", False),
                "cible": {"methode": cible[0], "url": cible[1], "source": cible[2]} if cible else None,
                "statut": statut, "erreur": err, "verdict": verdict,
                "invisible_agent": invisible_agent(el),
                "gestionnaire": _a_un_gestionnaire(el),
                "attrs": {k: v for k, v in (el.get("attrs") or {}).items()
                          if k.startswith(("hx-", "x-on:", "@", "on", "href", "action", "role", "aria-"))},
            })
            if el.get("tag") == "a" and cible and cible[2] == "href" and _meme_origine(cible[1], base):
                lien = cible[1].split("#", 1)[0]
                if not EXCLUS.search(lien):
                    entree["liens"].append(lien)
    except Exception as e:  # noqa: BLE001 — la page est injoignable : c'est un resultat
        entree["erreur"] = type(e).__name__
    finally:
        page.remove_listener("response", _on_response)
    entree["reseau"] = reseau[:80]
    entree["resume"] = resumer(entree["elements"])
    return entree


async def recenser_surface(spec: dict, max_pages: int = MAX_PAGES) -> dict:
    base = spec["base"].rstrip("/")
    out = {"surface": spec["surface"], "base": base, "socket": _etat_socket(base),
           "joignable": _joignable(base), "login": None, "pages": [], "resume": {}}
    if out["socket"] != "accepte":
        out["resume"] = {"injoignable": out["socket"]}
        return out
    from nokido_agent.tools.forge_playwright_browser import PlaywrightBrowser

    async with PlaywrightBrowser(headed=False) as br:
        page = br.page
        await page.add_init_script(INIT_JS)
        if spec.get("login") == "form":
            out["login"] = await _login_form(page, base)
        cache: dict = {}
        vus, file = set(), _graines(spec, base)
        while file and len(out["pages"]) < max_pages:
            url = file.pop(0)
            if url in vus:
                continue
            vus.add(url)
            entree = await _page_census(page, url, base, cache)
            out["pages"].append(entree)
            for lien in entree.get("liens", []):
                if lien not in vus and lien not in file:
                    file.append(lien)
        out["pages_non_visitees"] = len(file)
    uniques = pages_uniques(out["pages"])
    total = resumer([e for p in uniques for e in p["elements"]])
    total["pages"] = len(uniques)
    total["pages_doublons"] = len(out["pages"]) - len(uniques)
    out["resume"] = total
    return out


# --------------------------------------------------- mode SANS navigateur
# Mesure 2026-08-26 : depuis un run_job (compte sandbox, session 0) firefox.exe et
# node.exe apparaissent mais `launch_persistent_context` expire a 180 s — le driver
# n'obtient jamais la main. Le mode navigateur est donc un mode SESSION OWNER. Ce mode
# statique lit le HTML rendu par le serveur (web_hub = HTMX, rendu cote serveur) et
# applique le MEME classifieur. Ce qu'il ne voit pas, il le DIT : ecouteurs poses par
# JS, visibilite calculee, arbre a11y — `mode: statique` dans le rapport.
class _Extracteur(__import__("html.parser").parser.HTMLParser):
    TAGS = {"a", "button", "input", "select", "textarea", "summary"}
    TAGS_TEXTE = {"a", "button", "summary", "label"}
    CONTENEURS = {"html", "body", "main", "header", "footer", "nav", "section", "article", "aside", "form"}
    ACTIONS = ("hx-get", "hx-post", "hx-put", "hx-delete", "hx-patch", "x-on:", "@", "onclick", "onsubmit")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements: list = []
        self._pile: list = []
        self._formulaires: list = []
        self._labels: dict = {}
        self._label_courant = None
        self.titre = ""
        self._dans_titre = False

    def _attrs(self, attrs):
        return {k.lower(): (v or "") for k, v in attrs}

    def handle_starttag(self, tag, attrs):
        a = self._attrs(attrs)
        tag = tag.lower()
        if tag == "title":
            self._dans_titre = True
        if tag == "form":
            self._formulaires.append((a.get("action", ""), (a.get("method") or "get").lower()))
        if tag == "label":
            self._label_courant = {"for": a.get("for"), "texte": ""}
        # `hx-headers` / `hx-target` / `hx-swap` sur <body> ou <main> configurent htmx,
        # ils n'agissent pas : mesure 2026-08-26, 7 « invisibles » qui etaient des
        # conteneurs. Seuls les attributs d'ACTION rendent un element actionnable.
        actionnable = tag in self.TAGS or (tag not in self.CONTENEURS and (
            any(k.startswith(self.ACTIONS) for k in a) or a.get("role") in (
                "button", "link", "checkbox", "tab", "menuitem", "switch")))
        if not actionnable:
            self._pile.append(None)
            return
        forme = self._formulaires[-1] if self._formulaires else None
        el = {
            "i": len(self.elements), "tag": tag,
            "input_type": (a.get("type") or "text").lower() if tag == "input" else None,
            "role": a.get("role") or {"a": "link", "button": "button", "input": "textbox", "select": "combobox",
                                      "textarea": "textbox", "summary": "button"}.get(tag),
            "name": (a.get("aria-label") or a.get("value") or a.get("alt") or a.get("title")
                     or a.get("placeholder") or "").strip(),
            "visible": "hidden" not in a and a.get("type") != "hidden",
            "attrs": {k: v[:200] for k, v in a.items() if k.startswith(
                ("hx-", "x-on:", "@", "data-", "on", "aria-", "href", "action", "method", "type", "name", "id",
                 "role", "disabled", "title", "placeholder"))},
            "listeners": 0,
            "form_action": forme[0] if forme and tag != "form" else None,
            "form_method": forme[1] if forme and tag != "form" else None,
            "disabled": "disabled" in a,
            "_id": a.get("id"),
        }
        if tag == "input" and el["input_type"] in ("submit", "button", "reset", "image"):
            el["role"] = "button"
        if tag == "input" and el["input_type"] == "checkbox":
            el["role"] = "checkbox"
        if tag == "input" and el["input_type"] == "hidden":
            el["role"] = None
        self.elements.append(el)
        self._pile.append(el if tag in self.TAGS_TEXTE or el["role"] in ("button", "link") else None)

    def handle_data(self, data):
        if self._dans_titre:
            self.titre += data
        if self._label_courant is not None:
            self._label_courant["texte"] += data
        for el in self._pile[-3:]:
            if el is not None and not el["name"]:
                el["_texte"] = (el.get("_texte", "") + data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._dans_titre = False
        if tag == "form" and self._formulaires:
            self._formulaires.pop()
        if tag == "label" and self._label_courant is not None:
            if self._label_courant["for"]:
                self._labels[self._label_courant["for"]] = self._label_courant["texte"].strip()
            self._label_courant = None
        if self._pile:
            el = self._pile.pop()
            if el is not None and not el["name"]:
                el["name"] = " ".join((el.pop("_texte", "") or "").split())[:90]

    def finir(self):
        for el in self.elements:
            if not el["name"] and el.get("_id") and el["_id"] in self._labels:
                el["name"] = self._labels[el["_id"]][:90]
            el.pop("_texte", None)
            el.pop("_id", None)
        return self.elements


def _session_statique(base: str, login: str | None) -> tuple:
    """Ouvreur urllib avec cookies ; login web_hub par le formulaire (jeton du coffre)."""
    import http.cookiejar
    import urllib.parse
    import urllib.request

    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    etat = None
    if login == "form":
        try:
            from app.web_hub.auth import AuthConfig

            cfg = AuthConfig.from_env()
            if not getattr(cfg, "enabled", False):
                etat = "inutile"
            elif not getattr(cfg, "admin_token", ""):
                etat = "absent"
            else:
                # Sans `Accept: text/html` la route rend un JSON 200 SUR /auth/login (mode
                # API) : juger le login a l'URL finale le disait « echec » alors que le
                # cookie etait pose (mesure 2026-08-26). On juge a l'EFFET : un GET /
                # qui ne rend plus 401.
                req = urllib.request.Request(
                    base + "/auth/login",
                    data=urllib.parse.urlencode({"admin_token": cfg.admin_token, "redirect_to": "/"}).encode(),
                    headers={"Accept": "text/html"})
                op.open(req, timeout=8)
                statut, _, _ = _get_statique(op, base + "/")
                etat = "ok" if statut == 200 else "echec (GET / -> %s)" % statut
        except Exception as e:  # noqa: BLE001
            etat = "echec (%s)" % type(e).__name__
    return op, etat


def _graines(spec: dict, base: str) -> list:
    """Pages de depart. La racine de web_hub REDIRIGE vers un kit de design sans lien
    (mesure 2026-08-26 : 1 page, 0 element) — un crawl par liens y meurt. La barre
    laterale est la vraie carte de navigation : on lit ses href, plus les graines
    declarees."""
    graines = [base + "/"] + [base + p for p in spec.get("graines", [])]
    sources = {
        "web_hub": [ROOT / "app" / "web_hub" / "app.py", ROOT / "app" / "web_hub" / "wired_routes.py"],
        "deno_web_hub": [ROOT / "proxy_deno" / "web_hub" / "main.ts"],
    }.get(spec["surface"], [])
    for f in sources:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # source illisible : les graines declarees suffisent, le compte de pages le montre
        if f.suffix == ".py":
            chemins = re.findall(r"""@(?:app|router)\.get\(\s*["'](/[^"'{}]*)["']""", src)
        else:
            chemins = re.findall(r"""["'](/[a-z][a-z0-9_\-/]{1,40})["']""", src)
        for h in chemins:
            if not EXCLUS.search(h) and h not in ("/auth/login",):
                graines.append(base + h)
    vus, out = set(), []
    for g in graines:
        if g not in vus:
            vus.add(g)
            out.append(g)
    return out


def _get_statique(op, url: str) -> tuple:
    """(statut, corps|None, url_finale) — trois etats, jamais un 200 invente."""
    import urllib.error

    try:
        r = op.open(url, timeout=8)
        ctype = r.headers.get("content-type", "")
        corps = r.read(1_500_000).decode("utf-8", errors="replace") if "html" in ctype or "text" in ctype else None
        return r.status, corps, r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, None, url
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__, url


def recenser_surface_statique(spec: dict, max_pages: int = MAX_PAGES) -> dict:
    base = spec["base"].rstrip("/")
    out = {"surface": spec["surface"], "base": base, "mode": "statique", "socket": _etat_socket(base),
           "joignable": _joignable(base), "login": None, "pages": [], "resume": {}}
    if out["socket"] != "accepte":
        out["resume"] = {"injoignable": out["socket"]}
        return out
    op, out["login"] = _session_statique(base, spec.get("login"))
    cache: dict = {}
    vus, file = set(), _graines(spec, base)
    while file and len(out["pages"]) < max_pages:
        url = file.pop(0)
        if url in vus:
            continue
        vus.add(url)
        statut, corps, finale = _get_statique(op, url)
        entree = {"url": url, "titre": "", "chargement": statut, "elements": [], "reseau": [],
                  "aria_chars": None, "liens": [], "redirige_vers": finale if finale != url else None}
        if corps is None or not isinstance(corps, str):
            entree["erreur"] = corps if isinstance(corps, str) else "sans corps HTML"
            entree["resume"] = resumer([])
            out["pages"].append(entree)
            continue
        ex = _Extracteur()
        try:
            ex.feed(corps)
        except Exception as e:  # noqa: BLE001 — HTML cassé : on le dit
            entree["erreur"] = "html illisible (%s)" % type(e).__name__
        entree["titre"] = " ".join(ex.titre.split())[:120]
        for el in ex.finir():
            cible = _cible_de(el, finale)
            statut_c, err = ("non_sonde", None)
            if cible is not None and not _meme_origine(cible[1], base):
                statut_c = "externe"
            elif cible is not None and DANGEREUX.search(urlparse(cible[1]).path):
                statut_c = "prudence"
            elif cible is not None:
                cle = cible[1].split("#", 1)[0]
                if cle not in cache:
                    s, _, _ = _get_statique(op, cle)
                    cache[cle] = (s, None if s is not None else "injoignable")
                statut_c, err = cache[cle]
            verdict = classer(el, statut_c, finale)
            entree["elements"].append({
                "i": el["i"], "tag": el["tag"], "role": el.get("role"), "name": el.get("name"),
                "visible": el.get("visible", True), "disabled": el.get("disabled", False),
                "cible": {"methode": cible[0], "url": cible[1], "source": cible[2]} if cible else None,
                "statut": statut_c, "erreur": err, "verdict": verdict,
                "invisible_agent": invisible_agent(el), "gestionnaire": _a_un_gestionnaire(el),
                "attrs": {k: v for k, v in (el.get("attrs") or {}).items()
                          if k.startswith(("hx-", "x-on:", "@", "on", "href", "action", "role", "aria-"))},
            })
            if el.get("tag") == "a" and cible and cible[2] == "href" and _meme_origine(cible[1], base):
                lien = cible[1].split("#", 1)[0]
                if not EXCLUS.search(lien) and lien not in vus and lien not in file:
                    file.append(lien)
        entree["resume"] = resumer(entree["elements"])
        out["pages"].append(entree)
    out["pages_non_visitees"] = len(file)
    uniques = pages_uniques(out["pages"])
    total = resumer([e for p in uniques for e in p["elements"]])
    total["pages"] = len(uniques)
    total["pages_doublons"] = len(out["pages"]) - len(uniques)
    out["resume"] = total
    return out


def _contrat(surfaces: list) -> dict:
    """Squelette de contrat par surface : pages -> actions mesurees. A CURER par
    l'owner (etats attendus, dependances), pas a prendre pour un contrat signe."""
    contrat = {"genere_le": datetime.now().isoformat(timespec="seconds"), "surfaces": {}}
    for s in surfaces:
        pages = {}
        for p in s.get("pages", []):
            actions = [
                {"nom": e["name"], "role": e["role"], "cible": e["cible"], "verdict": e["verdict"]}
                for e in p["elements"] if e["verdict"] not in ("CONTROLE", "VISUEL") and e.get("visible", True)
            ]
            pages[p["url"]] = {"titre": p.get("titre"), "actions": actions,
                               "reseau_chargement": [r["url"] for r in p.get("reseau", [])][:20]}
        contrat["surfaces"][s["surface"]] = {"base": s["base"], "socket": s.get("socket"),
                                             "login": s.get("login"), "pages": pages}
    return contrat


def _rapport(surfaces: list, manifeste: dict, date: str) -> str:
    modes = sorted({s.get("mode", "navigateur") for s in surfaces})
    L = ["# Recensement du cablage des interfaces — %s (mode : %s)" % (date, ", ".join(modes)), ""]
    if "statique" in modes:
        L += ["RESERVE du mode statique (HTML serveur, sans navigateur) : un element VISUEL peut etre "
              "cable par un ecouteur JS pose a l'execution, et un JS_OPAQUE n'est pas sonde. Ces deux "
              "classes se tranchent en mode navigateur (session owner : "
              "`LAFORGE_PYTHON tools/forge_ui_nervous_census.py`).", ""]
    L += [
         "Verdicts : CABLE (route vivante) · CABLE_AUTH (401/403) · MORT (404/5xx/injoignable) · "
         "INCERTAIN (404 au GET sur une route non-GET : la sonde ne peut pas trancher) · "
         "EXTERNE (hors origine, non sonde) · PRUDENCE (cible a effet — logout/reset/kill… — jamais sondee) · "
         "JS_OPAQUE (gestionnaire sans cible lisible : sonde d'execution a faire) · VISUEL (decor) · "
         "CONTROLE (champ). `invisible_agent` = ni nom ni role accessible.", ""]
    L.append("| surface | socket | login | pages (doublons) | total | CABLE | CABLE_AUTH | MORT | INCERTAIN | EXTERNE | PRUDENCE | JS_OPAQUE | VISUEL | CONTROLE | invisible_agent | manifeste dit |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    correspondance = {"web_hub": "dashboard", "graph": "graph", "netcfg_ui": "netcfg"}
    for s in surfaces:
        r = s.get("resume", {})
        dit = manifeste.get(correspondance.get(s["surface"], s["surface"]), "—")
        L.append("| %s | %s | %s | %s (%s) | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            s["surface"], s.get("socket"), s.get("login") or "—", r.get("pages", 0), r.get("pages_doublons", 0),
            r.get("total", 0), r.get("CABLE", 0), r.get("CABLE_AUTH", 0), r.get("MORT", 0), r.get("INCERTAIN", 0),
            r.get("EXTERNE", 0), r.get("PRUDENCE", 0), r.get("JS_OPAQUE", 0), r.get("VISUEL", 0),
            r.get("CONTROLE", 0), r.get("invisible_agent", 0), dit))
    for s in surfaces:
        pages = [p for p in s.get("pages", []) if not p.get("doublon_de")]
        morts = [(p["url"], e) for p in pages for e in p["elements"] if e["verdict"] == "MORT"]
        opaques = [(p["url"], e) for p in pages for e in p["elements"] if e["verdict"] == "JS_OPAQUE"]
        invisibles = [(p["url"], e) for p in pages for e in p["elements"]
                      if e["invisible_agent"] and e.get("visible", True) and e["verdict"] != "CONTROLE"]
        if not (morts or opaques or invisibles):
            continue
        L += ["", "## %s (%s)" % (s["surface"], s["base"])]
        if morts:
            L.append("### MORT — le bouton pointe dans le vide (%d)" % len(morts))
            for url, e in morts[:25]:
                L.append("- `%s` — %s « %s » -> %s %s (%s)" % (
                    url.replace(s["base"], ""), e["role"], e["name"], e["cible"]["methode"],
                    e["cible"]["url"].replace(s["base"], ""), e["statut"] if e["statut"] is not None else e["erreur"]))
        if opaques:
            L.append("### JS_OPAQUE — gestionnaire sans cible lisible (%d) : phase 2 = sonde d'execution" % len(opaques))
            for url, e in opaques[:25]:
                L.append("- `%s` — %s « %s » attrs=%s" % (url.replace(s["base"], ""), e["role"], e["name"],
                                                          ",".join(sorted(e["attrs"].keys()))[:80]))
        if invisibles:
            L.append("### invisible_agent — a l'ecran mais hors de l'arbre accessible (%d)" % len(invisibles))
            for url, e in invisibles[:25]:
                L.append("- `%s` — <%s> role=%s nom=« %s » verdict=%s" % (
                    url.replace(s["base"], ""), e["tag"], e["role"], e["name"], e["verdict"]))
    return "\n".join(L) + "\n"


# ------------------------------------------------------ captures externes (Chrome)
def recenser_depuis_capture(spec: dict, captures: list) -> dict:
    """Pages capturees par un navigateur EXTERNE (Chrome MCP dans la session owner, le
    2026-08-26) : chaque capture = {url, titre, rows} ou `rows` a la forme de
    ELEMENTS_JS enrichie d'un `statut` deja sonde DANS la page (fetch same-origin,
    credentials inclus ; 'externe' / 'prudence' / entier / None) et d'un `fn`
    optionnel = fonction globale dont la source a livre la route (sans l'executer).
    Le classifieur et le rapport sont les memes : seule la source des lignes change."""
    base = spec["base"].rstrip("/")
    out = {"surface": spec["surface"], "base": base, "mode": "navigateur-externe",
           "socket": _etat_socket(base), "joignable": _joignable(base), "login": spec.get("login_etat"),
           "pages": [], "resume": {}}
    for cap in captures or []:
        url = cap.get("url") or base + "/"
        entree = {"url": url, "titre": (cap.get("titre") or "")[:120], "chargement": cap.get("chargement", 200),
                  "elements": [], "reseau": cap.get("reseau", [])[:80], "aria_chars": cap.get("aria_chars"), "liens": []}
        for el in cap.get("rows", []):
            cible = el.get("cible")
            if isinstance(cible, (list, tuple)) and len(cible) == 3:
                cible = {"methode": cible[0], "url": cible[1], "source": cible[2]}
            statut = el.get("statut", "non_sonde")
            verdict = classer(el, statut, url,
                              cible=(cible["methode"], cible["url"], cible["source"]) if cible else None)
            entree["elements"].append({
                "i": el.get("i"), "tag": el.get("tag"), "role": el.get("role"), "name": el.get("name"),
                "visible": el.get("visible", True), "disabled": el.get("disabled", False),
                "cible": cible, "statut": statut, "erreur": None, "verdict": verdict,
                "invisible_agent": invisible_agent(el), "gestionnaire": _a_un_gestionnaire(el),
                "fonction": el.get("fn"),
                "attrs": {k: v for k, v in (el.get("attrs") or {}).items()
                          if k.startswith(("hx-", "x-on:", "@", "on", "href", "action", "role", "aria-"))},
            })
        entree["resume"] = resumer(entree["elements"])
        out["pages"].append(entree)
    uniques = pages_uniques(out["pages"])
    total = resumer([e for p in uniques for e in p["elements"]])
    total["pages"] = len(uniques)
    total["pages_doublons"] = len(out["pages"]) - len(uniques)
    out["resume"] = total
    return out


def _session_interactive() -> bool:
    """Un navigateur pilote exige une session utilisateur. Sous un compte de service
    (session 0) `SESSIONNAME` est absent ou vaut `Services` : Firefox demarre mais le
    driver n'obtient jamais la main (mesure 2026-08-26, 180 s perdus par surface)."""
    if os.environ.get("NOKIDO_UI_CENSUS_NAVIGATEUR") == "1":
        return True
    nom = os.environ.get("SESSIONNAME", "")
    return bool(nom) and nom.lower() != "services" and not os.environ.get("USERNAME", "").lower().startswith("laforgesbx")


def _stdout_utf8() -> None:
    """La console owner est en cp1252 : un emoji du rapport y tue le process a la
    DERNIERE ligne, apres 88 s de travail deja ecrit sur disque. Mesure 2026-08-29 :
    UnicodeEncodeError sur '\\U0001f4ac' — le recensement etait complet, illisible.
    On force utf-8 sur la sortie ; si le flux ne se reconfigure pas (redirection,
    flux deja ferme), on continue : le rapport est sur disque, l'impression n'est
    qu'un confort."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError) as ex:
            print("[census] sortie non reconfigurable (%s) : le rapport reste sur "
                  "disque" % type(ex).__name__, file=sys.stderr)


def main(argv=None) -> int:
    _stdout_utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument("--surfaces", default="", help="noms separes par des virgules (defaut : toutes)")
    ap.add_argument("--max-pages", type=int, default=MAX_PAGES)
    ap.add_argument("--json", action="store_true", help="imprime la synthese JSON")
    ap.add_argument("--sans-navigateur", action="store_true",
                    help="HTML serveur + html.parser (depuis le sandbox) ; le mode navigateur exige la session owner")
    ap.add_argument("--capture", default="",
                    help="JSON de captures externes {surface: [{url,titre,rows}]} (Chrome MCP) a ingerer")
    a = ap.parse_args(argv)
    if a.capture:
        captures = json.loads(Path(a.capture).read_text(encoding="utf-8"))
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        date = datetime.now().strftime("%Y%m%d_%H%M")
        resultats = []
        for spec in SURFACES_DEFAUT:
            if spec["surface"] in captures:
                res = recenser_depuis_capture(spec, captures[spec["surface"]])
                resultats.append(res)
                (OUT_DIR / ("nervous_%s_navigateur_%s.json" % (spec["surface"], date))).write_text(
                    json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        rapport = _rapport(resultats, _manifest_etats(), date)
        (OUT_DIR / ("nervous_report_navigateur_%s.md" % date)).write_text(rapport, encoding="utf-8")
        print(rapport)
        return 0
    if not a.sans_navigateur and not _session_interactive():
        print("[census] session non interactive : mode SANS navigateur (le driver Firefox n'obtient pas la main en session 0)", flush=True)
        a.sans_navigateur = True
    voulues = {s.strip() for s in a.surfaces.split(",") if s.strip()}
    specs = [s for s in SURFACES_DEFAUT if not voulues or s["surface"] in voulues]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y%m%d_%H%M")
    manifeste = _manifest_etats()
    resultats = []
    t0 = time.time()
    for spec in specs:
        t1 = time.time()
        try:
            if a.sans_navigateur:
                res = recenser_surface_statique(spec, a.max_pages)
            else:
                res = asyncio.run(recenser_surface(spec, a.max_pages))
        except Exception as e:  # noqa: BLE001 — une surface qui casse le navigateur est un resultat
            res = {"surface": spec["surface"], "base": spec["base"], "socket": _etat_socket(spec["base"]),
                   "pages": [], "resume": {"erreur": "%s: %s" % (type(e).__name__, str(e)[:160])}}
        res["duree_s"] = round(time.time() - t1, 1)
        resultats.append(res)
        (OUT_DIR / ("nervous_%s_%s.json" % (spec["surface"], date))).write_text(
            json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print("[%s] socket=%s login=%s resume=%s (%.1fs)" % (
            spec["surface"], res.get("socket"), res.get("login"), res.get("resume"), res["duree_s"]), flush=True)
    rapport = _rapport(resultats, manifeste, date)
    (OUT_DIR / ("nervous_report_%s.md" % date)).write_text(rapport, encoding="utf-8")
    (OUT_DIR / "ui_contract_generated.json").write_text(
        json.dumps(_contrat(resultats), ensure_ascii=False, indent=1), encoding="utf-8")
    synthese = {"date": date, "duree_s": round(time.time() - t0, 1), "manifeste": manifeste,
                "surfaces": {r["surface"]: r.get("resume") for r in resultats},
                "rapport": str(OUT_DIR / ("nervous_report_%s.md" % date))}
    print(json.dumps(synthese, ensure_ascii=False, indent=1) if a.json else rapport)
    return 0


if __name__ == "__main__":
    sys.exit(main())
