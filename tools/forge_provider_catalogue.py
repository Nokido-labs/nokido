#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Quels modeles ce fournisseur autorise-t-il A CETTE CLE ?

Un `403` ou un `404` sur un appel de generation a deux causes tres differentes,
et les confondre coute des heures : la cle est morte, ou le MODELE demande a ete
retire. `GET /models` tranche en un appel — il rend 200 avec la liste quand la
cle est bonne, et 401/403 quand elle ne l'est pas.

Mesure du 2026-08-18 qui a motive ce module : `GROQ_API_KEY` etait ecartee par
la rotation pour « 403 », alors que la cle etait EXACTEMENT celle que l'owner
avait generee et qu'il n'a jamais revoquee. Accuser la cle, c'etait accuser
l'innocent : ce sont les modeles cables (mixtral…) qui avaient disparu du
catalogue gratuit.

Contexte owner : aucun de ces services n'est paye. On ne cherche donc pas « le
meilleur modele » mais « ce qui reste accessible en palier gratuit ».

N'affiche jamais une cle — seulement son suffixe de 4 caracteres, comme le CLI
du coffre.

Usage :
    run action=run_job script=tools/forge_provider_catalogue.py online=true
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TIMEOUT = 20

# Fournisseurs dont /models repond SANS cle (mesure 2026-10-15, requete anonyme) : un 200 y est
# NON PROBANT pour la cle. Mistral et Groq rendent 401 sans cle : chez eux, le 200 prouve bien.
MODELS_PUBLIC = frozenset({"sambanova", "openrouter"})

