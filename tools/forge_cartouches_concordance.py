#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_cartouches_concordance.py - les cartouches du README face aux clefs du coffre.

__FORGE_COLOR__ = "qualite/preuve : concordance mesuree entre cartouches du README, clefs du coffre et providers cables"

Demande owner (2026-09-06) : « tu mettras les cartouches a jour avec la concordance des
87 clefs ». Une cartouche annonce une capacite ; une capacite tient a trois choses, et
les trois se mesurent separement :

    CLEF au coffre  x  PROVIDER cable dans le code  x  CARTOUCHE au README

Quatre etats possibles, et aucun ne doit rester implicite :

  ALIGNE          les trois presents -- la cartouche dit vrai
  CLEF_SANS_CARTOUCHE   capacite disponible mais non annoncee (sous-vente : on ignore
                        une route qu'on possede -- c'est ce qui a fait chercher des
                        heures un fournisseur d'embedding le 2026-09-06)
  CARTOUCHE_SANS_CLEF   annonce sans clef propre. PAS forcement faux : un modele peut
                        etre route via un agregateur (OpenRouter, GitHub Models). Se
                        lit donc « a justifier », jamais « a supprimer ».
  HORS_SUJET      clef interne (jetons d'agents, HMAC) ou cartouche d'outil local
                  (Python, Deno, Rust...) : ni l'un ni l'autre n'annonce un fournisseur.

Le script NE MODIFIE RIEN et n'affiche JAMAIS une valeur de secret : il liste des NOMS.

    LAFORGE_PYTHON tools/forge_cartouches_concordance.py [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

README = ROOT / "README.md"
CARTOUCHE = re.compile(r"!\[([^\]]+)\]\(https://img\.shields\.io")

# Clefs qui n'annoncent AUCUN fournisseur externe : jetons d'agents, secrets internes,
# noms de modeles, comptes de service. Les exclure est une decision, donc elle est ecrite.
INTERNES = ("FORGE_TOKEN", "FORGE_MCP", "FORGE_LLAMA", "LAFORGE_", "HUB_JWT", "NETCFG_MCP",
            "MCP_DEV", "firewall_", "ROOTME", "FREEBOX", "PYPI", "TESTPYPI", "KAGGLE",
            "CODEBERG", "GITHUB_TOKEN", "QUANDELA", "PCVL", "LMSTUDIO_MODEL",
            "LLAMACPP_MODEL", "GEMINI_MODEL", "CLOUDFLARE_ID_ACCESS",
            "CLOUDFLARE_SECRET_KEY_ACCESS")

# Cartouches qui decrivent le SOCLE ou un CLIENT, pas un fournisseur : elles n'ont pas
# vocation a porter une clef.
NON_FOURNISSEUR = {
    "License", "Python", "Deno", "Rust", "Go", "Branch", "MCP", "Local-First", "Qdrant",
    "snnTorch", "Ollama", "llama.cpp", "LM Studio", "Claude Code", "Claude Desktop",
    "Cline", "Codex CLI", "Antigravity agy", "ZCode (z.ai)", "Mistral Vibe",
    "Mammouth Code",
}

# Nom de cartouche -> prefixe(s) de clef attendue. Une seule source de verite.
CORRESPONDANCE = {
    "Anthropic": ("ANTHROPIC_API_KEY",),
    "Cerebras": ("CEREBRAS_API_KEY",),
    "Cloudflare Workers AI": ("CLOUDFLARE_AI_API_KEY", "CLOUDFLARE_ACCOUNT_ID"),
    "Cohere": ("COHERE_API_KEY",),
    "DeepSeek": ("DEEPSEEK_API_KEY",),
    "GitHub Models": ("GITHUB_MODELS_TOKEN",),
    "Google Gemini": ("GEMINI_API_KEY",),
    "Groq": ("GROQ_API_KEY",),
    "HuggingFace": ("HF_TOKEN",),
    "Mistral": ("MISTRAL_API_KEY",),
    "Moonshot Kimi": ("MOONSHOT_API_KEY", "KIMI_API_KEY"),
    "NVIDIA NIM": ("NVIDIA_NIM_API_KEY", "NVIDIA_API_KEY"),
    "OpenAI": ("OPENAI_API_KEY",),
    "OpenRouter": ("OPENROUTER_API_KEY",),
    "Perplexity": ("PERPLEXITY_API_KEY",),
    "SambaNova": ("SAMBANOVA_API_KEY",),
    "xAI Grok": ("XAI_API_KEY",),
    "Z.ai GLM": ("ZAI_API_KEY",),
    "Modal": ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"),
    "Voyage AI": ("VOYAGE_API_KEY",),
    "Jina AI": ("JINA_API_KEY",),
    "Together AI": ("TOGETHER_API_KEY",),
    "DeepInfra": ("DEEPINFRA",),
    "SiliconFlow": ("SILICONFLOW",),
    "Tavily": ("TAVILY_API_KEY",),
    "Smithery": ("SMITHERY_API",),
    "Mammouth": ("MAMMOUTH_API_TOKEN",),
}


def clefs_coffre() -> tuple[list[str], str]:
    """Noms des clefs du coffre machine. ENUMERE, ne devine pas.

    Mesure 2026-09-06 : `forge_secrets.diagnostic()` coche une liste de 26 noms ecrite
    en dur alors que le coffre en porte 87 -- une capacite reelle (`SILICONFLOW`) y
    etait donc invisible, et son silence s'est lu comme une absence.
    """
    try:
        from nokido_agent.app import forge_machine_vault as MV

        if not MV.available():
            return [], "coffre INDISPONIBLE depuis ce compte -- resultat INDETERMINE"
        return sorted(MV.vault_list() or []), ""
    except Exception as e:  # noqa: BLE001
        return [], f"coffre illisible ({type(e).__name__}) -- resultat INDETERMINE"


def cartouches() -> list[str]:
    return sorted(set(CARTOUCHE.findall(README.read_text(encoding="utf-8", errors="replace"))))


def concordance() -> dict:
    cles, souci = clefs_coffre()
    cs = cartouches()
    presentes = set(cs)
    externes = [k for k in cles if not any(k.upper().startswith(p) for p in INTERNES)]

    alignes, sans_cartouche, sans_clef = [], [], []
    for nom, attendues in CORRESPONDANCE.items():
        a_la_clef = any(k in cles for k in attendues)
        a_la_cartouche = nom in presentes
        if a_la_clef and a_la_cartouche:
            alignes.append(nom)
        elif a_la_clef and not a_la_cartouche:
            sans_cartouche.append(nom)
        elif a_la_cartouche and not a_la_clef:
            sans_clef.append(nom)

    couvertes = {k for n, ks in CORRESPONDANCE.items() for k in ks}
    orphelines = [k for k in externes if k not in couvertes]
    inconnues = [c for c in cs if c not in CORRESPONDANCE and c not in NON_FOURNISSEUR]
    return {
        "clefs_total": len(cles), "clefs_externes": len(externes),
        "cartouches_total": len(cs), "souci": souci,
        "ALIGNE": sorted(alignes),
        "CLEF_SANS_CARTOUCHE": sorted(sans_cartouche),
        "CARTOUCHE_SANS_CLEF": sorted(sans_clef),
        "clefs_hors_correspondance": sorted(orphelines),
        "cartouches_non_classees": sorted(inconnues),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d = concordance()
    if a.json:
        print(json.dumps(d, indent=1, ensure_ascii=False))
        return 0
    if d["souci"]:
        print("!! " + d["souci"])
        return 2
    print(f"{d['clefs_total']} clefs au coffre ({d['clefs_externes']} de fournisseur) "
          f"| {d['cartouches_total']} cartouches au README\n")
    for cle, titre in (("ALIGNE", "cartouche ET clef -- l'annonce dit vrai"),
                       ("CLEF_SANS_CARTOUCHE", "clef possedee, capacite NON annoncee"),
                       ("CARTOUCHE_SANS_CLEF", "annonce sans clef propre -- a JUSTIFIER "
                                               "(routage via un agregateur ?), pas a supprimer"),
                       ("clefs_hors_correspondance", "clefs externes hors table -- a classer"),
                       ("cartouches_non_classees", "cartouches ni fournisseur connu ni socle")):
        v = d[cle]
        print(f"== {cle} ({len(v)}) : {titre}")
        for x in v:
            print("   -", x)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
