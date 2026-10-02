"""app/forge_provider_admin.py — Web UI admin pour LLM providers.

Route FastAPI servie par le hub :8766 :
    GET  /admin/providers           — page HTMX+Alpine (liste + formulaires)
    GET  /api/providers             — JSON tous providers avec statut
    GET  /api/providers/<name>      — détail un provider
    POST /api/providers/<name>/key  — set API key dans vault DPAPI
    DELETE /api/providers/<name>/key — remove API key
    POST /api/providers/<name>/test — ping santé / quota
    POST /api/providers/<name>/toggle — activate/deactivate use_case

Source de vérité :
    - Specs : `app/forge_provider_specs.PROVIDER_SPECS` (statique)
    - Quotas : `app/forge_provider_quota.quota_status()` (DB)
    - Secrets : `app/forge_secrets.{get,set,delete}_secret()` (vault DPAPI / keyring)
    - Health : `app/forge_provider_watcher` si dispo, sinon best-effort

Auth : ring ≤ 1 requis (MASTER ou SYSTEM). Les autres rings sont 403.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `api_delete_access` — DELETE /api/access/{cle} → retrait du coffre. Ring <= 1, liste blanche.
- `api_list_access` — GET /api/access → provenance des acces SSH (jamais leur valeur). Ring <= 1.
- `api_set_access` — POST /api/access/{cle} {"valeur": ...} → coffre. Ring <= 1, liste blanche.
- `definir_acces` — Pose un acces de la liste blanche au coffre DPAPI machine.
- `etat_des_acces` — Pour chaque acces : ou il est TROUVE (coffre, wcm, Nokido.env, environnement) -- jamais sa valeur.
- `retirer_acces` — Retire un acces de la liste blanche du coffre.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

logger = logging.getLogger("forge.provider_admin")

# Mapping provider_name (forge_provider_specs) -> vault key.
# Convention vault key : <VENDOR>_API_KEY ou <VENDOR>_TOKEN (cohérent forge_secrets.diagnostic).
PROVIDER_VAULT_KEY: dict[str, Optional[str]] = {
    # locaux (pas de clé)
    "ollama_local": None,
    "llamacpp_local": None,
    "lmstudio_native": None,
    # cloud free / paid
    "groq": "GROQ_API_KEY",
    "groq_fast": "GROQ_API_KEY",
    "groq_mixtral": "GROQ_API_KEY",
    "gemini_flash": "GEMINI_API_KEY",
    "gemini_flash_lite": "GEMINI_API_KEY",
    "gemini_pro": "GEMINI_API_KEY",
    "gemini_gemma": "GEMINI_API_KEY",
    "cohere_command_r": "COHERE_API_KEY",
    "cohere_command_r_plus": "COHERE_API_KEY",
    "sambanova": "SAMBANOVA_API_KEY",
    "sambanova_llama_70b": "SAMBANOVA_API_KEY",
    "sambanova_llama_405b": "SAMBANOVA_API_KEY",
    "github_gpt41_mini": "GITHUB_MODELS_TOKEN",
    "github_gpt4o_mini": "GITHUB_MODELS_TOKEN",
    "github_deepseek_v3": "GITHUB_MODELS_TOKEN",
    "mistral_small": "MISTRAL_API_KEY",
    "mistral_large": "MISTRAL_API_KEY",
    "hf_qwen_coder": "HF_TOKEN",
    "hf_llama": "HF_TOKEN",
    "openrouter_gpt_oss": "OPENROUTER_API_KEY",
    "openrouter_glm_air": "OPENROUTER_API_KEY",
    "openrouter_qwen_coder": "OPENROUTER_API_KEY",
    "xai_grok3": "XAI_API_KEY",
    "xai_grok3_mini": "XAI_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "nvidia_nim": "NVIDIA_API_KEY",
    "cloudflare_workers": "CF_API_TOKEN",
    "deepseek": "DEEPSEEK_API_KEY",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "anthropic_claude": "ANTHROPIC_API_KEY",
    "anthropic_claude_cli": None,  # auth OAuth via claude CLI
    "claude_agent_sdk": "ANTHROPIC_API_KEY",
}

# Réconciliation step 3 (2026-06-09, Option B multiplan) : compléter depuis la SOURCE
# DE VÉRITÉ forge_provider_canonical (dérivée de _PROVIDERS). setdefault = n'écrase PAS
# les entrées admin curées, ajoute juste les noms manquants (glm/kimi/deepseek/…).
# Non-cassant, fail-safe (fallback dict manuel si canonical indispo).
try:
    from nokido_agent.app.forge_provider_canonical import vault_key_map as _canon_vk
    for _n, _k in _canon_vk().items():
        if _k:
            PROVIDER_VAULT_KEY.setdefault(_n, _k)
except Exception:  # muet-ok import fallback default
    pass


def _resolve_vault_key(provider: str) -> Optional[str]:
    """Best-effort résolution clé vault depuis nom provider."""
    if provider in PROVIDER_VAULT_KEY:
        return PROVIDER_VAULT_KEY[provider]
    # Heuristique : préfixe vendeur connu
    for prefix, suffix in (
        ("groq_", "GROQ_API_KEY"),
        ("gemini_", "GEMINI_API_KEY"),
        ("cohere_", "COHERE_API_KEY"),
        ("sambanova_", "SAMBANOVA_API_KEY"),
        ("github_", "GITHUB_MODELS_TOKEN"),
        ("mistral_", "MISTRAL_API_KEY"),
        ("hf_", "HF_TOKEN"),
        ("openrouter_", "OPENROUTER_API_KEY"),
        ("xai_", "XAI_API_KEY"),
        ("anthropic_", "ANTHROPIC_API_KEY"),
    ):
        if provider.startswith(prefix):
            return suffix
    return None


def _provider_status(name: str, specs: dict) -> dict:
    """Construit le payload statut d'un provider."""
    from nokido_agent.app.forge_secrets import get_secret  # noqa: PLC0415

    vkey = _resolve_vault_key(name)
    has_key = bool(get_secret(vkey)) if vkey else (specs.get("tier") == "local")

    # Quota (best-effort, peut être absent si DB pas init)
    quota = {"ok": True, "pct_calls": 0.0, "pct_tokens": 0.0, "reason": ""}
    try:
        from nokido_agent.app.forge_provider_quota import quota_status  # noqa: PLC0415

        quota = quota_status(name) or quota
    except Exception:  # muet-ok quota init fallback
        pass

    return {
        "name": name,
        "tier": specs.get("tier", "unknown"),
        "context": specs.get("context", 0),
        "capabilities": specs.get("capabilities", []),
        "monthly_calls": specs.get("monthly_calls"),
        "daily_calls": specs.get("daily_calls"),
        "cost_usd_per_1m_in": specs.get("cost_usd_per_1m_in"),
        "cost_usd_per_1m_out": specs.get("cost_usd_per_1m_out"),
        "notes": specs.get("notes", ""),
        # Un provider RETIRE par son editeur doit le DIRE ici, sinon la page l'offre
        # comme disponible : mesure 2026-08-30, cinq slots GitHub Models etaient
        # affiches `free` douze jours apres le 410 Gone que le routeur, lui, connaissait.
        # Absent = en service ; une chaine = la raison ET sa date.
        "perime": specs.get("perime") or None,
        "vault_key": vkey,
        "has_key": has_key,
        "quota": quota,
    }