# (etiquette, cle au coffre, endpoint /models). Uniquement des surfaces
# OpenAI-compatibles : ailleurs, /models n'existe pas et un 404 ne dirait rien.
FOURNISSEURS = [
    # -- distants, dialecte OpenAI --
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1/models"),
    ("xai", "XAI_API_KEY", "https://api.x.ai/v1/models"),
    ("sambanova", "SAMBANOVA_API_KEY", "https://api.sambanova.ai/v1/models"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1/models"),
    ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1/models"),
    ("cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1/models"),
    ("deepseek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/models"),
    ("together", "TOGETHER_API_KEY", "https://api.together.xyz/v1/models"),
    ("deepinfra", "DEEPINFRA", "https://api.deepinfra.com/v1/openai/models"),
    ("siliconflow", "SILICONFLOW", "https://api.siliconflow.cn/v1/models"),
    ("nvidia", "NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1/models"),
    ("nvidia_nim", "NVIDIA_NIM_API_KEY", "https://integrate.api.nvidia.com/v1/models"),
    ("zai", "ZAI_API_KEY", "https://api.z.ai/api/paas/v4/models"),
    ("mammouth", "MAMMOUTH_API_TOKEN", "https://api.mammouth.ai/v1/models"),
    ("hf", "HF_TOKEN", "https://router.huggingface.co/v1/models"),
    ("cohere", "COHERE_API_KEY", "https://api.cohere.ai/v1/models"),
    ("voyage", "VOYAGE_API_KEY", "https://api.voyageai.com/v1/models"),
    ("jina", "JINA_API_KEY", "https://api.jina.ai/v1/models"),
    # -- locaux : pas de cle, mais un port qui repond ou pas --
    ("lmstudio", "LMSTUDIO_TOKEN", "http://127.0.0.1:1234/v1/models"),
    ("llamacpp", "FORGE_LLAMA_KEY", "http://127.0.0.1:8080/v1/models"),
    ("ollama", "", "http://127.0.0.1:11434/v1/models"),
    ("litellm", "LITELLM_API_KEY", "http://127.0.0.1:4000/v1/models"),
]

# Ces cles n'ouvrent pas un catalogue de modeles : les sonder ici produirait des
# 404 qu'on lirait a tort comme des pannes. Elles sont NOMMEES pour que leur
# absence du rapport ne passe pas pour un oubli.
HORS_PERIMETRE = {
    "TAVILY_API_KEY": "moteur de recherche, pas de /models",
    "SMITHERY_API": "registre MCP",
    "KAGGLE_API_TOKEN": "datasets",
    "CODEBERG_TOKEN": "forge git",
    "FREEBOX_APP_TOKEN": "domotique",
    "CLOUDFLARE_AI_API_KEY": "Workers AI — URL dependante du compte",
    "PCVL_CLOUD_TOKEN": "calcul quantique",
    "QUANDELA_TOKEN": "calcul quantique",
    "GITHUB_MODELS_TOKEN": "backend retire le 2026-08-18 (410 Gone)",
}


def _suffixe(cle: str) -> str:
    return f"...{cle[-4:]}" if cle else "(absente)"


def interroger(url: str, cle: str) -> tuple[int, list[str], str]:
    """(code, identifiants de modeles, detail). La cle ne sort pas d'ici."""
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {cle}",
        "User-Agent": "nokido-catalogue",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            brut = json.loads(r.read().decode("utf-8", errors="replace"))
            # PLUSIEURS FORMES, pas seulement OpenAI. Mesure 2026-09-03 : cohere
            # rend {"models": [...]} avec un champ `name`, pas {"data": [...]}
            # avec `id`. Le parseur mono-format rendait « HTTP 200 — 0 modele »,
            # et les 20 modeles reels devenaient ABSENTS DU CATALOGUE — dont
            # `command-r-08-2024`, qui EXISTE et fonctionne. Une absence TOTALE
            # sur une reponse REUSSIE accuse le parseur, jamais le fournisseur.
            donnees = brut
            if isinstance(brut, dict):
                for clef in ("data", "models", "results", "items"):
                    if isinstance(brut.get(clef), list):
                        donnees = brut[clef]
                        break
                else:
                    donnees = []
            ids = []
            for m in (donnees or []):
                if isinstance(m, dict):
                    v = m.get("id") or m.get("name") or m.get("model")
                    if v:
                        ids.append(str(v))
                elif isinstance(m, str):
                    ids.append(m)
            if r.status == 200 and not ids and isinstance(brut, dict):
                # On le DIT au lieu de rendre une liste vide silencieuse.
                return r.status, [], ("REPONSE 200 NON PARSEE — clefs racine : %s"
                                      % ", ".join(list(brut)[:6]))
            return r.status, sorted(ids), ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(400).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - corps illisible
            detail = exc.reason or ""
        return exc.code, [], detail.replace("\n", " ")[:200]
    except Exception as exc:  # noqa: BLE001 - DNS, TLS, reseau ferme
        return -1, [], f"{type(exc).__name__}: {exc}"[:120]


def modeles_cables() -> dict[str, list[str]]:
    """Ce que le routeur demande, par famille — pour confronter au catalogue."""
    from nokido_agent.app.forge_llm_router import PROVIDERS

    out: dict[str, list[str]] = {}
    for nom, fiche in PROVIDERS.items():
        famille = nom.split("_")[0]
        for m in fiche.get("models") or []:
            out.setdefault(famille, []).append(str(m))
    return out


# ── MATRICE MODELE x FOURNISSEUR (owner 15/10 : « des LLM peuvent etre injoignables par un provider et
# joignables par un autre ») ──────────────────────────────────────────────────────────────────────────
# /models dit ce qu'un fournisseur DECLARE ; seul un appel de GENERATION dit ce qu'il SERT a cette cle.
# Mesure du 15/10 qui l'a motivee : glm-5.x refuse en direct chez zAI (429/1113 sans solde), mistral-large
# refuse en direct chez Mistral (403/1910 hors palier) -- un MEME modele peut vivre chez un autre
# fournisseur. La matrice se lit par FAMILLE, jamais par slot : un refus qualifie un COUPLE.
MATRICE = ROOT / "sandbox" / "matrice_modele_fournisseur.json"
# Familles utiles (noyau normalise par `famille_de`) ; extensible sans toucher au code de sonde.
FAMILLES_UTILES = ("glm-5", "glm-4.5", "glm-4.7", "mistral-large", "mistral-medium", "mistral-small",
                   "llama-3.3-70b", "llama-3.1-8b", "deepseek-v3", "deepseek-r1", "qwen3", "gpt-oss-120b",
                   "gpt-oss-20b", "kimi-k2", "nemotron")
# Hors dialecte OpenAI pour la generation (le /chat/completions n'y existe pas a cet endroit).
SANS_GENERATION = frozenset({"cohere", "voyage", "jina"})


def famille_de(model_id: str) -> str:
    """Noyau comparable d'un identifiant : sans organisation, routage, suffixes de variante.
    `z-ai/glm-5:free` -> `glm-5` ; `mistralai/mistral-large-2411` -> `mistral-large` ;
    `meta-llama/Llama-3.3-70B-Instruct-Turbo` -> `llama-3.3-70b`."""
    import re as _re

    n = model_id.split(":", 1)[0].split("/")[-1].strip().lower()
    n = _re.sub(r"-(instruct|chat|turbo|latest|versatile|preview|fp8|hf)\b", "", n)
    n = _re.sub(r"-\d{4}(-\d{2}-\d{2})?$", "", n)          # millesimes : -2411, -2025-01-31
    n = n.replace("_", "-")
    for f in FAMILLES_UTILES:
        if n == f or n.startswith(f + "-") or n.startswith(f + "."):
            return f
    return n


def classer_reponse(code: int, detail: str) -> str:
    """Etat d'un COUPLE fournisseur x modele d'apres la reponse a une generation (jamais d'un modele seul)."""
    d = (detail or "").lower()
    if code == 200:
        return "JOIGNABLE"
    if code == 402 or "1113" in d or "insufficient balance" in d or "payment" in d or "credit" in d:
        return "SANS_SOLDE"
    if "1910" in d or "tier" in d or "subscription" in d or "not allowed" in d:
        return "HORS_PALIER"
    if code == 429:
        return "DEBIT"                     # limite de debit : PAS un refus, a re-sonder
    if code in (401, 403) or "api key" in d or "unauthorized" in d:
        return "CLEF_REFUSEE"
    if code == 404 or "not found" in d or "does not exist" in d:
        return "MODELE_ABSENT"
    return "INCONNU"


def sonder_generation(url_models: str, cle: str, model_id: str, timeout: int = 40) -> tuple[int, str, float]:
    """(code, detail, latence_ms) d'une generation MINIMALE. La cle ne sort pas d'ici."""
    import time as _t

    url = url_models.rsplit("/models", 1)[0] + "/chat/completions"
    corps = json.dumps({"model": model_id, "max_tokens": 16,
                        "messages": [{"role": "user", "content": "Reponds uniquement par le mot : OK"}]}).encode()
    req = urllib.request.Request(url, data=corps, method="POST", headers={
        "Authorization": f"Bearer {cle}", "Content-Type": "application/json", "User-Agent": "nokido-matrice"})
    t0 = _t.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(2000)
            return r.status, "", round((_t.time() - t0) * 1000)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read(400).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - corps illisible
            detail = str(exc.reason or "")
        return exc.code, detail.replace("\n", " ")[:200], round((_t.time() - t0) * 1000)
    except Exception as exc:  # noqa: BLE001 - DNS, TLS, delai : INCONNU, jamais « injoignable »
        return -1, f"{type(exc).__name__}: {exc}"[:120], round((_t.time() - t0) * 1000)


# ── Axe COMPETENCE (decision owner 15/10 : « les deux » -- matrice etendue d'abord, Promptfoo ensuite) ─────────
# JOIGNABLE n'est pas COMPETENT. Taches FIXES a correcteur DETERMINISTE : jamais un juge LLM (faux verts payes le
# 13/08), jamais d'execution du code produit par un modele. Un echec de TRANSPORT vaut INCONNU (None), pas « rate ».
def _objet_json(texte: str, strict: bool):
    t = (texte or "").strip()
    if not strict:
        debut, fin = t.find("{"), t.rfind("}")
        t = t[debut:fin + 1] if 0 <= debut < fin else ""
    try:
        obj = json.loads(t)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _ok_json_strict(texte: str) -> bool:
    return _objet_json(texte, strict=True) == {"a": 2, "b": [1, 2]}


def _ok_appel_outil(texte: str) -> bool:
    obj = _objet_json(texte, strict=False) or {}
    args = obj.get("arguments")
    return obj.get("outil") == "lire_fichier" and isinstance(args, dict) and args.get("chemin") == "notes.txt"


def _ok_calcul(texte: str) -> bool:
    return (texte or "").strip().rstrip(".") == "391"


def _ok_consigne(texte: str) -> bool:
    import re as _re

    return bool(_re.fullmatch(r"[A-ZÀ-ÖØ-Þ]+ [A-ZÀ-ÖØ-Þ]+ [A-ZÀ-ÖØ-Þ]+", (texte or "").strip()))


TACHES_COMPETENCE = (
    ("json_strict", 'Reponds UNIQUEMENT par cet objet JSON, sans aucun texte ni balise autour : {"a": 2, "b": [1, 2]}',
     _ok_json_strict),
    ("appel_outil", "Tu disposes d'un seul outil : lire_fichier(chemin). Pour lire le fichier notes.txt, reponds "
                    'UNIQUEMENT par un objet JSON de la forme {"outil": <nom>, "arguments": {"chemin": <chemin>}}.',
     _ok_appel_outil),
    ("calcul", "Combien font 17 * 23 ? Reponds par le nombre seul.", _ok_calcul),
    ("consigne", "Reponds par exactement trois mots, tous en MAJUSCULES, sans ponctuation.", _ok_consigne),
)


def generer_texte(url_models: str, cle: str, model_id: str, prompt: str, max_tokens: int = 400,
                  timeout: int = 60) -> tuple[int, str, float]:
    """(code, texte, latence_ms) d'une vraie generation. `max_tokens` >= 300 : les modeles qui raisonnent rendent
    un texte VIDE en dessous (glm-4.5-flash, mesure 15/10). La cle ne sort pas d'ici."""
    import time as _t

    url = url_models.rsplit("/models", 1)[0] + "/chat/completions"
    corps = json.dumps({"model": model_id, "max_tokens": max_tokens, "temperature": 0,
                        "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(url, data=corps, method="POST", headers={
        "Authorization": f"Bearer {cle}", "Content-Type": "application/json", "User-Agent": "nokido-matrice"})
    t0 = _t.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read(200_000).decode("utf-8", errors="replace"))
        texte = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return 200, texte if isinstance(texte, str) else "", round((_t.time() - t0) * 1000)
    except urllib.error.HTTPError as exc:
        return exc.code, "", round((_t.time() - t0) * 1000)
    except Exception:  # noqa: BLE001 - DNS, TLS, delai, corps illisible : INCONNU, rendu par le code -1
        return -1, "", round((_t.time() - t0) * 1000)


