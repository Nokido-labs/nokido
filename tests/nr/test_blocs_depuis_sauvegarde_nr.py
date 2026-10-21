# -*- coding: utf-8 -*-
"""NR (decision owner 19/10 ~21 h 45 : « garder le repli governed_edit », l'outiller) -- generer des blocs
SEARCH/REPLACE VERIFIES entre une version d'alpha et la version sauvee d'un executeur.

Mesure du 19/10 : la porte `forge_merge_gate --sauvegarde` est refusee en ecriture (PermissionError) sur les fichiers
ecrits par le compte du hub ; seul governed_edit peut les ecrire. Les 26 blocs de forge_agent_proxy (livraison
NEMOTRON 5a7c3ce91) ont ete generes par un script jetable : 20 `return resp.choices[0].message.content` IDENTIQUES
(SEARCH ambigu refuse) et un affichage du hub qui ecrase les doubles lignes vides. Contrat de
`forge_search_replace.blocs_depuis(ancien, nouveau)` :
  1. aller-retour EXACT : apply_to_text(ancien, parse_blocks(blocs)) == nouveau, verifie avant de rendre (sinon leve) ;
  2. chaque SEARCH est unique et commence ET finit par une ligne NON vide ;
  3. CRLF normalise (governed_edit lit en mode texte) ; versions identiques -> aucun bloc ;
  4. porte CLI `--blocs-depuis ANCIEN NOUVEAU`.
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))

import forge_search_replace as fsr  # noqa: E402

ANCIEN = (
    "class A:\n    def ask(self):\n        return resp.choices[0].message.content\n\n\n"
    "class B:\n    def ask(self):\n        return resp.choices[0].message.content\n\n\n"
    "class C:\n    def ask(self):\n        return resp.choices[0].message.content\n"
)
NOUVEAU = (
    "def _rendre(resp):\n    return resp.choices[0].message.content\n\n\n"
    "class A:\n    def ask(self):\n        return _rendre(resp)\n\n\n"
    "class B:\n    def ask(self):\n        return resp.choices[0].message.content\n\n\n"
    "class C:\n    def ask(self):\n        return _rendre(resp)\n"
)


def test_aller_retour_exact_malgre_les_lignes_repetees():
    blocs = fsr.blocs_depuis(ANCIEN, NOUVEAU)
    r = fsr.apply_to_text(ANCIEN, fsr.parse_blocks(blocs))
    assert r["ok"], r["failed"]
    assert r["text"] == NOUVEAU


def test_ancres_non_vides_et_uniques():
    for search, _ in fsr.parse_blocks(fsr.blocs_depuis(ANCIEN, NOUVEAU)):
        lignes = search.splitlines()
        assert lignes[0].strip() and lignes[-1].strip(), repr(search)
        assert ANCIEN.count(search) == 1, repr(search)


def test_crlf_normalise_et_identiques_sans_bloc():
    blocs = fsr.blocs_depuis(ANCIEN.replace("\n", "\r\n"), NOUVEAU)
    assert fsr.apply_to_text(ANCIEN, fsr.parse_blocks(blocs))["text"] == NOUVEAU
    assert fsr.blocs_depuis(ANCIEN, ANCIEN) == ""


def test_la_porte_cli(tmp_path, capsys):
    a, b = tmp_path / "a.py", tmp_path / "b.py"
    a.write_text(ANCIEN, encoding="utf-8")
    b.write_text(NOUVEAU, encoding="utf-8")
    assert fsr.main(["--blocs-depuis", str(a), str(b)]) == 0
    sortie = capsys.readouterr().out
    assert fsr.apply_to_text(ANCIEN, fsr.parse_blocks(sortie))["text"] == NOUVEAU


def test_un_aller_retour_impossible_leve(monkeypatch):
    monkeypatch.setattr(fsr, "apply_to_text", lambda t, b: {"ok": False, "text": t, "failed": [{"x": 1}]})
    with pytest.raises(ValueError):
        fsr.blocs_depuis(ANCIEN, NOUVEAU)
