"""
FORGE INTELLIGENCE v3 [GREEN]
DATE:2026-03-25 | VER:v_20260325_163726_astdoccerb
#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]
CONTRAINTE: +0 docs
"""
from __future__ import annotations
__FORGE_COLOR__ = "GREEN"
__FORGE_TAGS__ = "#FORGE:[score:90|agent:AST-doc|temp:0.00|risk:0.20|ast:KO|test:KO|lint:KO|color:GREEN|attempt:1]"

"""
forge_litellm_connector.py — Connecteur LiteLLM Proxy pour Nokido v0.13.3
===========================================================================
Deux modes :

Mode A — SDK direct (sans proxy) :
  litellm.completion(model="gemini/gemini-2.5-flash-preview", ...)
  → Appel direct Gemini via litellm SDK

Mode B — Via proxy local (recommandé) :
  litellm.completion(model="gemini-flash", api_base="http://localhost:4000", ...)
  → Passe par litellm_config.yaml → route vers Gemini
  → Avantages : fallback automatique, logs centralisés, contrôle droits

Lancement du proxy :
  pip install litellm --break-system-packages
  litellm --config litellm_config.yaml --port 4000

Ou via ce module :
  python forge_litellm_connector.py --start-proxy
"""


import asyncio
import contextlib as _contextlib
import logging
import os
import pathlib
import sys
from typing import Optional

logger = logging.getLogger(__name__)

_ROOT = pathlib.Path(__file__).resolve().parent.parent

# ── Config ────────────────────────────────────────────────────────────────────

from app.core.settings import _load_env  # migré vague 1

_ENV = _load_env()

# Proxy LiteLLM local (Mode B)
LITELLM_PROXY_URL = _ENV.get("LITELLM_PROXY_URL", "http://localhost:4000")
LITELLM_PROXY_KEY = _ENV.get("FORGE_MCP_TOKEN", "")  # même token que MCP
LITELLM_USE_PROXY = _ENV.get("LITELLM_USE_PROXY", "false").lower() == "true"

# Modèle par défaut via proxy
PROXY_DEFAULT_MODEL = _ENV.get("LITELLM_PROXY_MODEL", "default")

# Gemini direct (Mode A)
#
# AUDIT SECURITE 2026-09-22, finding E1. La cle etait resolue ICI, au CHARGEMENT
# du module, depuis `_ENV` — c'est-a-dire depuis `dict(os.environ)` apres lecture
# de `Nokido.env`. L'ordre documente de `forge_secrets.get_secret` est : coffre
# DPAPI machine, puis WCM per-user, puis `Nokido.env`, puis l'environnement EN
# EMETTANT un WARNING « non securise ». Ce module partait du TROISIEME echelon :
# les deux premiers n'etaient jamais interroges, et l'avertissement qui devait
# signaler le repli non securise n'etait jamais emis.
#
#     UNE REGLE ECRITE QU'AUCUNE PORTE NE CONSULTE NE GARDE RIEN.
#
# Et resoudre au CHARGEMENT rend une rotation de cle invisible jusqu'au
# redemarrage. La cle se demande donc a chaque appel, par `_cle_gemini()`.
GEMINI_MODEL = _ENV.get("GEMINI_MODEL", "gemini/gemini-2.5-flash-preview")


# Le coffre est importe SOUS SON NOM, et pas derriere une indirection.
#
# Mesure du 2026-09-22 : la premiere version de ce correctif passait par un
# wrapper `_get_secret`, cree pour la testabilite. Le gate golden-rules a casse
# son cliquet dessus (1 -> 3 violations de `laforge-cloud-secret-from-env`) et
# il avait RAISON sur la forme : son exemption `_repli_apres_coffre` marque une
# fonction comme legitime quand elle appelle le coffre sous l'un des noms
# `get_secret` / `vault_get` / `jeton_pour`. Un underscore devant suffisait a
# rendre le coffre INVISIBLE au detecteur.
#
#     CALL_SITE != DECISION_SITE, applique a mon propre code.
#
# Le gate refuse explicitement les noms generiques comme preuve qu'on parle au
# coffre (`resolve` a ete essaye puis retire dans la minute, il blanchissait
# toute fonction manipulant un chemin). Corriger le DIAGNOSTIC, jamais
# contourner le garde : la fonction appelle donc `get_secret` sous son nom.
try:
    from nokido_agent.app.forge_secrets import get_secret
