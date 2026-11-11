#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Combien de modeles sont JOIGNABLES en palier gratuit — et le rester.

Les catalogues bougent sans prevenir : en une journee on a vu GitHub Models
retire (410), `llama-3.3-70b-versatile` disparaitre de Groq, `gemini-2.5-pro`
devenir « no longer available to new users », les slugs `:free` d'OpenRouter
changer de forme. Cabler des noms de modeles a la main, c'est signer pour les
repayer tous les trimestres.

Ce module mesure trois choses DISTINCTES, qu'on confond tout le temps :

  DECLARE   le catalogue liste le modele                     (`GET /models`)
  GRATUIT   le fournisseur annonce un prix nul               (`pricing`, `:free`)
  JOIGNABLE une completion reelle a REPONDU                  (preuve)

Un modele declare n'est pas joignable ; un modele gratuit peut etre sature
(429) ; un modele joignable aujourd'hui peut disparaitre demain. Seule la
troisieme colonne est une preuve, et elle coute un appel — on l'echantillonne.

QUOTA : rapporte quand le fournisseur l'expose (OpenRouter `/key`, en-tetes
`x-ratelimit-*`), NON MESURE sinon. On ne devine pas un quota.

Sortie : `sandbox/free_tier_census.json`, horodate — deux passes comparees
disent ce qui a bouge chez qui.

    run action=run_job script=tools/forge_free_tier_census.py online=true
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ROOT d'abord : `nokido_agent` (lu pour les cles) se resout depuis la RACINE.
# Sans elle, le recenseur lance en job mourait en ModuleNotFoundError (2026-09-23).
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

try:
    from nokido_agent.tools.forge_process_inventory import contexte_execution
except ImportError:  # repli checkout
    from forge_process_inventory import contexte_execution
# APRES la mise en place du chemin (26/10) : importe en tete de module, le catalogue cassait le recenseur charge
# hors du depot (test_free_tier_census_importe_ses_cles_nr). Meme forme que l'import ci-dessus.
try:
    from nokido_agent.tools.forge_provider_catalogue import FOURNISSEURS, palier_ollama_cloud
except ImportError:  # repli checkout
    from forge_provider_catalogue import FOURNISSEURS, palier_ollama_cloud

SORTIE = ROOT / "sandbox" / "free_tier_census.json"
REGISTRE_ESSAIM = ROOT / "sandbox" / "swarm_membres_vivants.json"  # lu par forge_cli_swarm (GREEN AGY cb3f1114f)

# 29/10 (owner : « une info de fin de quota devrait nourrir le census pour eviter des mesures inutiles ensuite ») :
# l'executeur qui CONSTATE un quota epuise l'ecrit ici, sur le verdict du couple, avec une ECHEANCE : delai annonce par
# le fournisseur, sinon quota JOURNALIER -> prochain minuit UTC (forge_provider_catalogue.echeance_quota, meme lecture
# que la matrice), sinon solde/usage epuise -> ce defaut declare. Un 429 de DEBIT simple n'est PAS un epuisement
# (classer_reponse : DEBIT, a re-sonder) : rien n'est consigne. Le census reste proprietaire du fichier.
QUOTA_REPOS_DEFAUT_S = 4 * 3600
_RE_SOLDE_EPUISE = re.compile(r"insufficient balance|no resource package|please recharge|hit your usage limit|"
                              r"usagelimitexceeded|quota exceeded|credit balance is too low|"
                              r"reached your (?:monthly |daily )?usage limit|free usage limit reached", re.I)
# 29/10 soir, mesure : Ollama Cloud « you have reached your monthly usage limit » -- quota MENSUEL, revient au 1er du
# mois suivant (UTC), pas dans 4 h.
_RE_MENSUEL = re.compile(r"\bmonthly\b|\bper month\b|\bmensuel", re.I)
_RE_ECHEANCE = re.compile(r"(?:retry|try again)\s*(?:after|in)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*"
                          r"(s|sec|secs|seconds?|m|min|mins|minutes?|h|hours?)?\b", re.I)
_UNITE_S = {"s": 1, "m": 60, "h": 3600}


# 29/10 (owner, constitution : DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE) : ces surfaces ne sont PAS des fournisseurs
# reseau toujours debout. Une prothese juste-a-temps qui dort n'est pas en panne ; une bibliotheque in-process n'a pas
# de serveur a sonder. Elles sortaient « NON MESURE -- URLError » a chaque passe.
A_LA_DEMANDE = {"lmstudio": "prothese juste-a-temps : forge_agent_proxy la reveille (ensure lmstudio) a la premiere requete"}
BIBLIOTHEQUES = {"litellm": "bibliotheque in-process (forge_agent_proxy -> forge_litellm_bridge) : aucun serveur attendu"}


def etat_hors_ligne(fournisseur: str, code: int, motif: str) -> tuple[str, str]:
    """Etat d'une surface dont le catalogue n'a pas repondu : A_LA_DEMANDE / BIBLIOTHEQUE / NON_MESURE."""
    if fournisseur in BIBLIOTHEQUES:
        return "BIBLIOTHEQUE", BIBLIOTHEQUES[fournisseur]
    if fournisseur in A_LA_DEMANDE:
        return "A_LA_DEMANDE", "%s (endormie : %s)" % (A_LA_DEMANDE[fournisseur], motif)
    return "NON_MESURE", motif


def echeance_quota(detail: str, maintenant: float | None = None) -> float | None:
    """Instant ou le quota redevient utilisable, ou None si le message ne decrit PAS un epuisement (debit simple)."""
    t = time.time() if maintenant is None else float(maintenant)
    d = str(detail or "")
    m = _RE_ECHEANCE.search(d)
    if m:
        unite = (m.group(2) or "s").lower()[0]
        return t + float(m.group(1)) * _UNITE_S.get(unite, 1)
    _m = re.search(r"retry-after=([0-9.]+)s?", d, re.I)
    if _m:
        return t + float(_m.group(1))
    try:
        from forge_provider_catalogue import _quota_journalier, echeance_quota as _minuit_utc
    except ImportError:  # repli checkout
        from tools.forge_provider_catalogue import _quota_journalier, echeance_quota as _minuit_utc
    if _RE_MENSUEL.search(d) and _RE_SOLDE_EPUISE.search(d):
        from datetime import datetime, timezone
        n = datetime.fromtimestamp(t, timezone.utc)
        return datetime(n.year + (n.month == 12), n.month % 12 + 1, 1, tzinfo=timezone.utc).timestamp()
    if _quota_journalier(d.lower()):
        from datetime import datetime, timezone
        return datetime.fromisoformat(_minuit_utc(datetime.fromtimestamp(t, timezone.utc))).timestamp()
    if _RE_SOLDE_EPUISE.search(d):
        return t + QUOTA_REPOS_DEFAUT_S
    return None


def quota_epuise_actif(verdict, maintenant: float | None = None) -> str | None:
    """Motif si le verdict porte un quota epuise dont l'echeance n'est pas passee, None sinon (absent = eligible)."""
    if not isinstance(verdict, dict):
        return None
    fin = verdict.get("quota_epuise_jusqu_a")
    if not isinstance(fin, (int, float)):
        return None
    t = time.time() if maintenant is None else float(maintenant)
    if t >= fin:
        return None
    return "quota epuise jusqu'a %s (%s)" % (time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(fin)),
                                            verdict.get("quota_motif") or "motif non rendu")


def consigner_quota_epuise(fournisseur: str, modele: str, detail: str, maintenant: float | None = None,
                           chemin=None) -> float | None:
    """Ecrit l'epuisement CONSTATE sur le verdict `fournisseur:modele` (les autres champs restent) ; rend l'echeance.
    Census illisible -> rien n'est ecrit (on ne jette jamais le recensement), None."""
    p = Path(chemin) if chemin else SORTIE
    try:
        doc = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    t = time.time() if maintenant is None else float(maintenant)
    fin = echeance_quota(detail, t)
    if fin is None:
        # forme ecrite par `sonder` sur un 429 (« retry-after=3600.0s ») : echeance_quota ne la lisait pas, et
        # l'epuisement n'etait JAMAIS consigne (NR du 30/10)
        _m = re.search(r"retry-after=([0-9.]+)s", str(detail or ""))
        fin = t + float(_m.group(1)) if _m else None
    if fin is None:
        return None
    tete = str(detail or "").strip().splitlines()[0][:200] if str(detail or "").strip() else "quota epuise"
    verdicts = doc.setdefault("verdicts", {})
    v = verdicts.get("%s:%s" % (fournisseur, modele))
    v = dict(v) if isinstance(v, dict) else {}
    v.update({"quota_epuise_jusqu_a": fin, "quota_motif": tete,
              "quota_constate_le": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))})
    verdicts["%s:%s" % (fournisseur, modele)] = v
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name("%s.%d.tmp" % (p.name, os.getpid()))
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        return None
    return fin


def extraire_delai_rate_limit(entetes: dict | object, maintenant: float | None = None) -> float | None:
    """Extrait la duree de cooldown (en secondes) depuis Retry-After ou x-ratelimit-reset*."""
    if not entetes:
        return None
    now = time.time() if maintenant is None else float(maintenant)
    items = entetes.items() if hasattr(entetes, "items") else []
    h = {str(k).lower(): str(v).strip() for k, v in items}

    # 1. Retry-After prioritaire (secondes ou date HTTP)
    val = h.get("retry-after")
    if val:
        try:
            return max(0.0, float(val))
        except ValueError:  # muet-ok : pas un nombre, essai suivant en date HTTP
            pass
        try:
            dt = parsedate_to_datetime(val)
            return max(0.0, dt.timestamp() - now)
        except Exception:  # noqa: BLE001  # muet-ok : ni nombre ni date, en-tete suivant ; aucun delai invente
            pass

    # 2. En-têtes x-ratelimit-reset*
    for k, v in h.items():
        if k.startswith("x-ratelimit-reset"):
            try:
                sec = float(v)
                if sec > 1_000_000_000:
                    return max(0.0, sec - now)
                return max(0.0, sec)
            except ValueError:  # muet-ok : pas un nombre, essai suivant en date HTTP
                pass
            try:
                dt = parsedate_to_datetime(v)
                return max(0.0, dt.timestamp() - now)
            except Exception:  # noqa: BLE001  # muet-ok : forme suivante (`1m26s`) essayee juste apres
                pass
            m = _RE_ECHEANCE.search(v)
            if m:
                unite = (m.group(2) or "s").lower()[0]
                return float(m.group(1)) * _UNITE_S.get(unite, 1)

    return None


def verifier_et_sauter_fournisseur(fournisseur: str, env_key: str | None = None, cle: str | None = None) -> tuple[bool, str, str]:
    """Verification pre-requete : should_skip ou cle absente -> (saute, etat, motif)."""
    if env_key and not cle:
        # 31/10 (CI de reference rouge) : une cle ABSENTE n'est pas un saut pour quota -- deux etats distincts ;
        # 640262e9a les confondait (test_une_cle_absente_est_dite_avec_son_nom).
        return True, "CLE_ABSENTE", f"cle manquante: {env_key}"
    try:
        from forge_provider_quota import should_skip
        if should_skip(fournisseur):
            return True, "SAUTE", f"quota fournisseur epuise (should_skip: {fournisseur})"
    except Exception as e:  # noqa: BLE001 - INCONNU n'est pas NON : on tente la mesure, mais la panne se dit
        print(f"[census] should_skip illisible pour {fournisseur} ({type(e).__name__}) : quota INCONNU, mesure tentee",
              file=sys.stderr)
    return False, "", ""
ECHANTILLON = 2        # completions reelles par fournisseur
TIMEOUT = 25

# (etiquette, cle, base OpenAI-compatible). La base sert AUSSI a completer.
# 26/10 (owner : « ton census ne rate aucun provider ? ») : la liste etait CODEE EN DUR (14 entrees) et omettait en
# silence 9 fournisseurs du catalogue (ollama_cloud, cohere, xai, together, jina, voyage, siliconflow, nvidia_nim,
# llamacpp). Elle DERIVE desormais du catalogue (source unique) ; le nom reste le point d'entree des lecteurs
# (cibler, bancs, essaim, main) et des tests qui le restreignent.
SURFACES = list(FOURNISSEURS)

_INADAPTES = ("embed", "bge-", "nomic", "whisper", "tts", "clip", "guard",
              "rerank", "moderation", "image", "vision", "moondream", "llava",
              # 21/10 : deepinfra etait « sonde » sur Qwen3-ASR -- un modele non chat ne prouve aucun palier de chat
              "asr", "speech", "audio", "ocr", "transcri")


_NON_CHAT_META = ("embed", "audio", "speech", "image", "rerank", "moderation", "transcri", "text-to-", "-to-image",
                  "asr", "ocr", "tts")


