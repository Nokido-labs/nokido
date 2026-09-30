# -*- coding: utf-8 -*-
"""forge_robots.py — Robots Exclusion Protocol (RFC 9309) pour les crawls Nokido.

Ecrit le 2026-09-04 apres qu'un audit NPSC a rendu RFC-9309 en VIOLATION :
33 modules recuperaient des pages web arbitraires et `robotparser`,
`robots.txt` et `can_fetch` n'apparaissaient dans AUCUN fichier versionne.
Deux manquements distincts, pas un :

  1. section 2.3   — robots.txt n'etait jamais recupere ni respecte ;
  2. section 2.2.1 — le crawler se DEGUISAIT en navigateur
     (`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36`)
     au lieu de s'identifier par un product token.

RFC 9309 n'est pas une politesse : c'est la norme qui rend le crawl legitime.

## Ce que la norme impose sur le RESULTAT de la recuperation (section 2.3.1.3)

Ce point est le coeur du module, et le seul qui demande un jugement :

  | reponse            | comportement exige                                  |
  |--------------------|-----------------------------------------------------|
  | 2xx                | parser et appliquer les regles                       |
  | 4xx (unavailable)  | acces AUTORISE sans restriction                      |
  | 5xx (unreachable)  | le crawleur DEVRAIT supposer une interdiction totale |
  | erreur reseau      | traite comme unreachable                             |

Autrement dit : « pas de robots.txt » (404) AUTORISE, « je n'ai pas pu le lire »
(500, timeout) INTERDIT. Confondre les deux, c'est exactement l'erreur que le
projet paye ailleurs sous le nom « une source qui se tait n'est pas une source
qui dit non » — ici la norme tranche dans l'autre sens, et c'est deliberе : le
doute profite au site, pas au robot.

## Ce que ce module ne fait PAS

Il ne fetch pas la page. Il repond a « ai-je le droit ? » et rend la raison.
Le refus est une DECISION, pas une exception : l'appelant la journalise.
"""
from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/conformite-crawl"

import time
import urllib.error
import urllib.parse
import urllib.request
from urllib.robotparser import RobotFileParser

# Product token (RFC 9309 section 2.2.1) : lettres, tiret, underscore uniquement.
# Il doit rester STABLE — c'est par lui qu'un site nous adresse ses regles.
PRODUCT_TOKEN = "NokidoBot"
USER_AGENT = PRODUCT_TOKEN + "/1.0"

# Duree de cache par defaut (section 2.4 : « SHOULD NOT be longer than 24 hours »).
TTL_DEFAUT_S = 24 * 3600
TIMEOUT_S = 10

# Verdicts d'acces au fichier robots.txt lui-meme.
ROBOTS_OK = "OK"                    # 2xx, regles appliquees
ROBOTS_ABSENT = "ABSENT"            # 4xx : rien ne nous restreint
ROBOTS_INJOIGNABLE = "INJOIGNABLE"  # 5xx / reseau : interdiction supposee

_cache: dict[str, dict] = {}


def _origine(url: str) -> str | None:
    """Rend le scheme://authority d'une URL, ou None si elle n'est pas HTTP(S)."""
    try:
        p = urllib.parse.urlsplit(url)
    except Exception:
        return None
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return "%s://%s" % (p.scheme, p.netloc)


def _ttl_depuis_entetes(entetes) -> int:
    """Respecte `Cache-Control: max-age` quand il est present (section 2.4)."""
    brut = ""
    try:
        brut = entetes.get("Cache-Control") or ""
    except Exception:
        return TTL_DEFAUT_S
    for morceau in brut.split(","):
        morceau = morceau.strip().lower()
        if morceau.startswith("max-age="):
            try:
                return max(60, min(int(morceau.split("=", 1)[1]), TTL_DEFAUT_S))
            except ValueError:
                return TTL_DEFAUT_S
    return TTL_DEFAUT_S


