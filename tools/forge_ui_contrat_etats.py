#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""tools/forge_ui_contrat_etats.py — TEMOIN : le Hub distingue-t-il LOADING, DATA et ERROR ?

__FORGE_COLOR__ declare plus bas (le census lit la premiere ligne ancree, pas la docstring).

POURQUOI CE MODULE EXISTE (mesures du 2026-09-11, sur le bundle SERVI).
Les six `fetch` de la page Hub ecrasent l'echec dans la valeur du vide :

    .then(r => r.ok ? r.json() : [])   .catch(() => setMem([]))

Un HTTP 500 et une liste legitimement vide produisent alors le MEME ecran. Le defaut
a DEUX formes, et elles ne se refutent pas par le meme test :

    persona / provenance / federation : l'etat initial est `useState([])`, donc
        LOADING == DATA_VIDE == ERROR — les trois rendent « Memoire vide ».
    overview (Accueil, Cap)           : l'etat initial est `useState(null)` et
        l'echec y RETOURNE, donc ERROR == LOADING — l'ecran annonce
        « Chargement de la roadmap active… » pour un chargement qui ne reprendra
        jamais. Ici ERROR et DATA_VIDE different DEJA : un test qui ne comparerait
        que ces deux-la passerait au vert sans rien prouver.

D'ou le choix de mesurer les TROIS etats, sur DEUX cibles, plutot qu'un couple.

ANTI-DUP. `forge_ui_campaign` juge la surface (33 pages, clics, captures) et
`forge_ui_temoin` rend lisible ce qu'elle a etabli ; aucun des deux ne FORCE une
reponse — ils observent le backend tel qu'il est. Ce module ne juge qu'une seule
propriete et il est le seul a intercepter le transport (`page.route`) pour fabriquer
les trois etats a volonte. Il reutilise la methode de login prouvee par la campagne
(formulaire `/auth/login`, `input[name=admin_token]`), pas un jeton porte en en-tete :
le middleware attend un JWT ou le cookie de session, et un `Bearer <jeton brut>` rend
401 — c'est-a-dire que la sonde mesurerait sa propre erreur.

NAVIGATEUR. Canaux SYSTEME (`chrome`, `msedge`), jamais le magasin ms-playwright :
mesure du 2026-09-11 — le magasin ne porte aucun chromium, et son firefox-1532 (qui
est pourtant la revision exacte reclamee par la lib) se lance puis gele sur
`RenderCompositorSWGL failed mapping default framebuffer` sous un compte sans session
graphique. Lancement NU (`launch`), jamais `launch_persistent_context`, qui pend
180 s sans rien nommer.

TROIS ETATS POUR LE VERDICT, comme pour le sujet :
    DISTINCT     les etats compares rendent des ecrans differents — le contrat tient
    INDISTINCT   deux etats rendent le MEME ecran — le contrat est rompu
    NON_JUGE     navigateur, service ou login indisponible — on le DIT, on ne conclut pas

USAGE (le chemin est relatif au depot Nokido, pas au superrepo) :
    run action=run_job script=tools/forge_ui_contrat_etats.py
    run action=shell network=true code="<python> <depot>/tools/forge_ui_contrat_etats.py"

