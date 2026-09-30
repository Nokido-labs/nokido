"""
forge_openai_proxy.py - OpenAI-compatible bridge for LobeHub / Cline / others.

Exposes /v1/chat/completions + /v1/models that wrap the Nokido `ask` MCP
tool. Allows using Nokido as a custom OpenAI-compat provider.

Configuration LobeHub :
  - Provider type : OpenAI Compatible
  - Base URL    : http://127.0.0.1:7777/v1   (or http://<host_lan_ip>:7777/v1)
  - API Key     : laforge-local              (dummy)
  - Models      : auto via /v1/models

Run:
  LAFORGE_PYTHON tools/forge_openai_proxy.py [--port 7777] [--host 127.0.0.1]

Concurrency / event-loop notes (2026-05-02 deadlock fix):
  - Uses a single httpx.AsyncClient singleton (true async I/O, no
    run_in_executor saturation under N parallel requests).
  - Bounded semaphore (HUB_CONCURRENCY) prevents starving uvicorn loop.
  - When the Nokido cascade returns ok=false, this proxy returns
    HTTP 502 with OpenAI-shaped error body. Previously returned HTTP 200
    with empty content - misleading for clients and probes.

Author: CLAUDE - 2026-05-02 (rewritten 2026-05-02 for async + 502)
"""

from __future__ import annotations

# Import oublie, mesure le 2026-09-08 : sys.stderr L616.
import sys

import argparse
import asyncio
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

ROOT = Path(__file__).resolve().parent.parent
HUB_URL = os.environ.get("FORGE_HUB_URL", "http://127.0.0.1:8766/mcp")
TOKEN = os.environ.get("FORGE_MCP_TOKEN", "")

# Bounded concurrency to upstream hub - prevents proxy event-loop starvation
# under burst load (N parallel requests with 30s+ timeout each).
HUB_CONCURRENCY = int(os.environ.get("FORGE_PROXY_HUB_CONCURRENCY", "8"))
HUB_TIMEOUT_DEFAULT = int(os.environ.get("FORGE_PROXY_HUB_TIMEOUT", "180"))

# Voie outils (decision owner 2026-09-25) : si la requete OpenAI porte `tools`, le `ask` du
# hub ne sait PAS function-call -> relai direct au fournisseur du modele DEMANDE, a condition
# que la sonde l'ait MESURE capable d'appeler un outil (voir _toolcall_passthrough). Les
# anciennes variables FORGE_TOOLCALL_BACKEND_URL / _MODEL / _KEY imposaient UN modele a toute
# requete outillee, quel que soit celui demande : elles ne sont plus lues.