def _meta_non_chat(m: dict) -> bool:
    """Le CATALOGUE (/models) dit-il que ce modele n'est pas du chat ? (modalite, type, task) -- sans meta : non."""
    arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
    modalite = arch.get("modality") or ""
    if isinstance(modalite, (list, tuple)):
        modalite = "->".join(map(str, modalite))
    modalite = str(modalite).lower()
    if modalite and not modalite.endswith("->text") and modalite != "text":
        return True
    if "audio" in modalite.split("->")[0]:
        return True
    for champ in ("type", "task", "pipeline_tag"):
        v = str(m.get(champ) or "").lower()
        if v and any(k in v for k in _NON_CHAT_META):
            return True
    return False


def modeles_chat(modeles: list[dict]) -> list[dict]:
    """Liste BLANCHE chat tiree du catalogue : meta du fournisseur d'abord, puis exclusion par nom (_INADAPTES)."""
    return [m for m in modeles
            if not _meta_non_chat(m) and not any(mot in str(m.get("id", "")).lower() for mot in _INADAPTES)]


_RAISONNEMENT = ("nemotron", "reason", "-r1", "/r1", "gpt-oss", "qwq", "thinking", "magistral", "deepseek-r")
BUDGET_STANDARD = 8
BUDGET_RAISONNEMENT = 256   # mesure 24/10 : nemotron-3-ultra rend VIDE a 96 jetons et repond 400


def budget_jetons(modele: str) -> int:
    n = str(modele).lower()
    return BUDGET_RAISONNEMENT if any(k in n for k in _RAISONNEMENT) else BUDGET_STANDARD


TIMEOUT_NVIDIA = 90   # 25 s -> illisible (mesure) : NIM a froid est lent
TIMEOUTS_BASE = {"nvidia.com": TIMEOUT_NVIDIA}


def timeout_pour(base: str) -> int:
    return next((t for h, t in TIMEOUTS_BASE.items() if h in str(base)), TIMEOUT)


def _motif_http(code: int, detail: str = "") -> str:
    return f"HTTP {code}"


def _etat_http(code: int, detail: str = "") -> str:
    from forge_provider_catalogue import classer_reponse
    return classer_reponse(code, detail)


def _corps_erreur(exc) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:500]
    except Exception:  # noqa: BLE001
        return ""


