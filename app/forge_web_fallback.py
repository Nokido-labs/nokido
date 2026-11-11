"""
forge_web_fallback.py - Fallback SearXNG: engines generaux -> duckduckgo -> vide
Pas de LLM externe. Tout local.
"""

from __future__ import annotations
import asyncio, json, urllib.request, urllib.parse, logging, time
import os
import re
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger("Nokido.WebFallback")
SEARXNG_URL = "http://127.0.0.1:8080"
SEARXNG_TIMEOUT = 5


# UNE ERREUR N'EST PAS « AUCUN RESULTAT » (15/10). Mesure : `web_search` a repondu « Aucun
# resultat » alors que SearXNG etait ETEINT (connexion refusee), puis encore juste apres son
# reveil (ping OK, recherches vides) : l'appelant concluait a l'absence de resultats -- UNKNOWN
# lu comme NO. `_searxng_diag` rend (resultats, erreur) ; `web_search_diag` porte les erreurs ;
# les signatures historiques (`_searxng_sync`, `web_search_with_fallback`) sont gardees.
def _searxng_diag(query: str, max_results: int, engines: str = "", categories: str = "") -> tuple:
    """(resultats, erreur) : erreur = None si SearXNG a REPONDU (meme une liste vide)."""
    params: Dict = {"q": query, "format": "json"}
    if engines:
        params["engines"] = engines
    if categories:
        params["categories"] = categories
    url = SEARXNG_URL + "/search?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"User-Agent": "LaForge/1.0"}), timeout=SEARXNG_TIMEOUT
        ) as r:
            return [
                x for x in json.loads(r.read()).get("results", [])[:max_results] if x.get("title") or x.get("content")
            ], None
    except Exception as e:  # noqa: BLE001 - rendu comme erreur NOMMEE, jamais comme liste vide muette
        logger.warning(f"[searxng/{engines or 'default'}] {type(e).__name__}: {e}")
        return [], "%s/%s: %s" % (engines or "default", type(e).__name__, str(e)[:120])


def _searxng_sync(query: str, max_results: int, engines: str = "") -> List[Dict]:
    return _searxng_diag(query, max_results, engines)[0]


OLLAMA_WEB_SEARCH = "https://ollama.com/api/web_search"


def _cle_ollama() -> str:
    """OLLAMA_API_KEY du coffre (offre gratuite, owner 24/10) ; '' si absente ou coffre illisible."""
    try:
        from nokido_agent.app.forge_secrets import get_secret

        return get_secret("OLLAMA_API_KEY") or ""
    except Exception as e:  # noqa: BLE001 - coffre illisible : dit par l'appelant (pas de cle)
        logger.warning("[web] coffre illisible pour OLLAMA_API_KEY (%s)", type(e).__name__)
        return ""


def _pre_flight(query: str, provider: str = "ollama_cloud") -> tuple:
    """(ok, raison) du pare-feu semantique AVANT tout envoi cloud (regle d'or 4) ; illisible = refus."""
    try:
        from nokido_agent.app.forge_semantic_firewall import get_firewall

        res = get_firewall().pre_flight(query, provider=provider)
        return bool(getattr(res, "ok", False)), str(getattr(res, "reason", "") or "")
    except Exception as e:  # noqa: BLE001 - pare-feu absent : on n'envoie pas
        return False, "pare-feu indisponible (%s)" % type(e).__name__


def _ollama_web_search(query: str, max_results: int) -> tuple:
    """([resultats], erreur) via la recherche web GRATUITE d'Ollama Cloud (decision owner 26/10).

    Repli quand SearXNG ne trouve rien (moteurs generalistes suspendus, mesure 26/10). La requete ne
    part qu'apres le pare-feu ; toute panne est NOMMEE (cle absente, refus, 429, reseau)."""
    import os as _os

    if _os.environ.get("LAFORGE_WEB_OLLAMA", "1") == "0":
        return [], ""
    ok, raison = _pre_flight(query)
    if not ok:
        return [], "ollama_cloud: requete retenue par le pare-feu (%s)" % raison[:120]
    cle = _cle_ollama()
    if not cle:
        return [], "ollama_cloud: OLLAMA_API_KEY absente du coffre"
    corps = json.dumps({"query": query, "max_results": max(1, min(int(max_results), 10))}).encode()
    req = urllib.request.Request(OLLAMA_WEB_SEARCH, data=corps, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + cle})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return [], "ollama_cloud: HTTP %s" % e.code
    except Exception as e:  # noqa: BLE001 - reseau, egress, JSON : nomme
        return [], "ollama_cloud: %s" % type(e).__name__
    res = [{"title": x.get("title", ""), "url": x.get("url", ""), "content": x.get("content", "")}
           for x in (d.get("results") or []) if isinstance(x, dict) and x.get("url")]
    return res, ""