def load_token() -> str:
    """Jeton de la passerelle. SON marqueur, jamais le maitre.

    Corrige le 2026-09-02 -- c'etait un CONFUSED DEPUTY. Cette passerelle relaie
    des clients reels et propage LEUR nom (`LaForge-Agent-Name`), ce qui exigeait
    jusqu'ici le jeton MAITRE : lui seul conservait l'agent declare et son ring.
    Consequence : toute requete atteignant :7777 choisissait son identite cote
    hub ET heritait du ring correspondant, administration comprise. Le port est
    local, mais « local » n'est pas « de confiance » -- un client non
    authentifie de cette passerelle disposait du hub entier.

    Le droit de deleguer vit desormais dans le VIDEUR, source de verite, et non
    plus dans un jeton maitre eparpille en peripherie : la passerelle prouve son
    identite propre, le registre lui accorde `delegation.ring_min_delegue`, et
    la trace porte `via=delegated:OPENAI_PROXY`.

    Le repli maitre est conserve pour ne pas rendre la passerelle muette si le
    marqueur n'est pas provisionne -- mais le hub le NOMME desormais
    (`via=bearer_maitre`), donc il ne peut plus passer inapercu.
    """
    try:
        import sys as _sys

        _sys.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        propre = get_secret("FORGE_TOKEN_OPENAI_PROXY")
        if propre:
            return propre
    except Exception:  # muet-ok : coffre indisponible -> replis ci-dessous, la passerelle ne doit pas tomber
        pass
    env_propre = os.environ.get("FORGE_TOKEN_OPENAI_PROXY", "")
    if env_propre:
        return env_propre
    if TOKEN:
        return TOKEN
    env = ROOT / "Nokido.env"
    if env.exists():
        for line in env.read_text(errors="ignore").splitlines():
            if line.startswith("FORGE_TOKEN_OPENAI_PROXY="):
                return line.split("=", 1)[1].strip()
            if line.startswith("FORGE_MCP_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


_TOKEN = load_token()
_REPLI_HUB_DIT = False


def _jeton_hub() -> str:
    """Jeton presente AU HUB, resolu A CHAQUE APPEL.

    DEUX DIRECTIONS A NE PAS CONFONDRE, et la confusion a ete payee le
    2026-09-02 : `_identite_client()` authentifie ce qui ENTRE sur :7777 ;
    ce jeton-ci est ce que la passerelle presente EN SORTIE vers le hub.
    Durcir l'entree ne durcit pas la sortie -- l'entree etait deja gouvernee
    pendant que la sortie portait encore le MAITRE, c'est-a-dire un
    passe-partout capable de se declarer n'importe quel agent.

    Le bail vaut 1800 s et la passerelle vit des jours : le resoudre une fois
    au chargement reviendrait a presenter un jeton expire. `jeton_pour` porte
    son propre cache thread-safe, donc ce chemin ne cree pas de rafale.
    """
    global _REPLI_HUB_DIT
    try:
        import sys as _sys

        _sys.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_agent_credential import jeton_pour  # type: ignore

        court = jeton_pour("OPENAI_PROXY")
        if court:
            return court
    except Exception as _e:  # noqa: BLE001
        if not _REPLI_HUB_DIT:
            _REPLI_HUB_DIT = True
            import logging as _logging

            _logging.getLogger(__name__).warning(
                "[proxy] pont jeton a bail indisponible (%s) — repli sur le "
                "credential charge au demarrage, PERMANENT donc ni expirable "
                "ni revocable. Dit UNE fois pour ne pas noyer le journal.",
                type(_e).__name__)
    return _TOKEN


# --- SemanticFirewall : Golden Rule #4 — jamais d'envoi LLM sans pre/post_flight.
# Le gateway est la membrane où entrent les prompts des CLI externes (shell_gpt,
# llm, aichat, LobeHub…) → la barrière hémato-encéphalique vit ICI. Best-effort :
# si le module est indisponible on logue + dégrade (ne brick pas le gateway),
# mais il est normalement présent dans l'env Nokido.
_FW = None
_FW_TRIED = False


def _fw():
    global _FW, _FW_TRIED
    if not _FW_TRIED:
        _FW_TRIED = True
        try:
            import sys as _s

            _s.path.insert(0, str(ROOT / "app"))
            from nokido_agent.app.forge_semantic_firewall import get_firewall

            _FW = get_firewall()
        except Exception as e:  # noqa: BLE001
            print(
                f"[!] SemanticFirewall indisponible — gateway DEGRADE (pas de pre/post_flight): {e}",
                flush=True,
            )
            _FW = None
    return _FW


# httpx singleton + semaphore - lazy init (must run inside event loop).
import httpx

_HTTPX: httpx.AsyncClient | None = None
_HUB_SEM: asyncio.Semaphore | None = None


def _ensure_runtime() -> tuple[httpx.AsyncClient, asyncio.Semaphore]:
    """Lazy init httpx client + semaphore on first use (inside loop)."""
    global _HTTPX, _HUB_SEM
    if _HTTPX is None:
        # max_connections cap aligns with concurrency cap; HTTP/1.1 keep-alive
        limits = httpx.Limits(
            max_connections=HUB_CONCURRENCY * 2,
            max_keepalive_connections=HUB_CONCURRENCY,
        )
        _HTTPX = httpx.AsyncClient(
            limits=limits,
            timeout=httpx.Timeout(HUB_TIMEOUT_DEFAULT, connect=5.0),
        )
    if _HUB_SEM is None:
        _HUB_SEM = asyncio.Semaphore(HUB_CONCURRENCY)
    return _HTTPX, _HUB_SEM


# Identité du CLIENT gateway courant (RFC 6648 : LaForge-Agent-Name > Agent-Name > X-Agent-Name).
# ContextVar -> propagée à hub_call dans la même task async, sans churn de signatures.
import contextvars as _ctxvars  # noqa: E402

_CLIENT_AGENT = _ctxvars.ContextVar("client_agent", default="OPENAI_PROXY")

# --------------------------------------------------------------------------- #
# IDENTITE DU CLIENT : PROUVEE, plus DECLAREE  (2026-09-02)
# --------------------------------------------------------------------------- #
# Jusqu'ici cette passerelle croyait l'en-tete `LaForge-Agent-Name` sur parole et
# le relayait au hub. Avec le jeton maitre, cela donnait a tout appelant de
# :7777 l'identite ET le ring de son choix -- confused deputy. Le jeton maitre
# est parti, mais la CREDULITE restait : un appelant anonyme choisissait encore
# son nom, borne au plancher de delegation.
#
# Le remede n'exige aucune nouvelle table de secrets : les clients ONT deja un
# credential au coffre (`FORGE_TOKEN_<AGENT>`). Le client presente le sien dans
# `Authorization: Bearer`, exactement comme une clef d'API OpenAI, et la
# passerelle le VALIDE. L'identite devient prouvee de bout en bout.
#
# Regle, et c'est elle qui ferme la faille :
#   jeton entrant reconnu   -> identite PROUVEE, relayee au hub ;
#   jeton absent ou inconnu -> identite = OPENAI_PROXY, JAMAIS le nom declare.
# L'en-tete de nom redevient ce qu'il aurait toujours du etre : un indice de
# journalisation, jamais une preuve.
_CLIENT_PROUVE = _ctxvars.ContextVar("client_prouve", default=False)
_CACHE_CLES: dict = {"ts": 0.0, "par_jeton": {}}
# TTL du cache = DELAI DE REVOCATION. Les deux sont la meme chose, et c'est ce
# qui doit guider la valeur : pendant cette fenetre, un credential retire du
# coffre continue d'ouvrir l'identite qu'il ouvrait. 60 s etait un choix de
# confort ; 10 s coute une lecture de coffre toutes les dix secondes -- une
# depense sans commune mesure avec une identite revoquee qui survit une minute.
# `LAFORGE_PROXY_CLES_TTL` permet de descendre a 0 (aucun cache) si le besoin
# de revocation immediate depasse le cout, sans retoucher le code.
_TTL_CLES = float(os.environ.get("LAFORGE_PROXY_CLES_TTL", "10"))

# Isolation locale : mesure par defaut, refus seulement si on l'arme.
# Deux drapeaux et non un seul, parce que « observer » et « bloquer » sont deux
# decisions distinctes : on veut pouvoir mesurer longtemps avant de couper.
_PAIR_LOCAL_ACTIF = (os.environ.get("LAFORGE_PROXY_PAIR_LOCAL", "1") or "").strip().lower() \
    in ("1", "true", "on", "yes")
_PAIR_LOCAL_BLOQUANT = (os.environ.get("LAFORGE_PROXY_PAIR_LOCAL_BLOQUANT", "") or "") \
    .strip().lower() in ("1", "true", "on", "yes")


def _politique_locale() -> dict:
    """Politique de processus autorises, depuis l'environnement.

    `LAFORGE_PROXY_PROCESS_AUTORISES` / `_INTERDITS`, noms separes par des
    virgules. Vide = mesure seule : le module rend INDETERMINE et rien n'est
    refuse. C'est voulu -- une allowlist devinee refuserait des clients
    legitimes et donnerait l'illusion d'un controle.
    """
    def _lst(cle):
        return [x.strip() for x in (os.environ.get(cle, "") or "").split(",") if x.strip()]

    return {"autorises": _lst("LAFORGE_PROXY_PROCESS_AUTORISES"),
            "interdits": _lst("LAFORGE_PROXY_PROCESS_INTERDITS"),
            # Un NOM ne prouve rien : `claude.exe` depose ailleurs porte le meme
            # nom que le vrai. Le CHEMIN distingue le binaire legitime de son
            # homonyme -- recommandation de la revue M2M du 2026-09-02, qui
            # comble la limite que forge_pair_local signalait deja.
            "chemins_autorises": _lst("LAFORGE_PROXY_CHEMINS_AUTORISES")}


def _table_clients() -> dict:
    """{jeton_client: NOM_AGENT} depuis le coffre. Cache 60 s.

    Ne lit QUE les identites deja declarees au registre : aucune clef inventee,
    aucune liste paralelle a maintenir -- c'est le meme materiau que celui qui
    authentifie ces agents en direct aupres du hub.
    """
    import time as _t

    now = _t.time()
    if now - _CACHE_CLES["ts"] < _TTL_CLES and _CACHE_CLES["par_jeton"]:
        return _CACHE_CLES["par_jeton"]
    table: dict = {}
    try:
        import json as _j
        import sys as _s

        _s.path.insert(0, str(ROOT / "app"))
        from nokido_agent.app.forge_secrets import get_secret  # type: ignore

        reg = ROOT / "config" / "agent_identities.json"
        agents = (_j.loads(reg.read_text(encoding="utf-8")) or {}).get("agents") or {}
        for nom, meta in agents.items():
            try:
                if int(meta.get("ring", 4)) > 3:
                    continue          # au plancher, rien a prouver
            except (TypeError, ValueError):
                continue
            val = get_secret("FORGE_TOKEN_%s" % nom)
            if val:
                table[val] = nom.upper()
    except Exception:  # muet-ok : table vide -> tout client retombe sur OPENAI_PROXY, jamais l'inverse
        table = {}
    _CACHE_CLES.update({"ts": now, "par_jeton": table})
    return table


def _identite_client(headers) -> tuple:
    """(nom, prouvee). Le nom declare n'est JAMAIS retenu sans preuve.

    Le defaut est `OPENAI_PROXY` : une passerelle qui ne sait pas qui l'appelle
    parle en son propre nom, elle n'emprunte pas celui qu'on lui souffle.
    """
    brut = headers.get("Authorization") or headers.get("authorization") or ""
    if brut.lower().startswith("bearer "):
        jeton = brut[7:].strip()
        # Comparaison en TEMPS CONSTANT. Un `dict.get` sort des l'octet qui
        # differe : le temps de reponse depend alors du prefixe correct, ce qui
        # se mesure et permet de reconstruire un jeton octet par octet. Le cout
        # est de parcourir toute la table (27 entrees) a chaque requete -- une
        # depense negligeable devant ce qu'elle empeche.
        # On ne s'arrete PAS au premier succes : sortir tot reintroduirait la
        # fuite qu'on vient de fermer.
        import hmac as _hm

        trouve = ""
        for _tok, _nom in _table_clients().items():
            try:
                if _hm.compare_digest(jeton.encode(), _tok.encode()):
                    trouve = _nom
            except Exception:  # muet-ok : jeton non encodable -> non reconnu, jamais autorise
                pass
        if trouve:
            return trouve, True
    return "OPENAI_PROXY", False


async def hub_call(name: str, args: dict, timeout: int | None = None) -> dict:
    """Call MCP hub asynchronously via shared httpx.AsyncClient."""
    client, sem = _ensure_runtime()
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_jeton_hub()}",
        # RFC 6648 : LaForge-Agent-Name (PAS X-). Propage l'identité du client gateway
        # (ex. CLAUDE_DESKTOP) si fournie, sinon OPENAI_PROXY -> gouvernance hub par client réel.
        "LaForge-Agent-Name": _CLIENT_AGENT.get(),
    }
    t = timeout if timeout is not None else HUB_TIMEOUT_DEFAULT
    async with sem:
        resp = await client.post(HUB_URL, json=body, headers=headers, timeout=t)
        resp.raise_for_status()
        return resp.json()


# ============================================================
# OpenAI-compatible endpoints
# ============================================================
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

# Mapping models LobeHub -> providers Nokido `ask`
MODEL_TO_PROVIDER = {
    # Nokido native cascade (router = RouterCascadeProvider ; 'auto' n'est PAS un provider valide)
    "laforge-cascade": "router",
    # nokido/auto : sans outils (titres de session...), la cascade du routeur via `ask` ;
    # avec outils, _servir_auto (candidats mesures, bascule typee).
    "auto": "router",
    "nokido/auto": "router",
    "laforge-router": "router",
    # Local
    "qwen2.5-coder": "ollama",
    "qwen2.5-coder-7b": "ollama",
    "qwen2.5-coder-32b": "ollama",
    "qwen3-8b": "ollama",
    "deepseek-r1-14b": "ollama",
    "deepseek-coder": "ollama",
    "gemma4-e4b": "ollama",
    "llamacpp-local": "llamacpp",
    "lmstudio": "lmstudio",
    # Cloud
    "claude-sonnet-4.6": "claude",
    "gemini-2.5-flash": "gemini",
    "gemini-2.5-pro": "gemini",
    # CLI OAuth REELS (le vrai AGY qui code/raisonne, pas l'API gemini) exposes
    # comme modeles :7777 -> debat CLI-to-CLI qui TRANSITE PAR LE HUB (owner
    # 2026-08-13 : "tu n'es qu'un client, transite par lui"). Route vers le
    # provider gemini_cli (=agy.exe). ⚠️ Exige l'OAuth agy accessible au hub :
    # en headless pur il rend "authentication failed" — c'est alors un geste
    # owner (pont dans la session interactive), pas un defaut de ce mapping.
    "agy": "gemini_cli",
    "antigravity": "gemini_cli",
    "agy-cli": "gemini_cli",
    "claude-code": "claude_cli",
    "groq-llama-70b": "groq",
    "deepseek-v3": "deepseek",
    "grok-2": "grok",
    "mistral-large": "mistral",
    "gpt-4o-github": "gpt4o_github",
    "kimi-think": "kimi_think",
    "glm5": "glm5",
    "perplexity": "perplexity",
}