def _outil_natif(url_models: str, cle: str, model_id: str, sonde_fn=None) -> tuple:
    """(verdict, code) de l'APPEL D'OUTIL NATIF par la sonde existante `forge_tool_call_probe.interroger` (vrais
    `tool_calls` : APPELLE / IGNORE / REFUSE / NON_MESURE) -- convergence P2 du 15/10 : la matrice consomme la
    famille des sondes d'endpoints au lieu de re-sonder. APPELLE -> True ; IGNORE/REFUSE -> False ; NON_MESURE
    (debit, panne, transport) -> None, jamais un echec du modele."""
    if sonde_fn is None:
        try:
            from nokido_agent.tools import forge_tool_call_probe as _tcp
        except ImportError:
            import forge_tool_call_probe as _tcp

        sonde_fn = _tcp.interroger
    try:
        v = sonde_fn(url_models.rsplit("/models", 1)[0], cle, model_id) or {}
    except Exception:  # noqa: BLE001 - sonde illisible : non mesure, dit par le code -1
        return None, -1
    etat = v.get("etat")
    if etat == "NON_MESURE":
        return None, 429
    if etat == "REFUSE":
        # La sonde range en REFUSE tout code hors 429/5xx. Un 401/402/403/404/408 dit que l'ACCES est refuse
        # (clef, solde, modele absent, delai) -- pas que le modele refuse les outils : non mesure. Seul un 400
        # (parametre `tools` rejete) est un vrai echec de competence.
        import re as _re

        m = _re.match(r"HTTP (\d+)", v.get("motif") or "")
        code = int(m.group(1)) if m else -1
        return (None, code) if code in (401, 402, 403, 404, 408, -1) else (False, 200)
    return {"APPELLE": True, "IGNORE": False}.get(etat), 200


