#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lever les serveurs LLM LOCAUX, puis les prouver — pas les promettre.

Trois surfaces locales etaient annoncees mortes sans qu'on sache si elles
etaient absentes, arretees, ou simplement mal sondees : LM Studio (:1234),
llama.cpp (:8080), LiteLLM (:4000). Ce module fait la chaine complete pour
chacune : port deja ouvert ? sinon LANCER, attendre, puis `/v1/models` ET une
COMPLETION reelle. Un service qui ecoute mais ne complete pas n'est pas pret.

TROIS ETATS, jamais deux : VIVANT (a complete), MORT (a refuse, avec le
message), NON_MESURE (binaire introuvable, ACL, budget) — parce qu'un binaire
qu'on ne SAIT pas trouver n'est pas un binaire absent. Mesure du 2026-08-18 :
les comptes sandbox ne lisent pas `%USERPROFILE%\\`, ce qui faisait
rapporter « modele absent » pour des fichiers bien presents.

A LANCER EN JOB DETACHE — jamais en appel synchrone : demarrer un serveur et
attendre son port depasse largement le cap de l'event loop du hub, et c'est
ainsi que le hub est mort deux fois (17 et 18 aout).

    run action=run_job script=tools/forge_local_llm_bringup.py online=true
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nokido_agent.tools.forge_endpoint_commun import lire, taille_apparente  # noqa: E402

# Alias : le socle porte le geste, ce module garde son vocabulaire.
_taille_apparente = taille_apparente

PROFIL = Path(os.environ.get("NOKIDO_OWNER_HOME", r"%USERPROFILE%"))
SORTIE = ROOT / "sandbox" / "local_llm_bringup.json"
def _attente_max() -> int:
    """`--attente N`. Le canal privilegie est coupe a 120 s et un depassement
    synchrone a tue le hub les 17 et 18 aout : on borne, on ne parie pas."""
    for i, a in enumerate(sys.argv):
        if a == "--attente" and i + 1 < len(sys.argv):
            try:
                return max(5, int(sys.argv[i + 1]))
            except ValueError:
                break
    return 90


ATTENTE_MAX = 90          # defaut ; voir _attente_max() pour la valeur effective
CONFIG_LITELLM = ROOT / "sandbox" / "litellm_nokido.yaml"


def _get(url: str, timeout: float = 5.0, cle: str = "") -> tuple[int, str]:
    code, corps, _entetes = lire(url, cle, timeout=int(timeout))
    return code, corps


def _post(url: str, charge: dict, timeout: float = 60.0, cle: str = "") -> tuple[int, str]:
    code, corps, _entetes = lire(url, cle, json.dumps(charge).encode("utf-8"),
                                 timeout=int(timeout))
    return code, corps


def port_ouvert(url_models: str, cle: str = "") -> bool:
    return _get(url_models, timeout=3.0, cle=cle)[0] == 200


def attendre(url_models: str, secondes: int, cle: str = "") -> bool:
    fin = time.time() + secondes
    while time.time() < fin:
        if port_ouvert(url_models, cle):
            return True
        time.sleep(3)
    return False


def _lancer(argv: list[str], cwd: str | None = None, nom: str = "service") -> tuple[bool, str]:
    """Detache — mais JAMAIS muet.

    Premiere version : `stdout=DEVNULL`. llama-server s'est alors lance sans
    ouvrir son port, avec 133 Mo de RSS au lieu des ~4,5 Go d'un 7B charge, et
    il etait impossible de savoir POURQUOI : sa sortie avait ete jetee. « Mort
    sans rien ecrire » est un diagnostic qu'on s'inflige soi-meme. La sortie va
    desormais dans sandbox/, ou on peut la lire.
    """
    journal = ROOT / "sandbox" / f"{nom}_server.log"
    try:
        journal.parent.mkdir(parents=True, exist_ok=True)
        flux = open(journal, "a", encoding="utf-8", errors="replace")
    except OSError:
        flux = subprocess.DEVNULL
    try:
        drapeaux = 0
        if os.name == "nt":
            drapeaux = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "DETACHED_PROCESS", 8)
        subprocess.Popen(argv, cwd=cwd, creationflags=drapeaux,
                         stdout=flux, stderr=subprocess.STDOUT)
        return True, f"journal : sandbox/{nom}_server.log"
    except FileNotFoundError:
        return False, "binaire introuvable"
    except PermissionError as exc:
        return False, f"ACL : {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"[:120]


# Un modele de RAISONNEMENT (r1, -think…) place sa sortie dans un champ
# `reasoning` et laisse `content` VIDE quand la limite de tokens est courte : on
# le compterait mort alors qu'il repond. Meme piege que `openai/gpt-oss` chez
# Groq. Les embeddings et l'audio n'ont pas de `chat/completions` du tout.
_INADAPTES = ("r1", "think", "reason", "embed", "bge-", "nomic", "whisper",
              "guard", "tts", "clip", "moondream", "llava")