def list_providers() -> list[dict]:
    """Tous providers + statut. Trié par tier (local d'abord)."""
    from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS  # noqa: PLC0415

    out = [_provider_status(name, spec) for name, spec in PROVIDER_SPECS.items()]
    tier_order = {"local": 0, "free": 1, "subscription_quota": 2, "paid_api": 3, "unknown": 4}
    return sorted(out, key=lambda p: (tier_order.get(p["tier"], 9), p["name"]))


def set_provider_key(provider: str, api_key: str) -> dict:
    """Stocke la clé API dans vault. Retourne statut."""
    if not api_key or not api_key.strip():
        return {"ok": False, "error": "empty key"}
    vkey = _resolve_vault_key(provider)
    if not vkey:
        return {"ok": False, "error": f"no vault key mapping for {provider}"}
    from nokido_agent.app.forge_secrets import set_secret  # noqa: PLC0415

    ok = set_secret(vkey, api_key.strip())
    return {"ok": ok, "vault_key": vkey, "preview": "***" + api_key.strip()[-4:]}


def delete_provider_key(provider: str) -> dict:
    """Supprime la clé du vault."""
    vkey = _resolve_vault_key(provider)
    if not vkey:
        return {"ok": False, "error": "no vault key mapping"}
    try:
        from nokido_agent.app.forge_machine_vault import vault_delete  # noqa: PLC0415

        ok = vault_delete(vkey)
        # Invalide aussi le cache forge_secrets
        from nokido_agent.app.forge_secrets import invalidate_cache  # noqa: PLC0415

        invalidate_cache(vkey)
        return {"ok": ok, "vault_key": vkey}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc)}


# ── Acces SSH au coffre (owner 2026-09-25) ──────────────────────────────────────────
# « Il ne faut pas mettre en dur mes acces SSH sur la version dist ; proposer de les
# renseigner au vault, comme les clefs API, sur la page de config des acces. »
# LISTE BLANCHE : cette page n'est pas un ecrivain de secret generique -- une cle
# hors liste est refusee. Lecteurs : forge_settings.Settings (TUI), via get_secret.
ACCES_AU_COFFRE = {
    "SSH_HOST": "Hôte SSH (TUI)",
    "SSH_PORT": "Port SSH",
    "SSH_USER": "Utilisateur SSH",
    "PRIVATE_KEY_PATH": "Chemin de la clé privée SSH",
}


def etat_des_acces() -> list[dict]:
    """Pour chaque acces : ou il est TROUVE (coffre, wcm, Nokido.env, environnement) -- jamais sa valeur.

    `en_clair` signale un acces encore lu dans Nokido.env ou l'environnement : a migrer au coffre.
    Une source qui leve est DITE (illisibles) : ILLISIBLE n'est pas ABSENT."""
    from nokido_agent.app import forge_secrets as _fsec  # noqa: PLC0415

    out = []
    for cle, libelle in ACCES_AU_COFFRE.items():
        source, illisibles = None, []
        for nom in ("coffre", "wcm", "dotenv"):
            valeur, illisible = _fsec._sonder(nom, cle)
            if illisible:
                illisibles.append(nom)
            elif valeur:
                source = nom
                break
        if source is None and os.environ.get(cle):
            source = "environ"
        out.append({"cle": cle, "libelle": libelle, "source": source,
                    "en_clair": source in ("dotenv", "environ"), "illisibles": illisibles})
    return out


def definir_acces(cle: str, valeur: str) -> dict:
    """Pose un acces de la liste blanche au coffre DPAPI machine."""
    if cle not in ACCES_AU_COFFRE:
        return {"ok": False, "error": "acces hors liste blanche : %s" % cle}
    if not isinstance(valeur, str) or not valeur.strip():
        return {"ok": False, "error": "valeur vide"}
    from nokido_agent.app import forge_secrets as _fsec  # noqa: PLC0415

    return {"ok": bool(_fsec.set_secret(cle, valeur.strip())), "cle": cle}


def retirer_acces(cle: str) -> dict:
    """Retire un acces de la liste blanche du coffre."""
    if cle not in ACCES_AU_COFFRE:
        return {"ok": False, "error": "acces hors liste blanche : %s" % cle}
    try:
        from nokido_agent.app.forge_machine_vault import vault_delete  # noqa: PLC0415
        from nokido_agent.app.forge_secrets import invalidate_cache  # noqa: PLC0415

        ok = bool(vault_delete(cle))
        invalidate_cache(cle)
        return {"ok": ok, "cle": cle}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, str(e)[:120])}


def test_provider(provider: str) -> dict:
    """Ping santé / test rapide. Best-effort (pas de vrai appel cloud pour
    éviter de bruler du quota — juste valide la clé + retourne specs."""
    from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS  # noqa: PLC0415

    if provider not in PROVIDER_SPECS:
        return {"ok": False, "error": "unknown provider"}
    vkey = _resolve_vault_key(provider)
    if vkey:
        from nokido_agent.app.forge_secrets import get_secret  # noqa: PLC0415

        if not get_secret(vkey):
            return {"ok": False, "error": f"no key in vault for {vkey}"}
    # Health check via forge_provider_watcher si dispo
    try:
        from nokido_agent.app.forge_provider_watcher import check_health  # type: ignore  # noqa: PLC0415

        h = check_health(provider)
        return {"ok": h.get("ok", True), **h}
    except Exception:
        return {"ok": True, "note": "key present, no health-check module"}


