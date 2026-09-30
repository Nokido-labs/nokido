"""forge_provider_alias.py -- la verite a UNE adresse : `forge_agent_proxy.ask`.

QUATRE registres de fournisseurs coexistaient, et j'ai perdu cinq passes d'arene a
interroger le mauvais :

    forge_agent_proxy._PROVIDERS   39 noms  <- ce que `ask()` accepte, SEUL executable
    forge_llm_router.PROVIDERS     33 noms  <- affichage, quotas, rings
    catalogue LiteLLM installe     2656 modeles / 109 fournisseurs (debranche)
    listes ecrites a la main       source de toutes mes erreurs

Mesure 2026-09-02 : ces deux registres ont **3 noms communs sur 39 et 33**. Ils ne
divergent pas, ils sont quasi DISJOINTS -- deux conventions de nommage. Le hub
nomme par (fournisseur, modele) : `gemini_flash`, `groq_fast`. `ask` nomme par
famille : `gemini`, `groq`. Interroger l'un avec les noms de l'autre rend
`Provider 'X' inconnu`, message qui se lit a tort comme « ce fournisseur est mort ».

CE MODULE NE FUSIONNE RIEN. Il declare le MAPPING, explicitement, entree par
entree. Un alias DEDUIT par prefixe serait une invention : `nvidia_nemotron_super`
ne se devine pas en `nvidia_nim`, et une regle qui marche sur 30 cas sur 33
fabrique deux erreurs silencieuses. Ce qu'on ne sait pas mapper vaut None, et le
test le dit.

API ajoutee depuis le 2026-09-22 (premiere ligne de la docstring de chaque symbole) :
- `refus_de_resolution` — Raison de REFUSER qu'`ask` serve `nom` par son alias ; None si la resolution est FIDELE.
"""

from __future__ import annotations

# --- amorce namespace (point d'entree) : `sys.path[0]` vaut le dossier du
# script, pas la racine du depot. Sans cette ligne, `from nokido_agent...`
# leve ModuleNotFoundError quand ce fichier est lance par chemin.
import sys as _sys_amorce
from pathlib import Path as _Path_amorce
_RACINE_AMORCE = str(_Path_amorce(__file__).resolve().parent.parent)
if _RACINE_AMORCE not in _sys_amorce.path:
    _sys_amorce.path.insert(0, _RACINE_AMORCE)

__FORGE_COLOR__ = "moelle/alias-fournisseurs"

from typing import Dict, List, Optional

# Nom du registre du hub -> nom EXECUTABLE par `forge_agent_proxy.ask`.
# `None` = aucun equivalent connu : on le DECLARE au lieu de deviner.
ALIAS: Dict[str, Optional[str]] = {
    # Google
    "gemini_flash": "gemini",
    "gemini_pro": "gemini",
    "gemini_flash_lite": "gemini_flash_lite",
    "gemini_gemma": "gemini_gemma",
    # Groq
    "groq_fast": "groq",
    "groq_allam": "groq",
    "groq_mixtral": "groq",
    # Mistral
    "mistral_small": "mistral",
    "mistral_large": "mistral",
    # 2026-09-25 : emplacement du routeur pour nokido/auto (codestral, mesure APPELLE).
    "mistral_codestral": "mistral",
    # Cohere
    "cohere_command_r": "cohere",
    "cohere_command_r_plus": "cohere",
    # xAI
    "xai_grok3": "grok",
    "xai_grok3_mini": "grok",
    # OpenRouter
    "openrouter_free": "openrouter_free",
    "openrouter_gpt_oss": "openrouter_free",
    "openrouter_glm_air": "openrouter_free",
    "openrouter_qwen_coder": "openrouter_free",
    # GitHub Models -- NOTE : mesure 2026-09-02, le service rend HTTP 410
    # `github_models_retirement_brownout`. L'alias reste declare pour que la
    # disparition soit LISIBLE plutot que muette.
    "github_gpt41_mini": "gpt4o_github",
    "github_gpt4o_mini": "gpt4o_github",
    "github_llama_70b": "gpt4o_github",
    "github_phi4_mini": "gpt4o_github",
    "github_deepseek_v3": "gpt4o_github",
    "github_codestral": "gpt4o_github",
    "github_cohere_rp": "gpt4o_github",
    # HuggingFace
    "hf_qwen_coder": "hf",
    "hf_llama": "hf",
    # SambaNova
    "sambanova_llama_405b": "sambanova",
    "sambanova_llama_70b": "sambanova",
    # NVIDIA
    "nvidia_nemotron_super": "nvidia_nim",
    # Locaux
    "llamacpp_local": "llamacpp",
    "lmstudio_native": "lmstudio",
    "ollama_local": "ollama",
    "docker_local": "docker",
}