def _model_to_provider(model: str) -> tuple[str, str | None]:
    """Returns (provider, model_override) for the `ask` tool."""
    model_low = model.lower().strip()
    if model_low in MODEL_TO_PROVIDER:
        return MODEL_TO_PROVIDER[model_low], None
    # Format provider/model (e.g. "ollama/qwen3:8b") -> split
    if "/" in model:
        prov, sub = model.split("/", 1)
        return prov.lower(), sub
    # Fallback : cascade qualité via RouterCascadeProvider (name='router')
    return "router", model


def _openai_error(
    message: str, etype: str = "upstream_error", status: int = 502, code: str | None = None
) -> JSONResponse:
    """OpenAI-shaped error response."""
    err: dict[str, Any] = {"message": message, "type": etype}
    if code:
        err["code"] = code
    return JSONResponse({"error": err}, status_code=status)


def _extract_ask_text(rpc_resp: dict) -> tuple[str, dict]:
    """Pull the JSON payload out of MCP `tools/call` envelope.

    Returns (raw_text, parsed_inner). parsed_inner is the parsed JSON dict
    if the inner text was JSON, else {}.
    """
    text = rpc_resp.get("result", {}).get("content", [{}])[0].get("text", "")
    try:
        inner = json.loads(text)
        if isinstance(inner, dict):
            return text, inner
    except Exception:
        pass
    return text, {}


async def health(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "forge_openai_proxy",
            "hub": HUB_URL,
            "version": "1.1",
            "concurrency": HUB_CONCURRENCY,
            "timestamp": int(time.time()),
        }
    )


async def list_models(request: Request) -> JSONResponse:
    """GET /v1/models - list of models available via configured providers."""
    try:
        r = await hub_call("hub", {"action": "list_providers"}, timeout=20)
        text = r.get("result", {}).get("content", [{}])[0].get("text", "{}")
        try:
            data = json.loads(text)
        except Exception:
            data = {}
        configured = data.get("configured", []) if isinstance(data, dict) else []
        models = []
        for p in configured:
            if not p.get("available"):
                continue
            for m in p.get("models", [p["name"]]):
                models.append(
                    {
                        "id": m,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "laforge",
                        "provider": p["name"],
                        "ring": p.get("ring", 3),
                        "latency_ms": p.get("latency_ms"),
                    }
                )
        for alias in MODEL_TO_PROVIDER:
            if not any(m["id"] == alias for m in models):
                models.append(
                    {
                        "id": alias,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "laforge-alias",
                    }
                )
        return JSONResponse({"object": "list", "data": models})
    except Exception:
        # FAIL-SOFT (durable, anti crash-loop) : hub indisponible au boot -> 500 sur /v1/models
        # -> le superviseur tue le proxy -> crash-loop -> :7777 down après CHAQUE reboot. On sert
        # la liste statique des alias (200) : le proxy reste UP, le routage se rétablit dès que le
        # hub répond. RÈGLE : ne JAMAIS 500 sur la découverte de modèles (santé du service).
        fallback = [
            {"id": a, "object": "model", "created": int(time.time()), "owned_by": "laforge-alias"}
            for a in MODEL_TO_PROVIDER
        ]
        return JSONResponse({"object": "list", "data": fallback})


# ── Voie outils : le modele DEMANDE, mesure capable, ou un refus qui le dit ───────────────
# MESURE du 2026-09-25 : opencode demandait un modele, la passerelle en imposait un autre
# (qwen2.5-coder:latest via ollama) a toute requete outillee ; ce 7B rendait ses appels
# d'outil en TEXTE, opencode n'executait rien, et rien ne disait qu'un autre modele avait
# repondu. La liste BLANCHE est desormais la mesure de tools/forge_tool_call_probe.py : seul
# `APPELLE` est servi. IGNORE est le pire cas -- le modele ne rougit nulle part, il bavarde --
# et c'est exactement le defaut qu'on venait de payer.
_AGENTS_CLI = {"claude_cli", "gemini_cli"}
_VERDICTS_MEMO: dict = {"cle": None, "verdicts": {}}
# Empreintes deja controlees saines : un agent renvoie TOUT son historique a chaque tour.
_FW_SAINS: set = set()
_FW_SAINS_MAX = 4096


def _surfaces_outils() -> dict:
    """fournisseur -> (nom de cle, URL de base) : la table de la sonde qui a MESURE, pas une copie."""
    from nokido_agent.tools.forge_tool_call_probe import SURFACES

    return {nom: (cle, base) for nom, cle, base in SURFACES}


def _verdicts_outils(chemin: Path | None = None) -> dict:
    """(fournisseur, modele) -> APPELLE / IGNORE / REFUSE / NON_MESURE, relu quand le rapport change.

    Leve si le rapport est illisible : l'appelant le DIT, il ne conclut pas « aucun modele ».
    """
    if chemin is None:
        from nokido_agent.tools.forge_tool_call_probe import SORTIE

        chemin = SORTIE
    cle = (str(chemin), chemin.stat().st_mtime)
    if _VERDICTS_MEMO["cle"] != cle:
        lignes = json.loads(chemin.read_text(encoding="utf-8")).get("resultats") or []
        _VERDICTS_MEMO["verdicts"] = {
            (str(r.get("fournisseur")), str(r.get("modele"))): str(r.get("etat"))
            for r in lignes if isinstance(r, dict)
        }
        _VERDICTS_MEMO["cle"] = cle
    return _VERDICTS_MEMO["verdicts"]


def _cle_fournisseur(nom_cle: str) -> str:
    """Cle du fournisseur, lue comme la sonde l'a lue (coffre d'abord), jamais passee en argument."""
    if not nom_cle:
        return ""
    from nokido_agent.app.forge_secrets import get_secret

    return get_secret(nom_cle) or ""


def _resoudre_voie_outils(model: str) -> dict:
    """Modele demande -> {"etat": "SERVI", ...} ou {"etat": "REFUSE", "motif"} -- jamais un AUTRE modele."""
    demande = (model or "").strip()
    alias = MODEL_TO_PROVIDER.get(demande.lower())
    if alias in _AGENTS_CLI:
        return {"etat": "REFUSE", "motif": (
            f"'{demande}' est un agent CLI ({alias}) : il repond en texte et execute ses PROPRES "
            f"outils, il ne fait pas de function-calling OpenAI. Le piloter par le hub "
            f"(ask provider={alias}, agy_run), pas comme modele d'un autre agent.")}
    try:
        verdicts = _verdicts_outils()
        surfaces = _surfaces_outils()
    except Exception as exc:  # noqa: BLE001 - rapport ou table illisible : on le DIT
        return {"etat": "REFUSE", "motif": (
            f"mesure du function-calling ILLISIBLE ({type(exc).__name__}) : aucun modele ne peut "
            f"etre prouve capable d'appeler un outil -- relancer tools/forge_tool_call_probe.py")}
    servables = ", ".join(sorted(f"{f}/{m}" for (f, m), e in verdicts.items()
                                 if e == "APPELLE" and f in surfaces)) or "aucun"
    fournisseur, _, modele = demande.partition("/")
    if not modele or fournisseur not in surfaces:
        return {"etat": "REFUSE", "motif": (
            f"'{demande}' : jamais mesure pour le function-calling (forme attendue "
            f"<fournisseur>/<modele>, fournisseurs mesures : {', '.join(sorted(surfaces))}). "
            f"Modeles qui appellent REELLEMENT un outil : {servables}")}
    etat = verdicts.get((fournisseur, modele))
    if etat != "APPELLE":
        constat = f"mesure {etat}" if etat else "jamais mesure"
        return {"etat": "REFUSE", "motif": (
            f"'{demande}' : function-calling {constat} (tools/forge_tool_call_probe.py). "
            f"Modeles qui appellent REELLEMENT un outil : {servables}")}
    nom_cle, base = surfaces[fournisseur]
    hote = base.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return {"etat": "SERVI", "fournisseur": fournisseur, "modele": modele, "servi": demande,
            "url": f"{base.rstrip('/')}/chat/completions", "nom_cle": nom_cle,
            "local": hote in ("127.0.0.1", "localhost")}


def _texte_du_message(m: dict) -> str:
    contenu = m.get("content")
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return "\n".join(str(c.get("text", "")) for c in contenu
                         if isinstance(c, dict) and c.get("type") in ("text", "input_text"))
    return ""