def _req(url: str, cle: str, charge: bytes | None = None, timeout: int = TIMEOUT):
    entetes = {"User-Agent": "nokido-census"}
    if cle:
        entetes["Authorization"] = f"Bearer {cle}"
    if charge is not None:
        entetes["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=charge, headers=entetes)


def _racine(base: str) -> str:
    """Base d'API sans « / » final ni « /models » final : plusieurs entrees de SURFACES finissent deja par /models, et
    les appels ajoutaient le suffixe (/models/models, /models/chat/completions ; enquete OPENCODE_DEFAUT2 27/10)."""
    b = str(base or "").rstrip("/")
    return b[: -len("/models")] if b.endswith("/models") else b


def catalogue(base: str, cle: str) -> tuple[int, list[dict], dict, str]:
    """(code, modeles bruts, en-tetes, detail) — les en-tetes portent parfois le quota."""
    try:
        with urllib.request.urlopen(_req(f"{_racine(base)}/models", cle), timeout=TIMEOUT) as r:
            brut = json.loads(r.read().decode("utf-8", errors="replace"))
            donnees = brut.get("data") if isinstance(brut, dict) else brut
            return r.status, [m for m in (donnees or []) if isinstance(m, dict)], dict(r.headers), ""
    except urllib.error.HTTPError as exc:
        # Code et raison SEULEMENT, jamais le corps (26/10) : un 401 renvoie parfois la cle partiellement masquee
        # (« Incorrect API key provided: sk-...abcd »), qui finirait dans sandbox/free_tier_census.json.
        return exc.code, [], {}, ("HTTP %s %s" % (exc.code, exc.reason or "")).strip()[:120]
    except Exception as exc:  # noqa: BLE001 - reseau, DNS, port ferme
        return -1, [], {}, f"{type(exc).__name__}: {exc}"[:120]


def _lire_catalogue(base: str, cle: str) -> tuple[int, list[dict], dict, str]:
    """catalogue() normalise en 4 valeurs : les remplacants de test (et d'eventuels appelants) rendent encore
    (code, modeles, en-tetes) -- 8 NR cassaient sur « not enough values to unpack » au passage a 4 (26/10)."""
    r = tuple(catalogue(base, cle))
    return (r + ("",))[:4] if len(r) == 3 else r[:4]


def est_gratuit(modele: dict, etiquette: str) -> bool | None:
    """True/False si le fournisseur l'annonce, None s'il ne dit rien.

    None n'est PAS False : beaucoup d'API ne publient aucun prix, et compter
    « non gratuit » ce qui n'est pas annonce donnerait un chiffre faux.
    """
    identifiant = str(modele.get("id") or "")
    if identifiant.endswith(":free"):
        return True
    prix = modele.get("pricing")
    if isinstance(prix, dict):
        try:
            return all(float(prix.get(champ, 0) or 0) == 0.0
                       for champ in ("prompt", "completion"))
        except (TypeError, ValueError):
            return None
    if etiquette in ("ollama", "lmstudio", "litellm"):
        return True            # local : aucun paiement possible
    return None


def _taille(identifiant: str) -> float:
    import re

    trouve = re.findall(r"(\d+(?:\.\d+)?)\s*b\b", identifiant.lower())
    return min((float(x) for x in trouve), default=999.0)


# Outil minimal de la sonde (exigence swarm/MCP, owner 16/10) : un modele qui refuse `tools` n'est pas utilisable par
# le swarm, meme gratuit. Les EN-TETES DE LIMITE se lisent sur la COMPLETION (Groq, Mistral), pas sur le catalogue.
_OUTIL_SONDE = [{"type": "function", "function": {"name": "nokido_ping", "description": "sonde de support des outils",
                                                  "parameters": {"type": "object", "properties": {}}}}]
_MARQUES_LIMITE = ("ratelimit", "retry-after", "x-trial")
PAUSE_S = 1.5   # entre deux appels au MEME fournisseur : le 429 Mistral du 16/10 venait probablement de la sonde


def _limites(entetes) -> dict:
    items = entetes.items() if hasattr(entetes, "items") else []
    return {str(k).lower(): v for k, v in items if any(m in str(k).lower() for m in _MARQUES_LIMITE)}


def _lire_reponse(corps: dict) -> tuple[bool, str]:
    choix = (corps.get("choices") or [{}])[0]
    message = choix.get("message") or {}
    if str(message.get("content") or "").strip():
        return True, ""
    # Vecu 16/10 : un modele de RAISONNEMENT depense les 8 tokens a reflechir -- `content` vide, mais le
    # fournisseur a REPONDU (openrouter/free, nemotron-3-super:free, gpt-oss lus « reponse vide » a tort).
    if str(message.get("reasoning") or message.get("reasoning_content") or "").strip():
        return True, "OK (raisonnement seul, budget de 8 tokens)"
    if choix.get("finish_reason") == "length":
        return True, "OK (coupe par le budget de 8 tokens)"
    return False, "reponse vide"


def _completer(base: str, cle: str, modele: str, outils: bool, max_tokens: int | None = None):
    charge = {"model": modele, "messages": [{"role": "user", "content": "ping"}],
              "max_tokens": max_tokens or budget_jetons(modele)}
    if outils:
        charge["tools"] = _OUTIL_SONDE
    with urllib.request.urlopen(_req(f"{_racine(base)}/chat/completions", cle, json.dumps(charge).encode("utf-8")),
                                timeout=timeout_pour(base)) as r:
        entetes = getattr(r, "headers", None) or {}
        return json.loads(r.read().decode("utf-8", errors="replace")), entetes


def sonder(base: str, cle: str, modele: str, outils: bool = False, fournisseur: str | None = None) -> dict:
    """Une completion reelle : joignable, motif, en-tetes de limite de la COMPLETION, et (outils=True) support de
    `tools` -- None si non teste, False si le modele refuse (400/404/422) puis re-sonde sans."""
    d = {"joignable": False, "motif": "", "limites": {}, "outils": None}
    refus_avec_outils = False
    nom_fournisseur = fournisseur or base
    tentatives_restantes = 1
    if outils:
        while True:
            try:
                corps, entetes = _completer(base, cle, modele, True, max_tokens=budget_jetons(modele))
                ok, motif = _lire_reponse(corps)
                d.update(joignable=ok, motif=motif, limites=_limites(entetes), outils=True)
                return d
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    entetes_err = getattr(exc, "headers", None) or {}
                    delai = extraire_delai_rate_limit(entetes_err)
                    if delai is None:
                        delai = extraire_delai_rate_limit(dict(_limites(entetes_err)))
                    if delai is not None and delai <= 30.0 and tentatives_restantes > 0:
                        tentatives_restantes -= 1
                        time.sleep(delai)
                        continue
                    if delai is not None and delai > 30.0:
                        consigner_quota_epuise(nom_fournisseur, modele, f"HTTP 429 retry-after={delai}s")
                        d.update(motif=_motif_http(exc.code), limites=_limites(exc.headers or {}),
                                 etat="QUOTA_EPUISE")
                        return d
                    d.update(motif=_motif_http(exc.code), limites=_limites(exc.headers or {}),
                             etat=_etat_http(exc.code, _corps_erreur(exc)))
                    return d
                if exc.code == 402:
                    d.update(motif=_motif_http(exc.code), limites=_limites(exc.headers or {}),
                             etat="SANS_SOLDE")
                    return d
                if exc.code not in (400, 404, 422):
                    d.update(motif=_motif_http(exc.code), limites=_limites(exc.headers or {}),
                             etat=_etat_http(exc.code, _corps_erreur(exc)))
                    return d
                refus_avec_outils = True
                break
            except Exception as exc:  # noqa: BLE001
                d["motif"] = type(exc).__name__
                return d
    tentatives_restantes = 1
    while True:
        try:
            corps, entetes = _completer(base, cle, modele, False, max_tokens=budget_jetons(modele))
            ok, motif = _lire_reponse(corps)
            d.update(joignable=ok, motif=motif, limites=_limites(entetes))
            # Le refus des outils n'est PROUVE que si l'appel SANS outils reussit (vecu 16/10 : un modele absent, 404 avec
            # et sans outils, etait affiche « outils REFUSES ») ; sinon il reste INDETERMINE (None).
            if refus_avec_outils:
                d["outils"] = False
            return d
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                entetes_err = getattr(exc, "headers", None) or {}
                delai = extraire_delai_rate_limit(entetes_err)
                if delai is None:
                    delai = extraire_delai_rate_limit(dict(_limites(entetes_err)))
                if delai is not None and delai <= 30.0 and tentatives_restantes > 0:
                    tentatives_restantes -= 1
                    time.sleep(delai)
                    continue
                if delai is not None and delai > 30.0:
                    consigner_quota_epuise(nom_fournisseur, modele, f"HTTP 429 retry-after={delai}s")
                    d.update(motif=_motif_http(exc.code), limites=_limites(exc.headers or {}),
                             etat="QUOTA_EPUISE")
                    return d
                d.update(motif=_motif_http(exc.code), limites=_limites(exc.headers or {}),
                         etat=_etat_http(exc.code, _corps_erreur(exc)))
                return d
            if exc.code == 402:
                d.update(motif=_motif_http(exc.code), limites=_limites(exc.headers or {}),
                         etat="SANS_SOLDE")
                return d
            d.update(motif=_motif_http(exc.code), limites=_limites(exc.headers or {}),
                     etat=_etat_http(exc.code, _corps_erreur(exc)))
            return d
        except Exception as exc:  # noqa: BLE001
            d["motif"] = type(exc).__name__
            return d



def joignable(base: str, cle: str, modele: str, fournisseur: str | None = None) -> tuple[bool, str]:
    d = sonder(base, cle, modele, fournisseur=fournisseur)
    return d["joignable"], d["motif"]


def quota(etiquette: str, cle: str, entetes: dict) -> str:
    """Ce que le fournisseur EXPOSE. Jamais une estimation."""
    for nom, valeur in entetes.items():
        if "ratelimit" in nom.lower() and "remaining" in nom.lower():
            return f"{nom}={valeur}"
    if etiquette == "openrouter" and cle:
        try:
            with urllib.request.urlopen(_req("https://openrouter.ai/api/v1/key", cle),
                                        timeout=TIMEOUT) as r:
                d = (json.loads(r.read().decode("utf-8", errors="replace")) or {}).get("data") or {}
                # Owner 16/10 : /key EXPOSE aussi le palier et le debit -- les dire, ou dire qu'ils manquent.
                palier = d.get("is_free_tier")
                rl = d.get("rate_limit") if isinstance(d.get("rate_limit"), dict) else None
                debit = (f"{rl.get('requests')}/{rl.get('interval')}" if rl and rl.get("requests") is not None
                         else "NON EXPOSE")
                return (f"usage={d.get('usage')} limite={d.get('limit')} "
                        f"restant={d.get('limit_remaining')} "
                        f"palier_gratuit={'INCONNU' if palier is None else palier} debit={debit}")
        except Exception:  # noqa: BLE001 - endpoint absent ou refuse
            return "NON MESURE (endpoint /key muet)"
    return "NON MESURE (le fournisseur ne l'expose pas)"


def comparer(precedent: dict, courant: list[dict]) -> list[str]:
    """Ce qui a BOUGE depuis la derniere passe — le coeur de l'adaptation.

    Un catalogue qui perd un modele ne previent personne : c'est l'appel suivant
    qui echoue, des semaines plus tard, et on accuse alors la cle. Comparer deux
    passes datees transforme cette panne differee en signal immediat.
    """
    if not precedent:
        return ["premiere passe : aucun point de comparaison"]
    avant = {f.get("fournisseur"): f for f in precedent.get("fournisseurs", [])}
    lignes = []
    for fiche in courant:
        nom = fiche.get("fournisseur")
        vieux = avant.get(nom)
        if not vieux:
            lignes.append(f"  + {nom} : nouveau dans le recensement")
            continue
        if vieux.get("etat") == "NON_MESURE" and fiche.get("etat") != "NON_MESURE":
            lignes.append(f"  ^ {nom} : REDEVENU mesurable")
        if fiche.get("etat") == "NON_MESURE" and vieux.get("etat") != "NON_MESURE":
            lignes.append(f"  ! {nom} : n'est PLUS mesurable (HTTP {fiche.get('code')})")
        d_av, d_ap = vieux.get("declares", 0), fiche.get("declares", 0)
        if d_av and d_ap and d_ap != d_av:
            signe = "+" if d_ap > d_av else "-"
            lignes.append(f"  {signe} {nom} : catalogue {d_av} -> {d_ap} modeles")
        g_av, g_ap = vieux.get("gratuits_annonces", 0), fiche.get("gratuits_annonces", 0)
        if g_av != g_ap:
            lignes.append(f"  $ {nom} : gratuits annonces {g_av} -> {g_ap}")
    for nom in avant:
        if not any(f.get("fournisseur") == nom for f in courant):
            lignes.append(f"  - {nom} : DISPARU du recensement")
    return lignes or ["  aucun changement depuis la passe precedente"]


def lire_cibles(argv) -> list[tuple[str, str]]:
    """`--cible fournisseur:modele,fournisseur:modele` -> [(fournisseur, modele), ...] ; [] sans l'option."""
    if "--cible" not in argv:
        return []
    i = argv.index("--cible")
    brut = argv[i + 1] if i + 1 < len(argv) else ""
    return [tuple(x.split(":", 1)) for x in brut.split(",") if ":" in x]  # type: ignore[misc]


def cibler(cibles) -> list[dict]:
    """Sonde des modeles NOMMES (owner 16/10 : une affirmation sans source -- « tel modele est gratuit chez tel
    fournisseur » -- se tranche par mesure). Pour chacun : DECLARE au catalogue de notre cle (None si le catalogue est
    illisible : jamais lu « absent »), JOIGNABLE par une completion reelle meme s'il n'est pas declare, quota expose."""
    from nokido_agent.app.forge_secrets import get_secret

    par_nom = {etiquette: (env_key, base) for etiquette, env_key, base in SURFACES}
    lus: dict = {}
    sortie = []
    cibles_fournisseurs_sautes: dict[str, str] = {}
    for fournisseur, modele in cibles:
        if fournisseur not in par_nom:
            sortie.append({"fournisseur": fournisseur, "modele": modele, "etat": "FOURNISSEUR_INCONNU"})
            continue
        env_key, base = par_nom[fournisseur]
        cle = (get_secret(env_key) or "") if env_key else ""
        # Check should_skip or missing key
        saute, etat_skip, motif_skip = verifier_et_sauter_fournisseur(fournisseur, env_key, cle)
        if saute:
            sortie.append({
                "fournisseur": fournisseur,
                "modele": modele,
                "etat": etat_skip,
                "motif": motif_skip,
                "code": -1
            })
            continue
        if fournisseur in A_LA_DEMANDE:   # 30/10 : jamais de completion = jamais de chargement juste-a-temps
            sortie.append({"fournisseur": fournisseur, "modele": modele, "etat": "A_LA_DEMANDE",
                           "motif": "completion non tentee (chargement juste-a-temps hors admission RAM)"})
            continue
        if fournisseur in cibles_fournisseurs_sautes:
            sortie.append({
                "fournisseur": fournisseur,
                "modele": modele,
                "etat": "SAUTE",
                "motif": cibles_fournisseurs_sautes[fournisseur],
                "code": -1
            })
            continue
        if fournisseur not in lus:
            lus[fournisseur] = _lire_catalogue(base, cle)
        code, modeles, entetes, detail = lus[fournisseur]
        # Catalogue illisible != modele absent (test_un_catalogue_illisible_ne_dit_pas_absent) : on SONDE quand meme,
        # declare=None ; la raison du catalogue est gardee dans l'entree (26/10).
        # For ollama_cloud, only consider FREE models
        if fournisseur == "ollama_cloud":
            modeles = [m for m in modeles if palier_ollama_cloud(str(m.get("id"))) == "FREE"]
        declare = (modele in {str(m.get("id")) for m in modeles}) if code == 200 else None
        if any(s["fournisseur"] == fournisseur and "joignable" in s for s in sortie):
            time.sleep(PAUSE_S)   # jamais deux appels colles au meme fournisseur
        d = sonder(base, cle, modele, outils=True, fournisseur=fournisseur)
        if d.get("etat") == "QUOTA_EPUISE" or "HTTP 429 retry-after=" in (d.get("motif") or ""):
            cibles_fournisseurs_sautes[fournisseur] = f"429 rate limit > 30s ({d.get('motif')})"
        entree_sortie = {"fournisseur": fournisseur, "modele": modele, "declare": declare,
                         "catalogue": "" if code == 200 else (detail or "HTTP %s" % code), "joignable": d["joignable"],
                         "motif": d["motif"], "outils": d["outils"], "limites": d["limites"],
                         "quota": quota(fournisseur, cle, entetes)}
        if d.get("etat"):
            entree_sortie["etat"] = d["etat"]
        sortie.append(entree_sortie)
    return sortie


def consigner(resultats, registre: dict) -> dict:
    """Verse les verdicts d'une passe ciblee au registre (RED 4 du plan AGY, owner 16/10 : « y en a marre de refaire ces
    enquetes ») : cle fournisseur:modele, horodatee ; la mesure la plus recente remplace l'ancienne, les autres et le
    recensement restent. Un resultat SANS mesure garde son etat, jamais un « joignable: false » fabrique (UNKNOWN != NO)."""
    verdicts = dict(registre.get("verdicts") or {})
    quand = time.strftime("%Y-%m-%dT%H:%M:%S")
    for r in resultats:
        cle = "%s:%s" % (r["fournisseur"], r["modele"])
        entree = {k: v for k, v in r.items() if k not in ("fournisseur", "modele")}
        entree["mesure_le"] = quand
        # RED6 (19/10) : persistance d'un echec = echecs CONSECUTIFS ; un succes remet a zero, un resultat sans mesure
        # (joignable ni True ni False) ne touche pas au compteur.
        avant = verdicts.get(cle) or {}
        if entree.get("joignable") is False:
            entree["echecs_consecutifs"] = (int(avant.get("echecs_consecutifs") or 0)
                                            if avant.get("joignable") is False else 0) + 1
        elif entree.get("joignable") is True:
            entree["echecs_consecutifs"] = 0
        elif "echecs_consecutifs" in avant:
            entree["echecs_consecutifs"] = avant["echecs_consecutifs"]
        verdicts[cle] = entree
    return {**registre, "verdicts": verdicts}


REGISTRE_UNIFIE = ROOT / "data" / "surfaces_free_tier_registry.json"


def _spec_de(fournisseur: str, specs: dict) -> dict | None:
    """Fiche forge_provider_specs du fournisseur : cle exacte, sinon cle prefixee (`ollama` -> `ollama_local`)."""
    if fournisseur in specs:
        return specs[fournisseur]
    return next((v for k, v in specs.items() if k.startswith(fournisseur + "_")), None)


def registre_unifie(census: dict, specs: dict) -> dict:
    """RED4 (plan 60d8ed546, releve AGY job_6cfab01f) : registre UNIFIE des surfaces fournisseur:modele.

    Fusion des verdicts et des preuves du recensement avec forge_provider_specs. Liste BLANCHE : GRATUIT_PROUVE seulement
    si la surface est JOIGNABLE et son tier gratuit/local ; PAYANT_PROUVE sur un 402 ; tout le reste INCONNU. Une valeur
    non mesuree vaut None (acces_cli n'est mesure nulle part a ce jour)."""
    census = census or {}
    brutes = {}
    for f in census.get("fournisseurs") or []:
        for p in (f or {}).get("preuves") or []:
            cle = "%s:%s" % (f.get("fournisseur"), p.get("modele"))
            brutes[cle] = {"joignable": p.get("joignable"), "motif": p.get("motif"), "quota": f.get("quota"),
                           "mesure_le": census.get("horodatage")}
    for cle, v in (census.get("verdicts") or {}).items():
        brutes[cle] = dict(brutes.get(cle) or {}, **(v or {}))
    surfaces = []
    for cle, v in sorted(brutes.items()):
        fournisseur, _, modele = cle.partition(":")
        spec = _spec_de(fournisseur, specs or {})
        tier = str((spec or {}).get("tier") or "")
        if v.get("joignable") is True and tier in ("free", "local"):
            statut = "GRATUIT_PROUVE"
        elif str(v.get("motif") or "").startswith("HTTP 402"):
            statut = "PAYANT_PROUVE"
        else:
            statut = "INCONNU"
        surfaces.append({
            "fournisseur": fournisseur, "modele": modele, "statut_gratuit": statut,
            "declare": v.get("declare"), "gratuit_annonce": True if tier in ("free", "local") else None,
            "joignable": v.get("joignable"), "quota_primaire": v.get("quota"),
            "specialite": (spec or {}).get("notes"), "capabilities": (spec or {}).get("capabilities"),
            "acces_cli": None, "acces_swarm": True if spec else None,
            "outils_supportes": v.get("outils"), "mesure_le": v.get("mesure_le"),
            "dimensions": v.get("dimensions") or fiche_dimensions()})
    totaux = {"surfaces": len(surfaces),
              "joignables": sum(1 for s in surfaces if s["joignable"] is True),
              "gratuits_prouves": sum(1 for s in surfaces if s["statut_gratuit"] == "GRATUIT_PROUVE"),
              "inconnus": sum(1 for s in surfaces if s["statut_gratuit"] == "INCONNU")}
    return {"version_schema": "1", "horodatage": census.get("horodatage"), "surfaces": surfaces, "totaux": totaux}


# ---------------------------------------------------------------------------------------------------------------------
# Dimensions MESUREES et DISTINCTES par `fournisseur:modele` (owner 23/10) : specialite, force par specialite, effet de
# l'effort. Etat OBSERVE (date + echantillon) | DECLARE (source citee, jamais une mesure) | UNKNOWN (aucune valeur).
# Rapport : sandbox/workspace/rapport_calibration_effort_census_20261023.md
# ---------------------------------------------------------------------------------------------------------------------
SPECIALITES = ("code", "raisonnement", "outils", "vision", "voix")
ETATS_DIMENSION = ("OBSERVE", "DECLARE", "UNKNOWN")

# Plan des bancs (deterministes, juge non-LLM). Rien ici n'EXECUTE un banc : c'est un plan chiffrable.
BANCS = dict(
    code=dict(items=18, tokens_entree=700, tokens_sortie=500, juge="deterministe"),
    raisonnement=dict(items=15, tokens_entree=250, tokens_sortie=1500, juge="deterministe"),
    outils=dict(items=10, tokens_entree=600, tokens_sortie=120, juge="deterministe"),
    vision=dict(items=8, tokens_entree=1200, tokens_sortie=60, juge="deterministe"),
    voix=dict(items=6, tokens_entree=600, tokens_sortie=100, juge="deterministe"),
    effort=dict(items=6, repetitions=3, niveaux=("low", "medium", "high"),
                tokens_entree=1500, tokens_sortie=2500, juge="deterministe"),
)

# Cibles des bancs : TOUS les LLM joignables, pas seulement Claude (surface CLI ou modele cloud du swarm).
# INDISPONIBLE = mesure impossible maintenant, avec MOTIF ; ce n'est ni un 0 ni un echec du modele.
SURFACES_CIBLES = {
    "cli:claude": {"genre": "cli", "etat": "DISPONIBLE", "effort": "cli_flag"},
    "cli:vibe": {"genre": "cli", "etat": "DISPONIBLE", "effort": "UNKNOWN"},
    "local:ollama": {"genre": "local", "etat": "DISPONIBLE", "effort": "UNKNOWN"},
    "cli:agy": {"genre": "cli", "etat": "INDISPONIBLE", "motif": "quota epuise quelques heures"},
    "cli:codex": {"genre": "cli", "etat": "INDISPONIBLE", "motif": "quota quasi vide, mode headless incertain"},
    "swarm:forge_agent_proxy": {"genre": "cloud", "etat": "DISPONIBLE", "effort": "reasoning_effort"},
    "swarm:free_tier": {"genre": "cloud", "etat": "DISPONIBLE", "effort": "reasoning_effort"},
}
# Fournisseurs dont l'API accepte `reasoning_effort` (declare ; a confirmer par un appel reel, jamais OBSERVE d'office).
FOURNISSEURS_REASONING_EFFORT = ("openai", "groq", "openrouter", "mistral", "deepinfra", "nvidia", "zai", "mammouth")


def surface_cible(cle: str) -> dict:
    """Etat d'une surface visee par les bancs : DISPONIBLE | INDISPONIBLE(motif) | INCONNUE. Jamais un 0 fabrique."""
    s = SURFACES_CIBLES.get(cle)
    if s is None:
        return {"etat": "INCONNUE", "motif": "surface hors plan"}
    return dict(s)


def parametre_effort(fournisseur: str, surface: str | None = None) -> str:
    """`reasoning_effort` (API) si le fournisseur le supporte, flag CLI pour claude, sinon UNKNOWN."""
    if surface == "cli:claude":
        return "cli_flag"
    if surface and surface.startswith("cli:"):
        return "UNKNOWN"
    return "reasoning_effort" if fournisseur in FOURNISSEURS_REASONING_EFFORT else "UNKNOWN"


def dimension(etat: str, valeur=None, mesure_le=None, echantillon: int = 0, source=None) -> dict:
    if etat not in ETATS_DIMENSION:
        raise ValueError("etat hors liste blanche : %r" % (etat,))
    if etat == "OBSERVE":
        if valeur is None or not mesure_le or not echantillon or echantillon < 1:
            raise ValueError("OBSERVE exige valeur, mesure_le et echantillon >= 1")
    elif etat == "DECLARE":
        if echantillon:
            raise ValueError("un declare ne cite pas d'echantillon")
        if not source:
            raise ValueError("un declare exige une source")
        mesure_le, echantillon = None, 0
    else:
        if valeur is not None:
            raise ValueError("UNKNOWN ne porte aucune valeur")
        mesure_le, echantillon = None, 0
    return {"etat": etat, "valeur": valeur, "mesure_le": mesure_le, "echantillon": int(echantillon or 0),
            "source": source}


def _effort_vierge(raison: str = "aucune mesure") -> dict:
    return {"etat": "UNKNOWN", "valeur": None, "mesure_le": None, "echantillon": 0, "source": None,
            "niveaux": {}, "raison": raison}


def effet_effort(mesures, mesure_le) -> dict:
    """Meme tache a efforts differents : cout, latence, reussite par niveau. Un seul niveau ne compare rien."""
    import statistics
    par = {}
    for m in mesures or []:
        par.setdefault(m["effort"], []).append(m)
    if len(par) < 2:
        return _effort_vierge("moins de 2 niveaux d'effort : rien a comparer")
    niveaux = {}
    for nom, ms in par.items():
        couts = [m["cout_usd"] for m in ms if m.get("cout_usd") is not None]
        lats = [m["latence_ms"] for m in ms if m.get("latence_ms") is not None]
        niveaux[nom] = {"n": len(ms),
                        "latence_ms_mediane": statistics.median(lats) if lats else None,
                        "taux_reussite": sum(1 for m in ms if m.get("reussi")) / len(ms),
                        "cout_usd_moyen": sum(couts) / len(couts) if couts else None}
    n = sum(len(v) for v in par.values())
    return {"etat": "OBSERVE", "valeur": None, "mesure_le": mesure_le, "echantillon": n, "source": None,
            "niveaux": niveaux, "raison": None}


def fiche_dimensions(observes=None, declare=None) -> dict:
    """Fiche vierge (UNKNOWN partout) enrichie. Une force mesuree (juge deterministe) prouve la specialite ; un declare
    n'en dit rien sur la force et ne devient jamais OBSERVE."""
    observes, declare = observes or {}, declare or {}
    fiche = {"specialite": {s: dimension("UNKNOWN") for s in SPECIALITES},
             "force": {s: dimension("UNKNOWN") for s in SPECIALITES},
             "effort": _effort_vierge()}
    for spec, source in (declare.get("specialite") or {}).items():
        if spec not in SPECIALITES:
            raise ValueError("specialite inconnue : %r" % (spec,))
        fiche["specialite"][spec] = dimension("DECLARE", valeur=True, source=source)
    for spec, o in (observes.get("force") or {}).items():
        if spec not in SPECIALITES:
            raise ValueError("specialite inconnue : %r" % (spec,))
        if o.get("juge") != "deterministe":
            raise ValueError("une force exige un juge deterministe, recu %r" % (o.get("juge"),))
        n = o.get("echantillon") or 0
        fiche["force"][spec] = dimension("OBSERVE", valeur=o.get("valeur"), mesure_le=o.get("mesure_le"),
                                         echantillon=n, source=o.get("juge"))
        fiche["specialite"][spec] = dimension("OBSERVE", valeur=True, mesure_le=o.get("mesure_le"),
                                              echantillon=n, source="force mesuree")
    if observes.get("effort"):
        fiche["effort"] = observes["effort"]
    return fiche


def consigner_dimensions(resultats: dict, registre: dict) -> dict:
    """Verse les fiches sous verdicts[cle]['dimensions']. Une dimension UNKNOWN n'ecrase JAMAIS une mesure anterieure
    (UNKNOWN != NO) ; une dimension mesuree ou declaree remplace l'ancienne. Le verdict joignable reste intact."""
    if not resultats:
        return registre
    verdicts = dict(registre.get("verdicts") or {})
    for cle, fiche in resultats.items():
        entree = dict(verdicts.get(cle) or {})
        anc = entree.get("dimensions") or fiche_dimensions()
        fusion = {"specialite": dict(anc.get("specialite") or {}), "force": dict(anc.get("force") or {}),
                  "effort": anc.get("effort") or _effort_vierge()}
        for groupe in ("specialite", "force"):
            for spec, d in (fiche.get(groupe) or {}).items():
                if d.get("etat") != "UNKNOWN" or spec not in fusion[groupe]:
                    fusion[groupe][spec] = d
        if (fiche.get("effort") or {}).get("etat") != "UNKNOWN":
            fusion["effort"] = fiche["effort"]
        entree["dimensions"] = fusion
        verdicts[cle] = entree
    return {**registre, "verdicts": verdicts}


def passe_dimensions(cibles, en_ligne=None, banc=None) -> dict:
    """Hors ligne : HORS_LIGNE, aucun resultat (pas de faux echec). `banc(fournisseur, modele)` est injecte par
    l'appelant et rend une fiche ; sans banc, rien n'est mesure (aucun banc n'est lance par ce module)."""
    if en_ligne is not None and not en_ligne():
        return {"etat": "HORS_LIGNE", "resultats": {}}
    resultats = {}
    if banc is not None:
        for fournisseur, modele in cibles:
            resultats["%s:%s" % (fournisseur, modele)] = banc(fournisseur, modele)
    return {"etat": "OK", "resultats": resultats}


def cout_estime_banc(specialite: str, prix_entree_usd_mtok, prix_sortie_usd_mtok) -> dict:
    """ESTIMATION du cout d'un banc (jamais une mesure). Prix inconnu -> cout inconnu (None), jamais 0."""
    b = BANCS[specialite]
    appels = b["items"]
    if specialite == "effort":
        appels = b["items"] * b["repetitions"] * len(b["niveaux"])
    if prix_entree_usd_mtok is None or prix_sortie_usd_mtok is None:
        usd = None
    else:
        usd = appels * (b["tokens_entree"] * prix_entree_usd_mtok + b["tokens_sortie"] * prix_sortie_usd_mtok) / 1e6
    return {"usd": usd, "appels": appels, "nature": "ESTIMATION"}


# ---------------------------------------------------------------------------------------------------------------------
# Lanceur des bancs (owner 23/10, GO force + effort). Point d'entree :
#   python tools/forge_free_tier_census.py --dimensions <cibles> --bancs <liste> --sortie <json> [--budget c=usd,...] [--dry-run]
# Juges DETERMINISTES (tests caches hors ligne, reponse exacte, egalite JSON). Les donnees sont dans
# forge_free_tier_census_bancs.py. Rapport : sandbox/workspace/rapport_bancs_census_20261023.md
# ---------------------------------------------------------------------------------------------------------------------
class Limite429(Exception):
    """Le fournisseur refuse pour quota : la cible est INDISPONIBLE (nommee), le modele n'a RIEN rate."""


class BinaireAbsent(Exception):
    """Le binaire de la surface est introuvable sous ce compte : INDISPONIBLE nomme, jamais ERREUR muette."""


LOCAL_OLLAMA_UNITES = ("qwen2.5-coder:7b",)   # unite S de la table de paliers ; sa mesure decidera, la table ne bouge pas


def resoudre_chemin(p) -> Path:
    """Un chemin relatif se resout contre la RACINE du depot (jamais le cwd du job : sandbox/workspace/sandbox/...)."""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def avec_contexte(doc: dict) -> dict:
    """En-tete `contexte_execution` : une mesure ne vaut que pour le compte/profil/reseau qui l'a produite."""
    return {**doc, "contexte_execution": contexte_execution()}


def _binaire_vibe() -> str | None:
    """Comme l'executeur (forge_task_executor._bin_vibe) : LAFORGE_VIBE_BIN, sinon ~/.local/bin/vibe.exe sous
    LAFORGE_AGENT_HOME, sinon le PATH. None si rien n'existe."""
    import os
    import shutil
    env = os.environ.get("LAFORGE_VIBE_BIN")
    if env and Path(env).exists():
        return str(env)
    home = os.environ.get("LAFORGE_AGENT_HOME", os.path.expanduser("~"))
    absolu = Path(home) / ".local" / "bin" / "vibe.exe"
    if absolu.exists():
        return str(absolu)
    return shutil.which("vibe")


def _cle_registre(cible: str, modele: str) -> str:
    return modele if cible == "swarm:free_tier" else "%s:%s" % (cible, modele)


def consigner_fichier_resultats(chemin, registre=None) -> int:
    """Verse au registre (census) les fiches d'un fichier de resultats des bancs. Rend le nombre de fiches versees ;
    fichier illisible -> 0 et le registre n'est PAS touche."""
    registre = Path(registre) if registre is not None else SORTIE
    try:
        doc = json.loads(Path(chemin).read_text(encoding="utf-8"))
        fiches = {}
        for cible, c in (doc.get("cibles") or {}).items():
            for modele, u in (c.get("unites") or {}).items():
                if u.get("fiche"):
                    fiches[_cle_registre(cible, modele)] = u["fiche"]
    except (OSError, ValueError, AttributeError):
        return 0
    if not fiches:
        return 0
    try:
        reg = json.loads(registre.read_text(encoding="utf-8")) if registre.exists() else {}
    except (OSError, ValueError):
        print("registre ILLISIBLE : %s non touche" % registre)
        return 0
    reg = consigner_dimensions(fiches, reg)
    registre.parent.mkdir(parents=True, exist_ok=True)
    registre.write_text(json.dumps(reg, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return len(fiches)


MOTIF_FAUX_ZERO = ("faux 0.0 : reponses d'erreur du proxy (ok:false/texte d'erreur/vide) jugees comme mauvaises "
                   "reponses ; corrige par _appel_proxy/ProxyErreur (rapport_bancs_faux_zero_20261024.md)")


def invalider_faux_zeros(registre, unites, cible="swarm:forge_agent_proxy") -> int:
    """Marque INVALIDE (sans rien supprimer) les fiches OBSERVE des unites listees. Rend le nombre de fiches marquees."""
    registre = Path(registre)
    try:
        reg = json.loads(registre.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for modele in unites:
        f = reg.get(_cle_registre(cible, modele))
        if isinstance(f, dict) and "invalide" not in f:
            f["invalide"] = {"motif": MOTIF_FAUX_ZERO, "le": time.strftime("%Y-%m-%dT%H:%M:%S")}
            n += 1
    if n:
        registre.write_text(json.dumps(reg, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return n


def main_consigner(argv, registre=None) -> int:
    """`--consigner <resultats.json>` : consigne un fichier de resultats existant dans le census."""
    if not argv:
        print("--consigner <resultats.json> requis")
        return 2
    chemin = resoudre_chemin(argv[0])
    if not chemin.exists():
        print("fichier de resultats absent : %s" % chemin)
        return 1
    n = consigner_fichier_resultats(chemin, registre)
    print("%d fiche(s) consignee(s) dans %s" % (n, registre or SORTIE))
    return 0 if n else 1


class ProxyErreur(RuntimeError):
    """Le proxy n'a pas rendu de reponse (ok:false, erreur, vide) : erreur hors denominateur, pas un echec du modele."""


class NonSupporte(Exception):
    """La surface ne porte pas ce banc (image, outils, effort) : UNKNOWN avec motif, jamais un 0."""


CLAUDE_MODELES = ("haiku", "sonnet", "opus")
# Prix publics en HYPOTHESE (rapport 23/10 : sonnet 3/15, haiku 1/5 et opus 15/75 a confirmer) ; le CLI charge un
# contexte (~0,07 USD/appel mesure). Palier gratuit : 0 USD (cout = quota). vibe : prix inconnu -> None.
PRIX_USD_MTOK = {"haiku": (1.0, 5.0), "sonnet": (3.0, 15.0), "opus": (15.0, 75.0)}
SURCOUT_CLI_CLAUDE_USD = 0.07
BANCS_DE_FORCE = ("code", "raisonnement", "outils", "vision")
ARRET_ERREURS_CONSECUTIVES = 3


def _bancs_data():
    import forge_free_tier_census_bancs as D
    return D


def _sans_accent(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")


_SCRIPT_JUGE_CODE = r'''
import json, socket, sys
def _hors_ligne(*a, **k):
    raise OSError("hors ligne")
socket.socket.connect = _hors_ligne
socket.create_connection = _hors_ligne
socket.getaddrinfo = _hors_ligne
p = json.loads(sys.stdin.read())
ns = {}
exec(compile(p["code"], "<reponse>", "exec"), ns)
f = ns[p["fonction"]]
for args, attendu in p["tests"]:
    r = f(*args)
    if r != attendu or isinstance(r, bool) != isinstance(attendu, bool):
        sys.exit(1)
sys.exit(0)
'''


def juge_code(item: dict, texte) -> bool:
    """Execute les tests CACHES de l'item sur le code rendu, dans un sous-processus isole (-I, dossier vide, reseau
    coupe, env minimal, 10 s). Vert = tous les tests passent. Tout le reste (absent, faux, boucle, exception) = faux."""
    import os
    import re
    import subprocess
    import tempfile
    t = str(texte or "")
    m = re.findall(r"```(?:python|py)?[ \t]*\n(.*?)```", t, re.S)
    code = max(m, key=len) if m else t
    if not code.strip():
        return False
    env = {k: v for k, v in os.environ.items() if k.upper() in ("SYSTEMROOT", "PATH", "TEMP", "TMP", "COMSPEC")}
    env["PYTHONIOENCODING"] = "utf-8"
    payload = json.dumps({"code": code, "fonction": item["fonction"], "tests": item["tests"]})
    try:
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-I", "-c", _SCRIPT_JUGE_CODE], input=payload, text=True, encoding="utf-8", errors="replace", cwd=d,
                               env=env, capture_output=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


def juge_exact(item: dict, texte) -> bool:
    """Reponse exacte : apres le DERNIER « Reponse finale : », sinon la derniere ligne ; premier mot, casse, accents et
    ponctuation ignores. « 1650 » n'est pas « 165 »."""
    import re
    t = _sans_accent(str(texte or "")).lower()
    trouve = re.findall(r"reponse\s+finale\s*:(.*)", t)
    segment = trouve[-1] if trouve else (next((l for l in reversed(t.splitlines()) if l.strip()), ""))
    mots = segment.strip(" *_`<>()[]\"'.,;:!?\t").split()
    if not mots:
        return False
    return mots[0].strip(" *_`<>()[]\"'.,;:!?") == _sans_accent(str(item["reponse"])).lower()


def juge_outils(item: dict, tool_calls) -> bool:
    """Un seul appel d'outil, nom ET arguments egaux (JSON, ordre libre) a l'attendu."""
    if not isinstance(tool_calls, list) or len(tool_calls) != 1 or not isinstance(tool_calls[0], dict):
        return False
    c = tool_calls[0]
    args = c.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return False
    return c.get("name") == item["attendu"]["name"] and args == item["attendu"]["arguments"]


def tier_proxy(nom: str):
    """cost_tier du registre du proxy (0 = gratuit/local/abonnement). Illisible -> None (jamais suppose gratuit)."""
    try:
        t = getattr(_registre_proxy()[nom], "cost_tier")
    except Exception:  # noqa: BLE001 - registre/hub/attribut illisible
        return None
    return t if isinstance(t, int) and not isinstance(t, bool) and t >= 0 else None


# Le registre range ces fournisseurs en cost_tier 0 sans attribut distinctif (pas de kind/is_cli) : liste nommee.
# Jamais mesures dans un banc, meme avec --inclure-payants (quota owner / mort / depense indirecte).
EXCLUS_PROXY = {
    "claude_agent_sdk": "abonnement : quota owner",
    "claude_cli": "abonnement : quota owner",
    "codex_cli": "abonnement : quota owner",
    "copilot_cli": "abonnement : quota owner",
    "gemini_cli": "client mort",
    "router": "meta-routeur : non mesurable, depense indirecte",
    "router_local": "meta-routeur : non mesurable, depense indirecte",
    "swarm": "meta-routeur : non mesurable, depense indirecte",
    "agent": "meta-routeur : non mesurable, depense indirecte",
    "nervous": "meta-routeur : non mesurable, depense indirecte",
}


def filtrer_proxy(noms, inclure_payants: bool = False) -> tuple[list[str], list[tuple[str, str]]]:
    """(retenus, [(exclu, motif)]) : par defaut cost_tier 0 seulement ; illisible, abonnement, mort, meta-routeur EXCLUS."""
    retenus, exclus = [], []
    for n in noms:
        if n in EXCLUS_PROXY:
            exclus.append((n, EXCLUS_PROXY[n]))
            continue
        t = tier_proxy(n)
        if t is None:
            exclus.append((n, "cout illisible (fail-closed)"))
        elif t == 0 or inclure_payants:
            retenus.append(n)
        else:
            exclus.append((n, "payant (cost_tier %d), --inclure-payants absent" % t))
    return retenus, exclus


def unites_de(cible: str, inclure_payants: bool = False) -> list[str]:
    """Modeles/membres d'une cible, LUS sans appel : claude = haiku/sonnet/opus ; vibe = vibe ; free_tier = couples
    joignables du census ; proxy = providers du registre. Illisible -> [] (jamais invente)."""
    if cible == "cli:claude":
        return list(CLAUDE_MODELES)
    if cible == "cli:vibe":
        return ["vibe"]
    if cible == "local:ollama":
        return list(LOCAL_OLLAMA_UNITES)
    try:
        if cible == "swarm:free_tier":
            doc = json.loads(SORTIE.read_text(encoding="utf-8"))
            return ["%s:%s" % (f, m) for f, ms in sorted(candidats_frais(doc, max_age_s=7 * 86400).items()) for m in ms]
        if cible == "swarm:forge_agent_proxy":
            return filtrer_proxy(sorted(_registre_proxy()), inclure_payants)[0]
    except Exception:  # noqa: BLE001 - registre absent ou hub non importable : aucune unite lisible, dit par le plan
        return []
    return []


def effort_supporte(cible: str, modele: str) -> bool:
    if cible == "cli:claude":
        return True
    if cible == "swarm:free_tier":
        return parametre_effort(modele.split(":", 1)[0], cible) == "reasoning_effort"
    return False


def _prix_de(cible: str, modele: str):
    if cible == "cli:claude":
        return PRIX_USD_MTOK.get(modele)
    if cible in ("swarm:free_tier", "local:ollama"):
        return (0.0, 0.0)
    if cible == "swarm:forge_agent_proxy":
        return (0.0, 0.0) if tier_proxy(modele) == 0 else None  # payant/illisible : cout INCONNU, jamais 0
    return None


def _appels_et_cout(cible: str, modele: str, bancs) -> tuple[int, float | None]:
    prix = _prix_de(cible, modele)
    appels, usd = 0, 0.0
    for b in bancs:
        if b == "voix" or (b == "effort" and not effort_supporte(cible, modele)):
            continue
        e = cout_estime_banc(b, *(prix or (None, None)))
        appels += e["appels"]
        usd = None if (usd is None or e["usd"] is None) else usd + e["usd"]
    if usd is not None and cible == "cli:claude":
        usd += appels * SURCOUT_CLI_CLAUDE_USD
    return appels, usd


def plan_bancs(cibles, bancs, unites=None, budgets=None, inclure_payants: bool = False) -> dict:
    """Chiffre le lancement SANS aucun appel : appels et cout ESTIME par cible (None = inconnu, jamais 0)."""
    sortie = {}
    for cible in cibles:
        s = surface_cible(cible)
        if s["etat"] != "DISPONIBLE":
            sortie[cible] = {"etat": s["etat"], "motif": s.get("motif"), "appels": 0, "cout_usd_estime": None,
                             "nature": "ESTIMATION", "unites": []}
            continue
        us = list((unites or {}).get(cible) or unites_de(cible, inclure_payants)) if unites is None or cible in unites else []
        appels, usd, inconnus = 0, 0.0, 0
        for m in us:
            a, u = _appels_et_cout(cible, m, bancs)
            appels += a
            inconnus += a if u is None else 0
            usd = None if (usd is None or u is None) else usd + u
        budget = (budgets or {}).get(cible)
        sortie[cible] = {"etat": "DISPONIBLE", "motif": None if us else "aucune unite lisible", "unites": us,
                         "appels": appels, "cout_usd_estime": usd, "nature": "ESTIMATION", "budget_usd": budget, "appels_cout_inconnu": inconnus,
                         "budget_depasse_par_estimation": bool(budget is not None and usd is not None and usd > budget)}
    return {"bancs": list(bancs), "cibles": sortie}


def _banc_vide(nom: str, prevus: int, etat="UNKNOWN", motif=None) -> dict:
    return {"etat": etat, "valeur": None, "reussis": 0, "echantillon": 0, "erreurs": 0, "items_prevus": prevus,
            "juge": "deterministe", "motif": motif}


def _requetes(nom: str, D):
    """(item, requete) pour un banc de force. Une requete ne porte que le banc : aucune donnee du projet."""
    if nom == "code":
        return [(i, {"banc": nom, "item_id": i["id"], "prompt": i["prompt"] + " Reponds uniquement par le code Python.",
                     "max_tokens": 600}) for i in D.CODE]
    if nom == "raisonnement":
        return [(i, {"banc": nom, "item_id": i["id"], "prompt": i["prompt"], "max_tokens": 1500}) for i in D.RAISONNEMENT]
    if nom == "outils":
        return [(i, {"banc": nom, "item_id": i["id"], "prompt": i["prompt"], "tools": D.OUTILS_SCHEMAS,
                     "max_tokens": 200}) for i in D.OUTILS]
    return [(i, {"banc": nom, "item_id": i["id"], "prompt": i["prompt"], "image": D.image_vision(i),
                 "max_tokens": 200}) for i in D.VISION]


class _ArretCible(Exception):
    pass


def lancer_bancs(cibles, bancs, appel, budgets=None, unites=None, sleep=time.sleep, maintenant=None, apres_unite=None,
                 horloge=time.monotonic) -> dict:
    """Execute les bancs. `appel(cible, modele, requete) -> {texte, tool_calls, cout_usd}` est INJECTE (factice en test).
    429 -> unite INDISPONIBLE nommee, pas un echec ; budget (USD reels cumules par cible) atteint -> arret de la cible ;
    PAUSE_S entre deux appels de la meme cible ; cout inconnu compte a part, jamais 0."""
    D = _bancs_data()
    mesure_le = maintenant or time.strftime("%Y-%m-%dT%H:%M:%S")
    budgets = budgets or {}
    doc = {"mesure_le": mesure_le, "bancs": list(bancs), "cibles": {}}
    for cible in cibles:
        s = surface_cible(cible)
        if s["etat"] != "DISPONIBLE":
            doc["cibles"][cible] = {"etat": s["etat"], "motif": s.get("motif"), "unites": {}, "appels": 0}
            continue
        st = {"appels": 0, "cout": 0.0, "connus": 0, "inconnus": 0, "appele": False}
        budget = budgets.get(cible)
        c = {"etat": "OK", "motif": None, "unites": {}, "budget_usd": budget}
        doc["cibles"][cible] = c

        def un_appel(modele, req, st=st, cible=cible, budget=budget):
            if budget is not None and (budget <= 0 or (st["connus"] and st["cout"] >= budget - 1e-9)):
                raise _ArretCible()
            if st["appele"]:
                sleep(PAUSE_S)
            st["appele"] = True
            st["appels"] += 1
            t0 = horloge()
            r = appel(cible, modele, req) or {}
            cout = r.get("cout_usd")
            if cout is None:
                st["inconnus"] += 1
            else:
                st["cout"] += cout
                st["connus"] += 1
            return r, cout, int((horloge() - t0) * 1000)

        liste = list((unites or {}).get(cible) or []) if unites is not None else unites_de(cible)
        try:
            for modele in liste:
                u = {"etat": "OK", "motif": None, "bancs": {}, "effort": _effort_vierge("banc effort non demande")}
                c["unites"][modele] = u
                try:
                    _banc_unite(cible, modele, bancs, u, un_appel, D, mesure_le)
                except Limite429 as exc:
                    u["etat"], u["motif"] = "INDISPONIBLE", "429 : %s" % exc
                except BinaireAbsent as exc:
                    u["etat"], u["motif"] = "INDISPONIBLE", str(exc)
                except _ArretCible:
                    u["fiche"] = _fiche_unite(u, mesure_le)
                    raise
                u["fiche"] = _fiche_unite(u, mesure_le)
                if apres_unite:
                    apres_unite(doc)
        except _ArretCible:
            c["etat"] = "BUDGET_ATTEINT"
            c["motif"] = "budget %s USD atteint" % budget
        c["appels"] = st["appels"]
        c["cout_usd"] = st["cout"] if (st["connus"] or not st["inconnus"]) else None
        c["appels_cout_inconnu"] = st["inconnus"]
        if c["etat"] == "OK" and c["unites"] and all(v["etat"] == "INDISPONIBLE" for v in c["unites"].values()):
            c["etat"], c["motif"] = "INDISPONIBLE", "429 sur toutes les unites"
    return doc


def _banc_unite(cible, modele, bancs, u, un_appel, D, mesure_le) -> None:
    consecutives = {"n": 0}

    def jouer(nom, req, juge):
        """-> (reussi|None, cout, latence). None = erreur hors modele (hors denominateur)."""
        try:
            r, cout, ms = un_appel(modele, req)
        except (Limite429, NonSupporte, BinaireAbsent, _ArretCible):
            raise
        except Exception as exc:  # noqa: BLE001 - reseau, binaire absent, JSON illisible : pas un echec du modele
            consecutives["n"] += 1
            if consecutives["n"] >= ARRET_ERREURS_CONSECUTIVES:
                u["etat"], u["motif"] = "ERREUR", "%d erreurs consecutives (%s)" % (consecutives["n"], type(exc).__name__)
                raise _ArretUnite() from exc
            return None, None, None, ("%s: %s" % (type(exc).__name__, exc))[:200]
        consecutives["n"] = 0
        return bool(juge(r)), cout, ms, None

    try:
        for nom in bancs:
            if nom == "voix":
                u["bancs"]["voix"] = _banc_vide("voix", BANCS["voix"]["items"], motif="UNKNOWN assume (owner 23/10)")
                continue
            if nom == "effort":
                _banc_effort(cible, modele, u, jouer, D, mesure_le)
                continue
            items = _requetes(nom, D)
            b = _banc_vide(nom, len(items))
            u["bancs"][nom] = b
            for item, req in items:
                if nom == "code":
                    juge = (lambda r, item=item: juge_code(item, r.get("texte")))
                elif nom == "outils":
                    juge = (lambda r, item=item: juge_outils(item, r.get("tool_calls")))
                else:
                    juge = (lambda r, item=item: juge_exact(item, r.get("texte")))
                try:
                    ok, _cout, _ms, motif = jouer(nom, req, juge)
                except NonSupporte as exc:
                    b["motif"] = str(exc)
                    break
                finally:
                    _maj_banc(b)
                if ok is None:
                    b["erreurs"] += 1
                    b["motif"] = motif
                else:
                    b["echantillon"] += 1
                    b["reussis"] += 1 if ok else 0
                _maj_banc(b)
            # Après chaque banc, vérifier s'il y a des erreurs mais aucun échantillon exploitable
            bs = list(u["bancs"].values())
            if bs and u["etat"] in ("OK", "ERREUR") and sum(b["erreurs"] for b in bs) and not any(b["echantillon"] for b in bs):
                # toutes les reponses sont des erreurs : l'unite est INDISPONIBLE (motif nomme), pas a 0.0
                motif = next((b["motif"] for b in bs if b["erreurs"] and b["motif"]), None) or u.get("motif") or "erreur"
                u["etat"], u["motif"] = "INDISPONIBLE", "%d reponse(s) en erreur, aucune exploitable : %s" % (
                    sum(b["erreurs"] for b in bs), motif)
    except _ArretUnite:
        __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_free_tier_census.py', 1095, exc_info=True)
    finally:
        for b in u["bancs"].values():
            _maj_banc(b)
        bs = list(u["bancs"].values())
        if bs and u["etat"] in ("OK", "ERREUR") and sum(b["erreurs"] for b in bs) and not any(b["echantillon"] for b in bs):
            # toutes les reponses sont des erreurs : l'unite est INDISPONIBLE (motif nomme), pas a 0.0
            motif = next((b["motif"] for b in bs if b["erreurs"] and b["motif"]), None) or u.get("motif") or "erreur"
            u["etat"], u["motif"] = "INDISPONIBLE", "%d reponse(s) en erreur, aucune exploitable : %s" % (
                sum(b["erreurs"] for b in bs), motif)


class _ArretUnite(Exception):
    pass


def _maj_banc(b: dict) -> None:
    if b["echantillon"]:
        b["etat"], b["valeur"] = "OBSERVE", b["reussis"] / b["echantillon"]


def _banc_effort(cible, modele, u, jouer, D, mesure_le) -> None:
    cfg = BANCS["effort"]
    if not effort_supporte(cible, modele):
        u["effort"] = _effort_vierge("effort non pilotable sur cette surface : UNKNOWN assume")
        return
    mesures = []
    try:
        for _ in range(cfg["repetitions"]):
            for niveau in cfg["niveaux"]:
                for t in D.EFFORT:
                    req = {"banc": "effort", "item_id": t["id"], "prompt": t["prompt"], "effort": niveau,
                           "max_tokens": 3000}
                    info = {}

                    def juge(r, t=t, info=info):
                        return juge_exact(t, r.get("texte"))
                    try:
                        ok, cout, ms, _m = jouer("effort", req, juge)
                    except NonSupporte as exc:
                        u["effort"] = _effort_vierge(str(exc))
                        return
                    if ok is not None:
                        mesures.append({"effort": niveau, "cout_usd": cout, "latence_ms": ms, "reussi": ok})
    finally:
        if mesures and u["effort"]["etat"] == "UNKNOWN":
            u["effort"] = effet_effort(mesures, mesure_le)


def _fiche_unite(u: dict, mesure_le: str) -> dict:
    force = {nom: {"valeur": b["valeur"], "echantillon": b["echantillon"], "juge": "deterministe", "mesure_le": mesure_le}
             for nom, b in u["bancs"].items() if nom in SPECIALITES and b["etat"] == "OBSERVE"}
    observes = {"force": force}
    if u["effort"].get("etat") == "OBSERVE":
        observes["effort"] = u["effort"]
    return fiche_dimensions(observes=observes)


# --- fournisseurs REELS (jamais lances par les NR ; uniquement par le point d'entree en ligne) ---------------------------
def _appel_depuis_texte(texte: str):
    """CLI sans tool_calls natifs : l'appel est demande en JSON {"name","arguments"} dans le texte."""
    import re
    m = re.findall(r"\{.*\}", str(texte or ""), re.S)
    for brut in sorted(m, key=len, reverse=True):
        try:
            d = json.loads(brut)
        except ValueError:
            __import__("logging").getLogger(__name__).debug("chemin muet journalise (%s:%d)", 'tools/forge_free_tier_census.py', 1162, exc_info=True)
            continue
        if isinstance(d, dict) and "name" in d and "arguments" in d:
            return [{"name": d["name"], "arguments": d["arguments"]}]
    return []


def _consigne_outils(req: dict) -> str:
    noms = json.dumps([t["function"] for t in req["tools"]], ensure_ascii=False)
    return (req["prompt"] + "\nOutils disponibles : " + noms +
            "\nReponds UNIQUEMENT par un objet JSON {\"name\": ..., \"arguments\": {...}} (un seul appel).")


def _est_limite(texte: str) -> bool:
    t = str(texte).lower()
    return "429" in t or "rate limit" in t or "usage limit" in t or "quota" in t or "limit reached" in t


def _appel_cli(cible: str, modele: str, req: dict) -> dict:
    import os
    import shutil
    import subprocess
    import tempfile
    if cible == "cli:vibe" and (req.get("image") or req.get("tools") or req.get("effort")):
        raise NonSupporte("vibe en CLI headless : ni image, ni tool_calls structures, ni effort")
    binaire = shutil.which("claude") if cible == "cli:claude" else _binaire_vibe()
    if not binaire:
        raise BinaireAbsent("binaire %s introuvable sous ce compte" % ("claude" if cible == "cli:claude" else "vibe"))
    prompt = _consigne_outils(req) if req.get("tools") else req["prompt"]
    with tempfile.TemporaryDirectory() as d:   # dossier VIDE : aucun fichier du projet n'est lisible par le modele
        cmd = [binaire, "-p", prompt]
        if cible == "cli:claude":
            cmd += ["--model", modele, "--output-format", "json", "--strict-mcp-config"]
            if req.get("effort"):
                cmd += ["--effort", req["effort"]]
            if req.get("image"):
                Path(d, "image.png").write_bytes(req["image"])
                cmd[2] = prompt + "\nL'image est le fichier image.png du dossier courant : lis-le."
                cmd += ["--allowedTools", "Read"]
        p = subprocess.run(cmd, cwd=d, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
    sortie = (p.stdout or "") + (p.stderr or "")
    remplace = "�" in sortie   # octets non-utf-8 remplaces au decodage : note, jamais silencieux
    if p.returncode != 0 and _est_limite(sortie):
        raise Limite429(sortie.strip()[:120])
    if cible == "cli:vibe":
        return {"texte": p.stdout, "tool_calls": [], "cout_usd": None, "decodage_remplace": remplace}
    doc = json.loads(p.stdout)
    if doc.get("is_error") and _est_limite(doc.get("result")):
        raise Limite429(str(doc.get("result"))[:120])
    if doc.get("is_error"):
        raise RuntimeError(str(doc.get("result"))[:120])
    texte = doc.get("result") or ""
    return {"texte": texte, "tool_calls": _appel_depuis_texte(texte) if req.get("tools") else [],
            "cout_usd": doc.get("total_cost_usd"), "decodage_remplace": remplace}


def _appel_free_tier(modele: str, req: dict) -> dict:
    import base64
    from nokido_agent.app.forge_secrets import get_secret
    fournisseur, nom = modele.split(":", 1)
    env_key, base = next(((e, b) for f, e, b in SURFACES if f == fournisseur), (None, None))
    if base is None:
        raise NonSupporte("fournisseur hors SURFACES")
    contenu = req["prompt"]
    if req.get("image"):
        contenu = [{"type": "text", "text": req["prompt"]},
                   {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(req["image"]).decode()}}]
    charge = {"model": nom, "messages": [{"role": "user", "content": contenu}], "max_tokens": req.get("max_tokens", 600)}
    if req.get("tools"):
        charge["tools"] = req["tools"]
    if req.get("effort"):
        charge["reasoning_effort"] = req["effort"]
    cle = (get_secret(env_key) or "") if env_key else ""
    saute, etat_skip, motif_skip = verifier_et_sauter_fournisseur(fournisseur, env_key, cle)
    if saute:
        raise NonSupporte(f"{fournisseur} saute: {motif_skip}")
    tentatives_restantes = 1
    while True:
        try:
            with urllib.request.urlopen(_req(f"{_racine(base)}/chat/completions", cle, json.dumps(charge).encode("utf-8")),
                                        timeout=120) as r:
                corps = json.loads(r.read().decode("utf-8", errors="replace"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                entetes_err = getattr(exc, "headers", None) or {}
                delai = extraire_delai_rate_limit(entetes_err)
                if delai is not None and delai <= 30.0 and tentatives_restantes > 0:
                    tentatives_restantes -= 1
                    time.sleep(delai)
                    continue
                if delai is not None and delai > 30.0:
                    consigner_quota_epuise(fournisseur, nom, f"HTTP 429 retry-after={delai}s")
                raise Limite429("HTTP 429 %s retry-after=%s" % (fournisseur, (exc.headers or {}).get("retry-after"))) from exc
            if exc.code == 402:
                raise RuntimeError("HTTP 402 : SANS_SOLDE") from exc
            if exc.code in (400, 404, 422) and (req.get("tools") or req.get("image") or req.get("effort")):
                raise NonSupporte("HTTP %d : %s refuse cette capacite" % (exc.code, fournisseur)) from exc
            raise
    msg = (corps.get("choices") or [{}])[0].get("message") or {}
    appels = [{"name": (t.get("function") or {}).get("name"), "arguments": (t.get("function") or {}).get("arguments")}
              for t in (msg.get("tool_calls") or [])]
    return {"texte": msg.get("content") or "", "tool_calls": appels, "cout_usd": 0.0}


def _appel_proxy(modele: str, req: dict) -> dict:
    if req.get("image") or req.get("tools") or req.get("effort"):
        raise NonSupporte("forge_agent_proxy.ask : texte seul (ni image, ni outils, ni effort)")
    import asyncio
    from nokido_agent.app.forge_agent_proxy import ask
    r = asyncio.run(ask(modele, req["prompt"]))
    if isinstance(r, dict):
        if _est_limite(r.get("error") or ""):
            raise Limite429(str(r.get("error"))[:120])
        err = r.get("error")
        texte = r.get("text") or r.get("response") or r.get("content") or ""
        # ok:false / erreur / vide = le fournisseur n'a PAS repondu : ERREUR hors denominateur, jamais un 0 du modele
        if r.get("ok") is False or err or not str(texte).strip():
            raise ProxyErreur(str(err or "reponse vide")[:160])
        r = texte
    elif not str(r).strip():
        raise ProxyErreur("reponse vide")
    return {"texte": str(r), "tool_calls": [], "cout_usd": None}


def _appel_ollama(modele: str, req: dict) -> dict:
    if req.get("image"):
        raise NonSupporte("ollama local %s : pas de vision" % modele)
    charge = {"model": modele, "messages": [{"role": "user", "content": req["prompt"]}],
              "max_tokens": req.get("max_tokens", 600), "stream": False}
    if req.get("tools"):
        charge["tools"] = req["tools"]
    rq = urllib.request.Request("http://127.0.0.1:11434/v1/chat/completions", json.dumps(charge).encode("utf-8"),
                                {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(rq, timeout=300) as r:
            corps = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.URLError as exc:
        raise BinaireAbsent("ollama local injoignable (127.0.0.1:11434) : %s" % type(exc).__name__) from exc
    msg = (corps.get("choices") or [{}])[0].get("message") or {}
    appels = [{"name": (t.get("function") or {}).get("name"), "arguments": (t.get("function") or {}).get("arguments")}
              for t in (msg.get("tool_calls") or [])]
    return {"texte": msg.get("content") or "", "tool_calls": appels, "cout_usd": 0.0}


def appel_reel(cible: str, modele: str, req: dict) -> dict:
    if cible == "local:ollama":
        return _appel_ollama(modele, req)
    if cible in ("cli:claude", "cli:vibe"):
        return _appel_cli(cible, modele, req)
    if cible == "swarm:free_tier":
        return _appel_free_tier(modele, req)
    if cible == "swarm:forge_agent_proxy":
        return _appel_proxy(modele, req)
    raise NonSupporte("cible sans fournisseur : %s" % cible)


def _lire_budgets(brut: str) -> dict:
    sortie = {}
    for x in brut.split(","):
        cible, _, usd = x.partition("=")
        if not cible or not usd:
            raise ValueError("budget attendu cible=usd, recu %r" % x)
        sortie[cible.strip()] = float(usd)
    return sortie


def _valeur_option(argv, nom):
    i = argv.index(nom) if nom in argv else -1
    return argv[i + 1] if 0 <= i < len(argv) - 1 and not argv[i + 1].startswith("--") else None


def main_bancs(argv, appel=None, unites=None, sleep=time.sleep) -> int:
    """`--dimensions <cibles> --bancs <liste> --sortie <json> [--budget c=usd,...] [--dry-run]`. Sans --dry-run, --sortie
    est OBLIGATOIRE (un lancement en ligne qui ne garde rien gaspille le quota)."""
    cibles = [c for c in (_valeur_option(argv, "--dimensions") or "").split(",") if c]
    bancs = [b for b in (_valeur_option(argv, "--bancs") or ",".join(BANCS_DE_FORCE + ("effort",))).split(",") if b]
    if not cibles:
        print("--dimensions <cibles> requis (ex. cli:claude,cli:vibe,swarm:free_tier)")
        return 2
    if any(b not in BANCS for b in bancs):
        print("banc inconnu : %s (valides : %s)" % (sorted(set(bancs) - set(BANCS)), ", ".join(BANCS)))
        return 2
    try:
        budgets = _lire_budgets(_valeur_option(argv, "--budget") or "") if "--budget" in argv else {}
    except ValueError as exc:
        print("--budget invalide : %s" % exc)
        return 2
    payants = "--inclure-payants" in argv
    plan = plan_bancs(cibles, bancs, unites=unites, budgets=budgets, inclure_payants=payants)
    for cible, p in plan["cibles"].items():
        if p["etat"] != "DISPONIBLE":
            print("%-26s %s : %s" % (cible, p["etat"], p["motif"]))
            continue
        usd = ("inconnu (%d appels a cout inconnu)" % p["appels_cout_inconnu"]) if p["cout_usd_estime"] is None \
            else "%.2f USD" % p["cout_usd_estime"]
        print("%-26s %d appels, cout ESTIME %s, unites=%s%s%s" % (
            cible, p["appels"], usd, len(p["unites"]), " (%s)" % p["motif"] if p["motif"] else "",
            " -- BUDGET %.2f < estimation" % p["budget_usd"] if p["budget_depasse_par_estimation"] else ""))
    if "swarm:forge_agent_proxy" in plan["cibles"] and unites is None:
        try:
            ret, exc = filtrer_proxy(sorted(_registre_proxy()), payants)
        except Exception:  # noqa: BLE001 - hub non importable : rien a lister
            ret, exc = [], []
        print("proxy retenus (%d) : %s" % (len(ret), ", ".join(ret) or "aucun"))
        for n, motif in exc:
            print("proxy exclu %s : %s" % (n, motif))
    if "--dry-run" in argv:
        print("dry-run : aucun appel emis")
        return 0
    sortie = _valeur_option(argv, "--sortie")
    if not sortie:
        print("--sortie <json> requis pour un lancement en ligne (ou --dry-run)")
        return 2
    cible_json = resoudre_chemin(sortie)

    def ecrire(doc):
        doc = avec_contexte({**doc, "commande": "python tools/forge_free_tier_census.py " + " ".join(argv),
                             "budgets": budgets})
        cible_json.parent.mkdir(parents=True, exist_ok=True)
        cible_json.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return doc

    doc = lancer_bancs(cibles, bancs, appel or appel_reel, budgets=budgets, unites=unites, sleep=sleep, apres_unite=ecrire)
    ecrire(doc)
    for cible, c in doc["cibles"].items():
        print("%-26s %s appels=%s cout_reel=%s" % (cible, c["etat"], c.get("appels"), c.get("cout_usd")))
    print("consigne au census : %d fiche(s)" % consigner_fichier_resultats(cible_json))
    print("resultats : %s" % cible_json)
    return 0


def _afficher_dimensions(bancs: bool) -> int:
    """CLI --dimensions [--bancs] : LIT seulement. N'execute aucun banc."""
    try:
        census = json.loads(SORTIE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        census = {}
    for s in registre_unifie(census, {})["surfaces"]:
        d = s["dimensions"]
        etats = {g: sorted({v["etat"] for v in d[g].values()}) for g in ("specialite", "force")}
        print("%s:%s specialite=%s force=%s effort=%s" % (s["fournisseur"], s["modele"], etats["specialite"],
                                                          etats["force"], d["effort"]["etat"]))
    if bancs:
        for nom in BANCS:
            print("banc %-12s %s" % (nom, cout_estime_banc(nom, 0.0, 0.0)))
        for cle, v in SURFACES_CIBLES.items():
            print("cible %-26s %s %s" % (cle, v["etat"], v.get("motif") or ""))
    return 0


def _ecrire_registre_unifie(cible) -> int:
    try:
        census = json.loads(SORTIE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"recensement ILLISIBLE ({type(exc).__name__}) : registre unifie NON ecrit")
        return 1
    try:
        from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS
    except ImportError:  # repli checkout : le pont nokido_agent n'existe pas
        from forge_provider_specs import PROVIDER_SPECS
    reg = registre_unifie(census, PROVIDER_SPECS)
    cible = Path(cible)
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"registre unifie : {cible} -- {reg['totaux']}")
    return 0


def main() -> int:
    if "--consigner" in sys.argv:
        return main_consigner(sys.argv[sys.argv.index("--consigner") + 1:][:1])
    if _valeur_option(sys.argv, "--dimensions"):    # --dimensions <cibles> : lanceur des bancs ; seul : lecture du registre
        return main_bancs(sys.argv[1:])
    if "--dimensions" in sys.argv:
        return _afficher_dimensions("--bancs" in sys.argv)
    if "--essaim" in sys.argv:
        # 21/10 : candidats FRAIS -> porteurs du proxy -> membres sondes par ask -> registre lu par l'essaim.
        try:
            doc = json.loads(SORTIE.read_text(encoding="utf-8")) if SORTIE.exists() else {}
        except (OSError, json.JSONDecodeError):
            doc = {}
        m = membres_essaim(candidats_frais(doc), porteurs_du_proxy(_registre_proxy(), SURFACES),
                           census=doc, matrice=_matrice_courante())
        membres, sans_porteur = m.get("membres") or [], m.get("sans_porteur") or []
        import asyncio
        verdicts = asyncio.run(sonder_essaim(membres, _ask_essaim))
        ecrit = ecrire_membres_vivants(verdicts, REGISTRE_ESSAIM, forces=m.get("forces"))
        for membre, v in verdicts.items():
            if v.get("etat") != "OK":
                print(f"[essaim] ecarte {membre} : {v.get('etat')} ({v.get('raison') or 'sans motif rendu'})")
        print(f"[essaim] membres vivants : {len(ecrit.get('membres_ok') or [])}/{len(membres)} OK -> {REGISTRE_ESSAIM}")
        print(f"[essaim] sans porteur : {', '.join(sans_porteur) if sans_porteur else 'aucun'}")
        return 0
    if "--registre-unifie" in sys.argv:
        i = sys.argv.index("--registre-unifie")
        suivant = sys.argv[i + 1] if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--") else None
        return _ecrire_registre_unifie(suivant or REGISTRE_UNIFIE)
    cibles = lire_cibles(sys.argv[1:])
    if cibles:
        resultats = cibler(cibles)
        for r in resultats:
            if r.get("etat"):
                print(f"{r['fournisseur']:12} {r['modele'][:44]:46} {r['etat']}")
                continue
            declare = {True: "declare", False: "NON declare", None: "catalogue ILLISIBLE"}[r["declare"]]
            outils = {True: "outils OK", False: "outils REFUSES", None: "outils non testes"}[r.get("outils")]
            print(f"{r['fournisseur']:12} {r['modele'][:44]:46} {declare:20} "
                  f"{'JOIGNABLE' if r['joignable'] else 'injoignable (' + str(r['motif']) + ')'}  {outils}  "
                  f"limites: {r.get('limites') or 'aucun en-tete'}  quota: {r['quota']}")
        try:
            registre = json.loads(SORTIE.read_text(encoding="utf-8")) if SORTIE.exists() else {}
        except (OSError, json.JSONDecodeError) as exc:
            # un registre illisible n'est jamais reecrit : ce serait jeter le recensement et les verdicts anterieurs
            print(f"(registre ILLISIBLE : {type(exc).__name__} -- verdicts NON gardes, rien ecrase)")
            return 0
        try:
            SORTIE.parent.mkdir(parents=True, exist_ok=True)
            SORTIE.write_text(json.dumps(consigner(resultats, registre), ensure_ascii=False, indent=1),
                              encoding="utf-8")
            print(f"verdicts gardes : {SORTIE} (cle fournisseur:modele) -- la prochaine session les LIT")
        except OSError as exc:
            print(f"(verdicts NON gardes : {exc})")
        return 0
    from nokido_agent.app.forge_secrets import get_secret

    precedent = {}
    try:
        precedent = json.loads(SORTIE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        precedent = {}

    total_declare = total_gratuit = total_joignable = 0
    rapport = []
    for etiquette, env_key, base in SURFACES:
        cle = (get_secret(env_key) or "") if env_key else ""
        # Check should_skip or missing key
        saute, etat_skip, motif_skip = verifier_et_sauter_fournisseur(etiquette, env_key, cle)
        if saute:
            rapport.append({
                "fournisseur": etiquette,
                "etat": etat_skip,
                "motif": motif_skip,
                "code": -1
            })
            continue
        code, modeles, entetes, detail = _lire_catalogue(base, cle)
        if code != 200:
            # Use detail if available, else default
            etat_hl, motif = etat_hors_ligne(etiquette, code, detail if detail else f"HTTP {code}")
            print(f"{etiquette:12} {etat_hl.replace('_', ' ')} -- {motif}")
            rapport.append({
                "fournisseur": etiquette,
                "etat": etat_hl,
                "motif": motif,
                "code": code
            })
            continue

        utiles = modeles_chat(modeles)
        if etiquette == "ollama_cloud":
            utiles = [m for m in utiles if palier_ollama_cloud(str(m.get("id"))) == "FREE"]
        # RED 3 du plan AGY (16/10) : « Groq : 6 modeles » etait compte APRES ce filtre -- dire les deux, et lesquels.
        ecartes = sorted(str(m.get("id")) for m in modeles if m not in utiles)
        gratuits = [m for m in utiles if est_gratuit(m, etiquette) is True]
        inconnus = [m for m in utiles if est_gratuit(m, etiquette) is None]

        # Preuve par echantillon : les plus PETITS repondent vite et suffisent
        # a prouver que le palier repond (un 405B a froid ne prouverait rien).
        candidats = sorted(gratuits or inconnus,
                           key=lambda m: _taille(str(m.get("id", ""))))[:ECHANTILLON]
        if etiquette in A_LA_DEMANDE:
            # 30/10 : une completion vers LM Studio lui fait charger un modele JUSTE-A-TEMPS (5,36 Go, RAM 99 %) hors de
            # l'admission de forge_ensure_service. Catalogue lu, completion NON tentee, et c'est dit.
            raison = "a la demande : completion non tentee (chargement juste-a-temps hors admission RAM)"
            print(f"{etiquette:12} declares={len(utiles):<4} {raison}")
            rapport.append({"fournisseur": etiquette, "etat": "A_LA_DEMANDE", "raison": raison, "motif": raison,
                            "declares": len(utiles), "declares_bruts": len(modeles), "ecartes": ecartes})
            continue
        if not candidats:  # 21/10 : SambaNova (6 declares) jamais sonde et absent du bilan -- ne plus le taire
            raison = "aucun candidat : %d gratuit(s) annonce(s), %d prix non publie(s) sur %d declare(s)" % (
                len(gratuits), len(inconnus), len(utiles))
            print(f"{etiquette:12} NON SONDE -- {raison}")
            rapport.append({"fournisseur": etiquette, "etat": "NON_SONDE", "raison": raison, "motif": raison,
                            "declares": len(utiles), "declares_bruts": len(modeles), "ecartes": ecartes})
            continue
        preuves = []
        for m in candidats:
            ok, motif = joignable(base, cle, str(m.get("id")), fournisseur=etiquette)
            preuves.append({"modele": str(m.get("id")), "joignable": ok, "motif": motif})
        joints = sum(1 for p in preuves if p["joignable"])

        total_declare += len(utiles)
        total_gratuit += len(gratuits)
        total_joignable += joints
        print(f"{etiquette:12} declares={len(utiles):<4} (bruts={len(modeles)}, ecartes={len(ecartes)}) "
              f"gratuits_annonces={len(gratuits):<4} "
              f"prix_non_publie={len(inconnus):<4} echantillon_joignable={joints}/{len(preuves)}"
              f"  quota: {quota(etiquette, cle, entetes)}")
        for p in preuves:
            print(f"               {p['modele'][:44]:46} {'OK' if p['joignable'] else p['motif']}")
        rapport.append({"fournisseur": etiquette, "etat": "MESURE", "declares": len(utiles), "declares_bruts": len(modeles),
                        "declares_utiles": len(utiles), "ecartes": ecartes,
                        "gratuits_annonces": len(gratuits),
                        "prix_non_publie": len(inconnus), "preuves": preuves,
                        "quota": quota(etiquette, cle, entetes)})

    print(f"\nTOTAL declares={total_declare} · gratuits ANNONCES={total_gratuit} · "
          f"echantillons PROUVES joignables={total_joignable}")
    print(f"\n--- ce qui a bouge depuis {precedent.get('horodatage', '(jamais)')} ---")
    for ligne in comparer(precedent, rapport):
        print(ligne)
    print("« gratuits annonces » compte ce que les fournisseurs publient ; les autres "
          "ne publient aucun prix et ne sont donc ni comptes gratuits ni comptes payants.")
    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps(
            {"horodatage": time.strftime("%Y-%m-%dT%H:%M:%S"), "fournisseurs": rapport,
             "verdicts": precedent.get("verdicts") or {},
             "totaux": {"declares": total_declare, "gratuits_annonces": total_gratuit,
                        "echantillons_joignables": total_joignable}},
            ensure_ascii=False, indent=1), encoding="utf-8")
        try:
            affiche = SORTIE.relative_to(ROOT)
        except ValueError:      # registre hors du depot (tmp de la CI de reference) : chemin complet, jamais une exception
            affiche = SORTIE
        print(f"registre : {affiche} — deux passes comparees disent ce qui a bouge")
    except OSError as exc:
        print(f"(registre non ecrit : {exc})")
    return 0


# ── Essaim cloud (RED 1da121b2a, owner 19/10 : l'essaim ne s'assigne que sur des couples PROUVES vivants) ────────────
# GREEN d'OPENCODE_GLM (cb9637e1f, session coupee par une panne du fournisseur) repris le 20/10 : porteurs indexes par
# FOURNISSEUR du census et hote compare (client.base_url compris), sonde illisible = INDETERMINE.

# 21/10 : aucun provider du proxy n'expose son URL -- l'appariement par hote ne trouvait RIEN dans le vrai registre.
# Repli DECLARE, filtre sur les noms presents (un nom absent du registre n'est jamais invente).
PORTEURS_DECLARES = {"groq": ["groq"], "openrouter": ["openrouter_free"], "mistral": ["mistral_free", "mistral"],
                     "zai": ["zai_glm_flash"], "cerebras": ["cerebras"], "ollama": ["ollama"],
                     "nvidia": ["nvidia_nim"], "sambanova": ["sambanova"], "deepseek": ["deepseek"], "hf": ["hf"]}


def porteurs_du_proxy(registre, surfaces) -> dict:
    """{fournisseur du census: [providers du proxy qui parlent au meme HOTE d'API]} ; sans hote lisible, la table
    PORTEURS_DECLARES filtree sur le registre. NR test_census_essaim_cable_nr (vrai registre)."""
    from urllib.parse import urlsplit

    def _hote(p):
        u = getattr(p, "base_url", None) or getattr(getattr(p, "client", None), "base_url", None)
        return urlsplit(str(u)).netloc.lower() if u else None

    hotes = {nom: _hote(p) for nom, p in (registre or {}).items()}
    porteurs = {}
    for etiquette, _cle, base in surfaces:
        h = urlsplit(str(base or "")).netloc.lower()
        noms = sorted(n for n, x in hotes.items() if x and x == h) or [
            n for n in PORTEURS_DECLARES.get(etiquette, []) if n in (registre or {})]
        if noms:
            porteurs[etiquette] = noms
    return porteurs


def _matrice_courante() -> dict:
    """Matrice modele x fournisseur sur disque (lecteur existant : forge_provider_catalogue.MATRICE) ; absente -> {}."""
    try:
        from forge_provider_catalogue import MATRICE
        return json.loads(Path(MATRICE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  muet-ok : pas de matrice = aucune force de ce cote, le reste reste lisible
        return {}


def force_observee(fournisseur: str, modele: str, census=None, matrice=None) -> dict:
    """{"force": moyenne des mesures OBSERVE | None, "source": ...}. Sources : fiches `dimensions.force` du census
    (OBSERVE seulement : un DECLARE n'est jamais une mesure) et competences de la matrice (json_strict, appel_outil,
    calcul, consigne : `score`). Aucune mesure -> force None (UNKNOWN)."""
    valeurs, sources = [], []
    v = ((census or {}).get("verdicts") or {}).get("%s:%s" % (fournisseur, modele)) or {}
    for spec, d in (((v.get("dimensions") or {}).get("force")) or {}).items():
        if isinstance(d, dict) and d.get("etat") == "OBSERVE" and isinstance(d.get("valeur"), (int, float)):
            valeurs.append(float(d["valeur"]))
            sources.append("census:force.%s" % spec)
    for voies in ((matrice or {}).get("familles") or {}).values():
        for voie in voies or []:
            score = (voie.get("competence") or {}).get("score")
            if voie.get("fournisseur") == fournisseur and voie.get("modele") == modele and isinstance(score, (int, float)):
                valeurs.append(float(score))
                sources.append("matrice:competence")
    if not valeurs:
        return {"force": None, "source": "UNKNOWN"}
    return {"force": round(sum(valeurs) / len(valeurs), 4), "source": "+".join(sorted(set(sources)))}


def _rang_force(forces: dict, membre: str):
    f = (forces.get(membre) or {}).get("force")
    return (f is None, -(f or 0.0))     # mesures d'abord (fort -> faible), UNKNOWN apres, jamais avant


def membres_essaim(candidats, porteurs, census=None, matrice=None, n=None) -> dict:
    """Chaque modele candidat devient `porteur:id_brut` (premier porteur par nom) ; un fournisseur sans porteur est
    NOMME dans `sans_porteur`, jamais tu. Classes par force OBSERVEE (`forces` : force + source par membre) ; `n` borne
    (None = tous, pour sonder avant de garder les N plus forts)."""
    membres, sans_porteur, forces = [], [], {}
    for fournisseur, modeles in (candidats or {}).items():
        siens = sorted(porteurs.get(fournisseur) or [])
        if not siens:
            sans_porteur.append(fournisseur)
            continue
        for m in modeles:
            nom = "%s:%s" % (siens[0], m)
            membres.append(nom)
            forces[nom] = force_observee(fournisseur, m, census, matrice)
    membres.sort(key=lambda x: _rang_force(forces, x))     # tri stable : a force egale l'ordre d'entree reste
    if n is not None:
        membres = membres[:n]
    return {"membres": membres, "sans_porteur": sans_porteur, "forces": forces}


async def sonder_essaim(membres, ask_fn) -> dict:
    """{membre: {"etat": OK|VIDE|KO|INDETERMINE, "ms"}} par `ask_fn(provider, tache, model=...)`, classe par la liste
    BLANCHE de forge_cli_swarm._classer ; une sonde qui leve est INDETERMINE (UNKNOWN n'est pas NO)."""
    import forge_cli_swarm as cs
    resultats = {}
    for membre in membres:
        provider, _, modele = membre.partition(":")
        t0 = time.time()
        raison = ""
        try:
            r = await ask_fn(provider, "ping", model=modele or None)
            etat = cs._classer(bool(r.get("ok")), str(r.get("text") or ""), r.get("error"))
            raison = str(r.get("error") or "")[:200]
        except Exception as e:  # noqa: BLE001 - sonde illisible, raison GARDEE (21/10 : le 14e membre KO sans motif)
            etat, raison = "INDETERMINE", "%s: %s" % (type(e).__name__, str(e)[:160])
        resultats[membre] = {"etat": etat, "ms": int((time.time() - t0) * 1000), "raison": raison}
    return resultats


def _registre_proxy() -> dict:
    """Providers du proxy (import paresseux : le census reste lisible sans le hub)."""
    from nokido_agent.app.forge_agent_proxy import _PROVIDERS
    return _PROVIDERS


async def _ask_essaim(provider, task, **k):
    from nokido_agent.app.forge_agent_proxy import ask
    return await ask(provider, task, **k)


def candidats_frais(doc, maintenant=None, max_age_s: int = 6 * 3600) -> dict:
    """{fournisseur: [modeles]} prouves FRAIS : les preuves de la passe (`fournisseurs[].preuves`, joignable vrai) et
    les verdicts --cible JOIGNABLES horodates (`mesure_le`) de moins de `max_age_s`. Un verdict sans date ou plus vieux
    est un cumul recopie, jamais une preuve (21/10 : lu pour frais, 6 membres sur 8 morts)."""
    candidats = {}
    for f in (doc or {}).get("fournisseurs") or []:
        modeles = [str(p["modele"]) for p in (f.get("preuves") or [])
                   if isinstance(p, dict) and p.get("joignable") and p.get("modele")]
        if f.get("fournisseur") and modeles:
            candidats[f["fournisseur"]] = modeles
    maintenant = time.time() if maintenant is None else maintenant
    for cle, v in ((doc or {}).get("verdicts") or {}).items():
        if not (isinstance(v, dict) and v.get("joignable") is True and v.get("mesure_le") and ":" in cle):
            continue
        try:
            age = maintenant - time.mktime(time.strptime(str(v["mesure_le"]), "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, OverflowError):  # muet-ok : une date illisible n'est pas une preuve fraiche, rien a dire de plus
            continue
        if 0 <= age <= max_age_s:
            fournisseur, modele = cle.split(":", 1)
            if modele not in candidats.setdefault(fournisseur, []):
                candidats[fournisseur].append(modele)
    return candidats


def ecrire_membres_vivants(verdicts, chemin, maintenant=None, forces=None, n: int = 4) -> dict:
    """Registre horodate des seuls membres OK, les `n` plus forts (force mesuree d'abord, UNKNOWN apres) ; chaque
    membre porte sa force et la source de la mesure ; rend le document ecrit."""
    forces = forces or {}
    ok = [m for m, v in (verdicts or {}).items() if (v or {}).get("etat") == "OK"]
    ok.sort(key=lambda x: _rang_force(forces, x))
    ok = ok[:n]
    doc = {"membres_ok": ok,
           "membres": [{"nom": m, "force": (forces.get(m) or {}).get("force"),
                        "source": (forces.get(m) or {}).get("source") or "UNKNOWN"} for m in ok],
           "mesure_le": time.time() if maintenant is None else maintenant}
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


if __name__ == "__main__":
    raise SystemExit(main())