# ─────────────────────────────── clients MCP ────────────────────────────────
# Meme coffre DPAPI que les cles providers ci-dessus, autre usage : ici ce sont les
# jetons d'AUTHENTIFICATION des clients (Claude Code, codex, Gemini...) vers le hub.
# Ils vivent au coffre, mais plusieurs clients ne lisent PAS le coffre : ils lisent une
# VARIABLE D'ENVIRONNEMENT (codex : `bearer_token_env_var`). D'ou un desaccord possible
# et parfaitement silencieux -- mesure 2026-08-03 : jeton valide au coffre, hub rendant
# HTTP 200, et codex affichant « Tools: (none) » parce que sa variable portait une
# ANCIENNE valeur. C'est ce desaccord que cette vue rend visible.
_MCP_AGENTS = ["CLAUDE", "GEMINI", "CODEX", "CLINE", "CLAUDE_DESKTOP", "VSCODE",
               "LMSTUDIO", "ANTIGRAVITY", "DSPY_ROUTER"]

_CMD_RESYNC = ('"%~/miniforge3/python.exe" tools/forge_provision_clients.py --apply')


def _empreinte_secret(v: Optional[str]) -> Optional[str]:
    """sha8 : compare sans divulguer. Une queue de jeton reste un morceau de jeton."""
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(v.encode()).hexdigest()[:8] if v else None


def _compte_owner() -> Optional[str]:
    """Compte proprietaire du profil ou vit le depot, deduit de son chemin.

    Faute de source declaree, le chemin est la seule mesure disponible. Sert a
    savoir si le process qui lit le registre est CELUI dont on veut la ruche.
    """
    import os  # noqa: PLC0415

    try:
        parts = os.path.abspath(__file__).replace("\\", "/").split("/")
        idx = [i for i, p in enumerate(parts) if p.lower() == "users"]
        if idx and len(parts) > idx[0] + 1:
            return parts[idx[0] + 1]
    except Exception:  # noqa: BLE001
        pass
    return None


def _env_utilisateur(nom: str) -> tuple[Optional[str], bool]:
    """(valeur, lisible). TROIS etats : posee / absente / ILLISIBLE.

    PIEGE MESURE le 2026-08-03, et corrige dans le tour meme : `HKEY_CURRENT_USER`
    designe la ruche DU PROCESS QUI LIT. Depuis le compte du hub ou du bac a sable,
    la cle `Environment` s'ouvre tres bien — elle est simplement VIDE des variables
    de l'owner. Le premier jet rendait donc `lisible=True, valeur=None`, soit
    « variable jamais posee », pour NEUF agents que l'owner venait de provisionner.
    Un acces qui reussit sur la mauvaise ruche est un faux negatif, pas une mesure :
    il faut d'abord verifier qu'on lit la BONNE.
    """
    import os  # noqa: PLC0415

    attendu = os.environ.get("LAFORGE_OWNER_USER") or _compte_owner()
    courant = os.environ.get("USERNAME") or ""
    if attendu and courant.lower() != attendu.lower():
        return None, False  # ruche d'un autre compte -> on ne voit pas, on ne conclut pas
    try:
        import winreg  # noqa: PLC0415

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            try:
                val, _typ = winreg.QueryValueEx(k, nom)
                return (val or None), True
            except FileNotFoundError:
                return None, True
    except Exception:  # noqa: BLE001
        return None, False


def list_mcp_clients() -> list[dict]:
    """Etat de chaque client MCP : jeton au coffre vs jeton dans l'environnement."""
    from nokido_agent.app.forge_secrets import get_secret  # noqa: PLC0415

    out = []
    for agent in _MCP_AGENTS:
        cle = "FORGE_TOKEN_%s" % agent
        au_coffre = None
        try:
            au_coffre = get_secret(cle)
        except Exception:  # noqa: BLE001
            au_coffre = None
        env_val, env_lisible = _env_utilisateur(cle)
        sha_coffre, sha_env = _empreinte_secret(au_coffre), _empreinte_secret(env_val)

        if not au_coffre:
            etat, remede = "SANS_JETON", "provisionner : %s" % _CMD_RESYNC
        elif not env_lisible:
            etat, remede = "ENV_ILLISIBLE", ("le hub ne lit pas le registre de l'owner — "
                                             "verdict impossible depuis ici, pas 'absent'")
        elif sha_env is None:
            etat, remede = "ENV_ABSENTE", ("le client qui lit bearer_token_env_var "
                                           "s'authentifiera a vide : %s" % _CMD_RESYNC)
        elif sha_env != sha_coffre:
            etat, remede = "DESACCORD", ("l'environnement porte une ANCIENNE valeur : %s, "
                                         "puis ROUVRIR le terminal du client" % _CMD_RESYNC)
        else:
            etat, remede = "ALIGNE", None
        out.append({"agent": agent, "vault_key": cle, "etat": etat,
                    "sha_coffre": sha_coffre, "sha_env": sha_env,
                    "env_lisible": env_lisible, "remede": remede})
    return out


def _ring_du_porteur(request) -> int:
    """Ring déduit d'une identité PROUVÉE : un Bearer égal au jeton hub du coffre.

    MESURE 2026-09-18 — la version précédente lisait `X-Ring`, un en-tête posé par
    le CLIENT, et lui obéissait. Mesuré contre le hub vivant, sur un provider
    volontairement inexistant (aucune écriture possible) :

        POST /api/providers/<x>/key   sans en-tête        -> 403
        POST /api/providers/<x>/key   X-Ring: 0           -> 200   <-- franchi
        POST /api/providers/<x>/key   Bearer <jeton hub>  -> 403   <-- refusé

    L'identité AUTO-DÉCLARÉE était acceptée pendant que l'identité PROUVÉE était
    refusée : l'inversion exacte de ce que `_HEADER_FLOOR_RING = 4` interdit côté
    videur. Portée du trou : écriture ET suppression de clés dans le coffre DPAPI.

    `X-Ring` n'avait aucun émetteur dans le dépôt — 0 occurrence hors de cette
    fonction sur `app/**/*.py`, `tools/**/*.py`, `tests/**/*.py`,
    `app/web_hub/static/*.js`, `proxy_deno/core/*.ts`, `docs/*.md` (non scanné :
    le reste du dépôt, dit plutôt que tu). Le fermer ne prive donc aucun appelant
    connu, il ferme un contournement.
    """
    import hmac  # noqa: PLC0415

    entete = request.headers.get("Authorization", "")
    if not entete.lower().startswith("bearer "):
        return 99
    presente = entete[7:].strip()
    attendu = ""
    try:
        from nokido_agent.app.forge_secrets import get_secret  # noqa: PLC0415

        attendu = get_secret("FORGE_MCP_TOKEN") or ""
    except Exception:  # noqa: BLE001 — repli sur l'autre nom d'import du module
        try:
            from app.forge_secrets import get_secret  # noqa: PLC0415

            attendu = get_secret("FORGE_MCP_TOKEN") or ""
        except Exception:  # noqa: BLE001 — coffre illisible : traité en INCONNU
            attendu = ""
    if not attendu or not presente:
        # Coffre illisible ou porteur vide = INCONNU, pas « autorisé ». On ne
        # transforme jamais une absence de preuve en permission d'écrire.
        return 99
    return 1 if hmac.compare_digest(presente, attendu) else 99