except ImportError:  # chemin d'import alternatif selon la racine du sys.path
    try:
        from forge_secrets import get_secret  # type: ignore
    except ImportError:
        get_secret = None  # type: ignore


@_contextlib.contextmanager
def _env_temporaire(nom: str, valeur: str):
    """Pose `nom` dans l'environnement du processus, et le REND a son etat.

    Le nom est un PARAMETRE, jamais un litteral : ce helper ne resout aucun
    secret, il restaure un etat. C'est la raison pour laquelle il ne declenche
    pas la regle qui poursuit les secrets lus depuis l'environnement — et cette
    raison est ecrite ici plutot que laissee a deduire.

    La restauration passe par `finally` : sans elle, une exception laisserait la
    valeur en place, et c'est precisement le defaut E1 qu'on vient de fermer.
    """
    ancien = os.environ.get(nom)
    try:
        os.environ[nom] = valeur
        yield
    finally:
        if ancien is None:
            os.environ.pop(nom, None)
        else:
            os.environ[nom] = ancien


def _cle_gemini() -> str:
    """Resout la cle Gemini A CHAQUE APPEL, coffre d'abord.

    Le repli sur `_ENV` reste emprunte quand le coffre est muet — couper l'acces d'un
    connecteur qui fonctionne serait une regression et non un durcissement — mais il
    est desormais ANNONCE, ce qui etait precisement ce qui manquait.
    """
    valeur = None
    if get_secret is not None:
        try:
            valeur = get_secret("GEMINI_API_KEY")
        except Exception as exc:  # noqa: BLE001
            # PAS muet : un coffre qui refuse doit se distinguer d'un coffre vide.
            logger.warning("[LiteLLMConnector] coffre injoignable: %r", exc)
    if valeur:
        return valeur
    repli = _ENV.get("GEMINI_API_KEY", "")
    if repli:
        logger.warning(
            "[LiteLLMConnector] GEMINI_API_KEY resolue hors du coffre (repli "
            "Nokido.env / environnement) — chemin NON SECURISE, a migrer au coffre"
        )
    return repli


# ── Vérification proxy ────────────────────────────────────────────────────────


