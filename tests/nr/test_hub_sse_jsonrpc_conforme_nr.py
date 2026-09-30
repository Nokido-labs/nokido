"""NR — tout `data:` SSE du hub est un message JSON-RPC (2026-09-26).

Mesure : le hub ouvrait chaque flux SSE de `tools/call` par
`data: {"type":"progress","status":"running"}`. Le client MCP de Claude Code valide chaque
`data:` comme JSON-RPC : il rejetait l'evenement (`invalid_union`) et journalisait une
coupure du transport a CHAQUE appel servi en SSE. Correctif : un commentaire SSE, applique
par `tools/forge_patch_hub_sse_conforme.py` (fichier CRITIQUE).

Contrat du patch : il pose le commentaire et l'AST tient ; rejoue, il ne change rien ;
`--verifier` n'ecrit jamais ; une ancre manquante -> RIEN n'est ecrit.
Invariant du depot (chemin REEL) : aucun `"data: " + <litteral>` du hub ne porte autre chose
qu'un message JSON-RPC 2.0.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_patch_hub_sse_conforme as fp  # noqa: E402  (import strict)


def _nl(texte: str) -> str:
    return "\r\n" if "\r\n" in texte else "\n"


def _avant_patch(cible: Path) -> str:
    """L'etat NON patche : si le depot porte le patch, chaque remplacement est ramene a son ancre."""
    src = cible.read_bytes().decode("utf-8")
    if fp.TEMOIN not in src:
        return src
    nl = _nl(src)
    for _etiquette, ancre, remplacement in fp.PATCH_HUB:
        r = remplacement.replace("\n", nl)
        assert src.count(r) == 1, "remplacement non unique dans %s : inverse impossible" % cible.name
        src = src.replace(r, ancre.replace("\n", nl), 1)
    assert fp.TEMOIN not in src, "%s porte le temoin hors du point du patch" % cible.name
    return src


@pytest.fixture
def copie(tmp_path, monkeypatch):
    hub = tmp_path / "nokido_hub.py"
    hub.write_bytes(_avant_patch(fp.HUB).encode("utf-8"))
    monkeypatch.setattr(fp, "HUB", hub)
    return hub


def _litteraux_data(texte: str) -> list:
    """Chaque litteral colle a `"data: "` par une concatenation : `"data: " + '<litteral>'`."""
    trouves = []
    for noeud in ast.walk(ast.parse(texte)):
        if not (isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Add)):
            continue
        gauche, droite = noeud.left, noeud.right
        if (isinstance(gauche, ast.Constant) and gauche.value == "data: "
                and isinstance(droite, ast.Constant) and isinstance(droite.value, str)):
            trouves.append((noeud.lineno, droite.value))
    return trouves


def _non_jsonrpc(litteraux: list) -> list:
    fautifs = []
    for ligne, valeur in litteraux:
        try:
            message = json.loads(valeur)
        except ValueError:
            fautifs.append((ligne, valeur))
            continue
        if not (isinstance(message, dict) and message.get("jsonrpc") == "2.0"):
            fautifs.append((ligne, valeur))
    return fautifs


def test_l_etat_non_patche_porte_bien_le_defaut(copie):
    """Le detecteur voit le defaut mesure : sans cela, l'invariant du depot passerait a vide."""
    fautifs = _non_jsonrpc(_litteraux_data(copie.read_bytes().decode("utf-8")))
    assert any('"type":"progress"' in v for _l, v in fautifs), fautifs


def test_le_patch_pose_le_commentaire_et_l_ast_tient(copie):
    assert fp.main([]) == 0
    texte = copie.read_bytes().decode("utf-8")
    ast.parse(texte)
    for etiquette, _ancre, remplacement in fp.PATCH_HUB:
        assert remplacement.replace("\n", _nl(texte)) in texte, etiquette
    assert _non_jsonrpc(_litteraux_data(texte)) == []


def test_rejoue_il_ne_change_rien(copie):
    assert fp.main([]) == 0
    avant = copie.read_bytes()
    assert fp.main([]) == 0
    assert copie.read_bytes() == avant


def test_verifier_n_ecrit_jamais(copie):
    avant = copie.read_bytes()
    assert fp.main(["--verifier"]) == 0
    assert copie.read_bytes() == avant


def test_une_ancre_manquante_et_rien_n_est_ecrit(copie):
    texte = copie.read_bytes().decode("utf-8")
    ancre = fp.PATCH_HUB[0][1].replace("\n", _nl(texte))
    copie.write_bytes(texte.replace(ancre, "", 1).encode("utf-8"))
    avant = copie.read_bytes()
    assert fp.main([]) == 2
    assert copie.read_bytes() == avant


def test_le_depot_n_emet_que_du_jsonrpc_en_sse():
    """Chemin REEL : le hub du depot porte le patch et aucun `data:` litteral hors JSON-RPC."""
    texte = fp.HUB.read_bytes().decode("utf-8")
    assert fp.TEMOIN in texte, "patch non applique au hub du depot"
    assert _non_jsonrpc(_litteraux_data(texte)) == []
