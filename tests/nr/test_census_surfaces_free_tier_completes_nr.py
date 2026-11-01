# -*- coding: utf-8 -*-
"""NR -- le census joint les free tiers ajoutes le 30/10 (owner « ABSOLUMENT tous les free tiers »).

Rendu MISTRAL 5345fc8af integre : 15 surfaces au catalogue (forge_provider_catalogue.FOURNISSEURS), URL alignees
sur la convention `.../models` (une base sans suffixe aurait fait lire le mauvais chemin), aucun `<id>` litteral.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_provider_catalogue as P  # noqa: E402

pytestmark = pytest.mark.timeout(60)
ATTENDUS = {"gemini": "GEMINI_API_KEY", "codestral": "CODESTRAL_API_KEY", "github_models": "GITHUB_MODELS_TOKEN",
            "kimi": "KIMI_API_KEY", "fireworks": "FIREWORKS_API_KEY", "chutes": "CHUTES_API_KEY",
            "scaleway": "SCALEWAY_SECRET_KEY", "nebius": "NEBIUS_API_KEY", "hyperbolic": "HYPERBOLIC_API_KEY",
            "novita": "NOVITA_API_KEY", "dashscope": "DASHSCOPE_API_KEY", "opencode_zen": "OPENCODE_API_KEY",
            "llama_api": "LLAMA_API_KEY", "kluster": "KLUSTER_API_KEY", "pollinations": "",
            "stepfun": "STEPFUN_API_KEY", "poolside": "POOLSIDE_API_KEY", "regolo": "REGOLO_API_KEY",
            "writer": "WRITER_API_KEY", "clarifai": "CLARIFAI_PAT", "inception": "INCEPTION_API_KEY",
            "reka": "REKA_API_KEY", "nous": "NOUS_API_KEY"}


def test_chaque_free_tier_est_au_catalogue_avec_sa_cle():
    par_nom = {e[0]: e for e in P.FOURNISSEURS}
    for nom, cle in ATTENDUS.items():
        assert nom in par_nom, nom
        assert par_nom[nom][1] == cle, (nom, par_nom[nom][1])


def test_convention_models_et_aucun_gabarit_litteral():
    for nom, _cle, url in P.FOURNISSEURS:
        if nom in ATTENDUS:
            assert url.endswith("/models"), (nom, url)
            assert "<" not in url and ">" not in url, (nom, url)