def _premier_modele(corps: str) -> str:
    """Le modele INSTRUCT le plus LEGER du catalogue.

    MESURE 2026-08-18 : prouver qu'un service repond avec un 7B a froid demande
    plus de 240 s (relecture disque, RAM sous pression) et le faisait compter
    NON_MESURE ; le meme service repond en 4,3 s avec un 1.5B. On cherche ici
    une preuve de VIE, pas un banc d'essai : le plus petit suffit et ne ment pas.
    """
    try:
        donnees = json.loads(corps).get("data") or []
    except Exception:  # noqa: BLE001 - corps non JSON
        return ""
    ids = [str(m.get("id")) for m in donnees if isinstance(m, dict) and m.get("id")]
    utiles = [i for i in ids if not any(mot in i.lower() for mot in _INADAPTES)]
    if utiles:
        return sorted(utiles, key=_taille_apparente)[0]
    return ids[0] if ids else ""


def completer(base: str, modele: str, cle: str = "") -> tuple[bool, str]:
    """La preuve : une completion reelle, pas un port qui repond.

    TIMEOUT GENEREUX, et c'est mesure : un 7B qu'Ollama doit charger depuis le
    disque met plusieurs minutes au premier appel. A 60 s, Ollama et LiteLLM
    rendaient `TimeoutError` et se faisaient compter MORTS — alors que LiteLLM
    avait repondu « pret » vingt minutes plus tot, modele encore chaud. Un
    chargement n'est pas une panne : il est classe NON_MESURE.
    """
    code, corps = _post(f"{base}/chat/completions", {
        "model": modele,
        "messages": [{"role": "user", "content": "Reponds par le seul mot: pret"}],
        "max_tokens": 16,
    }, timeout=240.0, cle=cle)
    if code == -1 and "Timeout" in corps:
        return False, "SONDE INADAPTEE (240s sans reponse : chargement du modele ?)"
    if code != 200:
        return False, f"HTTP {code} — {corps[:150]}"
    try:
        choix = (json.loads(corps).get("choices") or [{}])[0]
        texte = (choix.get("message") or {}).get("content") or ""
        return bool(texte.strip()), texte.strip()[:60] or "reponse vide"
    except Exception as exc:  # noqa: BLE001
        return False, f"reponse illisible ({type(exc).__name__})"


def bringup(nom: str, base: str, argv: list[str] | None, cle: str = "",
            cwd: str | None = None) -> dict:
    url_models = f"{base}/models"
    fiche = {"service": nom, "base": base, "lance": False}
    if not port_ouvert(url_models, cle):
        if not argv:
            fiche.update(etat="NON_MESURE", motif="aucune commande de lancement connue")
            return fiche
        ok, motif = _lancer(argv, cwd, nom)
        fiche["lance"] = ok
        fiche["journal"] = motif
        if not ok:
            fiche.update(etat="NON_MESURE", motif=f"lancement impossible ({motif})")
            return fiche
        budget = _attente_max()
        if not attendre(url_models, budget, cle):
            # Un serveur qui charge encore n'est pas un serveur mort.
            fiche.update(etat="NON_MESURE",
                         motif=f"port encore muet apres {budget}s (chargement ?)")
            return fiche
    code, corps = _get(url_models, cle=cle)
    modele = _premier_modele(corps)
    if not modele:
        fiche.update(etat="MORT", motif=f"/models HTTP {code} sans aucun modele")
        return fiche
    fiche["modele"] = modele
    ok, detail = completer(base, modele, cle)
    etat = "VIVANT" if ok else ("NON_MESURE" if detail.startswith("SONDE INADAPTEE") else "MORT")
    fiche.update(etat=etat, motif=detail)
    return fiche


def _ecrire_config_litellm() -> Path:
    """Proxy minimal vers Ollama — le seul local prouve vivant aujourd'hui."""
    CONFIG_LITELLM.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_LITELLM.write_text(
        "model_list:\n"
        "  - model_name: local-qwen\n"
        "    litellm_params:\n"
        # 1.5B : le proxy doit prouver qu'il ROUTE, pas endurer le chargement
        # d'un 7B (>240 s a froid) qu'on lirait ensuite comme une panne.
        "      model: ollama/qwen2.5-coder:1.5b\n"
        "      api_base: http://127.0.0.1:11434\n",
        encoding="utf-8")
    return CONFIG_LITELLM