def _resolve_request_ring(request) -> int:
    """Ring de la requête. Autorité : le middleware du hub, sinon le porteur.

    Fallback 99 = deny. Aucun en-tête auto-déclaré n'entre plus ici.
    """
    try:
        # Le middleware du hub fait autorité quand il a résolu une identité.
        if hasattr(request, "state") and hasattr(request.state, "ring"):
            r = request.state.ring
            if isinstance(r, int):
                return r
        return _ring_du_porteur(request)
    except Exception:
        return 99


# ─── Handlers Starlette (utilisés par nokido_hub.py) ────────────────────────


_ORDRE_TIERS = ("local", "free", "subscription_quota", "paid_api")


def _echappe(v) -> str:
    import html as _html  # noqa: PLC0415

    return _html.escape("" if v is None else str(v), quote=True)


def _page_inventaire(providers: list) -> str:
    """Inventaire des fournisseurs, rendu CÔTÉ SERVEUR, sans une ligne de JavaScript.

    Pourquoi ce gabarit remplace `_HTML_PAGE` (mesures 2026-09-18) :

    - les boutons d'action de l'ancienne page ne peuvent PLUS aboutir depuis un
      navigateur : l'écriture au coffre exige désormais un porteur prouvé, et cette
      page est servie sans middleware d'auth (200 sans le moindre en-tête). Laisser
      des boutons qui répondent 403 est pire que ne pas en mettre ;
    - deux des trois liens de son en-tête étaient MORTS (`/admin/dashboard` et
      `/admin/rbac` → 404 mesurés) ;
    - le style est calé sur `nokido.css`, comme la page des tuiles, au lieu d'un
      moteur Tailwind de 407 Ko qui fabrique les classes après le parse.

    Les gestes (saisie, retrait, test) vivent sur `:7400/providers`, derrière la
    session du portail. Cette page-ci INFORME ; elle n'agit pas — ce qui la rend
    aussi conforme à « rien ne doit se lancer au clic ».
    """
    par_tier: dict = {}
    for p in providers:
        par_tier.setdefault(p.get("tier") or "unknown", []).append(p)

    avec, sans, sans_emplacement = 0, 0, 0
    for p in providers:
        if not p.get("vault_key"):
            sans_emplacement += 1
        elif p.get("has_key"):
            avec += 1
        else:
            sans += 1

    lignes = []
    for tier in list(_ORDRE_TIERS) + sorted(set(par_tier) - set(_ORDRE_TIERS)):
        lot = par_tier.get(tier)
        if not lot:
            continue
        lignes.append(
            '<tr class="groupe"><td colspan="6">%s <span class="cpt">%d</span></td></tr>'
            % (_echappe(tier.replace("_", " ")), len(lot))
        )
        for p in sorted(lot, key=lambda x: x.get("name") or ""):
            if not p.get("vault_key"):
                etat = '<span class="laforge-status laforge-status-info">sans coffre</span>'
            elif p.get("has_key"):
                etat = '<span class="laforge-status laforge-status-up">clé présente</span>'
            else:
                etat = '<span class="laforge-status laforge-status-down">clé absente</span>'

            marque = ""
            if p.get("perime"):
                marque = ('<div class="perime" title="%s">retiré par l\'éditeur</div>'
                          % _echappe(p["perime"]))

            caps = "".join('<span class="cap">%s</span>' % _echappe(c)
                           for c in (p.get("capabilities") or []))
            quota = "—"
            if p.get("monthly_calls"):
                quota = "%s/mois" % format(p["monthly_calls"], ",d").replace(",", " ")
                if p.get("daily_calls"):
                    quota += " · %s/jour" % format(p["daily_calls"], ",d").replace(",", " ")
            elif tier == "local":
                quota = '<span class="dim">sans limite</span>'

            notes = ""
            if p.get("notes"):
                notes = '<div class="notes" title="%s">%s</div>' % (
                    _echappe(p["notes"]), _echappe(p["notes"]))

            lignes.append(
                '<tr><td><div class="nom">%s</div>%s%s</td>'
                '<td><div class="caps">%s</div></td>'
                '<td class="mono">%s</td><td class="mono">%s</td>'
                '<td class="mono cle">%s</td><td>%s</td></tr>'
                % (_echappe(p.get("name")), marque, notes, caps,
                   format(p["context"], ",d").replace(",", " ") if p.get("context") else "—",
                   quota, _echappe(p.get("vault_key") or "—"), etat)
            )

    return _GABARIT % {
        "total": len(providers),
        "avec": avec,
        "sans": sans,
        "sans_emplacement": sans_emplacement,
        "lignes": "".join(lignes),
    }


async def admin_providers_page(request):
    """GET /admin/providers → inventaire des fournisseurs (lecture seule)."""
    import asyncio  # noqa: PLC0415

    from starlette.responses import HTMLResponse  # noqa: PLC0415

    # `list_providers` sonde les backends et le coffre : mesuré à plus de 25 s le
    # 2026-08-26 quand ollama était figé. L'exécuter DANS la boucle d'événements
    # gèlerait le service entier — c'est la maladie corrigée le 17-18/09. On le
    # déporte dans un fil.
    try:
        données = await asyncio.to_thread(list_providers)
    except Exception as exc:  # noqa: BLE001 — on NOMME ce qu'on n'a pas pu lire
        return HTMLResponse(
            _GABARIT % {"total": 0, "avec": 0, "sans": 0, "sans_emplacement": 0,
                        "lignes": '<tr><td colspan="6" class="vide">Catalogue illisible '
                                  '(%s) — ce n\'est pas « aucun fournisseur », c\'est '
                                  '« je n\'ai pas pu voir ».</td></tr>'
                                  % _echappe(type(exc).__name__)},
            status_code=503,
        )
    return HTMLResponse(_page_inventaire(données))