def _pare_feu_entree(messages: list, voie: dict) -> str | None:
    """Motif du premier refus, sinon None. TOUT ce qui part passe : system, user, et les RESULTATS
    d'outil (fichiers lus) -- l'ancienne voie ne lisait que le dernier message user."""
    fw = _fw()
    if fw is None:
        return None  # passerelle DEGRADE, annoncee au premier appel de _fw()
    fournisseur = "local" if voie["local"] else voie["fournisseur"]
    for i, m in enumerate(messages or []):
        if not isinstance(m, dict) or m.get("role") == "assistant":
            continue  # l'assistant rejoue ce que le modele a deja produit
        texte = _texte_du_message(m)
        if not texte.strip():
            continue
        empreinte = hashlib.sha256(f"{fournisseur}\x00{texte}".encode("utf-8", "replace")).hexdigest()
        if empreinte in _FW_SAINS:
            continue
        try:
            pf = fw.pre_flight(texte, ring=3, provider=fournisseur)
        except Exception as exc:  # noqa: BLE001 - un pare-feu illisible ne vaut pas un feu vert
            return f"pare-feu ILLISIBLE sur le message {i} ({m.get('role')}) : {type(exc).__name__}"
        if not pf.ok:
            return f"message {i} ({m.get('role')}) : {pf.reason}"
        if len(_FW_SAINS) >= _FW_SAINS_MAX:
            _FW_SAINS.clear()  # memo seulement : le vider coute des re-controles, jamais un trou
        _FW_SAINS.add(empreinte)
    return None


def _pare_feu_sortie(message: dict) -> str | None:
    """Motif du refus de sortie, sinon None. Les ARGUMENTS d'outil sont controles comme le texte :
    c'est par eux qu'une sortie piegee deviendrait une action."""
    fw = _fw()
    if fw is None:
        return None
    morceaux = [message.get("content") or ""]
    for tc in message.get("tool_calls") or []:
        fn = (tc or {}).get("function") or {}
        morceaux.append(f"{fn.get('name', '')} {fn.get('arguments', '')}")
    sortie = "\n".join(x for x in morceaux if isinstance(x, str) and x)
    if not sortie.strip():
        return None
    try:
        pfr = fw.post_flight(sortie)
    except Exception as exc:  # noqa: BLE001
        return f"pare-feu de sortie ILLISIBLE : {type(exc).__name__}"
    return None if pfr.ok else f"{pfr.tag} {pfr.reason}".strip()


# Pseudonymisation (decision owner 2026-09-25). MESURE : opencode met `Working directory:
# C:\Users\<compte>\...` dans CHAQUE prompt systeme ; la DLP le classe sensible et refuse toute
# donnee sensible vers le cloud -> chaque requete bloquee. Vers un fournisseur CLOUD, la voie
# passe par la SovereignMembrane en mode REVERSIBLE : le fournisseur ne voit que des alias
# (stables par client, d'un tour a l'autre), la reponse -- texte ET arguments d'outil, JSON
# valide -- est restituee avant le client. Le pare-feu juge ensuite le texte ENVELOPPE : ce que
# la membrane aurait rate reste BLOQUE par la DLP. Local : rien ne sort, rien a masquer.
_MEMBRANES: dict = {}


def _membrane_de(client: str):
    """Une membrane par identite cliente (alias persistants par mission)."""
    if client not in _MEMBRANES:
        from nokido_agent.app.forge_sovereign_membrane import SovereignMembrane

        _MEMBRANES[client] = SovereignMembrane.for_mission("passerelle_%s" % client)
    return _MEMBRANES[client]


def _ouvrir_voie_outils(model: str, messages: list,
                        tools: list | None = None) -> tuple[dict | None, JSONResponse | None]:
    """(voie, None) si le modele demande est servable et l'entree saine, sinon (None, erreur OpenAI).

    La voie porte ce qui PART (`messages`, `tools`, enveloppes vers le cloud) et la `membrane`
    qui restituera la reponse (None en local).
    """
    voie = _resoudre_voie_outils(model)
    if voie["etat"] != "SERVI":
        return None, _openai_error(voie["motif"], etype="invalid_request_error", status=400,
                                   code="tool_calling_non_prouve")
    return _preparer_voie(voie, messages, tools)


def _preparer_voie(voie: dict, messages: list,
                   tools: list | None) -> tuple[dict | None, JSONResponse | None]:
    """Voie RESOLUE -> ce qui PART : membrane vers le cloud, pare-feu. (voie prete, None) ou erreur."""
    membrane = None
    if not voie["local"]:
        try:
            membrane = _membrane_de(_CLIENT_AGENT.get())
            messages = membrane.wrap_objet(messages)
            tools = membrane.wrap_objet(tools) if tools else tools
        except Exception as exc:  # noqa: BLE001 - sans membrane, rien ne part au cloud
            return None, _openai_error(
                "membrane souveraine ILLISIBLE (%s) : requete NON envoyee a %s"
                % (type(exc).__name__, voie["fournisseur"]),
                etype="upstream_error", status=503, code="membrane_illisible")
    motif = _pare_feu_entree(messages, voie)
    if motif:
        return None, _openai_error(f"blocked by semantic firewall: {motif}",
                                   etype="invalid_request_error", status=403, code="firewall_blocked")
    return dict(voie, messages=messages, tools=tools, membrane=membrane), None


_CLE_ILLISIBLE = -1  # code interne : la requete n'est PAS partie


async def _appel_brut(voie: dict, charge: dict) -> tuple[dict | None, int | None, str]:
    """UN appel COMPLET : (reponse, None, "") ou (None, code HTTP | None si injoignable, detail)."""
    cle = _cle_fournisseur(voie["nom_cle"])
    if voie["nom_cle"] and not cle and not voie["local"]:
        return None, _CLE_ILLISIBLE, (f"cle {voie['nom_cle']} ILLISIBLE pour le compte de la passerelle : "
                                      f"requete NON envoyee a {voie['fournisseur']}")
    entetes = {"Content-Type": "application/json"}
    if cle:
        entetes["Authorization"] = f"Bearer {cle}"
    client, _sem = _ensure_runtime()
    try:
        resp = await client.post(voie["url"], json=charge, headers=entetes, timeout=HUB_TIMEOUT_DEFAULT)
        resp.raise_for_status()
        return resp.json(), None, ""
    except httpx.HTTPStatusError as e:
        return None, e.response.status_code, e.response.text[:300]
    except httpx.HTTPError as e:
        return None, None, f"{type(e).__name__} {e}"


async def _appel_outille(voie: dict, charge: dict) -> tuple[dict | None, JSONResponse | None]:
    """UN appel COMPLET au fournisseur du modele demande : (reponse, None) ou (None, erreur OpenAI)."""
    donnees, code, detail = await _appel_brut(voie, charge)
    if donnees is not None:
        return donnees, None
    if code == _CLE_ILLISIBLE:
        return None, _openai_error(detail, etype="upstream_error", status=503, code="cle_illisible")
    if code is None:
        return None, _openai_error(f"{voie['servi']} injoignable : {detail}",
                                   etype="upstream_error", status=502)
    return None, _openai_error(f"{voie['servi']} : HTTP {code} du fournisseur : {detail}",
                               etype="upstream_error", status=502)


# ── Observabilite de la passerelle (cahier des charges nokido/auto, owner 2026-09-25) ───────
# Le hub est la source d'autorite de la consommation : l'usage RAPPORTE par le fournisseur va
# au recorder canonique (forge_token_monitor.log_call), chaque requete laisse UNE ligne de
# decision rejouable (tente / ecarte / servi, et pourquoi).
_JOURNAL_DECISIONS = ROOT / "sandbox" / "passerelle_decisions.jsonl"


def _compter_jetons(voie: dict, donnees: dict, latence_ms: float, requete: str,
                    logique: str = "") -> str:
    """Usage RAPPORTE -> token_usage. Absent : compteurs None = NON MESURE, jamais un zero.

    Rend "COMPTE" ou "NON_COMPTE: <cause>" -- la cause va au journal de decision, LISIBLE.
    MESURE 2026-09-25 : un echec n'etait ecrit que sur stderr (capture du superviseur,
    chemin inconnu) ; la requete nokido/auto de preuve manquait au journal sans cause visible.
    """
    usage = (donnees or {}).get("usage") or {}
    entree, sortie = usage.get("prompt_tokens"), usage.get("completion_tokens")
    rapporte = entree is not None and sortie is not None
    try:
        from nokido_agent.app.forge_token_monitor import log_call

        log_call(agent_id=_CLIENT_AGENT.get(), provider=voie["fournisseur"], model=voie["servi"],
                 prompt_tokens=entree, completion_tokens=sortie, latency_ms=round(latence_ms, 1),
                 source="passerelle_7777", execution_id=requete, provenance=_CLIENT_AGENT.get(),
                 transport="openai_compat", measurement_kind="REPORTED" if rapporte else "UNKNOWN",
                 measurement_source=("api_usage:%s" % voie["fournisseur"]) if rapporte else None,
                 meta={"modele_logique": logique} if logique else None)
        return "COMPTE"
    except Exception as exc:  # noqa: BLE001 - un usage non compte se DIT
        cause = "NON_COMPTE: %s: %s" % (type(exc).__name__, str(exc)[:160])
        print("[proxy] usage %s pour %s" % (cause, voie["servi"]), file=sys.stderr, flush=True)
        return cause