# Fournisseurs dont Nokido detient une CLEF mais qui n'ont AUCUNE entree dans
# `ask()` : ils sont payes/disponibles et pourtant inatteignables. C'est une
# DETTE, pas une fatalite -- et la nommer est ce qui la rend traitable.
ABSENTS_DE_ASK: List[str] = [
    # (vide) -- `together_ai` a ete cable le 2026-09-02.
]

# TROISIEME ETAT, entre « joignable » et « non configure » : la clef EXISTE et le
# service la REFUSE. Le cablage est bon, l'appel part, le fournisseur repond 401.
# Sans cette categorie, on range ces cas en « injoignable » et on cherche la panne
# du mauvais cote -- j'ai enterre des fournisseurs entiers sur ce malentendu.
#
# DEUX faits distincts, qu'un seul code HTTP ne separe pas -- et il faut les
# DEUX pour decider quoi faire :
#   (a) la POLITIQUE du fournisseur (existe-t-il un palier gratuit ?) ;
#   (b) l'ETAT de notre clef (le fournisseur l'accepte-t-il ?).
# Un refus d'authentification ne dit RIEN de (a) : il faut la doc. Et une
# politique payante ne dit rien de (b) : il faut la mesure. Together illustre
# le piege -- clef invalide (mesure) ET aucun palier gratuit (doc), si bien que
# renouveler la clef ne suffirait PAS a le rendre joignable.
#
# PIEGE PAYE le 2026-09-02, a relire avant de conclure sur un fournisseur :
# `urllib` sans User-Agent se fait jeter par le WAF Cloudflare de Together en
# `403 error code: 1010`, qui n'est PAS une reponse de l'API. Lu tel quel, ce
# code fait accuser le credit ou le palier. Avec un User-Agent de navigateur,
# la meme clef rend `401 invalid_api_key` -- le vrai motif. Verifier d'abord
# que la reponse vient de l'API et non d'un pare-feu place devant elle.
CLEF_REFUSEE: Dict[str, str] = {
    "together_ai": "PAYANT SANS PALIER GRATUIT + clef invalide. Doc Together "
                   "(2026-09-02) : 'does not currently offer free trials', acces "
                   "conditionne a un achat de 5 USD minimum, plateforme "
                   "entierement PREPAYEE (solde nul = API suspendue). Mesure du "
                   "meme jour : 401 invalid_api_key sur /v1/models ET "
                   "/v1/chat/completions ; la clef au coffre fait 25 car. et "
                   "commence par 'key_' quand Together emet du 64-hex. Donc "
                   "renouveler la clef NE SUFFIRAIT PAS -- hors panel gratuit "
                   "tant que l'owner n'a pas achete de credit.",
    "grok": "PREPAYE (aucun palier gratuit) + clef invalide. Doc xAI "
            "(2026-09-02) : 'Sign up for an account at console.x.ai, then load it "
            "with credits to start using the API'. A la difference de Together, xAI "
            "n'AFFIRME nulle part l'absence d'essai gratuit -- il ne la mentionne "
            "pas. PIEGE DE LECTURE : la grille de quotas expose un 'Tier 0, spend "
            "threshold $0' avec des limites non nulles (grok-4.6 : 150 RPS, 50M "
            "TPM). Ce Tier 0 est le palier de RATE LIMIT par defaut, PAS un palier "
            "gratuit : il dit combien on peut appeler, jamais que c'est offert. La "
            "facturation reste a l'usage sur credits PREPAYES. Mesure du meme jour : "
            "400 'Incorrect API key provided' sur /v1/models ET "
            "/v1/language-models, clef de 84 car. presente au coffre. Piege : chez "
            "xAI un refus d'AUTH sort en 400, la ou tout le monde rend 401 -- lu "
            "comme une requete malformee, il fait chercher la panne cote client.",
}


