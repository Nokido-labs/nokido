"""NR — le patch qui cable l'elicitation dans les fichiers CRITIQUES du hub (26/09).

Contrat de `tools/forge_patch_hub_elicitation.py` :
  - applique, il pose CHAQUE point d'appel (hub H1-H4, registre R1-R2) et l'AST tient ;
  - rejoue, il ne change rien (idempotent) ; `--verifier` n'ecrit jamais ;
  - une seule ancre manquante -> AUCUN des deux fichiers n'est ecrit (tout ou rien).
Les copies partent de l'etat NON patche : si le depot porte deja le patch, chaque
remplacement est ramene a son ancre (inverse exact), sinon la copie est prise telle quelle.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_patch_hub_elicitation as fp  # noqa: E402  (import strict)


def _nl(texte: str) -> str:
    return "\r\n" if "\r\n" in texte else "\n"


def _avant_patch(cible: Path, patch: list) -> str:
    src = cible.read_bytes().decode("utf-8")
    if fp.TEMOIN not in src:
        return src
    nl = _nl(src)
    for _etiquette, ancre, remplacement in patch:
        r = remplacement.replace("\n", nl)
        assert src.count(r) == 1, "remplacement non unique dans %s : inverse impossible" % cible.name
        src = src.replace(r, ancre.replace("\n", nl), 1)
    assert fp.TEMOIN not in src, "%s cite le module hors des points du patch" % cible.name
    return src


@pytest.fixture
def copies(tmp_path, monkeypatch):
    hub, reg = tmp_path / "nokido_hub.py", tmp_path / "forge_mcp_registry.py"
    hub.write_bytes(_avant_patch(fp.HUB, fp.PATCH_HUB).encode("utf-8"))
    reg.write_bytes(_avant_patch(fp.REGISTRE, fp.PATCH_REGISTRE).encode("utf-8"))
    monkeypatch.setattr(fp, "HUB", hub)
    monkeypatch.setattr(fp, "REGISTRE", reg)
    return hub, reg


def test_le_patch_pose_chaque_point_d_appel(copies):
    assert fp.main([]) == 0
    for cible, patch in ((copies[0], fp.PATCH_HUB), (copies[1], fp.PATCH_REGISTRE)):
        texte = cible.read_bytes().decode("utf-8")
        ast.parse(texte)
        for etiquette, _ancre, remplacement in patch:
            assert remplacement.replace("\n", _nl(texte)) in texte, etiquette


def test_rejoue_il_ne_change_rien(copies):
    assert fp.main([]) == 0
    avant = [c.read_bytes() for c in copies]
    assert fp.main([]) == 0
    assert [c.read_bytes() for c in copies] == avant


def test_verifier_n_ecrit_jamais(copies):
    avant = [c.read_bytes() for c in copies]
    assert fp.main(["--verifier"]) == 0
    assert [c.read_bytes() for c in copies] == avant


def test_le_depot_porte_le_cablage():
    """Chemin REEL : le hub et le registre du depot portent chaque point d'appel. Sans lui,
    les NR du module passeraient pendant que le hub ne l'appellerait jamais."""
    for cible, patch in ((fp.HUB, fp.PATCH_HUB), (fp.REGISTRE, fp.PATCH_REGISTRE)):
        texte = cible.read_bytes().decode("utf-8")
        for etiquette, _ancre, remplacement in patch:
            assert remplacement.replace("\n", _nl(texte)) in texte, "%s : %s absent" % (cible.name, etiquette)


def test_une_ancre_manquante_et_rien_n_est_ecrit(copies):
    hub, reg = copies
    texte = hub.read_bytes().decode("utf-8")
    h2 = fp.PATCH_HUB[2][1].replace("\n", _nl(texte))
    hub.write_bytes(texte.replace(h2, "", 1).encode("utf-8"))
    avant = [c.read_bytes() for c in copies]
    assert fp.main([]) == 2
    assert [c.read_bytes() for c in copies] == avant
