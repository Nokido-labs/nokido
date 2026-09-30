# -*- coding: utf-8 -*-
"""NR — on nettoie ce qu'on CONSTRUIT, on oublie ce qu'on RELAIE.

MESURE DU 2026-09-22
    `GET /api/mcp/servers` est une route NUE (aucune garde, 200 sans jeton).
    Son handler anonymise soigneusement la liste des serveurs :

        cmd = conf.get("command", "?").split("/")[-1].split("\\\\")[-1]
        "args": [str(a).split("/")[-1].split("\\\\")[-1] for a in args[:2]]

    ... puis recopie un bloc entier SANS aucun filtre :

        return JSONResponse({"servers": result,
                             "preferences": data.get("preferences", {})})

    L'effort d'anonymisation est REEL, et il s'arrete a la partie CONSTRUITE.
    La partie RELAYEE part telle quelle.

CE QUI PART, ET QUI N'A AUCUN LECTEUR
    19 cles de `claude_desktop_config.json`, dont `localAgentModeTrustedFolders`
    (chemins absolus de l'owner), `bypassPermissionsGateByAccount`,
    `remoteToolsDeviceName`, `coworkHipaaRestricted`.

    Et personne ne les lit. Mesure des DEUX appelants :
      * le JS inline du hub ne touche que `d.error` et `d.servers`
        (`s.name`, `s.url`, `s.command`, `s.enabled`) ;
      * `tools/tmp_patch_mcp_cfg.py` est un one-shot qui ne mentionne jamais
        `preferences`.

        PRODUCED != CONSUMED

    Retirer ce bloc ne casse donc aucun consommateur : c'est le moindre
    privilege applique a une reponse, pas un durcissement d'acces.

CE QUE CE FICHIER VERROUILLE
    La reponse ne relaie plus `preferences`, ET elle continue de porter les
    champs que l'interface consomme. Sans ce second test, « ne rien renvoyer »
    passerait aussi -- et casserait la page.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
_HUB = _RACINE / "tools" / "nokido_hub.py"


def _handler(nom: str):
    src = _HUB.read_text(encoding="utf-8", errors="replace")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError("handler %s introuvable -- re-mesurer" % nom)


def _cles_rendues(fn) -> set:
    """Les cles des dictionnaires passes a une JSONResponse de ce handler.

    On lit l'AST, pas le texte : un retour reformate ne doit pas faire rougir
    ce test, mais une cle ajoutee, si.
    """
    cles = set()
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call)
                and (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
                == "JSONResponse"):
            continue
        for a in n.args:
            if isinstance(a, ast.Dict):
                for k in a.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        cles.add(k.value)
    return cles


def test_la_reponse_ne_relaie_plus_les_preferences():
    """LE COEUR. Le bloc recopie ne doit plus partir."""
    cles = _cles_rendues(_handler("mcp_config_get"))
    assert "preferences" not in cles, (
        "la reponse relaie encore `preferences` : 19 cles de la configuration "
        "Claude Desktop de l'owner -- dont des chemins absolus et "
        "`bypassPermissionsGateByAccount` -- partent sur une route NUE, sans "
        "qu'aucun appelant ne les lise")


def test_la_reponse_porte_TOUJOURS_ce_que_l_interface_lit():
    """CONTRE-EPREUVE. « Ne plus rien renvoyer » passerait le test precedent
    et casserait la page : le JS inline lit `d.servers` et `d.error`."""
    cles = _cles_rendues(_handler("mcp_config_get"))
    assert "servers" in cles, (
        "la liste des serveurs a disparu de la reponse : l'interface affiche "
        "alors une page vide")
    assert "error" in cles, (
        "le canal d'erreur a disparu : le JS lit `d.error` pour afficher la "
        "cause, il afficherait un vide a la place")


def test_l_anonymisation_des_serveurs_est_conservee():
    """Le nettoyage qui MARCHAIT ne doit pas partir avec le correctif.

    Les deux branches (actifs et desactives) reduisent `command` et `args` au
    nom de fichier. C'est cette partie-la qui etait juste.
    """
    src = ast.unparse(_handler("mcp_config_get"))
    assert src.count("split('/')[-1]") >= 2 or src.count('split("/")[-1]') >= 2, (
        "l'anonymisation des commandes a disparu : les chemins complets des "
        "serveurs MCP repartiraient dans la reponse")


def test_le_detecteur_de_cles_ne_rend_pas_vide():
    """CONTROLE POSITIF : si `_cles_rendues` rendait toujours un ensemble vide,
    le premier test passerait sans rien mesurer."""
    cles = _cles_rendues(_handler("mcp_config_get"))
    assert cles, "aucune cle lue dans le handler : l'instrument ne mesure rien"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