# NOMS TROMPEURS (owner 2026-09-24 : « gemini-flash-lite-latest via provider n'est pas le modele fort »).
# Le registre LIVRE fait servir ces noms par des modeles flash-lite : le NOM promet plus que ce qui est
# servi. `ask` les REFUSE au lieu de servir flash-lite en silence. La raison ne suppose AUCUNE surface
# (owner, meme jour : « Nokido devrait dans sa version dist savoir utiliser la surface presente ») :
# les surfaces fortes disponibles sont CALCULEES sur la machine par l'appelant (forge_agent_proxy).
NOMS_TROMPEURS: Dict[str, str] = {
    "gemini_flash": "le registre fait servir ce nom par des modeles flash-lite (le nom promet davantage) ; "
                    "flash-lite assume = gemini_flash_lite",
    "gemini_pro": "le registre fait servir ce nom par des modeles flash-lite (le nom promet un modele pro) ; "
                  "flash-lite assume = gemini_flash_lite",
}


def _queue_modele(m) -> str:
    """Dernier segment, sans le suffixe `-latest` (alias de version) : `openai/gpt-oss-120b` -> `gpt-oss-120b`."""
    q = str(m or "").split("/")[-1].strip().lower()
    return q[:-len("-latest")] if q.endswith("-latest") else q


def refus_de_resolution(nom: str, modele_servi) -> Optional[str]:
    """Raison de REFUSER qu'`ask` serve `nom` par son alias ; None si la resolution est FIDELE.

    Mesure du 2026-09-24 : la cible d'un alias repond avec son modele PAR DEFAUT -- `github_codestral`
    servi par gpt-4o, `sambanova_llama_405b` (promet DeepSeek-V3.1) par Llama 70B, `gemini_pro` par
    flash-lite. Brancher la table sans ce controle transformait un echec BRUYANT en substitution
    SILENCIEUSE. Fidele = le modele servi figure parmi ceux que le registre promet pour ce nom.
    Registre illisible = fidelite NON verifiable = refus (jamais « probablement bon »).
    """
    if nom in NOMS_TROMPEURS:
        return NOMS_TROMPEURS[nom]
    try:
        from nokido_agent.app.forge_llm_router import PROVIDERS as _HUB
    except Exception as e:  # noqa: BLE001
        return "registre du hub illisible (%s) : fidelite du modele non verifiable" % type(e).__name__
    h = _HUB.get(nom) or {}
    promis = h.get("models") or ([h["model"]] if h.get("model") else [])
    if not promis:
        return "aucun modele declare pour %s : substitution non verifiable" % nom
    if _queue_modele(modele_servi) in {_queue_modele(p) for p in promis}:
        return None
    return "%s promet %s, la cible sert %s : substitution refusee" % (
        nom, [_queue_modele(p) for p in promis][:3], _queue_modele(modele_servi))


def resoudre(nom: str) -> Optional[str]:
    """Nom du hub -> nom executable. Rend `nom` s'il est deja executable.

    Rend None si le nom est inconnu : ne pas inventer un alias plausible, c'est
    ainsi qu'on fabrique un appel qui echoue loin de sa cause.
    """
    if nom in ALIAS:
        return ALIAS[nom]
    return nom if _executable(nom) else None


def _executable(nom: str) -> bool:
    try:
        from nokido_agent.app.forge_agent_proxy import _PROVIDERS

        return nom in _PROVIDERS
    except Exception:  # noqa: BLE001
        return False


def diagnostic() -> Dict[str, object]:
    """Etat du mapping. Sert au test CI ET a l'humain qui debogue une divergence."""
    try:
        from nokido_agent.app.forge_agent_proxy import _PROVIDERS

        executables = set(_PROVIDERS)
    except Exception as e:  # noqa: BLE001
        # ILLISIBLE n'est pas VIDE : sans le registre cible, aucun verdict.
        return {"etat": "ILLISIBLE", "raison": str(e)[:100]}
    try:
        from nokido_agent.app.forge_llm_router import PROVIDERS as _HUB

        hub = set(_HUB)
    except Exception as e:  # noqa: BLE001
        return {"etat": "ILLISIBLE", "raison": str(e)[:100]}

    non_mappes = sorted(n for n in hub if resoudre(n) is None)
    casses = sorted(n for n, cible in ALIAS.items()
                    if cible is not None and cible not in executables)
    orphelins = sorted(n for n in ALIAS if n not in hub)
    return {
        "etat": "MESURE",
        "hub": len(hub),
        "executables": len(executables),
        "non_mappes": non_mappes,          # entrees du hub qu'on ne sait pas router
        "alias_casses": casses,            # alias pointant vers un nom inexistant
        "alias_orphelins": orphelins,      # alias pour une entree hub disparue
        "absents_de_ask": list(ABSENTS_DE_ASK),
        "clef_refusee": dict(CLEF_REFUSEE),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(diagnostic(), ensure_ascii=False, indent=1))