def _journaliser_decision(entree: dict) -> None:
    try:
        _JOURNAL_DECISIONS.parent.mkdir(parents=True, exist_ok=True)
        with open(_JOURNAL_DECISIONS, "a", encoding="utf-8") as f:
            f.write(json.dumps(entree, ensure_ascii=False) + "\n")
    except OSError as exc:
        print("[proxy] decision NON journalisee (%s) : requete %s"
              % (type(exc).__name__, entree.get("requete")), file=sys.stderr, flush=True)


# ── nokido/auto : modele LOGIQUE, le ROUTEUR choisit ─────────────────────────────────────────
# MESURE 2026-09-25 : opencode sur groq/openai/gpt-oss-20b -> « 413 ... TPM Limit 8000,
# Requested 25631 », et rien ne basculait. Aucun routage parallele : l'ORDRE et la SANTE
# viennent du routeur (chaine `agent_code`, ProviderSlot.is_available, record_*), la preuve
# d'appel d'outil vient de la sonde. La passerelle essaie, classe l'echec, bascule ou s'arrete.
MODELES_AUTO = {"auto", "nokido/auto"}
CHAINE_AUTO = "agent_code"
_REJOUABLES = {"CAPACITE", "DEBIT", "INDISPONIBLE", "AUTH"}


def _estimer_jetons(body: dict) -> int:
    """Estimation GROSSIERE (4 caracteres par jeton) de ce qui part : sert a ECARTER un candidat
    dont la capacite DECLAREE est depassee ; le verdict final reste celui du fournisseur (413)."""
    # 2,5 car./jeton et non 4 : MESURE runtime 2026-09-25, 25 330 jetons estimes a 4 car. pour
    # 41 010 comptes par le fournisseur (texte francais). Sous-estimer laisse partir une requete
    # vers un plafond declare trop petit (413, puis bascule) ; sur-estimer ecarte un candidat.
    return int(len(json.dumps([body.get("messages"), body.get("tools")], ensure_ascii=False,
                              default=str)) / 2.5)


def _classer_echec(code: int | None, detail: str) -> str:
    t = (detail or "").lower()
    if code == 413 or (code == 400 and any(k in t for k in (
            "context", "too large", "too long", "maximum", "tokens per"))):
        return "CAPACITE"
    if code == 429:
        return "DEBIT"
    if code is None or code >= 500:
        return "INDISPONIBLE"
    if code in (_CLE_ILLISIBLE, 401, 403):
        return "AUTH"
    return "NON_REJOUABLE"


def _resumer(tentatives: list[dict]) -> str:
    return ";".join("%s=%s" % (t["candidat"], t["classe"]) for t in tentatives)


def _candidats_auto(jetons: int) -> tuple[list[dict], list[dict]]:
    """(candidats, ecartes) dans l'ordre du ROUTEUR. Retenu = modele MESURE APPELLE, slot SAIN
    (cle, disjoncteur, refroidissement, debit : `is_available`), capacite DECLAREE suffisante.
    Chaque ecarte est NOMME avec sa raison."""
    from nokido_agent.app.forge_llm_router import chaine_active, get_router

    routeur = get_router()
    verdicts = _verdicts_outils()
    surfaces = _surfaces_outils()
    par_base = {base.rstrip("/"): nom for nom, (_cle, base) in surfaces.items()}
    candidats: list[dict] = []
    ecartes: list[dict] = []
    for nom in chaine_active(CHAINE_AUTO):
        slot = routeur.slot(nom)
        if slot is None:
            continue
        for modele_slot in slot.config.get("models") or []:
            # Identifiant « fournisseur/modele » de la SONDE. Un slot local declare son modele
            # SANS prefixe (lmstudio_native) : le fournisseur se lit alors sur son URL de base.
            # MESURE runtime 2026-09-25 : le repli local n'etait jamais candidat.
            prefixe = modele_slot.split("/", 1)[0]
            if prefixe in surfaces:
                identifiant = modele_slot
            else:
                local = par_base.get(str(slot.config.get("base_url") or "").rstrip("/"))
                identifiant = "%s/%s" % (local, modele_slot) if local else modele_slot
            if verdicts.get(tuple(identifiant.split("/", 1))) != "APPELLE":
                ecartes.append({"candidat": identifiant, "classe": "OUTILS_NON_PROUVES"})
                continue
            if not slot.is_available:
                ecartes.append({"candidat": identifiant, "classe": "INDISPONIBLE",
                                "detail": "routeur : cle, disjoncteur, refroidissement ou debit"})
                continue
            plafond = min((v for v in (slot.config.get("tpm"), slot.config.get("context")) if v),
                          default=None)
            if plafond and jetons > plafond:
                ecartes.append({"candidat": identifiant, "classe": "CAPACITE",
                                "detail": "~%d jetons > %d declares" % (jetons, plafond)})
                continue
            voie = _resoudre_voie_outils(identifiant)
            if voie["etat"] == "SERVI":
                candidats.append(dict(voie, slot=slot))
            else:
                ecartes.append({"candidat": identifiant, "classe": "OUTILS_NON_PROUVES",
                                "detail": voie["motif"][:120]})
    return candidats, ecartes


def _rendre(donnees: dict, servi: str, stream: bool, entetes: dict):
    if not stream:
        return JSONResponse(donnees, headers=entetes)
    return StreamingResponse(
        _sse_depuis_reponse(donnees, servi), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", **entetes},
    )


async def _servir_auto(body: dict, stream: bool):
    """Essaie les candidats du routeur dans l'ordre ; bascule SEULEMENT sur un echec rejouable.

    INVARIANT : l'appel amont est COMPLET (jamais de flux amont) et rien n'est transmis au client
    avant le succes -- une bascule ne peut donc jamais doubler une generation ni un appel d'outil.
    """
    requete = uuid.uuid4().hex[:16]
    jetons = _estimer_jetons(body)
    try:
        candidats, tentatives = _candidats_auto(jetons)
    except Exception as exc:  # noqa: BLE001 - un routeur illisible ne vaut pas un choix
        return _openai_error("nokido/auto : routeur ILLISIBLE (%s)" % type(exc).__name__,
                             etype="upstream_error", status=503, code="routeur_illisible")
    journal = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "requete": requete,
               "client": _CLIENT_AGENT.get(), "modele_logique": "nokido/auto",
               "jetons_estimes": jetons, "tentatives": tentatives, "servi": None}
    for n, voie in enumerate(candidats, 1):
        prete, erreur = _preparer_voie(voie, body.get("messages") or [], body.get("tools"))
        if erreur is not None:
            # Pare-feu ou membrane : le MEME contenu partirait partout -> non rejouable.
            tentatives.append({"tentative": n, "candidat": voie["servi"], "classe": "NON_REJOUABLE",
                               "detail": "entree refusee avant envoi"})
            _journaliser_decision(journal)
            return erreur
        charge = {k: v for k, v in body.items() if k not in ("stream", "stream_options")}
        charge.update(model=prete["modele"], stream=False, messages=prete["messages"])
        if body.get("tools"):
            charge["tools"] = prete["tools"]
        t0 = time.monotonic()
        donnees, code, detail = await _appel_brut(prete, charge)
        if donnees is None:
            classe = _classer_echec(code, detail)
            tentatives.append({"tentative": n, "candidat": voie["servi"], "classe": classe,
                               "http": code, "detail": (detail or "")[:160]})
            if classe == "DEBIT":
                voie["slot"].record_rate_limit()
            elif classe in ("INDISPONIBLE", "AUTH"):
                voie["slot"].record_failure()
            if classe in _REJOUABLES:
                continue
            break
        latence = (time.monotonic() - t0) * 1000
        choix = (donnees.get("choices") or [{}])[0] or {}
        motif = _pare_feu_sortie(choix.get("message") or {})
        if motif:
            tentatives.append({"tentative": n, "candidat": voie["servi"], "classe": "SORTIE_REFUSEE"})
            _journaliser_decision(journal)
            return _openai_error(f"response blocked by semantic firewall: {motif}",
                                 etype="upstream_error", status=502, code="firewall_post_blocked")
        voie["slot"].record_call(latence)
        if prete["membrane"] is not None:
            donnees["choices"] = prete["membrane"].unwrap_objet(donnees.get("choices") or [],
                                                                model=voie["servi"])
        tentatives.append({"tentative": n, "candidat": voie["servi"], "classe": "SERVI"})
        journal["servi"] = voie["servi"]
        journal["usage"] = _compter_jetons(prete, donnees, latence, requete, "nokido/auto")
        _journaliser_decision(journal)
        return _rendre(donnees, voie["servi"], stream, {
            "X-Nokido-Modele-Servi": voie["servi"], "X-Nokido-Modele-Logique": "nokido/auto",
            "X-Nokido-Requete": requete, "X-Nokido-Tentatives": _resumer(tentatives)})
    _journaliser_decision(journal)
    dernier = tentatives[-1]["classe"] if tentatives else ""
    return _openai_error(
        "nokido/auto : aucun modele n'a servi -- %s"
        % (_resumer(tentatives) or "chaine %s vide" % CHAINE_AUTO),
        etype="upstream_error", status=502 if dernier == "NON_REJOUABLE" else 503,
        code="auto_epuise")