async def is_proxy_alive(timeout: float = 2.0) -> bool:
    """Vérifie si le proxy LiteLLM est actif sur LITELLM_PROXY_URL."""
    try:
        import aiohttp

        async with aiohttp.ClientSession() as s:
            async with s.get(f"{LITELLM_PROXY_URL}/health", timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                return r.status == 200
    except Exception:
        return False


# ── Appel LLM unifié ─────────────────────────────────────────────────────────


async def complete(
    messages: list[dict],
    model: Optional[str] = None,
    max_tokens: int = 800,
    timeout: float = 60.0,
) -> str:
    """
    Appel LLM unifié — essaie dans l'ordre :
      1. LiteLLM proxy local (si LITELLM_USE_PROXY=true et proxy actif)
      2. LiteLLM SDK direct → Gemini
      3. LiteLLM SDK direct → Ollama
    """
    try:
        import litellm as _ll
    except ImportError:
        raise ImportError("litellm non installé.\n  pip install litellm --break-system-packages")

    # ── Mode B : proxy local ─────────────────────────────────────────────────
    if LITELLM_USE_PROXY and await is_proxy_alive():
        _model = model or PROXY_DEFAULT_MODEL
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: _ll.completion(
                    model=_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    api_base=LITELLM_PROXY_URL,
                    api_key=LITELLM_PROXY_KEY or "laforge",
                ),
            )
            answer = response.choices[0].message.content.strip()
            logger.info(f"[LiteLLMConnector] Proxy OK model={_model} chars={len(answer)}")
            return answer
        except Exception as e:
            logger.warning(f"[LiteLLMConnector] Proxy erreur: {e} — fallback SDK direct")

    # ── Mode A : SDK direct Gemini ───────────────────────────────────────────
    _cle = _cle_gemini()
    if _cle:
        _model = model or GEMINI_MODEL
        if not _model.startswith("gemini/"):
            _model = f"gemini/{_model}" if "gemini" in _model else GEMINI_MODEL
        # La cle transite par l'environnement parce que c'est la voie que cette
        # bibliotheque documente, mais elle n'y RESTE PAS : l'ecriture permanente
        # elargissait sa portee a tout module charge dans ce processus et a tout
        # sous-processus lance ensuite. L'etat anterieur est restaure quoi qu'il
        # arrive, y compris sur exception.
        #
        # Passer la cle en parametre serait plus propre. Ce n'est PAS fait ici :
        # `litellm` est ILLISIBLE depuis le compte sandbox (son import tente une
        # requete sortante et meurt sur la membrane), donc sa signature n'a pas pu
        # etre mesuree. On ne pose pas un correctif dont on ne peut pas eprouver la
        # forme — ILLISIBLE n'est ni COMPATIBLE ni INCOMPATIBLE.
        try:
            with _env_temporaire("GEMINI_API_KEY", _cle):
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _ll.completion(
                        model=_model,
                        messages=messages,
                        max_tokens=max_tokens,
                        timeout=timeout,
                    ),
                )
            answer = response.choices[0].message.content.strip()
            logger.info(f"[LiteLLMConnector] Gemini direct OK model={_model} chars={len(answer)}")
            return answer
        except Exception as e:
            logger.warning(f"[LiteLLMConnector] Gemini erreur: {e} — fallback Ollama")

    # ── Fallback : Ollama via litellm SDK ────────────────────────────────────
    _ollama_model = _ENV.get("LITELLM_MODEL", "ollama/qwen2.5")
    _ollama_base = _ENV.get("LITELLM_API_BASE", "http://localhost:11434")
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _ll.completion(
                model=_ollama_model,
                messages=messages,
                max_tokens=max_tokens,
                timeout=timeout,
                api_base=_ollama_base,
            ),
        )
        answer = response.choices[0].message.content.strip()
        logger.info(f"[LiteLLMConnector] Ollama fallback OK model={_ollama_model}")
        return answer
    except Exception as e:
        raise RuntimeError(
            f"Tous les backends LiteLLM ont échoué.\n"
            f"Dernière erreur: {e}\n"
            f"Vérifie GEMINI_API_KEY et LITELLM_PROXY_URL dans Nokido.env"
        )


# ── Mise à jour de forge_litellm_bridge pour utiliser ce connecteur ───────────


async def propose_via_connector(
    task: str,
    rag_ctx: str = "",
    max_tokens: int = 800,
) -> str:
    """Interface propose() compatible LiteLLMBridge."""
    messages = []
    if rag_ctx:
        messages.append({"role": "system", "content": f"Contexte:\n{rag_ctx}"})
    messages.append({"role": "user", "content": task})
    try:
        return await complete(messages, max_tokens=max_tokens)
    except Exception as e:
        logger.warning(f"[propose_via_connector] {e}")
        return ""


# ── Lancement proxy ───────────────────────────────────────────────────────────


def start_proxy(port: int = 4000, config: str = "litellm_config.yaml") -> None:
    """Lance le proxy LiteLLM en subprocess."""
    import subprocess

    config_path = _ROOT / config
    if not config_path.exists():
        print(f"❌ Config introuvable : {config_path}")
        sys.exit(1)
    # Injecter les env vars depuis Nokido.env
    env = {**os.environ, **{k: v for k, v in _load_env().items() if v}}
    print(f"🚀 LiteLLM proxy → {LITELLM_PROXY_URL}")
    print(f"   Config : {config_path}")
    print("   Ctrl+C pour arrêter")
    subprocess.run(
        [sys.executable, "-m", "litellm", "--config", str(config_path), "--port", str(port)],
        env=env,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LiteLLM Connector Nokido")
    parser.add_argument("--start-proxy", action="store_true", help="Lancer le proxy LiteLLM")
    parser.add_argument("--port", type=int, default=4000)
    parser.add_argument("--config", default="litellm_config.yaml")
    parser.add_argument("--test", help="Tester avec un prompt")
    args = parser.parse_args()

    if args.start_proxy:
        start_proxy(args.port, args.config)
    elif args.test:

        async def _test() -> None:
            """test."""
            answer = await complete(
                [{"role": "user", "content": args.test}],
                max_tokens=200,
            )
            print(f"Réponse: {answer}")

        asyncio.run(_test())
    else:
        parser.print_help()
