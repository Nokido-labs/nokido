"""NR — le patch qui cable `hub action=redemarrer_stack|ordre_bureau` dans le registre (26/09).

Contrat de `tools/forge_patch_hub_ordres_bureau.py` :
  - applique, il pose R1 (schema) et R2 (aiguillage) et l'AST tient ;
  - rejoue, il ne change rien (idempotent) ; `--verifier` n'ecrit jamais ;
  - une ancre manquante -> RIEN n'est ecrit ;
  - il laisse CONTIGU le bloc que le patch d'elicitation relit (son NR de chemin reel).
La copie part de l'etat NON patche : si le depot porte deja le patch, chaque remplacement
est ramene a son ancre (inverse exact), sinon la copie est prise telle quelle.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_patch_hub_elicitation as fe  # noqa: E402  (import strict)
import forge_patch_hub_ordres_bureau as fp  # noqa: E402  (import strict)


def _nl(texte: str) -> str:
    return "\r\n" if "\r\n" in texte else "\n"


def _avant_patch(cible: Path) -> str:
    src = cible.read_bytes().decode("utf-8")
    if fp.TEMOIN not in src:
        return src
    nl = _nl(src)
    for _etiquette, ancre, remplacement in fp.PATCH_REGISTRE:
        r = remplacement.replace("\n", nl)
        assert src.count(r) == 1, "remplacement non unique dans %s : inverse impossible" % cible.name
        src = src.replace(r, ancre.replace("\n", nl), 1)
    assert fp.TEMOIN not in src, "%s cite le module hors des points du patch" % cible.name
    return src


@pytest.fixture
def copie(tmp_path, monkeypatch):
    reg = tmp_path / "forge_mcp_registry.py"
    reg.write_bytes(_avant_patch(fp.REGISTRE).encode("utf-8"))
    monkeypatch.setattr(fp, "REGISTRE", reg)
    return reg


def test_le_patch_pose_chaque_point_d_appel(copie):
    assert fp.main([]) == 0
    texte = copie.read_bytes().decode("utf-8")
    ast.parse(texte)
    for etiquette, _ancre, remplacement in fp.PATCH_REGISTRE:
        assert remplacement.replace("\n", _nl(texte)) in texte, etiquette


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
    r2 = fp.PATCH_REGISTRE[1][1].replace("\n", _nl(texte))
    copie.write_bytes(texte.replace(r2, "", 1).encode("utf-8"))
    avant = copie.read_bytes()
    assert fp.main([]) == 2
    assert copie.read_bytes() == avant


def test_le_bloc_relu_par_le_patch_d_elicitation_reste_contigu(copie):
    assert fp.main([]) == 0
    texte = copie.read_bytes().decode("utf-8")
    for etiquette, _ancre, remplacement in fe.PATCH_REGISTRE:
        assert remplacement.replace("\n", _nl(texte)) in texte, "elicitation %s coupee" % etiquette


def test_le_depot_porte_le_cablage():
    """Chemin REEL : le registre du depot porte chaque point d'appel. Sans lui, les NR du
    module passeraient pendant que le hub ne l'appellerait jamais."""
    texte = fp.REGISTRE.read_bytes().decode("utf-8")
    for etiquette, _ancre, remplacement in fp.PATCH_REGISTRE:
        assert remplacement.replace("\n", _nl(texte)) in texte, "%s absent" % etiquette