# ── T2a, ORGANE DE RECHERCHE UNIQUE (decision owner 2026-11-10) ────────────────────────────────────────────────
# Cascade : SearXNG `general` + `it` (fusionnes) -> Tavily (repli BUDGETE, jamais un sujet prive) -> sources
# primaires (GitHub SANS jeton, PyPI) -> ollama cloud. duckduckgo retire : CAPTCHA mesure, etage « toujours ok » faux.
TAVILY_COMPTEUR = Path(__file__).resolve().parent.parent / "sandbox" / "tavily_budget.json"
TAVILY_PLAFOND = int(os.environ.get("LAFORGE_TAVILY_MOIS") or 1000)


def sujet_prive(query: str) -> bool:
    """La requete touche-t-elle un sujet prive (config/sujets_prives.txt) ? Liste illisible = OUI (fail-closed)."""
    try:
        from nokido_agent.app.forge_git_egress import sujets_prives
    except ImportError:
        try:
            from forge_git_egress import sujets_prives
        except ImportError:
            return True
    try:
        return any(re.search(m, query, re.I) for m in sujets_prives().get("mots") or [])
    except Exception:  # noqa: BLE001 - liste illisible : on n'envoie pas
        return True


def _tavily_budget() -> tuple:
    """(autorise, motif, alerte) sur le compteur MENSUEL ; illisible = compteur a zero, dit dans le motif."""
    mois = time.strftime("%Y-%m")
    try:
        d = json.loads(TAVILY_COMPTEUR.read_text(encoding="utf-8"))
        n = int(d.get("n", 0)) if d.get("mois") == mois else 0
    except (OSError, ValueError):
        n = 0
    if n >= TAVILY_PLAFOND:
        return False, "tavily: budget mensuel atteint (%d/%d)" % (n, TAVILY_PLAFOND), None
    alerte = ("tavily: 80 %% du budget mensuel (%d/%d)" % (n + 1, TAVILY_PLAFOND)
              if n + 1 >= 0.8 * TAVILY_PLAFOND else None)
    return True, "", alerte


def _tavily_compter() -> None:
    mois = time.strftime("%Y-%m")
    try:
        d = json.loads(TAVILY_COMPTEUR.read_text(encoding="utf-8"))
        n = int(d.get("n", 0)) if d.get("mois") == mois else 0
    except (OSError, ValueError):
        n = 0
    try:
        TAVILY_COMPTEUR.write_text(json.dumps({"mois": mois, "n": n + 1}), encoding="utf-8")
    except OSError as e:
        logger.warning("[web] compteur Tavily non ecrit (%s) : budget sous-compte", type(e).__name__)


def _tavily_diag(query: str, max_results: int) -> tuple:
    """(resultats, erreur NOMMEE) : cle au coffre, pare-feu AVANT l'envoi, client unique forge_web_search."""
    try:
        from nokido_agent.app.forge_secrets import get_secret
        cle = get_secret("TAVILY_API_KEY") or ""
    except Exception as e:  # noqa: BLE001
        return [], "tavily: coffre illisible (%s)" % type(e).__name__
    if not cle:
        return [], "tavily: TAVILY_API_KEY absente du coffre"
    ok, raison = _pre_flight(query, provider="tavily")
    if not ok:
        return [], "tavily: refuse par le pare-feu (%s)" % raison[:80]
    try:
        from nokido_agent.app.forge_web_search import search_tavily_diag
    except ImportError:
        from forge_web_search import search_tavily_diag
    return asyncio.run(search_tavily_diag(query, cle, max_results))


