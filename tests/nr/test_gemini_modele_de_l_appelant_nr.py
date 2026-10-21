# -*- coding: utf-8 -*-
"""NR -- le modele Gemini vient de l'APPELANT, jamais d'un GEMINI_MODEL global qui l'ecrase (owner 15/10).

Owner : « la valeur doit dependre de qui l'appelle, pas etre figee ». Mesure du jour : GEMINI_MODEL valait
`gemini-flash-lite-latest` au coffre et `gemini-2.5-pro` dans Nokido.env ; et `Gemini.ask` lisait
`_load_api_key("GEMINI_MODEL") or self.model` -- le global passait AVANT le modele que `ask(model=...)` pose sur
sa copie du fournisseur : le choix de l'appelant etait ignore.

Contrat, sur le chemin reel de `Gemini.ask` (faux `google.genai`, sans reseau) :
  1. un modele pose par l'appelant gagne sur un GEMINI_MODEL global different ;
  2. sans choix de l'appelant, le defaut de la classe (famille flash-lite, seule servie par le palier gratuit)
     gagne aussi sur le global.
"""
from __future__ import annotations

import asyncio
import copy
import sys
import types as _types
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app import forge_agent_proxy as ap  # noqa: E402


def _faux_genai(monkeypatch, vus):
    class _Modeles:
        async def generate_content(self, model, contents, config):
            vus.append(model)
            return _types.SimpleNamespace(text="ok")

    class _Client:
        def __init__(self, api_key=None):
            self.aio = _types.SimpleNamespace(models=_Modeles())

    genai = _types.ModuleType("google.genai")
    genai.Client = _Client
    gtypes = _types.ModuleType("google.genai.types")
    gtypes.GenerateContentConfig = lambda **kw: kw
    genai.types = gtypes
    google = _types.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    monkeypatch.setattr(ap, "_load_api_key",
                        lambda nom: {"GEMINI_API_KEY": "cle-factice", "GEMINI_MODEL": "gemini-2.5-pro"}.get(nom))


def _demander(fournisseur):
    return asyncio.run(fournisseur.ask("bonjour", [], "", 32, 5))


def test_le_modele_pose_par_l_appelant_gagne_sur_le_global(monkeypatch):
    vus = []
    _faux_genai(monkeypatch, vus)
    p = copy.copy(ap.Gemini())
    p.model = "gemini-choisi-par-l-appelant"
    assert _demander(p) == "ok"
    assert vus == ["gemini-choisi-par-l-appelant"]


def test_le_connecteur_mcp_gemini_ne_lit_plus_le_global():
    """15/10 (bb:roadmap_p2_gemini_model_deux_verites_20261015) : Nokido.env porte GEMINI_MODEL=gemini-2.5-pro, 429 sur
    la cle gratuite ; tools/forge_gemini_mcp_connector.py le lisait encore, avec un defaut perime
    (flash-preview-05-20). Le modele vient de l'appelant ; sans choix, la famille flash-lite. Par l'AST (le code, pas
    les commentaires) : l'import du connecteur exige le SDK Google et le coffre, un echec d'import serait un faux rouge."""
    import ast

    for nom in ("forge_gemini_mcp_connector.py", "forge_gemini_mcp_proxy.py"):
        src = (Path(__file__).resolve().parents[2] / "tools" / nom).read_text(encoding="utf-8")
        lit_global = [ast.unparse(n) for n in ast.walk(ast.parse(src))
                      if isinstance(n, ast.Call) and ast.unparse(n).startswith("os.environ.get('GEMINI_MODEL'")]
        assert not lit_global, (nom, lit_global)


def test_la_synchro_des_modeles_n_impose_plus_le_global():
    """16/10 : dernier lecteur restant (bb:roadmap_p2_gemini_model_deux_verites_20261015) -- forge_gemini_models_sync
    lisait get_secret("GEMINI_MODEL") comme modele « impose ». Un modele global impose est ce que la decision owner du
    15/10 supprime. Par l'AST : le code, pas les commentaires."""
    import ast

    src = (Path(__file__).resolve().parents[2] / "tools" / "forge_gemini_models_sync.py").read_text(encoding="utf-8")
    lit_global = [ast.unparse(n) for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Call) and ast.unparse(n).startswith("get_secret('GEMINI_MODEL'")]
    assert not lit_global, lit_global


def test_sans_choix_le_defaut_de_la_classe_gagne_sur_le_global(monkeypatch):
    vus = []
    _faux_genai(monkeypatch, vus)
    assert _demander(ap.Gemini()) == "ok"
    assert vus == [ap.Gemini.model] and vus != ["gemini-2.5-pro"]