Codes de retour : 0 = DISTINCT · 1 = INDISTINCT · 2 = NON_JUGE · 3 = INSTRUMENT_BRUYANT
"""
from __future__ import annotations

__FORGE_COLOR__ = "qualite/gate : temoin du contrat d etats LOADING DATA ERROR de l UI"

import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BASE = os.environ.get("NOKIDO_HUB_WEB", "http://127.0.0.1:7400")
SORTIE = ROOT / "sandbox" / "ui_contrat_etats"

# Delai laisse au rendu apres le clic de navigation. Les `fetch` partent dans un
# useEffect, donc APRES le montage : `domcontentloaded` ne les attend pas.
DELAI_RENDU_MS = 1500

# (vue, libelle du bouton de nav, motif d'interception, payload VIDE mais LEGITIME)
# Le payload vide est FABRIQUE, jamais emprunte au backend : si `/api/hub/persona`
# rendait un jour une liste non vide, « ERROR != DATA » deviendrait vrai sans que le
# contrat soit repare — un vert par accident de contenu.
CIBLES = [
    ("persona", "Mémoire persona", "**/api/hub/persona*", "[]"),
    ("accueil", "Accueil", "**/api/hub/overview*", "{}"),
]

MODES = ("LOADING", "DATA_REEL", "DATA_VIDE", "DATA_VIDE_BIS", "ERROR")

# Les modes dont depend le VERDICT. `DATA_REEL` n'en fait pas partie : il documente
# ce que le backend rend aujourd'hui, une valeur qui bouge et qui ne doit jamais
# decider. Le distinguer evite qu'un backend lent ou vide fasse basculer le jugement.
MODES_JUGES = ("LOADING", "DATA_VIDE", "DATA_VIDE_BIS", "ERROR")

# Au-dela, on ne dit pas « pas de donnee » mais « pas observe en N s ».
ATTENTE_REPONSE_REELLE_S = 15

JS_EMPREINTE = """() => {
  const nav = document.querySelector('nav');
  const navTxt = nav ? nav.innerText : '';
  let t = document.body ? document.body.innerText : '';
  if (navTxt) { t = t.split(navTxt).join(''); }
  return t.replace(/\\s+/g, ' ').trim();
}"""


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode("utf-8", "replace")).hexdigest()[:16]


def _jeton() -> tuple:
    """Rend (jeton, provenance). Le jeton n'est JAMAIS affiche ni journalise —
    seule sa provenance et sa longueur le sont."""
    try:
        from forge_secrets import get_secret  # type: ignore
        t = get_secret("LAFORGE_ADMIN_TOKEN")
        if t:
            return t, "coffre:LAFORGE_ADMIN_TOKEN"
    except Exception as exc:                                    # pragma: no cover
        # Surtout pas muet : un coffre qui leve et un coffre qui rend vide
        # amenent au meme repli, et seule cette trace les distingue.
        print("[temoin] coffre illisible (%s: %s) — repli sur l'environnement"
              % (type(exc).__name__, str(exc)[:120]))
    t = os.environ.get("LAFORGE_ADMIN_TOKEN")
    if t:
        return t, "env:LAFORGE_ADMIN_TOKEN"
    return None, "INTROUVABLE"


def _ouvrir_navigateur(p):
    """Rend (navigateur, canal, essais_rates). Leve si aucun canal ne demarre."""
    rates = []
    for canal in ("chrome", "msedge"):
        try:
            nav = p.chromium.launch(headless=True, channel=canal, timeout=25000)
            return nav, canal, rates
        except Exception as exc:
            rates.append("%s: %s" % (canal, str(exc).strip().splitlines()[0][:160]))
    raise RuntimeError("aucun canal navigateur lancable — " + " | ".join(rates))


def _connecter(contexte, jeton: str) -> tuple:
    """Login par le FORMULAIRE. Rend (ok, detail)."""
    page = contexte.new_page()
    try:
        page.goto(BASE + "/auth/login", wait_until="domcontentloaded", timeout=20000)
        champ = page.locator("input[name=admin_token]")
        if champ.count() == 0:
            return False, "formulaire /auth/login sans input[name=admin_token]"
        champ.first.fill(jeton)
        champ.first.press("Enter")
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        rep = page.context.request.get(BASE + "/hub")
        return (rep.status == 200), "GET /hub apres login -> HTTP %d" % rep.status
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, str(exc)[:200])
    finally:
        try:
            page.close()
        except Exception:  # noqa: BLE001 — muet-ok : page deja fermee ; sans effet sur le verdict du login
            pass


def _capturer(contexte, cible, mode: str) -> dict:
    """UNE capture = UNE page neuve, pour qu'aucun etat React ne survive d'un cas
    a l'autre. Les exceptions de rendu passent par `pageerror`, jamais par la
    console : une exception React ne fait pas de `console.error`."""
    _vue, libelle, motif, vide = cible
    page = contexte.new_page()
    erreurs, api = [], []
    page.on("pageerror", lambda e: erreurs.append(str(e)[:300]))
    page.on(
        "response",
        lambda r: api.append([r.url.split("/api/hub/")[-1], r.status])
        if "/api/hub/" in r.url else None,
    )

    if mode == "LOADING":
        # Handler qui n'agit pas : la requete reste pendante, l'ecran reste dans son
        # etat initial. C'est l'etat que l'utilisateur voit avant toute reponse.
        page.route(motif, lambda route: None)
    elif mode == "ERROR":
        page.route(motif, lambda route: route.fulfill(
            status=500, content_type="application/json",
            body='{"detail": "panne simulee par le temoin"}'))
    elif mode in ("DATA_VIDE", "DATA_VIDE_BIS"):
        page.route(motif, lambda route: route.fulfill(
            status=200, content_type="application/json", body=vide))
    # DATA_REEL : aucune interception.

    detail = ""
    note = ""
    texte = ""
    attente_s = None
    try:
        page.goto(BASE + "/hub", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector('button:has-text("%s")' % libelle, timeout=20000)
        page.click('button:has-text("%s")' % libelle)

        if mode == "DATA_REEL":
            # Le backend reel peut etre LENT. Mesure du 2026-09-11 :
            # `/api/hub/overview` n'avait pas repondu au bout de 1,5 s, l'ecran
            # restait en LOADING, et la capture s'appelait pourtant « donnee
            # reelle » -- l'instrument mesurait sa propre impatience. On attend
            # donc la REPONSE, observee par le listener installe des la creation
            # de la page (pas un `wait_for_response` pose apres coup, qui raterait
            # une reponse arrivee entre-temps).
            marqueur = motif.replace("**", "").rstrip("*").rsplit("/", 1)[-1]
            t0 = time.time()
            while time.time() - t0 < ATTENTE_REPONSE_REELLE_S:
                if any(str(c[0]).startswith(marqueur) for c in api):
                    attente_s = round(time.time() - t0, 2)
                    break
                page.wait_for_timeout(200)
            if attente_s is None:
                note = ("NON_OBSERVE : aucune reponse de %s en %d s — cette capture "
                        "ne dit pas ce que le backend rend, seulement qu'il n'a pas "
                        "repondu dans la fenetre" % (marqueur, ATTENTE_REPONSE_REELLE_S))

        page.wait_for_timeout(DELAI_RENDU_MS)
        texte = page.evaluate(JS_EMPREINTE)
    except Exception as exc:
        detail = "%s: %s" % (type(exc).__name__, str(exc)[:200])
    finally:
        # Les routes laissees pendantes (mode LOADING) sont annulees a la fermeture
        # et Playwright remonte alors un CancelledError dans sa boucle asyncio. Ce
        # bruit n'est pas un echec du temoin, mais un temoin qui crache des
        # tracebacks se fait lire comme casse : on les desamorce explicitement.
        try:
            page.unroute_all(behavior="ignoreErrors")
        except Exception:  # noqa: BLE001 — muet-ok : desamorcage de confort, sans effet sur la capture
            pass
        try:
            page.close()
        except Exception:  # noqa: BLE001 — muet-ok : le texte est deja extrait, aucune empreinte ne bouge
            pass

    return {
        "mode": mode,
        "sha": _sha(texte),
        "longueur": len(texte),
        "extrait": texte[:220],
        "pageerror": erreurs,
        "api_observee": api,
        "attente_reponse_s": attente_s,
        "note": note,
        "incident": detail,
    }


def juger(captures: dict) -> dict:
    """Fonction PURE : de cinq empreintes vers un verdict. Testable sans navigateur.

    Deux proprietes, parce que le defaut a deux formes. Une seule ne suffit pas :
    sur overview, ERROR et DATA_VIDE different DEJA.
    """
    c = {m: captures.get(m, {}) for m in MODES}
    # Une capture absente n'est pas une capture reussie : sans ce controle, le
    # premier acces a `sha` leverait un KeyError et l'appelant lirait un plantage
    # la ou la reponse honnete est « je n'ai pas pu juger ».
    manquants = [m for m in MODES_JUGES if "sha" not in c[m]]
    if manquants:
        return {"verdict": "NON_JUGE", "motif": "captures absentes: " + ", ".join(manquants)}
    incidents = [m for m in MODES_JUGES if c[m].get("incident")]
    if incidents:
        return {"verdict": "NON_JUGE", "motif": "captures en incident: " + ", ".join(incidents)}

    if c["DATA_VIDE"]["sha"] != c["DATA_VIDE_BIS"]["sha"]:
        # Deux captures du MEME etat qui different : l'ecran porte du bruit
        # (horloge, animation). Tout ecart mesure ensuite serait ininterpretable —
        # on ne rend pas un verdict avec un instrument qui bouge.
        return {"verdict": "INSTRUMENT_BRUYANT",
                "motif": "deux captures de DATA_VIDE different (%s != %s)"
                         % (c["DATA_VIDE"]["sha"], c["DATA_VIDE_BIS"]["sha"])}

    erreur_vs_vide = c["ERROR"]["sha"] != c["DATA_VIDE"]["sha"]
    erreur_vs_chargement = c["ERROR"]["sha"] != c["LOADING"]["sha"]
    return {
        "verdict": "DISTINCT" if (erreur_vs_vide and erreur_vs_chargement) else "INDISTINCT",
        "ERROR_distinct_de_DATA_VIDE": erreur_vs_vide,
        "ERROR_distinct_de_LOADING": erreur_vs_chargement,
        "sha": {m: c[m]["sha"] for m in MODES},
    }


def main(argv=None) -> int:
    debut = time.time()
    rapport = {
        "base": BASE,
        "cibles": len(CIBLES),
        "captures_attendues": len(CIBLES) * len(MODES),
        "captures_faites": 0,
        "navigateur": {"canal": None, "essais_rates": []},
        "login": {"provenance_jeton": None, "ok": None, "detail": None},
        "resultats": {},
        "verdict": "NON_JUGE",
    }

    jeton, provenance = _jeton()
    rapport["login"]["provenance_jeton"] = provenance
    rapport["login"]["longueur_jeton"] = len(jeton) if jeton else 0
    if not jeton:
        rapport["login"]["detail"] = "aucun LAFORGE_ADMIN_TOKEN (coffre ni environnement)"
        return _rendre(rapport, debut, 2)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        rapport["navigateur"]["essais_rates"].append("import playwright: %s" % exc)
        return _rendre(rapport, debut, 2)

    with sync_playwright() as p:
        try:
            nav, canal, rates = _ouvrir_navigateur(p)
        except Exception as exc:
            rapport["navigateur"]["essais_rates"].append(str(exc)[:400])
            return _rendre(rapport, debut, 2)
        rapport["navigateur"]["canal"] = canal
        rapport["navigateur"]["essais_rates"] = rates
        rapport["navigateur"]["version"] = nav.version

        try:
            contexte = nav.new_context(ignore_https_errors=True)
            ok, detail = _connecter(contexte, jeton)
            rapport["login"]["ok"] = ok
            rapport["login"]["detail"] = detail
            if not ok:
                return _rendre(rapport, debut, 2)

            for cible in CIBLES:
                vue = cible[0]
                captures = {}
                for mode in MODES:
                    captures[mode] = _capturer(contexte, cible, mode)
                    rapport["captures_faites"] += 1
                rapport["resultats"][vue] = {"captures": captures, "jugement": juger(captures)}
        finally:
            try:
                nav.close()
            except Exception:  # noqa: BLE001 — muet-ok : captures terminees, le rapport est constitue
                pass

    verdicts = [r["jugement"]["verdict"] for r in rapport["resultats"].values()]
    if not verdicts or "NON_JUGE" in verdicts:
        rapport["verdict"], code = "NON_JUGE", 2
    elif "INSTRUMENT_BRUYANT" in verdicts:
        rapport["verdict"], code = "INSTRUMENT_BRUYANT", 3
    elif "INDISTINCT" in verdicts:
        rapport["verdict"], code = "INDISTINCT", 1
    else:
        rapport["verdict"], code = "DISTINCT", 0
    return _rendre(rapport, debut, code)


def _rendre(rapport: dict, debut: float, code: int) -> int:
    rapport["duree_s"] = round(time.time() - debut, 1)
    try:
        SORTIE.mkdir(parents=True, exist_ok=True)
        (SORTIE / "report.json").write_text(
            json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        print("[temoin] rapport NON ecrit: %s" % exc)

    print("=== TEMOIN CONTRAT D ETATS UI (LOADING / DATA / ERROR) ===")
    print("base=%s  navigateur=%s  captures=%d/%d  duree=%ss"
          % (rapport["base"], rapport["navigateur"].get("canal"),
             rapport["captures_faites"], rapport["captures_attendues"],
             rapport["duree_s"]))
    if rapport["navigateur"]["essais_rates"]:
        for r in rapport["navigateur"]["essais_rates"]:
            print("  canal ecarte : %s" % r)
    print("login: %s (%s)" % (rapport["login"]["ok"], rapport["login"]["detail"]))
    for vue, res in rapport["resultats"].items():
        j = res["jugement"]
        print("  [%s] %s" % (vue, j["verdict"]))
        if "sha" in j:
            for mode in MODES:
                print("      %-14s %s  %s"
                      % (mode, j["sha"][mode], res["captures"][mode]["extrait"][:90]))
            print("      ERROR != DATA_VIDE : %s" % j["ERROR_distinct_de_DATA_VIDE"])
            print("      ERROR != LOADING   : %s" % j["ERROR_distinct_de_LOADING"])
        else:
            print("      motif: %s" % j.get("motif"))
    print("VERDICT: %s (rc=%d)" % (rapport["verdict"], code))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