def _primaires_diag(query: str, max_results: int) -> tuple:
    """(resultats, erreurs) : GitHub SANS jeton puis PyPI, par ForgeSourceDiscovery (aucun client duplique)."""
    erreurs: List[str] = []
    try:
        try:
            from nokido_agent.tools.forge_source_discovery import ForgeSourceDiscovery
        except ImportError:
            from forge_source_discovery import ForgeSourceDiscovery
        sd = ForgeSourceDiscovery()
    except Exception as e:  # noqa: BLE001
        return [], ["primaires: indisponibles (%s)" % type(e).__name__]
    res: List[Dict] = []
    for nom, f in (("github", sd._search_github), ("pypi", sd._search_pypi)):
        sd._derniere_erreur = None
        for r in f(query, max_results) or []:
            res.append({"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("snippet", "")})
        if getattr(sd, "_derniere_erreur", None):
            erreurs.append(sd._derniere_erreur)
    return res[:max_results], erreurs


async def web_search_diag(query: str, max_results: int = 5) -> Dict:
    """Cascade unique ; la cle `alertes` n'apparait que si une alerte existe (contrat anterieur intact)."""
    d = await _cascade(query, max_results)
    if not d.get("alertes"):
        d.pop("alertes", None)
    return d


_CATEGORIES = ("general", "it")
# 10/11 soir : le moteur `docker hub` de la categorie `it` repond a tout mot-cle (« meteo Lyon » -> images lyon24/*).
_DOCKER_HUB = re.compile(r"\b(docker|conteneur|container|image|compose|dockerfile)\b", re.I)


def _bruit_it(r: Dict, query: str) -> bool:
    return (r.get("engine") or "").lower() == "docker hub" and not _DOCKER_HUB.search(query or "")


async def _searxng_fusion(loop, query: str, max_results: int) -> tuple:
    """(fusion sans doublon d'URL, erreurs nommees, toutes_les_categories_en_erreur)."""
    erreurs: List[str] = []
    fusion: List[Dict] = []
    vues = set()
    n_err = 0
    for categorie in _CATEGORIES:
        res, err = await loop.run_in_executor(None, _searxng_diag, query, max_results, "", categorie)
        if err:
            erreurs.append(err)
            n_err += 1
        for r in res or []:
            if categorie == "it" and _bruit_it(r, query):
                continue
            if r.get("url") not in vues:
                vues.add(r.get("url"))
                r["_source"] = "searxng"
                r["_categorie"] = categorie
                fusion.append(r)
    return fusion, erreurs, n_err == len(_CATEGORIES)


_REVEIL_FOND_TS = 0.0
_REVEIL_FOND_S = 300  # un seul reveil de fond par fenetre (attente longue cote fond)
# Boots Docker mesures (sandbox/docker_boot_samples.jsonl, 200) : mediane 11,7 s, p90 14,9 s, max 31,7 s.
_REVEIL_FROID_S = 40  # pire cas de l'appel : 2x5 s SearXNG + 40 + rejeu 10 + Tavily ~5 = 65 s < plafond hub 70 s


def _ensure_searxng_sync(attente: int) -> bool:
    """Primitive EXISTANTE (forge_watch_agent._ensure_searxng : capacite servie puis superviseur)."""
    try:
        from nokido_agent.app.forge_watch_agent import _ensure_searxng
    except ImportError:  # repli checkout
        from forge_watch_agent import _ensure_searxng
    return bool(_ensure_searxng(wait_s=attente))


def _docker_a_froid():
    """True si le daemon Docker est DOWN (boot a froid), False s'il repond, None si illisible."""
    try:
        from nokido_agent.tools.forge_docker_keeper import _docker_info_ok
        return not bool(_docker_info_ok()[0])
    except Exception:  # noqa: BLE001 - muet-ok : illisible -> None, l'appelant garde le reveil synchrone
        return None


def _demarrer_fond(cible, **kwargs) -> None:
    import threading
    threading.Thread(target=cible, kwargs=kwargs, daemon=True, name="reveil-searxng").start()


def _reveiller_searxng() -> tuple:
    """(pret, erreur nommee) : reveil on-demand par la primitive EXISTANTE. Daemon UP : attente bornee
    LAFORGE_WEB_REVEIL_S (25 s ; le hub plafonne un appel a 70 s). Docker A FROID : attente synchrone
    LAFORGE_WEB_REVEIL_FROID_S (40 s ; boots mesures mediane 11,7 s) ; en echec seulement, UN reveil de fond pour les
    appels suivants. (0d72203cf partait en fond sur un « ~230 s » non mesure : Tavily paye pour rien.)"""
    global _REVEIL_FOND_TS
    attente = int(os.environ.get("LAFORGE_WEB_REVEIL_S") or 25)
    try:
        if _docker_a_froid() is True:
            froid = int(os.environ.get("LAFORGE_WEB_REVEIL_FROID_S") or _REVEIL_FROID_S)
            if _ensure_searxng_sync(froid):
                return True, None
            if time.time() - _REVEIL_FOND_TS >= _REVEIL_FOND_S:
                _REVEIL_FOND_TS = time.time()
                _demarrer_fond(_ensure_searxng_sync, attente=_REVEIL_FOND_S)
            return False, "reveil searxng: Docker a froid, pas pret apres %d s, reveil poursuivi en fond" % froid
        if _ensure_searxng_sync(attente):
            return True, None
        return False, "reveil searxng: pas pret apres %d s" % attente
    except Exception as e:  # noqa: BLE001 - nomme, la cascade continue
        return False, "reveil searxng: %s" % type(e).__name__


async def _cascade(query: str, max_results: int = 5) -> Dict:
    """{"results": [...], "erreurs": [...], "source": ..., "alertes": [...]} -- cascade UNIQUE, erreurs NOMMEES.

    `results` vide ET `erreurs` vide = tout a repondu sans rien trouver ; `erreurs` non vide = un etage n'a PAS pu
    chercher (moteur eteint, delai, refus, budget, limite de debit) : ce n'est jamais « aucun resultat »."""
    loop = asyncio.get_event_loop()
    alertes: List[str] = []
    fusion, erreurs, tout_en_erreur = await _searxng_fusion(loop, query, max_results)
    # REVEIL (10/11 soir) : SearXNG en ERREUR partout (pas « rien trouve ») = moteur endormi, pas un web vide. Le
    # corps le reveille (primitive _ensure_searxng : reclamation nommee relachee, superviseur) et rejoue UNE fois
    # avant de payer Tavily. Interrupteur global LAFORGE_WEB_REVEIL lu a chaque appel (coupe dans les NR).
    if not fusion and tout_en_erreur and os.environ.get("LAFORGE_WEB_REVEIL", "1") != "0":
        ok, err = await loop.run_in_executor(None, _reveiller_searxng)
        if ok:
            fusion, errs2, _ = await _searxng_fusion(loop, query, max_results)
            erreurs.extend(errs2)
        elif err:
            erreurs.append(err)
    if fusion:
        return {"results": fusion[: max_results * 2], "erreurs": erreurs, "source": "searxng", "alertes": alertes}
    # Interrupteurs GLOBAUX lus a chaque appel (comme LAFORGE_WEB_OLLAMA) : coupes par defaut dans les NR (aucun
    # reseau en test), allumes en production.
    if os.environ.get("LAFORGE_WEB_TAVILY", "1") == "0":
        pass
    elif sujet_prive(query):
        erreurs.append("tavily: sujet prive, rien n'est envoye")
    else:
        ok, motif, alerte = _tavily_budget()
        if not ok:
            erreurs.append(motif)
        else:
            _tavily_compter()
            if alerte:
                alertes.append(alerte)
                logger.warning("[web] %s", alerte)
            res, err = await loop.run_in_executor(None, _tavily_diag, query, max_results)
            if err:
                erreurs.append(err)
            if res:
                for r in res:
                    r["_source"] = "tavily"
                return {"results": res, "erreurs": erreurs, "source": "tavily", "alertes": alertes}
    res, errs = ([], []) if os.environ.get("LAFORGE_WEB_PRIMAIRES", "1") == "0" else \
        await loop.run_in_executor(None, _primaires_diag, query, max_results)
    erreurs.extend(errs)
    if res:
        for r in res:
            r["_source"] = "primaires"
        return {"results": res, "erreurs": erreurs, "source": "primaires", "alertes": alertes}
    res, err = await loop.run_in_executor(None, _ollama_web_search, query, max_results)
    if err:
        erreurs.append(err)
    if res:
        for r in res:
            r["_source"] = "ollama_cloud"
        return {"results": res, "erreurs": erreurs, "source": "ollama_cloud", "alertes": alertes}
    return {"results": [], "erreurs": erreurs, "source": None, "alertes": alertes}


async def web_search_with_fallback(
    query: str,
    max_results: int = 5,
) -> List[Dict]:
    """Resultats seuls de la cascade UNIQUE (web_search_diag). T2a owner 10/11 : l'ancienne cascade parallele
    (SearXNG puis duckduckgo « toujours ok », CAPTCHA mesure) est retiree -- un seul organe, une seule cascade."""
    return (await web_search_diag(query, max_results)).get("results", [])


def format_results(results: List[Dict], max_chars: int = 400) -> str:
    if not results:
        return "Aucun resultat web disponible."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"[{i}] {r.get('title', '')[:80]}\n"
            f"{r.get('content', '')[:max_chars]}\n"
            f"{r.get('url', '')[:120]} [{r.get('_source', '?')}]"
        )
    return "\n\n".join(lines)


def rendre_diag(d: Dict) -> str:
    """Rendu de l'outil `web_search` a partir de `web_search_diag` : un REPLI qui rend le DIT (10/11 soir).

    Mesure : SearXNG en timeout, Tavily (payant) a repondu, l'outil ne rendait que les resultats -- le repli
    passait pour le regime nominal. Resultats + erreurs ou alertes -> une ligne `source=... ; etages en erreur`."""
    results, erreurs = d.get("results") or [], d.get("erreurs") or []
    alertes = d.get("alertes") or []
    if results:
        txt = format_results(results)
        if erreurs or alertes:
            pied = "--- source=%s" % (d.get("source") or "?")
            if erreurs:
                pied += " ; etages en erreur (repli) : " + " ; ".join(erreurs)[:500]
            if alertes:
                pied += " ; alertes : " + " ; ".join(alertes)[:200]
            txt += "\n\n" + pied
        return txt
    if erreurs:
        return ("RECHERCHE NON FAITE (ce n'est PAS « aucun resultat ») : etages en erreur -- %s. "
                "Reveil : nokido_ensure_service service=searxng" % " ; ".join(erreurs)[:600])
    return "Aucun resultat (tous les etages ont repondu sans rien trouver)."
