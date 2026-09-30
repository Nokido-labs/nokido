# -*- coding: utf-8 -*-
"""Non-regression — la page de debat ne nomme que des providers qui EXISTENT.

Signale par l'owner le 2026-08-26 : le panneau local de `/forge/debate` rendait

    "error": "Provider 'ollama_local' inconnu. Dispo: [... 'ollama', 'llamacpp', ...]"

`ollama_local` n'a jamais existe au registre du hub — la page appelait un provider
IMAGINAIRE. Le defaut est vicieux parce que l'echec s'affichait dans le panneau du
backend : on l'imputait a ollama (« encore fige »), alors qu'il venait de l'APPELANT.
Un nom faux se lit comme un service en panne.

Meme famille que la route `/alerts` inventee par un modele et servie en prod (cf.
`test_ui_generee_cibles_nr`) : une cible non confrontee au registre reel.

A NE PAS confondre avec les deux autres panneaux du meme relevé : `groq` et `cerebras`
existent bel et bien, et leurs erreurs (« cle ECARTEE par la rotation (http403) ») sont
des messages JUSTES sur un etat reel. Ce test ne garde que l'existence du nom.

Hermetique : AST du registre + lecture du HTML, aucun appel reseau.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "app" / "web_hub" / "llm_debate.html"
REGISTRE = ROOT / "app" / "forge_agent_proxy.py"


def providers_de_la_page() -> list:
    if not PAGE.exists():
        pytest.skip("llm_debate.html absent")
    return re.findall(r'provider:\s*"([^"]+)"', PAGE.read_text(encoding="utf-8", errors="replace"))


def noms_du_registre() -> set:
    """Tout `name = "..."` declare dans une classe de forge_agent_proxy.

    Lu par AST : importer le module tirerait les clients LLM et le coffre."""
    if not REGISTRE.exists():
        pytest.skip("forge_agent_proxy.py absent")
    arbre = ast.parse(REGISTRE.read_text(encoding="utf-8", errors="replace"))
    noms = set()
    for n in ast.walk(arbre):
        if not isinstance(n, ast.ClassDef):
            continue
        for corps in n.body:
            if isinstance(corps, ast.Assign) and isinstance(corps.value, ast.Constant) \
                    and isinstance(corps.value.value, str):
                for c in corps.targets:
                    if isinstance(c, ast.Name) and c.id == "name":
                        noms.add(corps.value.value)
    return noms


def test_le_registre_est_lisible():
    """Sans registre, ce garde ne garderait rien — le dire plutot que passer."""
    noms = noms_du_registre()
    assert len(noms) >= 5, "registre suspect (%d noms) : %s" % (len(noms), sorted(noms))
    assert "ollama" in noms, "le registre ne contient meme pas `ollama` : lecture douteuse"


def test_la_page_declare_des_providers():
    assert providers_de_la_page(), "aucun provider declare dans la page"


def test_tout_provider_de_la_page_existe():
    """LE test. Un nom absent du registre echoue a CHAQUE appel, et son message
    d'erreur accuse le backend au lieu de l'appelant."""
    connus = noms_du_registre()
    inconnus = [p for p in providers_de_la_page() if p not in connus]
    assert not inconnus, (
        "provider(s) inexistant(s) dans la page de debat : %s — connus : %s"
        % (inconnus, sorted(connus)[:14]))


def test_le_nom_faux_historique_a_disparu():
    """Contre-epreuve du cas exact signale."""
    assert "ollama" + "_local" not in providers_de_la_page()


def test_letiquette_affichee_correspond_au_provider_appele():
    """Le panneau annonce un nom a l'utilisateur : s'il differe de celui appele,
    le diagnostic devient impossible a lire."""
    html = PAGE.read_text(encoding="utf-8", errors="replace")
    etiquettes = re.findall(r"data-prov>([a-z0-9_]+)<", html)
    appeles = providers_de_la_page()
    assert etiquettes == appeles, (
        "etiquettes %s != providers appeles %s" % (etiquettes, appeles))