async def _sse_depuis_reponse(donnees: dict, servi: str):
    """Rend une reponse COMPLETE, deja passee au pare-feu, en flux SSE OpenAI : texte, appels, fin."""
    cid = donnees.get("id") or f"chatcmpl-{uuid.uuid4().hex[:24]}"
    cree = int(donnees.get("created") or time.time())
    modele = donnees.get("model") or servi
    choix = (donnees.get("choices") or [{}])[0] or {}
    message = choix.get("message") or {}

    def _morceau(delta: dict, fin=None, **extra) -> str:
        charge = {"id": cid, "object": "chat.completion.chunk", "created": cree, "model": modele,
                  "choices": [{"index": 0, "delta": delta, "finish_reason": fin}], **extra}
        return f"data: {json.dumps(charge, ensure_ascii=False)}\n\n"

    yield _morceau({"role": "assistant"})
    texte = message.get("content") or ""
    for i in range(0, len(texte), 80):
        yield _morceau({"content": texte[i:i + 80]})
    appels = [dict(tc, index=n) for n, tc in enumerate(message.get("tool_calls") or [])
              if isinstance(tc, dict)]
    if appels:
        yield _morceau({"tool_calls": appels})
    fin = choix.get("finish_reason") or ("tool_calls" if appels else "stop")
    extra = {"usage": donnees["usage"]} if donnees.get("usage") else {}
    yield _morceau({}, fin, **extra)
    yield "data: [DONE]\n\n"


async def _toolcall_passthrough(body: dict, stream: bool):
    """Requete OpenAI AVEC `tools` : servie par le modele DEMANDE s'il est mesure capable, sinon refusee.

    `ask` (hub) ne fait pas de function-calling -> relai direct au fournisseur (URL et cle de la
    table de la sonde). Pare-feu sur tout ce qui part et sur ce qui revient (texte ET arguments
    d'outil) ; le modele servi est DECLARE (`X-Nokido-Modele-Servi`). L'appel amont est COMPLET
    meme si le client demande un flux : la sortie passe le pare-feu AVANT d'etre rendue, comme
    sur la voie `ask` (stream_chat_completion).
    """
    if str(body.get("model", "")).strip().lower() in MODELES_AUTO:
        return await _servir_auto(body, stream)
    voie, erreur = _ouvrir_voie_outils(str(body.get("model", "")), body.get("messages") or [],
                                       body.get("tools"))
    if erreur is not None:
        return erreur
    charge = {k: v for k, v in body.items() if k not in ("stream", "stream_options")}
    charge["model"] = voie["modele"]
    charge["stream"] = False
    charge["messages"] = voie["messages"]
    if body.get("tools"):
        charge["tools"] = voie["tools"]
    requete = uuid.uuid4().hex[:16]
    t0 = time.monotonic()
    donnees, erreur = await _appel_outille(voie, charge)
    if erreur is not None:
        return erreur
    choix = (donnees.get("choices") or [{}])[0] or {}
    motif = _pare_feu_sortie(choix.get("message") or {})
    if motif:
        return _openai_error(f"response blocked by semantic firewall: {motif}",
                             etype="upstream_error", status=502, code="firewall_post_blocked")
    if voie["membrane"] is not None:
        donnees["choices"] = voie["membrane"].unwrap_objet(donnees.get("choices") or [],
                                                           model=voie["servi"])
    _journaliser_decision({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "requete": requete,
        "client": _CLIENT_AGENT.get(), "modele_logique": None, "servi": voie["servi"],
        "usage": _compter_jetons(voie, donnees, (time.monotonic() - t0) * 1000, requete)})
    return _rendre(donnees, voie["servi"], stream,
                   {"X-Nokido-Modele-Servi": voie["servi"], "X-Nokido-Requete": requete})


async def chat_completions(request: Request) -> JSONResponse | StreamingResponse:
    """POST /v1/chat/completions - OpenAI ChatCompletion compat.

    Error semantics (post fix 2026-05-02):
      - cascade returns ok=false        -> HTTP 502 upstream_error
      - upstream timeout / network err  -> HTTP 504 timeout / 502 upstream_error
      - malformed request               -> HTTP 400 invalid_request_error
      - internal exception              -> HTTP 500 internal_error
    """
    # RFC identité du client gateway (Claude Desktop, etc.) : LaForge-Agent-Name > Agent-Name
    # > X-Agent-Name (legacy déprécié). Propagé au hub via _CLIENT_AGENT (gouvernance par client).
    # IDENTITE PROUVEE, plus declaree (2026-09-02). L'en-tete de nom n'est plus
    # relaye au hub : seul un jeton client RECONNU vaut identite. Un appelant
    # sans preuve parle desormais sous le nom de la passerelle, ce qui ferme
    # l'usurpation que la delegation ne faisait que borner.
    _h = request.headers
    _nom, _prouve = _identite_client(_h)
    _CLIENT_AGENT.set(_nom)
    _CLIENT_PROUVE.set(_prouve)

    # ISOLATION LOCALE -- point 5 de la revue du 2026-09-02. Ecouter sur
    # 127.0.0.1 protege du reseau, pas de la machine : tout processus du meme
    # compte peut se connecter. La recommandation classique (named pipe, socket
    # de domaine avec ACL) est inapplicable ici -- les clients implementent
    # l'API OpenAI, donc HTTP sur TCP ; changer de transport supprimerait le
    # service au lieu de le durcir. On identifie donc le PROCESSUS au bout de
    # la connexion, ce qui est l'equivalent d'une ACL au-dessus du transport.
    #
    # OBSERVATION d'abord, refus ensuite : la politique est VIDE au depart et se
    # remplit d'appelants MESURES. Armer une allowlist devinee couperait des
    # clients legitimes que personne n'a pense a lister -- meme discipline que
    # la matrice d'autorisation, qui a mis une journee a se remplir de faits.
    if _PAIR_LOCAL_ACTIF:
        try:
            from nokido_agent.app import forge_pair_local as _pl

            _v = _pl.verdict(request.client.port if request.client else None,
                             _politique_locale())
            if _v["etat"] == _pl.REFUSE and _PAIR_LOCAL_BLOQUANT:
                return _openai_error(
                    "process non autorise sur cette passerelle",
                    etype="permission_error", status=403)
            if _v["etat"] != _pl.AUTORISE:
                print("[proxy][pair-local] %s pid=%s process=%s : %s"
                      % (_v["etat"], _v.get("pid"), _v.get("process"), _v.get("motif")),
                      file=sys.stderr, flush=True)
        except Exception as _ple:  # muet-ok : l'isolation ne doit jamais casser le service ; l'echec est imprime
            print("[proxy][pair-local] mesure indisponible (%s)" % type(_ple).__name__,
                  file=sys.stderr, flush=True)
    if not _prouve and (_h.get("LaForge-Agent-Name") or _h.get("Agent-Name")
                        or _h.get("X-Agent-Name")):
        # Un nom annonce SANS preuve n'est pas une erreur du client -- c'est le
        # comportement historique. On le journalise pour que la transition soit
        # VISIBLE : sans cette trace, un client qui perd son identite le
        # decouvrirait par un refus, sans savoir pourquoi.
        # `print` vers stderr : ce module n'a pas de logger, et le superviseur
        # capture stderr. Une premiere version appelait `_log.info` -- un nom
        # qui n'existe nulle part ici : le NameError aurait ete leve a la
        # PREMIERE requete portant un nom, c'est-a-dire en production. Verifie
        # avant commit, pas apres.
        print("[proxy] nom declare sans jeton reconnu -> identite OPENAI_PROXY. "
              "Le client doit presenter son FORGE_TOKEN_<AGENT> dans "
              "Authorization: Bearer pour conserver son identite.",
              file=sys.stderr, flush=True)
    try:
        body = await request.json()
    except Exception as e:
        return _openai_error(f"invalid JSON body: {e}", etype="invalid_request_error", status=400)

    try:
        model = body.get("model", "laforge-cascade")
        messages = body.get("messages", [])
        max_tokens = int(body.get("max_tokens", 2000))
        # Autopoïèse : modèle local/cascade -> réveille le backend on-demand (signal -> daemon owner
        # forge_backend_power qui spawn ; le hub sandbox ne peut pas). Best-effort, jamais bloquant.
        try:
            from nokido_agent.tools.forge_backend_power import ensure as _ensure_backend
            if any(t in str(model).lower() for t in ("cascade", "coder", "qwen", "local", "llama")):
                _ensure_backend("llama_native")
        except Exception:
            pass
        stream = bool(body.get("stream", False))
        temperature = body.get("temperature", 0.7)

        # Tool-calling : `ask` ne function-call PAS -> relai vers un backend OpenAI tool-capable
        # (BYOK Copilot/Cline agentique : COPILOT_PROVIDER_BASE_URL=http://127.0.0.1:7777/v1).
        if body.get("tools"):
            return await _toolcall_passthrough(body, stream)

        if stream:
            return StreamingResponse(
                stream_chat_completion(model, messages, max_tokens, temperature, body),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        provider, model_override = _model_to_provider(model)
        prompt_parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                content = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
            prompt_parts.append(f"[{role}]\n{content}")
        prompt = "\n\n".join(prompt_parts)

        fw = _fw()
        pf = None
        if fw is not None:
            pf = fw.pre_flight(prompt, ring=3, provider=provider)
            if not pf.ok:
                return _openai_error(
                    f"blocked by semantic firewall: {pf.reason}",
                    etype="invalid_request_error",
                    status=403,
                    code="firewall_blocked",
                )
            prompt = pf.safe_task  # PII rédigées avant envoi upstream

        ask_args: dict[str, Any] = {
            "provider": provider,
            "message": prompt,
            "max_tokens": max_tokens,
            "thread_id": body.get("user", "lobehub_anon"),
        }
        if model_override:
            ask_args["model"] = model_override

        try:
            r = await hub_call("ask", ask_args, timeout=180)
        except httpx.TimeoutException as e:
            return _openai_error(f"upstream hub timeout: {e}", etype="timeout", status=504)
        except httpx.HTTPStatusError as e:
            return _openai_error(
                f"upstream hub HTTP {e.response.status_code}: {e.response.text[:200]}",
                etype="upstream_error",
                status=502,
            )
        except httpx.HTTPError as e:
            return _openai_error(
                f"upstream hub network error: {e}", etype="upstream_error", status=502
            )

        raw_text, inner = _extract_ask_text(r)

        # KEY FIX: cascade ok=false -> HTTP 502 (was: 200 + empty content)
        if inner and inner.get("ok") is False:
            err_msg = inner.get("error") or inner.get("text") or "cascade returned ok=false"
            return _openai_error(
                f"cascade failed (provider={inner.get('provider', provider)}): {err_msg}",
                etype="upstream_error",
                status=502,
                code="cascade_ok_false",
            )

        reply = (
            (inner.get("text") if inner else None)
            or (inner.get("response") if inner else None)
            or raw_text
        )
        if not reply or (isinstance(reply, str) and not reply.strip()):
            return _openai_error(
                "cascade returned empty response",
                etype="upstream_error",
                status=502,
                code="empty_response",
            )

        actual_provider = (inner.get("provider") if inner else None) or provider

        if fw is not None and pf is not None:
            pfr = fw.post_flight(reply, task=prompt)
            if not pfr.ok:
                return _openai_error(
                    f"response blocked by semantic firewall: {pfr.tag} {pfr.reason}".strip(),
                    etype="upstream_error",
                    status=502,
                    code="firewall_post_blocked",
                )
            reply = fw.restore(reply, pf.mapping)  # re-traduit les placeholders DLP

        return JSONResponse(
            {
                "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
                "system_fingerprint": f"nokido-{actual_provider}",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": len(prompt) // 4,
                    "completion_tokens": len(reply) // 4,
                    "total_tokens": (len(prompt) + len(reply)) // 4,
                },
            }
        )
    except Exception as e:
        return _openai_error(str(e), etype="internal_error", status=500)