def _recuperer(origine: str) -> dict:
    """Recupere et parse robots.txt. Rend l'entree de cache, sans jamais lever."""
    cible = origine + "/robots.txt"
    requete = urllib.request.Request(cible, headers={"User-Agent": USER_AGENT})
    parseur = RobotFileParser()
    parseur.set_url(cible)
    try:
        with urllib.request.urlopen(requete, timeout=TIMEOUT_S) as reponse:
            corps = reponse.read(512_000).decode("utf-8", "replace")
            parseur.parse(corps.splitlines())
            return {"statut": ROBOTS_OK, "parseur": parseur,
                    "expire": time.time() + _ttl_depuis_entetes(reponse.headers),
                    "detail": "HTTP %s, %d octets" % (reponse.status, len(corps))}
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            # « Unavailable » : la norme AUTORISE l'acces complet.
            return {"statut": ROBOTS_ABSENT, "parseur": None,
                    "expire": time.time() + TTL_DEFAUT_S,
                    "detail": "HTTP %s — aucun robots.txt, acces libre" % exc.code}
        return {"statut": ROBOTS_INJOIGNABLE, "parseur": None,
                "expire": time.time() + 600,
                "detail": "HTTP %s — le serveur ne peut pas repondre" % exc.code}
    except Exception as exc:
        # Reseau coupe, DNS, TLS, timeout : « unreachable ». Interdiction supposee.
        return {"statut": ROBOTS_INJOIGNABLE, "parseur": None,
                "expire": time.time() + 600,
                "detail": "%s : %s" % (type(exc).__name__, exc)}


def _entree(origine: str, forcer: bool = False) -> dict:
    entree = _cache.get(origine)
    if entree is not None and not forcer and entree["expire"] > time.time():
        return entree
    entree = _recuperer(origine)
    _cache[origine] = entree
    return entree


def decision(url: str, agent: str = PRODUCT_TOKEN, forcer: bool = False) -> dict:
    """« Ai-je le droit de recuperer cette URL ? » — et POURQUOI.

    Rend {autorise, motif, statut_robots, origine}. Jamais d'exception : un
    refus est une decision que l'appelant journalise, pas une panne.

    Une URL non-HTTP (fichier local, data:) sort autorisee : RFC 9309 ne la
    couvre pas, et repondre « non » y serait une invention de notre part.
    """
    origine = _origine(url)
    if origine is None:
        return {"autorise": True, "statut_robots": "HORS_PORTEE", "origine": None,
                "motif": "URL non HTTP(S) — RFC 9309 ne s'y applique pas"}
    entree = _entree(origine, forcer=forcer)
    statut = entree["statut"]
    if statut == ROBOTS_ABSENT:
        return {"autorise": True, "statut_robots": statut, "origine": origine,
                "motif": "aucun robots.txt (%s)" % entree["detail"]}
    if statut == ROBOTS_INJOIGNABLE:
        # Section 2.3.1.3 : « the crawler SHOULD assume complete disallow ».
        return {"autorise": False, "statut_robots": statut, "origine": origine,
                "motif": "robots.txt injoignable, interdiction supposee (%s)" % entree["detail"]}
    parseur = entree["parseur"]
    try:
        autorise = bool(parseur.can_fetch(agent, url))
    except Exception as exc:
        return {"autorise": False, "statut_robots": "ILLISIBLE", "origine": origine,
                "motif": "regles non evaluables (%s) — abstention" % type(exc).__name__}
    return {"autorise": autorise, "statut_robots": statut, "origine": origine,
            "motif": ("autorise par robots.txt" if autorise
                      else "INTERDIT par robots.txt pour %s" % agent)}


def autorise(url: str, agent: str = PRODUCT_TOKEN) -> bool:
    """Raccourci booleen. Preferer `decision()` : elle porte le MOTIF."""
    return bool(decision(url, agent)["autorise"])


def delai_courtoisie(url: str, agent: str = PRODUCT_TOKEN) -> float | None:
    """`Crawl-delay` demande par le site, en secondes. None si non exprime.

    Hors RFC 9309 (qui ne normalise pas ce champ) mais largement respecte ;
    l'ignorer alors que le site l'exprime revient a le lire a moitie.
    """
    origine = _origine(url)
    if origine is None:
        return None
    parseur = (_entree(origine) or {}).get("parseur")
    if parseur is None:
        return None
    try:
        valeur = parseur.crawl_delay(agent)
    except Exception:
        return None
    return float(valeur) if valeur is not None else None


def purger_cache() -> int:
    """Vide le cache. Rend le nombre d'origines oubliees (tests, rotation)."""
    n = len(_cache)
    _cache.clear()
    return n