def main() -> int:
    if "--inventaire" in sys.argv:
        # Lecture seule : quel compte VOIT quoi. Les comptes sandbox ne lisent
        # pas le profil owner, et un binaire invisible n'est pas un binaire
        # absent — la distinction decide qui doit lancer quoi.
        print(f"compte : {os.environ.get('USERNAME', '?')}")
        for chemin in (PROFIL / ".lmstudio" / "bin" / "lms.exe",
                       PROFIL / "AppData" / "Local" / "Programs" / "LM Studio" / "LM Studio.exe",
                       PROFIL / "llama-vulkan" / "llama-server.exe",
                       PROFIL / "llama-vulkan" / "models" / "qwen2.5-coder-7b-q4km.gguf",
                       PROFIL / "models" / "gemma4" / "gemma-4-E4B-it-Q4_K_M.gguf",
                       PROFIL / "miniforge3" / "Scripts" / "litellm.exe"):
            try:
                vu = chemin.exists()
            except OSError as exc:
                vu = f"ACL ({type(exc).__name__})"
            print(f"  {str(chemin)[:78]:80} {vu}")
        return 0

    lms = PROFIL / ".lmstudio" / "bin" / "lms.exe"
    llama = PROFIL / "llama-vulkan" / "llama-server.exe"
    modele_gguf = PROFIL / "llama-vulkan" / "models" / "qwen2.5-coder-7b-q4km.gguf"
    litellm_exe = PROFIL / "miniforge3" / "Scripts" / "litellm.exe"

    # LM Studio rend 401 sans jeton : sans cette lecture, on le declarerait MORT
    # alors qu'il repond parfaitement (mesure 2026-08-18, 5 modeles).
    try:
        from nokido_agent.app.forge_secrets import get_secret

        cle_lms = get_secret("LMSTUDIO_TOKEN") or ""
    except Exception:  # noqa: BLE001 - facade indisponible
        cle_lms = ""

    # Les URLs viennent de la TABLE DU ROUTEUR, jamais d'une valeur devinee.
    # MESURE 2026-08-18 : j'avais code 8080 puis 8081 en dur alors que
    # `llamacpp_local` declare 8091. Resultat : un service parfaitement vivant
    # compte pour mort, puis un second lancement sur le meme port a provoque
    # `Errno 10048` et TUE celui qui tournait. Deviner un port coute un service.
    def _url(slot: str, defaut: str) -> str:
        try:
            from nokido_agent.app.forge_llm_router import PROVIDERS

            brut = (PROVIDERS.get(slot) or {}).get("base_url") or defaut
        except Exception:  # noqa: BLE001 - routeur indisponible
            brut = defaut
        brut = brut.rstrip("/")
        return brut if brut.endswith("/v1") else brut + "/v1"

    url_llamacpp = _url("llamacpp_local", "http://127.0.0.1:8091/v1")
    port_llamacpp = url_llamacpp.rsplit(":", 1)[-1].split("/")[0]

    cibles = [
        ("ollama", _url("ollama_local", "http://127.0.0.1:11434/v1"), None, ""),
        ("lmstudio", _url("lmstudio_native", "http://127.0.0.1:1234/v1"),
         [str(lms), "server", "start"] if lms.exists() else None, cle_lms),
        ("llamacpp", url_llamacpp,
         [str(llama), "-m", str(modele_gguf), "--port", port_llamacpp, "-c", "4096"]
         if llama.exists() and modele_gguf.exists() else None, ""),
        ("litellm", "http://127.0.0.1:4000/v1",
         [str(litellm_exe), "--config", str(_ecrire_config_litellm()), "--port", "4000"]
         if litellm_exe.exists() else None, ""),
    ]

    print(f"compte d'execution : {os.environ.get('USERNAME', '?')} — "
          f"profil sonde : {PROFIL}")
    for nom, _b, argv, _c in cibles:
        if argv is None and nom != "ollama":
            print(f"  [{nom}] binaire introuvable DEPUIS CE COMPTE — NON_MESURE, "
                  f"pas 'absent' (les comptes sandbox ne lisent pas le profil owner)")

    for nom, base, _a, cle in cibles:
        if cle:
            print(f"  [{nom}] jeton lu au coffre (sans lui : 401)")
    fiches = [bringup(n, b, a, c) for n, b, a, c in cibles]
    print(f"\n{'service':12} {'etat':12} {'modele':34} motif")
    for f in fiches:
        print(f"  {f['service']:10} {f['etat']:12} {f.get('modele', '-')[:32]:34} {f['motif'][:80]}")
    vivants = [f["service"] for f in fiches if f["etat"] == "VIVANT"]
    print(f"\nVIVANTS (completion reelle) : {', '.join(vivants) or 'aucun'}")
    try:
        SORTIE.parent.mkdir(parents=True, exist_ok=True)
        SORTIE.write_text(json.dumps({"fiches": fiches}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
        print(f"detail : {SORTIE.relative_to(ROOT)}")
    except OSError as exc:
        print(f"(rapport non ecrit : {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