_GABARIT = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>Nokido — Inventaire des fournisseurs</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/static/nokido.css">
<style>
  .enveloppe { max-width:1280px; margin:0 auto; padding:22px 18px 60px; }
  header.tete { display:flex; flex-wrap:wrap; gap:14px; align-items:flex-end;
                justify-content:space-between; margin-bottom:16px; }
  header.tete h1 { margin:0; font-size:19px; letter-spacing:-0.2px; }
  header.tete p { margin:5px 0 0; color:var(--text-secondary); font-size:12.5px; max-width:72ch; }
  nav.ailleurs { display:flex; gap:14px; font-size:12.5px; }
  .renvoi { border-left:3px solid var(--purple); background:var(--bg-1);
            border-radius:var(--radius-sm); padding:11px 14px; margin-bottom:16px;
            font-size:12.5px; color:var(--text-secondary); }
  .chiffres { display:flex; flex-wrap:wrap; gap:18px; margin-bottom:14px;
              font-family:'JetBrains Mono',monospace; font-size:12px; }
  .chiffres b { color:var(--text-primary); }
  tr.groupe td { background:var(--bg-1); text-transform:uppercase; letter-spacing:.6px;
                 font-size:11px; color:var(--text-secondary); font-weight:600; }
  tr.groupe .cpt { color:var(--text-dim); font-weight:400; }
  .nom { font-family:'JetBrains Mono',monospace; font-weight:600; }
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
  .cle { color:var(--purple); }
  .dim { color:var(--text-dim); font-style:italic; }
  td.vide { text-align:center; color:var(--text-dim); padding:22px 0; }
</style>
</head>
<body>
<div class="enveloppe">
  <header class="tete">
    <div>
      <h1>Inventaire des fournisseurs</h1>
      <p>Ce que le corps SAIT de chaque fournisseur : palier, capacités, fenêtre de
         contexte, quota, et l'emplacement de sa clé au coffre. Lecture seule.</p>
    </div>
    <nav class="ailleurs">
      <a href="/admin/mcp_clients">Clients MCP</a>
      <a href="/">Hub</a>
    </nav>
  </header>

  <div class="renvoi">
    <strong>Saisir, remplacer ou retirer une clé</strong> se fait sur
    <a href="http://127.0.0.1:7400/providers">le poste de commande du portail</a>.
    Cette page-ci est servie sans authentification : elle informe, elle n'écrit pas.
    Voir aussi <a href="http://127.0.0.1:7400/llm-dashboard">où s'inscrire</a>.
  </div>

  <div class="laforge-card">
    <div class="chiffres">
      <span><b>%(total)d</b> fournisseurs</span>
      <span><b>%(avec)d</b> avec clé</span>
      <span><b>%(sans)d</b> sans clé</span>
      <span><b>%(sans_emplacement)d</b> sans emplacement au coffre</span>
    </div>
    <table class="laforge-table">
      <thead>
        <tr><th>Fournisseur</th><th>Capacités</th><th>Contexte</th><th>Quota</th>
            <th>Emplacement au coffre</th><th>État</th></tr>
      </thead>
      <tbody>%(lignes)s</tbody>
    </table>
  </div>
