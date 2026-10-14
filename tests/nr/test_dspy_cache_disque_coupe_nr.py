# -*- coding: utf-8 -*-
"""NR — le routeur dspy coupe le cache DISQUE de dspy, et un `import dspy` hors ligne ne le tue pas.

__FORGE_COLOR__ = "immunitaire/guard : non-regression du cache disque dspy coupe (diskcache sans correctif)"

CE QUI A ÉTÉ PAYÉ (2026-10-12). `diskcache` 5.6.3 (GHSA-w8v5-vhqr-4h9v) dépique ce qu'il trouve dans son dossier,
et AUCUNE version corrigée n'est publiée ; dspy l'exige (3.4.0 encore) et ouvre par défaut un cache disque
`~/.dspy_cache`. `app/forge_dspy_router.py` n'utilise dspy que pour ses Signatures (l'appel LLM passe par le hub) :
le cache disque n'a aucun usage, il est coupé à l'import. Sondé le même jour : hors ligne, `import dspy` mourait en
`ConnectionError` (tiktoken chargé à l'import par litellm) -- hors du garde `except ImportError` d'alors.

Les deux tests passent par un FAUX module `dspy` : ils ne dépendent ni du réseau ni du cache tiktoken (hors dépôt).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "app" / "forge_dspy_router.py"


def _charger(monkeypatch, faux_dspy):
    """Importe le module DEPUIS SON FICHIER, avec `dspy` remplace (objet module, ou exception a lever)."""
    if isinstance(faux_dspy, BaseException):
        class _Chercheur:
            def find_spec(self, nom, chemin=None, cible=None):
                if nom == "dspy":
                    raise faux_dspy
                return None

        monkeypatch.delitem(sys.modules, "dspy", raising=False)
        monkeypatch.setattr(sys, "meta_path", [_Chercheur()] + sys.meta_path)
    else:
        monkeypatch.setitem(sys.modules, "dspy", faux_dspy)
    spec = importlib.util.spec_from_file_location("forge_dspy_router_nr", MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _faux_dspy(appels: list):
    d = types.ModuleType("dspy")

    class Signature:
        pass

    d.Signature = Signature
    d.InputField = lambda **k: None
    d.OutputField = lambda **k: None
    d.configure_cache = lambda **k: appels.append(k)
    return d


def test_le_cache_disque_de_dspy_est_coupe_a_l_import(monkeypatch):
    appels: list = []
    mod = _charger(monkeypatch, _faux_dspy(appels))
    assert mod._DSPY_OK is True
    assert appels, "configure_cache n'a pas ete appele : le cache disque (diskcache) reste ouvert"
    assert appels[-1].get("enable_disk_cache") is False, appels[-1]


def test_un_import_dspy_hors_ligne_ne_tue_pas_le_module(monkeypatch):
    mod = _charger(monkeypatch, ConnectionError("tiktoken : WinError 10013"))
    assert mod._DSPY_OK is False
    rendu = mod.signature_call("CodePatchProposal", {}, provider="x", hub_token="")
    assert rendu["ok"] is False and "dspy" in rendu["error"]