def sonder_competence(url_models: str, cle: str, model_id: str, gen_fn=None, taches=TACHES_COMPETENCE,
                      outil_fn=None) -> dict:
    """Joue les taches fixes sur un couple. `reussies / mesurees` -- une tache dont le transport echoue n'est pas
    mesuree (None) ; le score n'existe que si au moins une tache l'a ete. La tache `appel_outil` passe par la
    VRAIE sonde d'appel d'outil (`_outil_natif`), plus par un objet JSON ecrit en texte."""
    gen_fn = gen_fn or generer_texte
    detail, codes, lat = {}, {}, []
    for nom, prompt, correcteur in taches:
        if nom == "appel_outil":
            ok, code = _outil_natif(url_models, cle, model_id, outil_fn)
            detail[nom] = ok
            if ok is None:
                codes[nom] = code
            continue
        code, texte, ms = gen_fn(url_models, cle, model_id, prompt)
        detail[nom] = bool(correcteur(texte)) if code == 200 else None
        if code == 200:
            lat.append(ms)
        else:
            codes[nom] = code
    mesurees = [v for v in detail.values() if v is not None]
    return {"reussies": sum(mesurees), "mesurees": len(mesurees), "total": len(taches),
            "score": round(sum(mesurees) / len(mesurees), 2) if mesurees else None,
            "taches": detail, "codes_non_mesurees": codes,
            "latence_ms_mediane": sorted(lat)[len(lat) // 2] if lat else None}


def reclasser_par_competence(voie: dict) -> dict:
    """Un 200 a 16 tokens ne prouve pas l'usage. Mesure du 15/10 : 20 couples OpenRouter payants « JOIGNABLES »
    rendaient tous 402 « Insufficient credits » a l'usage reel (puis meme a 16 tokens). Si AUCUNE tache de
    competence n'a pu se mesurer et que TOUS les codes disent la meme chose, l'etat suit l'usage : 402 -> SANS_SOLDE,
    429 -> DEBIT. Codes melanges ou transport : l'etat reste, la competence dit INCONNU."""
    c = voie.get("competence") or {}
    codes = set((c.get("codes_non_mesurees") or {}).values())
    if c.get("mesurees") == 0 and len(codes) == 1:
        nouveau = {402: "SANS_SOLDE", 429: "DEBIT"}.get(codes.pop())
        if nouveau:
            voie["etat_sonde_16_tokens"] = voie.get("etat")
            voie["etat"] = nouveau
    return voie


# CLI : memes taches, par le CHEMIN REEL du routeur (`forge_agent_proxy.ask`). Codex absent par defaut (owner 15/10 :
# non paye, quota tres limite) ; un CLI qui echoue (OAuth expire, fournisseur inconnu) est NOTE avec sa raison,
# jamais classe incompetent.
CLI_PAR_DEFAUT = ("gemini_cli", "opencode")


def _texte_de(reponse) -> tuple:
    """(texte, erreur) d'une reponse d'`ask` -- un dict, quelle que soit sa forme exacte."""
    if not isinstance(reponse, dict):
        return "", "reponse non conforme (%s)" % type(reponse).__name__
    if reponse.get("error"):
        return "", str(reponse.get("error"))[:160]
    for cle_texte in ("response", "text", "content", "reponse"):
        v = reponse.get(cle_texte)
        if isinstance(v, str):
            return v, ""
    return "", "aucun texte dans la reponse (cles : %s)" % ",".join(sorted(reponse))[:120]


def sonder_competence_cli(provider: str, ask_fn=None, taches=TACHES_COMPETENCE, timeout: int = 180) -> dict:
    """Les taches fixes jouees par un CLI via `ask` (sans contexte RAG, sans bascule). Echec d'appel = None."""
    import asyncio
    import time as _t

    if ask_fn is None:
        from nokido_agent.app.forge_agent_proxy import ask as _ask

        def ask_fn(p, prompt):
            return asyncio.run(_ask(p, prompt, rag_context=False, max_tokens=400, timeout=timeout, _bascule=False))
    detail, raisons, lat = {}, {}, []
    for nom, prompt, correcteur in taches:
        t0 = _t.time()
        try:
            texte, erreur = _texte_de(ask_fn(provider, prompt))
        except Exception as exc:  # noqa: BLE001 - un appel qui leve n'est pas une tache ratee : INCONNU, dit
            texte, erreur = "", "%s: %s" % (type(exc).__name__, str(exc)[:140])
        if erreur:
            detail[nom], raisons[nom] = None, erreur
            continue
        detail[nom] = bool(correcteur(texte))
        lat.append(round((_t.time() - t0) * 1000))
    mesurees = [v for v in detail.values() if v is not None]
    return {"reussies": sum(mesurees), "mesurees": len(mesurees), "total": len(taches),
            "score": round(sum(mesurees) / len(mesurees), 2) if mesurees else None, "taches": detail,
            "raisons_non_mesurees": raisons, "latence_ms_mediane": sorted(lat)[len(lat) // 2] if lat else None}


def construire_matrice(familles=FAMILLES_UTILES, get_secret=None, interroger_fn=None, sonder_fn=None,
                       par_famille_max: int = 3, competence: bool = False, competence_fn=None) -> dict:
    """Pour chaque fournisseur a cle presente : /models -> couples (famille, modele) ; puis une generation
    par couple d'une famille utile (au plus `par_famille_max` modeles par famille et fournisseur)."""
    import time as _t

    if get_secret is None:
        from nokido_agent.app.forge_secrets import get_secret
    interroger_fn = interroger_fn or interroger
    sonder_fn = sonder_fn or sonder_generation
    voulues = set(familles)
    out = {"mesure_le": _t.strftime("%Y-%m-%dT%H:%M:%S"), "familles": {}, "fournisseurs": {}}
    for etiquette, env_key, url in FOURNISSEURS:
        if etiquette in SANS_GENERATION or "127.0.0.1" in url or "localhost" in url:
            continue
        cle = get_secret(env_key) if env_key else ""
        if not cle:
            out["fournisseurs"][etiquette] = "CLE_ABSENTE"
            continue
        code, ids, detail = interroger_fn(url, cle)
        if code != 200:
            out["fournisseurs"][etiquette] = "MODELS_%s" % code
            continue
        out["fournisseurs"][etiquette] = "MODELS_200 (%d)" % len(ids)
        vus: dict = {}
        for mid in ids:
            f = famille_de(mid)
            if f in voulues and len(vus.setdefault(f, [])) < par_famille_max:
                vus[f].append(mid)
        for f, mids in vus.items():
            for mid in mids:
                c, d, lat = sonder_fn(url, cle, mid)
                voie = {"fournisseur": etiquette, "modele": mid, "etat": classer_reponse(c, d),
                        "code": c, "latence_ms": lat, "detail": d[:120]}
                if competence and voie["etat"] == "JOIGNABLE":
                    voie["competence"] = (competence_fn or sonder_competence)(url, cle, mid)
                    reclasser_par_competence(voie)
                out["familles"].setdefault(f, []).append(voie)
    for f in out["familles"]:
        out["familles"][f].sort(key=lambda v: (v["etat"] != "JOIGNABLE", v["latence_ms"]))
    return out


def ecrire_matrice(m: dict) -> bool:
    try:
        MATRICE.parent.mkdir(parents=True, exist_ok=True)
        tmp = MATRICE.with_suffix(".tmp")
        tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        import os as _os

        _os.replace(tmp, MATRICE)
        return True
    except OSError:
        return False


def voies_joignables(famille: str, age_max_j: float = 7.0) -> dict:
    """{"voies": [(fournisseur, modele, latence_ms)], "etat": ...} pour une famille. Matrice absente,
    illisible ou plus vieille que `age_max_j` : etat INCONNU / PERIMEE, jamais « aucune voie »."""
    import time as _t

    try:
        m = json.loads(MATRICE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"voies": [], "etat": "INCONNU", "raison": "matrice jamais mesuree"}
    except (OSError, ValueError):
        return {"voies": [], "etat": "INCONNU", "raison": "matrice illisible"}
    try:
        age_j = (_t.time() - _t.mktime(_t.strptime(m.get("mesure_le", ""), "%Y-%m-%dT%H:%M:%S"))) / 86400
    except (ValueError, OverflowError):
        age_j = None
    voies = [(v["fournisseur"], v["modele"], v["latence_ms"]) for v in m.get("familles", {}).get(famille_de(famille), [])
             if v.get("etat") == "JOIGNABLE"]
    # 19/10 (convergence census -> matrice) : un couple que le registre free tier PROUVE mort depuis la mesure est
    # ecarte et NOMME -- meme contrat que le routeur. Census illisible : rien d'ecarte, et c'est dit.
    try:
        from nokido_agent.app.forge_llm_router import injoignables_prouves
        morts, census = injoignables_prouves(), "lu"
    except Exception:  # noqa: BLE001 - UNKNOWN n'est pas NO : on garde les voies, on le dit
        morts, census = set(), "illisible"
    ecartees = ["%s:%s" % (f, mo) for f, mo, _ in voies if "%s:%s" % (f, mo) in morts]
    voies = [v for v in voies if "%s:%s" % (v[0], v[1]) not in morts]
    etat = "PERIMEE" if age_j is None or age_j > age_max_j else ("MESUREE" if voies else "AUCUNE_VOIE_MESUREE")
    return {"voies": voies, "etat": etat, "age_j": None if age_j is None else round(age_j, 2),
            "census": census, "ecartees_census": ecartees}


def candidates_du_clair(etiquette: str, env_key: str) -> list[tuple[int, str]]:
    """[(ligne, valeur)] du `.env` pour cette cle — commentees COMPRISES.

    Une cle fraichement collee se retrouve souvent derriere un `#` (ligne
    d'exemple reutilisee) ou sous un nom voisin. La tester AVANT de l'ecrire au
    coffre evite d'ecraser une entree valide par une valeur qu'on n'a pas
    verifiee — faute payee le 2026-08-18.
    """
    out: list[tuple[int, str]] = []
    for nom_fichier in ("Nokido.env", "nokido.env"):
        chemin = ROOT / nom_fichier
        if not chemin.exists():
            continue
        for i, ligne in enumerate(chemin.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            s = ligne.strip().lstrip("#").strip()
            if "=" not in s:
                continue
            cle, _, val = s.partition("=")
            cle, val = cle.strip(), val.strip()
            if val and (cle == env_key or etiquette.upper() in cle.upper()):
                out.append((i, val))
        break
    return out


def main() -> int:
    from nokido_agent.app.forge_secrets import get_secret

    if "--matrice" in sys.argv:
        m = construire_matrice(competence="--competence" in sys.argv)
        if "--cli" in sys.argv:
            i = sys.argv.index("--cli")
            noms = sys.argv[i + 1].split(",") if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--") \
                else list(CLI_PAR_DEFAUT)
            m["cli"] = {p.strip(): sonder_competence_cli(p.strip()) for p in noms if p.strip()}
            for p, c in m["cli"].items():
                print(f"cli {p:12} : {c['reussies']}/{c['mesurees']} mesurees (sur {c['total']}) {c['taches']} "
                      f"{('non mesurees : ' + str(c['raisons_non_mesurees'])[:200]) if c['raisons_non_mesurees'] else ''}")
        ok = ecrire_matrice(m)
        for f, voies in sorted(m["familles"].items()):
            j = [v for v in voies if v["etat"] == "JOIGNABLE"]
            print(f"{f:16} {len(j)}/{len(voies)} joignable(s) : "
                  + ", ".join(f"{v['fournisseur']}:{v['modele']} {v['etat']}" for v in voies)[:400])
            for v in j:
                c = v.get("competence")
                if c:
                    print(f"    competence {v['fournisseur']}:{v['modele']} : {c['reussies']}/{c['mesurees']} "
                          f"mesurees (sur {c['total']}) {c['taches']} mediane {c['latence_ms_mediane']} ms")
        print("fournisseurs :", json.dumps(m["fournisseurs"], ensure_ascii=False))
        print(f"matrice {'ecrite' if ok else 'NON ECRITE'} : {MATRICE}")
        print("Aucune cle n'a ete affichee.")
        return 0 if ok else 1
    cables = modeles_cables()
    if "--depuis-env" in sys.argv:
        print("=== candidates trouvees en clair (coffre NON modifie) ===")
        for etiquette, env_key, url in FOURNISSEURS:
            au_coffre = get_secret(env_key) or ""
            for ligne, val in candidates_du_clair(etiquette, env_key):
                if val == au_coffre:
                    print(f"  {etiquette:11} L{ligne:<5} {_suffixe(val)} — deja au coffre")
                    continue
                code, ids, detail = interroger(url, val)
                verdict = f"{len(ids)} modele(s)" if code == 200 else detail[:90]
                print(f"  {etiquette:11} L{ligne:<5} {_suffixe(val)} — HTTP {code} — {verdict}")
        print()
    for etiquette, env_key, url in FOURNISSEURS:
        local = "127.0.0.1" in url
        cle = (get_secret(env_key) or "") if env_key else ""
        if not cle and not local:
            print(f"\n=== {etiquette} — cle {env_key} ABSENTE du coffre : NON MESURE")
            continue
        code, ids, detail = interroger(url, cle)
        print(f"\n=== {etiquette} (cle {_suffixe(cle)}) — HTTP {code} — "
              f"{len(ids)} modele(s)")
        if code != 200:
            print(f"    {detail}")
            print("    -> 401/403 accuse la CLE ; 404 accuse l'URL ; -1 = non mesure")
            continue
        if etiquette in MODELS_PUBLIC:
            # MESURE 2026-10-15 : SambaNova et OpenRouter servent /models SANS cle (HTTP 200).
            # La cle SambaNova (…652c) obtenait 200 ici ET 401 invalid_api_key a la generation.
            # Ce 200 ne prouve donc RIEN de la cle : ni « elle vit », ni rearmement.
            print(f"    ⚠ /models est PUBLIC chez {etiquette} (200 sans cle) : ce 200 ne prouve PAS "
                  "la cle -- seul un appel authentifie (generation) tranche ; aucun rearmement")
        elif "--rearmer" in sys.argv:
            # Un 200 sur /models est la PREUVE que la cle vit. La rotation avait
            # pu l'ecarter pour un 403 qui visait en realite un modele retire :
            # ce qui innocente doit pouvoir lever la peine.
            try:
                from nokido_agent.app.forge_key_rotation import mark

                mark(env_key, cle, "ok", "catalogue /models 200")
                print(f"    [rotation] {env_key} rearmee (preuve : /models 200)")
            except Exception as exc:  # noqa: BLE001 - module absent
                print(f"    [rotation] rearmement impossible ({type(exc).__name__})")
        # Comparaison INSENSIBLE au suffixe de routage et au prefixe d'organisation.
        # Mesure 2026-09-03 : `Qwen/Qwen2.5-Coder-32B-Instruct:novita` etait declare
        # ABSENT alors que le catalogue HF porte le meme modele — `:novita` designe
        # le FOURNISSEUR d'inference, pas un autre modele. Une comparaison litterale
        # transforme une convention de nommage en panne imaginaire, et pousse a
        # debrancher ce qui marche.
        def _noyau(nom: str) -> str:
            return nom.split(":", 1)[0].split("/", 1)[-1].strip().lower()

        _index = {}
        for i in ids:
            _index.setdefault(_noyau(i), i)
        demandes = [m.split("/", 1)[-1] for m in cables.get(etiquette, [])]
        for m in demandes:
            trouve = m in ids or _noyau(m) in _index
            note = ""
            if trouve and m not in ids:
                note = "  (via %s)" % _index[_noyau(m)]
            # « ABSENT DE /models » n'est PAS « inexistant ». Mesure 2026-09-03 :
            # `mistral-large-latest` ne figure pas dans /models et rend pourtant
            # un 403 `tier_not_allowed` a l'appel — le modele EXISTE, il est hors
            # souscription. Il redeviendra disponible si le tier change : le
            # signaler, le faire SKIPPER par la rotation, jamais le debrancher.
            etat = "OK" if trouve else "ABSENT DE /models (verifier par un appel :"\
                                       " peut etre hors souscription)"
            print(f"    cable  {m:44} {etat}{note}")
        _noyaux_demandes = {_noyau(m) for m in demandes}
        libres = [i for i in ids if i not in demandes and _noyau(i) not in _noyaux_demandes]
        if libres:
            print(f"    disponibles non cables ({len(libres)}) : {', '.join(libres[:12])}")
    print("\n--- hors perimetre de cette sonde (nommes, pas oublies) ---")
    for nom, motif in sorted(HORS_PERIMETRE.items()):
        print(f"  {nom:26} {motif}")
    print("\nAucune cle n'a ete affichee (suffixe de 4 caracteres seulement).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