async def stream_chat_completion(model, messages, max_tokens, temperature, body):
    """SSE streaming (chunks fake - Nokido ask non-streaming, we slice).

    On upstream failure, emits a single chunk with finish_reason=stop and
    error embedded in content; this is the OpenAI streaming convention since
    SSE cannot retroactively change HTTP status. Clients should detect the
    `[ERR ...]` marker.
    """
    provider, model_override = _model_to_provider(model)
    prompt_parts = []
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, list):
            content = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        prompt_parts.append(f"[{role}]\n{content}")
    prompt = "\n\n".join(prompt_parts)

    fw = _fw()
    pf = None
    if fw is not None:
        pf = fw.pre_flight(prompt, ring=3, provider=provider)
        if not pf.ok:
            cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
            yield _stream_error_chunk(cid, int(time.time()), model, f"[ERR firewall blocked: {pf.reason}]")
            return
        prompt = pf.safe_task

    ask_args: dict[str, Any] = {
        "provider": provider,
        "message": prompt,
        "max_tokens": max_tokens,
        "thread_id": body.get("user", "lobehub_anon"),
    }
    if model_override:
        ask_args["model"] = model_override

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    try:
        try:
            r = await hub_call("ask", ask_args, timeout=180)
        except httpx.TimeoutException as e:
            yield _stream_error_chunk(completion_id, created, model, f"[ERR upstream timeout: {e}]")
            return
        except httpx.HTTPError as e:
            yield _stream_error_chunk(completion_id, created, model, f"[ERR upstream: {e}]")
            return

        raw_text, inner = _extract_ask_text(r)
        if inner and inner.get("ok") is False:
            err_msg = inner.get("error") or "cascade ok=false"
            yield _stream_error_chunk(
                completion_id, created, model, f"[ERR cascade failed: {err_msg}]"
            )
            return
        reply = (inner.get("text") if inner else None) or raw_text or ""

        if fw is not None and pf is not None:
            pfr = fw.post_flight(reply, task=prompt)
            if not pfr.ok:
                yield _stream_error_chunk(
                    completion_id, created, model, f"[ERR firewall post: {pfr.tag} {pfr.reason}]".strip()
                )
                return
            reply = fw.restore(reply, pf.mapping)

        chunk_size = 80
        for i in range(0, len(reply), chunk_size):
            chunk = reply[i : i + chunk_size]
            payload = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": chunk},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.01)

        end = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(end)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        yield _stream_error_chunk(completion_id, created, model, f"[ERR internal: {e}]")


def _stream_error_chunk(completion_id: str, created: int, model: str, msg: str) -> str:
    err = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {"content": msg}, "finish_reason": "stop"}],
    }
    return f"data: {json.dumps(err)}\n\n" + "data: [DONE]\n\n"


async def _shutdown():
    """Close httpx client cleanly on app shutdown."""
    global _HTTPX
    if _HTTPX is not None:
        await _HTTPX.aclose()
        _HTTPX = None


# ============================================================
# OpenAI Responses API shim — codex 0.139.0 exige wire_api="responses".
# Traduit Responses <-> Chat puis réutilise le chemin ask/toolcall (router rotation-aware) =>
# injection de modèles LOCAUX/souverains dans codex. Non-streaming (baseline ; SSE = suite si
# codex l'exige). tool-calling -> backend tool-capable (comme /v1/chat/completions).
# ============================================================
def _responses_input_to_messages(body: dict) -> list:
    """`input` (str | items Responses) + `instructions` -> messages chat."""
    msgs: list = []
    instr = body.get("instructions")
    if instr:
        msgs.append({"role": "system", "content": str(instr)})
    inp = body.get("input", "")
    if isinstance(inp, str):
        if inp:
            msgs.append({"role": "user", "content": inp})
    elif isinstance(inp, list):
        for item in inp:
            if not isinstance(item, dict):
                msgs.append({"role": "user", "content": str(item)})
                continue
            t = item.get("type", "message")
            if t == "function_call_output":
                msgs.append({"role": "tool", "tool_call_id": item.get("call_id", ""),
                             "content": str(item.get("output", ""))})
            elif t == "function_call":
                msgs.append({"role": "assistant",
                             "content": f"[appel outil {item.get('name')}({item.get('arguments', '')})]"})
            else:  # message
                content = item.get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") in ("input_text", "output_text", "text")
                    )
                msgs.append({"role": item.get("role", "user"), "content": content})
    return msgs


def _responses_tools_to_chat(tools) -> list:
    """Tools Responses (type:function + name/parameters top-level) -> tools chat (function imbriquée)."""
    out: list = []
    for t in tools or []:
        if not isinstance(t, dict):
            continue
        if t.get("type") == "function" and "function" not in t:
            out.append({"type": "function", "function": {
                "name": t.get("name"), "description": t.get("description", ""),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}}}})
        else:
            out.append(t)
    return out


