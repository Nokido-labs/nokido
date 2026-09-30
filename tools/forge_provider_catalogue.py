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
        if "--rearmer" in sys.argv:
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