</div>
</body>
</html>
"""


async def api_list_providers(request):
    """GET /api/providers → JSON list."""
    import asyncio  # noqa: PLC0415

    from starlette.responses import JSONResponse  # noqa: PLC0415

    # Hors de la boucle (2026-10-01) : list_providers sonde le coffre (WCM, imports a
    # froid) et compte les quotas en SQLite pour chaque provider -- 40 gels, 28 s de
    # boucle figee en 7 jours (journal de forge_loop_sentinel).
    return JSONResponse({"providers": await asyncio.to_thread(list_providers)})


async def api_get_provider(request):
    """GET /api/providers/{provider} → JSON detail."""
    from starlette.responses import JSONResponse  # noqa: PLC0415
    from nokido_agent.app.forge_provider_specs import PROVIDER_SPECS  # noqa: PLC0415

    provider = request.path_params.get("provider", "")
    if provider not in PROVIDER_SPECS:
        return JSONResponse({"error": "unknown provider"}, status_code=404)
    return JSONResponse(_provider_status(provider, PROVIDER_SPECS[provider]))


async def api_set_key(request):
    """POST /api/providers/{provider}/key → vault.set_secret."""
    from starlette.responses import JSONResponse  # noqa: PLC0415

    if _resolve_request_ring(request) > 1:
        return JSONResponse({"error": "ring <= 1 required"}, status_code=403)
    provider = request.path_params.get("provider", "")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    key = body.get("api_key", "")
    return JSONResponse(set_provider_key(provider, key))


def _sur_le_provider(request, action):
    """Garde de porteur + extraction du provider + appel. Un seul endroit.

    FACTORISE le 2026-09-18, sur refus du cliquet de duplication -- et il avait raison.
    En ajoutant le garde de ring a `api_test_provider`, je l'ai rendue structurellement
    IDENTIQUE a `api_delete_key` : meme import local, meme condition, meme extraction,
    seul l'appel final differait. Deux copies d'un garde de securite, c'est une copie de
    trop : le jour ou l'une est durcie, l'autre reste ouverte sans que rien ne le dise.
    """
    from starlette.responses import JSONResponse  # noqa: PLC0415

    if _resolve_request_ring(request) > 1:
        return JSONResponse({"error": "ring <= 1 required"}, status_code=403)
    return JSONResponse(action(request.path_params.get("provider", "")))


async def api_delete_key(request):
    """DELETE /api/providers/{provider}/key → vault.delete."""
    return _sur_le_provider(request, delete_provider_key)


async def api_list_mcp_clients(request):
    """GET /api/mcp_clients → état coffre vs environnement, par client."""
    from starlette.responses import JSONResponse  # noqa: PLC0415

    clients = list_mcp_clients()
    return JSONResponse({"clients": clients,
                         "a_traiter": [c for c in clients if c["etat"] not in ("ALIGNE",)],
                         "commande_resync": _CMD_RESYNC})


async def admin_mcp_clients_page(request):
    """GET /admin/mcp_clients → vue lisible du désaccord coffre/environnement.

    Volontairement SANS bouton d'action : le hub tourne sous un compte de service et
    n'a pas accès au registre de l'owner (mesuré : « REFUSE »). Un bouton qui échoue
    est pire qu'un bouton absent — il fait croire l'action faite. La page affiche donc
    la commande à lancer en session owner.
    """
    from starlette.responses import HTMLResponse  # noqa: PLC0415

    lignes = []
    for c in list_mcp_clients():
        couleur = {"ALIGNE": "#2e7d32", "DESACCORD": "#c62828", "ENV_ABSENTE": "#ef6c00",
                   "SANS_JETON": "#c62828", "ENV_ILLISIBLE": "#616161"}.get(c["etat"], "#616161")
        lignes.append(
            "<tr><td><b>%s</b></td><td style='color:%s'><b>%s</b></td>"
            "<td><code>%s</code></td><td><code>%s</code></td><td>%s</td></tr>"
            % (c["agent"], couleur, c["etat"], c["sha_coffre"] or "—",
               c["sha_env"] or ("illisible" if not c["env_lisible"] else "—"),
               c["remede"] or ""))
    html = (
        "<html><head><meta charset='utf-8'><title>Clients MCP</title>"
        "<link rel='stylesheet' href='/static/nokido.css'>"
        "<style>body{margin:0;padding:22px 18px 60px}"
        ".enveloppe{max-width:1080px;margin:0 auto}"
        "h1{font-size:19px;margin:0 0 6px}"
        "p{color:var(--text-secondary);font-size:12.5px;max-width:78ch}"
        "code{font-family:'JetBrains Mono',monospace;color:var(--purple);"
        "background:var(--bg-2);padding:.1rem .35rem;border-radius:3px}"
        "</style></head><body><div class='enveloppe'>"
        "<h1>Clients MCP — coffre vs environnement</h1>"
        "<p>Les jetons vivent au coffre DPAPI, mais certains clients lisent une "
        "<b>variable d'environnement</b> (codex : <code>bearer_token_env_var</code>). "
        "Un désaccord authentifie le client <b>à vide</b>, sans message d'erreur côté hub.</p>"
        "<table class='laforge-table'><tr><th>agent</th><th>état</th><th>sha8 coffre</th>"
        "<th>sha8 env</th><th>remède</th></tr>" + "".join(lignes) + "</table>"
        "<p>Resynchroniser (session <b>owner</b> — le hub n'a pas accès au registre "
        "utilisateur) :<br><code>%s</code><br>puis <b>rouvrir</b> le terminal du client : "
        "écrire la variable ne recharge jamais un process déjà lancé.</p>"
        "<p><a href='/admin/providers'>← Inventaire des fournisseurs</a></p>"
        "</div></body></html>" % _CMD_RESYNC)
    return HTMLResponse(html)


async def api_test_provider(request):
    """POST /api/providers/{provider}/test → health check.

    GARDÉ depuis le 2026-09-18 : la route était ouverte (200 sans le moindre
    en-tête) alors qu'elle fait PARTIR une requête réseau avec la clé du coffre.
    Sans garde, elle sert d'oracle de validité de clé à tout process local et
    consomme le quota du fournisseur.
    """
    return _sur_le_provider(request, test_provider)


async def api_list_access(request):
    """GET /api/access → provenance des acces SSH (jamais leur valeur). Ring <= 1."""
    from starlette.responses import JSONResponse  # noqa: PLC0415

    if _resolve_request_ring(request) > 1:
        return JSONResponse({"error": "ring <= 1 required"}, status_code=403)
    return JSONResponse({"ok": True, "acces": etat_des_acces()})


async def api_set_access(request):
    """POST /api/access/{cle} {"valeur": ...} → coffre. Ring <= 1, liste blanche."""
    from starlette.responses import JSONResponse  # noqa: PLC0415

    if _resolve_request_ring(request) > 1:
        return JSONResponse({"error": "ring <= 1 required"}, status_code=403)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    res = definir_acces(request.path_params.get("cle", ""), (body or {}).get("valeur", ""))
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


async def api_delete_access(request):
    """DELETE /api/access/{cle} → retrait du coffre. Ring <= 1, liste blanche."""
    from starlette.responses import JSONResponse  # noqa: PLC0415

    if _resolve_request_ring(request) > 1:
        return JSONResponse({"error": "ring <= 1 required"}, status_code=403)
    res = retirer_acces(request.path_params.get("cle", ""))
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


def get_starlette_routes():
    """Retourne la liste des Routes Starlette à brancher dans nokido_hub.app."""
    try:
        from starlette.routing import Route  # noqa: PLC0415
    except ImportError:
        return []
    return [
        Route("/admin/providers", admin_providers_page, methods=["GET"]),
        Route("/api/providers", api_list_providers, methods=["GET"]),
        Route("/api/providers/{provider}", api_get_provider, methods=["GET"]),
        Route("/api/providers/{provider}/key", api_set_key, methods=["POST"]),
        Route("/api/providers/{provider}/key", api_delete_key, methods=["DELETE"]),
        Route("/api/providers/{provider}/test", api_test_provider, methods=["POST"]),
        Route("/admin/mcp_clients", admin_mcp_clients_page, methods=["GET"]),
        Route("/api/mcp_clients", api_list_mcp_clients, methods=["GET"]),
        Route("/api/access", api_list_access, methods=["GET"]),
        Route("/api/access/{cle}", api_set_access, methods=["POST"]),
        Route("/api/access/{cle}", api_delete_access, methods=["DELETE"]),
    ]


# ─── HTML page (HTMX + Alpine.js + Tailwind via CDN) ─────────────────────────
# Single-file pour minimiser le déploiement. CDN externe : pas idéal pour
# air-gapped mais OK pour public release initial. Évolutif vers static/local.

_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Nokido — LLM Providers Admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Dependances SERVIES PAR LE HUB, jamais par un CDN. Toute la mise en page de cette
     page tient dans des classes Tailwind : si le script ne charge pas, les classes sont
     inertes et l'ecran s'effondre en un bloc sans grille ni colonnes. Les trois fichiers
     etaient deja vendorises dans app/web_hub/static (tailwind.min.js y pese les memes
     407 279 octets que le CDN) et le hub les sert en 200 -- mesure 2026-08-30. Un OS
     local-first ne fait pas dependre son ecran d'administration d'un tiers joignable. -->
<script src="/static/htmx.min.js"></script>
<script defer src="/static/alpine.min.js"></script>
<script src="/static/tailwind.min.js"></script>
<style>
  body { font-family: ui-sans-serif, system-ui, sans-serif; background:#0d1117; color:#c9d1d9; }
  .tier-local { color:#3fb950; }
  .tier-free  { color:#58a6ff; }
  .tier-paid_api, .tier-subscription_quota { color:#d29922; }
  .tier-unknown { color:#8b949e; }
  [x-cloak] { display: none !important; }
  .pill { padding:2px 8px; border-radius:6px; font-size:0.75rem; }
  .pill-on  { background:#238636; color:#fff; }
  .pill-off { background:#6e7681; color:#fff; }
  .cap { background:#1f6feb22; color:#79c0ff; padding:1px 6px; border-radius:4px; font-size:0.7rem; margin-right:4px; }
  table { width:100%; border-collapse:collapse; }
  th, td { padding:8px 12px; text-align:left; border-bottom:1px solid #21262d; }
  th { background:#161b22; font-weight:600; font-size:0.85rem; text-transform:uppercase; }
  input[type=password], input[type=text] { background:#0d1117; border:1px solid #30363d; color:#c9d1d9; padding:4px 8px; border-radius:4px; }
  button { background:#1f6feb; color:#fff; padding:4px 12px; border-radius:6px; border:none; cursor:pointer; font-size:0.85rem; }
  button:hover { background:#388bfd; }
  button.danger { background:#da3633; } button.danger:hover { background:#f85149; }
  button.ghost { background:transparent; border:1px solid #30363d; color:#c9d1d9; }
</style>
</head>
<body class="p-4 md:p-8 max-w-7xl mx-auto min-h-screen flex flex-col justify-between bg-[#0d1117] text-[#c9d1d9]">

<div>
<header class="mb-6 flex flex-col md:flex-row gap-4 justify-between items-start md:items-center pb-6 border-b border-[#30363d]">
  <div>
    <h1 class="text-2xl font-bold flex items-center gap-2">🔌 LLM Providers Admin</h1>
    <p class="text-xs md:text-sm text-gray-400 mt-1">Vault-backed API key management — DPAPI machine-wide (Win) / Keychain (macOS) / libsecret (Linux). Pas de .env touché.</p>
  </div>
  <div class="flex gap-3 text-sm font-semibold self-stretch md:self-auto justify-end">
    <a href="/admin/dashboard" class="text-blue-400 hover:text-blue-300 transition underline">Dashboard</a>
    <a href="/admin/rbac" class="text-blue-400 hover:text-blue-300 transition underline">RBAC</a>
    <a href="/" class="text-blue-400 hover:text-blue-300 transition underline">Hub /</a>
  </div>
</header>

<div x-data="providersApp()" x-init="load()" class="space-y-4">

  <!-- Filters -->
  <div class="flex flex-col lg:flex-row gap-4 items-stretch lg:items-center text-sm w-full bg-[#161b22]/50 p-4 rounded-xl border border-[#30363d]">
    <div class="relative flex-1">
      <input x-model="search" placeholder="Filter by name…" class="w-full bg-[#0d1117] border border-[#30363d] focus:border-[#58a6ff] focus:ring-1 focus:ring-[#58a6ff] text-[#c9d1d9] px-3.5 py-2 rounded-lg outline-none transition placeholder-gray-500">
    </div>
    <div class="flex flex-wrap items-center gap-4">
      <select x-model="tierFilter" class="bg-[#0d1117] border border-[#30363d] focus:border-[#58a6ff] text-[#c9d1d9] px-3.5 py-2 rounded-lg outline-none cursor-pointer transition">
        <option value="">All tiers</option>
        <option value="local">Local</option>
        <option value="free">Free cloud</option>
        <option value="subscription_quota">Subscription quota</option>
        <option value="paid_api">Paid API</option>
      </select>
      <label class="flex items-center gap-2 text-gray-400 cursor-pointer select-none text-xs md:text-sm">
        <input type="checkbox" x-model="onlyMissingKey" class="rounded border-[#30363d] bg-[#0d1117] text-[#1f6feb] focus:ring-0 w-4 h-4">
        <span>Only missing keys</span>
      </label>
      <button @click="load()" class="bg-transparent border border-[#30363d] hover:bg-[#21262d] text-[#c9d1d9] px-4 py-2 rounded-lg transition font-medium flex items-center gap-2 text-xs md:text-sm">
        <span>⟳</span> Refresh
      </button>
    </div>
    <span class="text-gray-500 text-xs md:text-sm self-center lg:ml-auto font-medium" x-text="`${visible().length} / ${providers.length} providers`"></span>
  </div>

  <!-- Table container (Horizontal scroll on mobile) -->
  <div class="overflow-x-auto w-full rounded-xl border border-[#30363d] bg-[#161b22]/20 backdrop-blur-sm shadow-xl">
    <table class="min-w-full divide-y divide-[#30363d] border-collapse">
      <thead class="bg-[#161b22]">
        <tr>
          <th class="px-6 py-4 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Provider</th>
          <th class="px-6 py-4 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Tier</th>
          <th class="px-6 py-4 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Capabilities</th>
          <th class="px-6 py-4 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Context</th>
          <th class="px-6 py-4 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Quota</th>
          <th class="px-6 py-4 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Vault key</th>
          <th class="px-6 py-4 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Status</th>
          <th class="px-6 py-4 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Actions</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-[#21262d] bg-[#0d1117]/30">
        <template x-for="p in visible()" :key="p.name">
          <tr class="hover:bg-[#161b22]/30 transition-colors">
            <td class="px-6 py-4 whitespace-nowrap">
              <div class="font-mono font-bold text-sm text-[#f0f6fc]" x-text="p.name"></div>
              <!-- Un provider RETIRE par son editeur doit se VOIR. Sans cette marque,
                   l'API le sait et l'ecran l'offre quand meme : c'est le motif du signal
                   mesure qui n'atteint pas la decision. Le titre porte la date et la cause. -->
              <template x-if="p.perime">
                <div class="mt-1 inline-block px-2 py-0.5 rounded-md text-[0.65rem] font-semibold bg-[#da3633]/15 text-[#f85149] border border-[#da3633]/40 cursor-help" :title="p.perime">RETIRE PAR L'EDITEUR</div>
              </template>
              <div class="text-xs text-gray-400 mt-1 max-w-xs truncate" :title="p.notes" x-text="p.notes"></div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm">
              <span :class="'tier-' + p.tier + ' font-semibold capitalize'" x-text="p.tier.replace('_', ' ')"></span>
            </td>
            <td class="px-6 py-4">
              <div class="flex flex-wrap gap-1">
                <template x-for="c in p.capabilities" :key="c">
                  <span class="px-2 py-0.5 rounded text-[10px] font-semibold bg-[#1f6feb]/10 border border-[#1f6feb]/20 text-[#58a6ff] uppercase tracking-wide" x-text="c"></span>
                </template>
              </div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300" x-text="p.context ? p.context.toLocaleString() : '-'"></td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-300">
              <template x-if="p.monthly_calls">
                <div>
                  <span class="font-semibold text-gray-100" x-text="p.monthly_calls.toLocaleString()"></span> <span class="text-gray-400 text-xs">calls/mo</span>
                  <template x-if="p.daily_calls">
                    <span class="text-gray-500"> · </span><span class="text-gray-400 text-xs" x-text="`${p.daily_calls.toLocaleString()}/day`"></span>
                  </template>
                </div>
              </template>
              <template x-if="!p.monthly_calls && p.tier === 'local'">
                <span class="text-xs text-gray-500 italic">unlimited</span>
              </template>
            </td>
            <td class="px-6 py-4 whitespace-nowrap font-mono text-xs">
              <span class="px-2 py-1 bg-[#0d1117] text-[#d370e3] border border-[#30363d] rounded" x-text="p.vault_key || '-'"></span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
              <span :class="p.has_key ? 'px-2.5 py-1 rounded-full text-xs font-semibold bg-[#238636]/10 text-[#56d364] border border-[#238636]/30' : (p.vault_key ? 'px-2.5 py-1 rounded-full text-xs font-semibold bg-[#da3633]/10 text-[#ff7b72] border border-[#da3633]/30' : 'px-2.5 py-1 rounded-full text-xs font-semibold bg-gray-800 text-gray-400 border border-gray-700')"
                    x-text="p.has_key ? '✓ Present' : (p.vault_key ? '✗ Missing' : 'n/a')"></span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm font-medium">
              <div class="flex items-center gap-2">
                <template x-if="p.vault_key">
                  <button @click="openKeyModal(p)" class="px-3 py-1.5 bg-[#1f6feb] hover:bg-[#388bfd] text-white rounded-lg transition-all text-xs font-semibold shadow-md flex items-center gap-1.5">
                    <span>🔑</span> Set key
                  </button>
                </template>
                <button @click="testProvider(p.name)" class="px-3 py-1.5 bg-[#21262d] hover:bg-[#30363d] text-[#c9d1d9] border border-[#30363d] rounded-lg transition-all text-xs font-semibold flex items-center gap-1.5">
                  <span>▶</span> Test
                </button>
                <template x-if="p.has_key && p.vault_key">
                  <button @click="deleteKey(p)" class="px-3 py-1.5 bg-[#da3633]/80 hover:bg-[#da3633] text-white rounded-lg transition-all text-xs font-semibold flex items-center gap-1.5">
                    <span>✗</span> Remove
                  </button>
                </template>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>

  <!-- Modal set key -->
  <div x-show="modalOpen" x-cloak class="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
       @click.self="modalOpen=false">
    <div class="bg-[#161b22] border border-[#30363d] p-6 rounded-xl w-full max-w-md space-y-4 shadow-2xl transition-all">
      <h3 class="text-lg font-bold text-white flex items-center gap-2">
        <span>🔑</span> Set API key for <span class="font-mono text-[#58a6ff]" x-text="modalProvider"></span>
      </h3>
      <p class="text-xs text-gray-400 leading-relaxed">
        Stored securely as <code class="px-1.5 py-0.5 bg-[#0d1117] text-[#d370e3] border border-[#30363d] rounded" x-text="modalVaultKey"></code> inside the local vault. 
        It will never be written to your project's <code>.env</code> file.
      </p>
      <input type="password" x-model="modalKey" placeholder="Paste API key here" 
             class="w-full bg-[#0d1117] border border-[#30363d] focus:border-[#58a6ff] focus:ring-1 focus:ring-[#58a6ff] text-[#c9d1d9] px-3 py-2.5 rounded-lg outline-none transition">
      <div class="flex justify-end gap-2 pt-2">
        <button class="px-4 py-2 bg-transparent hover:bg-[#21262d] text-[#c9d1d9] border border-[#30363d] rounded-lg transition text-sm font-semibold" @click="modalOpen=false">Cancel</button>
        <button class="px-4 py-2 bg-[#238636] hover:bg-[#2ea043] text-white rounded-lg transition text-sm font-semibold shadow-md" @click="saveKey()">Save to vault</button>
      </div>
    </div>
  </div>

  <!-- Toast -->
  <div x-show="toast" x-cloak x-transition.duration.300ms
       class="fixed bottom-4 right-4 bg-[#161b22] border border-[#30363d] text-white px-4 py-3 rounded-xl shadow-2xl flex items-center gap-2 text-sm z-50"
       x-text="toast"></div>

</div>
</div>

<script>
function providersApp() {
  return {
    providers: [], search: '', tierFilter: '', onlyMissingKey: false,
    modalOpen: false, modalProvider: '', modalVaultKey: '', modalKey: '',
    toast: '',

    async load() {
      try {
        const r = await fetch('/api/providers');
        const j = await r.json();
        this.providers = j.providers || [];
      } catch (e) { this.flash('Error loading providers: ' + e); }
    },

    visible() {
      return this.providers.filter(p =>
        (!this.search || p.name.includes(this.search.toLowerCase())) &&
        (!this.tierFilter || p.tier === this.tierFilter) &&
        (!this.onlyMissingKey || (p.vault_key && !p.has_key))
      );
    },

    openKeyModal(p) {
      this.modalProvider = p.name;
      this.modalVaultKey = p.vault_key;
      this.modalKey = '';
      this.modalOpen = true;
    },

    async saveKey() {
      try {
        const r = await fetch('/api/providers/' + this.modalProvider + '/key',
          {method:'POST', headers:{'Content-Type':'application/json'},
           body: JSON.stringify({api_key: this.modalKey})});
        const j = await r.json();
        if (j.ok) { this.flash('Saved ' + j.vault_key + ' → vault (' + j.preview + ')');
                    this.modalOpen=false; await this.load(); }
        else this.flash('Error: ' + (j.error || 'unknown'));
      } catch (e) { this.flash('Error: ' + e); }
    },

    async deleteKey(p) {
      if (!confirm('Remove ' + p.vault_key + ' from vault?')) return;
      try {
        const r = await fetch('/api/providers/' + p.name + '/key', {method:'DELETE'});
        const j = await r.json();
        if (j.ok) { this.flash('Removed ' + j.vault_key); await this.load(); }
        else this.flash('Error: ' + (j.error || 'unknown'));
      } catch (e) { this.flash('Error: ' + e); }
    },

    async testProvider(name) {
      try {
        const r = await fetch('/api/providers/' + name + '/test', {method:'POST'});
        const j = await r.json();
        this.flash((j.ok ? '✓ ' : '✗ ') + name + ': ' + (j.note || j.error || 'ok'));
      } catch (e) { this.flash('Error: ' + e); }
    },

    flash(msg) {
      this.toast = msg;
      setTimeout(() => { this.toast = ''; }, 4000);
    }
  };
}
</script>
</body>
</html>
"""


def main():
    """CLI helper — affiche le statut de tous les providers."""
    for p in list_providers():
        flag = "✓" if p["has_key"] else ("·" if p["tier"] == "local" else "✗")
        print(
            f"  {flag} {p['name']:<25} [{p['tier']:<19}] "
            f"key={p['vault_key'] or '-':<25} "
            f"caps={','.join(p['capabilities'])}"
        )


if __name__ == "__main__":
    main()