def _wrap_responses(text: str, model: str, tool_calls=None, usage=None) -> dict:
    """Réponse au format OpenAI Responses API (output items message/function_call)."""
    output: list = []
    for tc in (tool_calls or []):
        fn = tc.get("function", {}) if isinstance(tc, dict) else {}
        output.append({"type": "function_call", "id": "fc_" + uuid.uuid4().hex[:24],
                       "call_id": (tc.get("id") if isinstance(tc, dict) else None) or ("call_" + uuid.uuid4().hex[:16]),
                       "name": fn.get("name"), "arguments": fn.get("arguments", "{}"),
                       "status": "completed"})
    if text:
        output.append({"type": "message", "id": "msg_" + uuid.uuid4().hex[:24], "role": "assistant",
                       "status": "completed",
                       "content": [{"type": "output_text", "text": text, "annotations": []}]})
    return {"id": "resp_" + uuid.uuid4().hex[:24], "object": "response", "status": "completed",
            "model": model, "created_at": int(time.time()), "output": output,
            "usage": usage or {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}


async def responses(request: Request) -> JSONResponse:
    """POST /v1/responses — shim Responses API (codex). Traduit -> Chat -> ask/toolcall. Non-stream."""
    try:
        body = await request.json()
    except Exception as e:
        return _openai_error(f"invalid JSON body: {e}", etype="invalid_request_error", status=400)
    try:
        model = body.get("model", "laforge-cascade")
        max_tokens = int(body.get("max_output_tokens") or body.get("max_tokens") or 2000)
        messages = _responses_input_to_messages(body)
        tools = _responses_tools_to_chat(body.get("tools"))

        if tools:  # tool-calling -> la MEME voie que /v1/chat/completions, puis re-wrap Responses
            voie, erreur = _ouvrir_voie_outils(model, messages, tools)
            if erreur is not None:
                return erreur
            fwd = {"model": voie["modele"], "messages": voie["messages"], "tools": voie["tools"],
                   "stream": False, "max_tokens": max_tokens,
                   "temperature": body.get("temperature", 0.7)}
            d, erreur = await _appel_outille(voie, fwd)
            if erreur is not None:
                return erreur
            msg = (d.get("choices") or [{}])[0].get("message", {}) or {}
            motif = _pare_feu_sortie(msg)
            if motif:
                return _openai_error(f"response blocked by semantic firewall: {motif}",
                                     etype="upstream_error", status=502, code="firewall_post_blocked")
            if voie["membrane"] is not None:
                msg = voie["membrane"].unwrap_objet(msg, model=voie["servi"])
            return JSONResponse(_wrap_responses(msg.get("content") or "", voie["servi"],
                                                tool_calls=msg.get("tool_calls"), usage=d.get("usage")),
                                headers={"X-Nokido-Modele-Servi": voie["servi"]})

        provider, model_override = _model_to_provider(model)
        prompt = "\n\n".join(f"[{m.get('role', 'user')}]\n{m.get('content', '')}" for m in messages)
        fw = _fw()
        pf = None
        if fw is not None:
            pf = fw.pre_flight(prompt, ring=3, provider=provider)
            if not pf.ok:
                return _openai_error(f"blocked by semantic firewall: {pf.reason}",
                                     etype="invalid_request_error", status=403, code="firewall_blocked")
            prompt = pf.safe_task
        ask_args: dict[str, Any] = {"provider": provider, "message": prompt,
                                    "max_tokens": max_tokens, "thread_id": body.get("user", "codex_anon")}
        if model_override:
            ask_args["model"] = model_override
        try:
            r = await hub_call("ask", ask_args, timeout=180)
        except httpx.TimeoutException as e:
            return _openai_error(f"upstream hub timeout: {e}", etype="timeout", status=504)
        except httpx.HTTPError as e:
            return _openai_error(f"upstream hub error: {e}", etype="upstream_error", status=502)
        raw_text, inner = _extract_ask_text(r)
        if inner and inner.get("ok") is False:
            return _openai_error(f"cascade failed: {inner.get('error') or inner.get('text')}",
                                 etype="upstream_error", status=502, code="cascade_ok_false")
        reply = (inner.get("text") if inner else None) or (inner.get("response") if inner else None) or raw_text
        if not reply or not str(reply).strip():
            return _openai_error("cascade returned empty response", etype="upstream_error",
                                 status=502, code="empty_response")
        if fw is not None and pf is not None:
            try:
                pfr = fw.post_flight(reply, task=prompt)
                if not pfr.ok:
                    return _openai_error(f"response blocked by firewall: {pfr.reason}".strip(),
                                         etype="upstream_error", status=502, code="firewall_post_blocked")
                reply = fw.restore(reply, pf.mapping)
            except Exception:  # noqa: BLE001
                pass
        return JSONResponse(_wrap_responses(str(reply), model, usage=(inner or {}).get("usage")))
    except Exception as e:  # noqa: BLE001
        return _openai_error(str(e), etype="internal_error", status=500)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.environ.get("LAFORGE_OPENAI_PROXY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=7777)
    args = parser.parse_args()

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/v1/models", list_models, methods=["GET"]),
        Route("/v1/chat/completions", chat_completions, methods=["POST"]),
        Route("/v1/responses", responses, methods=["POST"]),
    ]
    app = Starlette(routes=routes)

    import uvicorn

    print(f"[+] forge_openai_proxy listen {args.host}:{args.port}")
    print(f"[+] hub upstream : {HUB_URL}")
    print(f"[+] hub concurrency cap : {HUB_CONCURRENCY}")
    print("[+] LobeHub config :")
    print("    Provider type : OpenAI Compatible")
    print(f"    Base URL      : http://{args.host}:{args.port}/v1")
    print("    API Key       : laforge-local (dummy)")
    # workers=1 keeps the singleton client / semaphore in one process.
    # limit_concurrency caps in-flight requests at the uvicorn level too.
    # TLS LOCAL -- point 5 de la revue du 2026-09-02, livre DESARME.
    #
    # Pourquoi desarme et pas actif : chaque client de cette passerelle est
    # configure avec une base `http://127.0.0.1:7777/v1`. Basculer en TLS les
    # casse TOUS d'un coup, et un certificat local n'est pas approuve par
    # defaut -- il faudrait aussi le poser dans le magasin de chaque client.
    # Ce n'est donc pas un durcissement qu'on active, c'est une migration qui
    # se prepare.
    #
    # L'architecture a deja un patron pour ca, et il est meilleur : Caddy
    # termine le TLS DEVANT le hub (`:8443 -> :8766`) sans que le hub le sache.
    # La voie coherente serait un bloc Caddy devant `:7777`. Elle n'est PAS
    # prise ici : la consigne owner interdit de modifier Caddy, et un
    # terminateur mal configure couperait le service.
    #
    # Ce qui est livre : la CAPACITE, pilotee par deux variables, pour que
    # l'activation soit une decision et non un chantier. Les deux fichiers
    # doivent exister -- sinon on demarre en clair EN LE DISANT, plutot que de
    # tomber au boot.
    # DECISION ACTEE le 2026-09-02, apres revue independante : PAS de TLS local
    # par defaut, et ce n'est pas un oubli.
    #
    # Motif de la revue : « le chiffrement du transport sur loopback n'apporte
    # aucune securite concrete additionnelle dans ce contexte ». L'adversaire
    # capable d'ecouter la pile reseau loopback possede deja SYSTEM ou root --
    # il dispose alors de moyens plus simples et plus devastateurs : lire la
    # memoire du processus, voler le jeton sur disque, attacher un debogueur.
    # La confidentialite du transport est DELEGUEE a l'isolation du noyau ;
    # l'authentification, elle, est applicative (jeton verifie en temps
    # constant). Cout du TLS ici : certificat local approuve par aucun client,
    # magasin de confiance a peupler machine par machine, clients Node/Electron
    # qui ignorent le magasin systeme -- pour un gain nul.
    #
    # La capacite reste livree ci-dessous : si une contrainte de conformite
    # l'exige un jour, la revue recommande CETTE voie (TLS natif) plutot qu'un
    # terminateur devant, parce qu'une erreur de certificat ne ferait alors
    # tomber que cette passerelle, pas le terminateur du hub.
    # Suffixe `_FILE` : ces deux variables portent des CHEMINS, pas des
    # secrets. La regle `cloud-secret-from-env` exclut deja `_PATH/_DIR/_FILE`
    # pour cette raison exacte, ecrite dans le scanner : « un garde qui crie
    # sur un chemin se fait desarmer ». Le nom disait « KEY », le contenu dit
    # « ou trouver la cle » -- c'est le nom qui etait faux.
    _cert = os.environ.get("LAFORGE_PROXY_TLS_CERT_FILE", "")
    _key = os.environ.get("LAFORGE_PROXY_TLS_KEY_FILE", "")
    _ssl = {}
    if _cert or _key:
        if _cert and _key and Path(_cert).exists() and Path(_key).exists():
            _ssl = {"ssl_certfile": _cert, "ssl_keyfile": _key}
            print("[+] TLS local ACTIF (cert=%s)" % _cert)
        else:
            # Ne PAS demarrer en clair en silence quand on a demande du TLS :
            # l'operateur croirait le canal chiffre. On le dit, fort.
            print("[!] TLS demande mais cert/cle absents ou incomplets "
                  "(cert=%r key=%r) -- DEMARRAGE EN CLAIR" % (_cert, _key),
                  file=sys.stderr, flush=True)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        workers=1,
        limit_concurrency=64,
        timeout_keep_alive=30,
        **_ssl,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
