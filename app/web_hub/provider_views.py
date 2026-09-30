# -*- coding: utf-8 -*-
"""Poste de saisie des cles fournisseurs — portail :7400, AUTHENTIFIE.

POURQUOI CE MODULE EXISTE (mesures 2026-09-18, hub vivant)
----------------------------------------------------------
La capacite « poser une cle au coffre » existait deja, cote hub, dans
`app/forge_provider_admin.py`. Ce module ne la reecrit pas : il la RELAIE depuis
la seule surface ou l'utilisateur est identifie. Trois mesures l'imposent :

1. `GET :8766/admin/providers` rend **200 sans le moindre en-tete** : la page
   d'administration du hub est hors du middleware d'auth. Elle ne peut donc pas
   servir de poste de saisie de secret.
2. Son ecriture etait gardee par `X-Ring`, un en-tete pose par le CLIENT. Un
   `X-Ring: 0` nu passait (200) pendant qu'un Bearer valide du hub etait refuse
   (403) : identite auto-declaree acceptee, identite prouvee refusee. Garde
   corrige le meme jour ; ce module emprunte desormais le chemin PROUVE.
3. `/llm-dashboard` est dans `auth._PUBLIC_PREFIXES` : y poser un champ qui ecrit
   au coffre aurait ouvert un trou pire que celui qu'on venait de fermer. Les
   routes d'ici vivent sous `/api/providers` et `/providers`, **hors** de cette
   allowlist, donc derriere la session du portail.

Repartition des roles, pour qu'aucune des deux pages ne double l'autre :
  :8766/admin/providers -> inventaire technique des slots (lecture)
  :7400/providers       -> poste de commande du coffre (saisie, retrait, test)

La cle ne transite qu'en corps de POST, jamais en URL, et n'est jamais journalisee.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `api_etat_acces` — Relaie `GET /api/access` du hub : provenance des acces, jamais leur valeur.
- `api_poser_acces` — Relaie au hub `POST /api/access/{cle}` : la valeur voyage en corps de POST.
- `api_retirer_acces` — Relaie au hub `DELETE /api/access/{cle}` : retrait de l'acces du coffre.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

# Base du hub DERIVEE de l'unique constante existante : ecrire un second littéral
# de port ferait deux sources de verite qui divergeraient au premier changement.
from app.web_hub.wired_routes import _HUB, _hub_token

log = logging.getLogger("nokido.hub.providers")

router = APIRouter()

_BASE = _HUB.rsplit("/mcp", 1)[0].rstrip("/")

# `list_providers` sonde les backends LLM : mesure du 2026-08-26, `/api/agents` a
# depasse 25 s parce qu'ollama etait fige. Une page d'affichage ne fait pas attendre
# deux minutes — elle DIT qu'elle n'a pas pu savoir.
_DELAI_LECTURE = 8.0
_DELAI_ECRITURE = 10.0
_DELAI_TEST = 20.0


async def _vers_hub(methode: str, chemin: str, *, json_corps: Any = None,
                    delai: float = _DELAI_LECTURE) -> tuple[int, dict]:
    """Relaie vers le hub avec le jeton du coffre. Ne journalise jamais le corps."""
    jeton = _hub_token()
    if not jeton:
        # Coffre illisible = INCONNU, pas « autorise » : on refuse en le nommant.
        return 503, {"ok": False, "error": "jeton hub illisible depuis le portail "
                                           "(coffre injoignable) — ecriture refusee"}
    entetes = {"Authorization": "Bearer " + jeton, "X-Agent-Name": "WEBHUB"}
    if json_corps is not None:
        entetes["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(timeout=delai) as c:
            r = await c.request(methode, _BASE + chemin, json=json_corps, headers=entetes)
    except httpx.TimeoutException:
        return 504, {"ok": False, "error": "le hub n'a pas repondu en %.0f s — etat INCONNU, "
                                           "pas « echec »" % delai}
    except Exception as exc:  # noqa: BLE001 — on NOMME ce qui empeche de voir
        return 502, {"ok": False, "error": "hub injoignable : %s" % type(exc).__name__}
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"ok": False, "error": "reponse du hub non-JSON (HTTP %d)" % r.status_code}


# Liens d'inscription. La regle est la DERIVATION depuis le domaine de l'endpoint
# `/models` declare par `tools/forge_provider_catalogue.FOURNISSEURS` -- on n'invente
# aucune adresse. Les exceptions ci-dessous ne sont pas des inventions non plus : ce sont
# les pages RELEVEES le 2026-09-18, quand la racine du domaine ne mene pas a la creation
# de cle. Sans elles, « deriver » enverrait l'utilisateur sur une page d'accueil
# commerciale au lieu du formulaire.
_INSCRIPTION_PRECISE = {
    "GROQ_API_KEY": "https://console.groq.com/keys",
    "XAI_API_KEY": "https://console.x.ai/",
    "OPENROUTER_API_KEY": "https://openrouter.ai/keys",
    "MISTRAL_API_KEY": "https://console.mistral.ai/api-keys/",
    "CEREBRAS_API_KEY": "https://cloud.cerebras.ai/platform/",
    "DEEPSEEK_API_KEY": "https://platform.deepseek.com/api_keys",
    "SAMBANOVA_API_KEY": "https://cloud.sambanova.ai/apis",
    "COHERE_API_KEY": "https://dashboard.cohere.com/api-keys",
    "HF_TOKEN": "https://huggingface.co/settings/tokens",
    "NVIDIA_API_KEY": "https://build.nvidia.com/",
    "NVIDIA_NIM_API_KEY": "https://build.nvidia.com/",
}

# SECONDE source, et elle est necessaire : ces fournisseurs n'exposent pas d'endpoint
# `/models` compatible OpenAI, donc ils sont ABSENTS de `FOURNISSEURS` -- et la fusion
# les a d'abord laisses sans lien. Mesure du 2026-09-18 : 5 fournisseurs majeurs
# (Anthropic, OpenAI, Gemini, Perplexity, GitHub Models) perdaient le lien que
# l'ancienne page portait. Fusionner ne doit RIEN faire disparaitre.
#
# Ces adresses ne sont pas devinees : elles sont reprises de `tools/llm-dashboard.html`,
# la page que cette fusion remplace. La provenance compte autant que la valeur.
_INSCRIPTION_HORS_MODELS = {
    "ANTHROPIC_API_KEY": "https://console.anthropic.com/settings/keys",
    "OPENAI_API_KEY": "https://platform.openai.com/api-keys",
    "GEMINI_API_KEY": "https://aistudio.google.com/app/apikey",
    "PERPLEXITY_API_KEY": "https://www.perplexity.ai/settings/api",
}

# Ecartes du catalogue de cles, avec leur RAISON. Une absence nommee n'est pas un oubli :
# les taire ferait chercher indefiniment pourquoi ils manquent.
HORS_CATALOGUE = {
    "Tavily": "moteur de recherche, pas d'endpoint /models",
    "Smithery": "registre MCP, pas un fournisseur de modeles",
    "Kaggle": "jeux de donnees",
    "Codeberg": "forge git",
    "Freebox": "domotique",
    "Cloudflare Workers AI": "URL dependante du compte",
    "Perceval / Quandela": "calcul quantique",
    "GitHub Models": "backend RETIRE le 2026-08-18 (410 Gone)",
}


def _inscriptions_par_cle() -> dict:
    """{env_key: url d'inscription} depuis la source unique du catalogue.

    Jointure par `vault_key` == `env_key`, et non par prefixe de nom : plusieurs slots
    partagent une famille (`nvidia` / `nvidia_nim`) et un prefixe ne les distingue pas.
    """
    import sys as _sys
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[2]
    for p in (str(racine / "tools"), str(racine)):
        if p not in _sys.path:
            _sys.path.insert(0, p)
    try:
        from forge_provider_catalogue import FOURNISSEURS
    except Exception as exc:  # noqa: BLE001 — illisible n'est pas vide : on le DIT
        log.warning("catalogue d'inscriptions illisible (%s) : seuls les liens releves "
                    "a la main restent disponibles", type(exc).__name__)
        return dict(_INSCRIPTION_HORS_MODELS)

    # La seconde source d'abord : elle couvre ce que le catalogue `/models` ignore.
    out = dict(_INSCRIPTION_HORS_MODELS)
    # Un filtre qui ecarte des donnees le DIT, sinon la couverture est surestimee en
    # silence : deux entrees malformees et la page annonce « tous relies » a tort.
    ecartes = []
    for entree in FOURNISSEURS:
        try:
            _nom, env_key, url = entree[0], entree[1], entree[2]
        except (IndexError, TypeError):
            ecartes.append(repr(entree)[:60])
            continue
        if not env_key:
            ecartes.append("%s (aucune cle de coffre declaree)" % (entree[0] if entree else "?"))
            continue
        if env_key in _INSCRIPTION_PRECISE:
            out[env_key] = _INSCRIPTION_PRECISE[env_key]
            continue
        hote = str(url).split("//", 1)[-1].split("/", 1)[0]
        if hote.startswith("127.0.0.1") or hote.startswith("localhost"):
            continue  # local : aucune inscription a proposer
        # `api.` prefixe l'endpoint machine, pas la page d'accueil humaine.
        if hote.startswith("api."):
            hote = hote[4:]
        out[env_key] = "https://" + hote + "/"
    if ecartes:
        log.warning("inscriptions : %d entree(s) du catalogue ecartee(s) sur %d — %s",
                    len(ecartes), len(FOURNISSEURS), "; ".join(ecartes[:5]))
    return out


@router.get("/api/providers/catalogue")
async def api_catalogue() -> JSONResponse:
    """Catalogue des fournisseurs. N'expose QUE l'etat present/absent d'une cle."""
    code, charge = await _vers_hub("GET", "/api/providers")
    if code != 200:
        return JSONResponse({"ok": False, "error": charge.get("error", "HTTP %d" % code)},
                            status_code=200 if code in (502, 503, 504) else code)
    liste = charge if isinstance(charge, list) else charge.get("providers", [])
    surs = []
    for p in liste:
        if not isinstance(p, dict):
            continue
        # Liste BLANCHE de champs : un champ inconnu ajoute en amont ne doit pas
        # se retrouver servi a l'ecran sans qu'on l'ait regarde.
        surs.append({k: p.get(k) for k in (
            "name", "tier", "capabilities", "context", "quota", "vault_key",
            "has_key", "notes", "perime", "monthly_calls", "daily_calls",
        )})

    # FUSION (demande owner 2026-09-18) : la table « ou s'inscrire » vivait sur une
    # SECONDE page, sans etat de cle ni action -- deux ecrans pour un seul sujet, et
    # celui qui listait les fournisseurs ne disait pas lesquels etaient configures.
    liens = _inscriptions_par_cle()
    for p in surs:
        p["inscription"] = liens.get(p.get("vault_key") or "")
    manquants = sorted({p["vault_key"] for p in surs
                        if p.get("vault_key") and not p.get("inscription")})
    return JSONResponse({
        "ok": True,
        "providers": surs,
        "hors_catalogue": HORS_CATALOGUE,
        # Dire ce qu'on n'a PAS pu relier vaut mieux qu'un lien absent sans explication.
        "sans_lien_d_inscription": manquants,
    })


async def _relayer_ecriture(request: Request, champ: str, vide: str, chemin_hub: str,
                            libelle: str) -> JSONResponse:
    """POST `{champ: valeur}` relaye au hub. Source unique des deux ecritures au coffre (cles, acces SSH ;
    cliquet clones 26/09). Journal : le LIBELLE (nom du slot), jamais la valeur, jamais un extrait."""
    try:
        corps = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": "corps JSON invalide"}, status_code=400)
    valeur = (corps or {}).get(champ, "")
    if not isinstance(valeur, str) or not valeur.strip():
        return JSONResponse({"ok": False, "error": vide}, status_code=400)
    code, charge = await _vers_hub("POST", chemin_hub, json_corps={champ: valeur}, delai=_DELAI_ECRITURE)
    log.info("%s -> HTTP %d", libelle, code)
    return JSONResponse(charge, status_code=200 if code == 200 else code)


async def _relayer_retrait(chemin_hub: str, libelle: str) -> JSONResponse:
    code, charge = await _vers_hub("DELETE", chemin_hub, delai=_DELAI_ECRITURE)
    log.info("%s -> HTTP %d", libelle, code)
    return JSONResponse(charge, status_code=200 if code == 200 else code)


@router.post("/api/providers/{provider}/key")
async def api_poser_cle(provider: str, request: Request) -> JSONResponse:
    return await _relayer_ecriture(request, "api_key", "cle vide", "/api/providers/%s/key" % provider,
                                   "coffre: ecriture demandee pour %s" % provider)


@router.delete("/api/providers/{provider}/key")
async def api_retirer_cle(provider: str) -> JSONResponse:
    return await _relayer_retrait("/api/providers/%s/key" % provider,
                                  "coffre: retrait demande pour %s" % provider)


# Acces SSH au coffre (owner 2026-09-25) : meme chemin PROUVE que les clefs -- relais
# authentifie vers le hub, qui garde la liste blanche et le ring. Sous /api/providers,
# donc HORS de l'allowlist publique. Jamais la valeur en journal ni en reponse.
@router.get("/api/providers/acces")
async def api_etat_acces() -> JSONResponse:
    """Relaie `GET /api/access` du hub : provenance des acces, jamais leur valeur."""
    code, charge = await _vers_hub("GET", "/api/access")
    return JSONResponse(charge, status_code=200 if code == 200 else code)


@router.post("/api/providers/acces/{cle}")
async def api_poser_acces(cle: str, request: Request) -> JSONResponse:
    """Relaie au hub `POST /api/access/{cle}` : la valeur voyage en corps de POST."""
    return await _relayer_ecriture(request, "valeur", "valeur vide", "/api/access/%s" % cle,
                                   "coffre: acces %s pose" % cle)


@router.delete("/api/providers/acces/{cle}")
async def api_retirer_acces(cle: str) -> JSONResponse:
    """Relaie au hub `DELETE /api/access/{cle}` : retrait de l'acces du coffre."""
    return await _relayer_retrait("/api/access/%s" % cle, "coffre: acces %s retire" % cle)


@router.post("/api/providers/{provider}/test")
async def api_tester(provider: str) -> JSONResponse:
    code, charge = await _vers_hub("POST", "/api/providers/%s/test" % provider,
                                   delai=_DELAI_TEST)
    return JSONResponse(charge, status_code=200 if code == 200 else code)


# Le firewall du hub refuse tout payload qui porte une balise de script en clair.
# La balise est donc composee a l'execution : c'est le prix d'un garde qui protege
# l'ecriture gouvernee, pas une astuce pour l'eviter.
_BALISE_JS = "<" + 'script src="/static/providers.js" defer></' + "script>"

_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Nokido — Cles fournisseurs</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/static/nokido.css">
<style>
  .enveloppe { max-width: 1280px; margin: 0 auto; padding: 22px 18px 60px; }
  header.tete { display:flex; flex-wrap:wrap; gap:14px; align-items:flex-end;
                justify-content:space-between; margin-bottom: 18px; }
  header.tete h1 { margin:0; font-size:19px; letter-spacing:-0.2px; }
  header.tete p  { margin:5px 0 0; color: var(--text-secondary); font-size:12.5px; max-width:70ch; }
  nav.ailleurs { display:flex; gap:14px; font-size:12.5px; }
  .filtres { display:flex; flex-wrap:wrap; gap:12px; align-items:center; margin-bottom:14px; }
  .filtres label { display:flex; align-items:center; gap:7px; color:var(--text-secondary); font-size:12.5px; }
  .compte { margin-left:auto; color:var(--text-dim); font-size:12px; font-family:'JetBrains Mono',monospace; }
  .nom { font-family:'JetBrains Mono',monospace; font-weight:600; color:var(--text-primary); }
  .notes { font-size:11px; color:var(--text-dim); max-width:34ch; overflow:hidden;
           text-overflow:ellipsis; white-space:nowrap; margin-top:3px; }
  .perime { display:inline-block; margin-top:4px; font-size:10.5px; font-weight:600;
            padding:1px 6px; border-radius:4px; color:var(--red);
            background:rgba(242,79,79,.12); border:1px solid rgba(242,79,79,.35); cursor:help; }
  .caps { display:flex; flex-wrap:wrap; gap:4px; }
  .cap { font-size:10px; text-transform:uppercase; letter-spacing:.4px; padding:1px 6px;
         border-radius:4px; color:var(--blue); background:rgba(59,178,208,.10);
         border:1px solid rgba(59,178,208,.22); }
  .mono { font-family:'JetBrains Mono',monospace; font-size:11.5px; color:var(--text-secondary); }
  .cle  { color:var(--purple); }
  .tier { font-weight:600; text-transform:capitalize; }
  .tier-local { color:var(--green); } .tier-free { color:var(--blue); }
  .tier-paid_api, .tier-subscription_quota { color:var(--yellow); }
  .actions { display:flex; gap:7px; flex-wrap:wrap; }
  .edition { background:var(--bg-1); }
  .edition .barre { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .edition .note { margin-top:7px; font-size:11.5px; color:var(--text-dim); max-width:80ch; }
  td.vide { text-align:center; color:var(--text-dim); padding:22px 0; }
  /* Rubriques : l'ordre est ACTIONNABLE (a configurer d'abord), pas alphabetique. */
  tr.groupe td { background:var(--bg-1); padding-top:14px; }
  .grp-titre { font-size:12px; text-transform:uppercase; letter-spacing:.6px;
               font-weight:700; color:var(--text-primary); }
  .grp-compte { display:inline-block; margin-left:8px; padding:0 7px; border-radius:999px;
                background:var(--bg-3); color:var(--text-secondary);
                font-family:'JetBrains Mono',monospace; font-size:10.5px; }
  .grp-note { margin-left:12px; font-size:11px; color:var(--text-dim); font-weight:400;
              text-transform:none; letter-spacing:0; }
  a.inscription { display:inline-block; margin-top:4px; font-size:11px; }
  #hors-catalogue { margin-top:20px; }
  #hors-catalogue .note { font-size:12px; color:var(--text-secondary); margin:0 0 6px; }
  #hors-catalogue ul.hors { margin:0 0 10px; padding-left:18px; font-size:12px;
                            color:var(--text-dim); line-height:1.6; }
</style>
</head>
<body>
<div class="enveloppe">
  <header class="tete">
    <div>
      <h1>&#128273; Fournisseurs &amp; cles</h1>
      <p>Ou s'inscrire, ce qui est configure, et la saisie au coffre
         <strong>DPAPI machine</strong> &mdash; en une seule page. Le fichier
         <code>.env</code> n'est pas touche&nbsp;; aucune valeur de cle n'est jamais
         affichee ni journalisee, seul l'etat <em>presente / absente</em> l'est.</p>
    </div>
    <nav class="ailleurs">
      <a href="/launcher">Lanceur</a>
      <a href="/">Tuiles</a>
    </nav>
  </header>

  <div class="laforge-card">
    <div class="filtres">
      <input id="filtre" class="laforge-input" placeholder="filtrer par nom" style="min-width:230px">
      <select id="tier" class="laforge-select">
        <option value="">tous les tiers</option>
        <option value="local">local</option>
        <option value="free">gratuit</option>
        <option value="subscription_quota">quota d'abonnement</option>
        <option value="paid_api">API payante</option>
      </select>
      <label><input type="checkbox" id="sans-cle"> seulement sans cle</label>
      <button id="relire" class="laforge-btn laforge-btn-ghost" type="button">relire</button>
      <span class="compte" id="compte">lecture…</span>
    </div>

    <table class="laforge-table">
      <thead>
        <tr><th>Fournisseur</th><th>Tier</th><th>Capacites</th><th>Contexte</th>
            <th>Emplacement au coffre</th><th>Etat</th><th>Actions</th></tr>
      </thead>
      <tbody id="lignes"></tbody>
    </table>
  </div>

  <div id="hors-catalogue" class="laforge-card" style="margin-top:14px"></div>

  <div id="acces-ssh" class="laforge-card" style="margin-top:14px"></div>
</div>
<div class="laforge-toast-stack" id="toasts"></div>
__JS__
</body>
</html>
""".replace("__JS__", _BALISE_JS)


@router.get("/api/souverainete")
async def api_souverainete() -> JSONResponse:
    """Part REELLE des appels servis en local, par fenetre.

    Demande owner du 2026-09-18 : l'ecran de souverainete doit representer le reel des
    actions effectuees. Jusqu'ici il affichait `PREF.get("power", 68)` -- une valeur que
    l'utilisateur REGLE lui-meme, presentee comme un pourcentage de souverainete.

    Premiere mesure, sur `token_usage` (23 140 appels) : 4,5 % de local tous temps
    confondus, et **0,0 % sur les 7 derniers jours**. L'ecart avec le curseur n'etait
    pas un detail d'affichage.

    Le calcul est deporte : quelques ms, mais c'est une lecture SQLite dans une base de
    25 Go, et ce portail a paye plusieurs gels pour avoir garde ce genre d'appel dans
    sa boucle d'evenements.
    """
    try:
        from nokido_agent.app.forge_souverainete_reelle import toutes_fenetres
    except Exception:  # noqa: BLE001 — repli sur l'autre nom d'import
        try:
            from app.forge_souverainete_reelle import toutes_fenetres
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"ok": False, "mesure": "INCONNU",
                                 "error": "module de mesure indisponible (%s)"
                                          % type(exc).__name__}, status_code=200)
    try:
        mesures = await asyncio.to_thread(toutes_fenetres)
    except Exception as exc:  # noqa: BLE001 — ILLISIBLE n'est pas « zero local »
        return JSONResponse({"ok": False, "mesure": "INCONNU",
                             "error": "journal d'usage illisible (%s)"
                                      % type(exc).__name__}, status_code=200)
    return JSONResponse({"ok": True, "fenetres": mesures})


@router.get("/providers")
async def page_providers() -> HTMLResponse:
    """GET /providers → poste de saisie. Hors allowlist publique : session requise."""
    return HTMLResponse(_PAGE)
