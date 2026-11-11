"""NR -- un mot de passe en clair ne passe plus : une seule definition, tous les points de sortie (owner 6/11).

Mesure du 6/11 : le mot de passe du certificat de dev Xbox etait committe dans deux fichiers et huit commits. Les motifs
exigeaient un nom api_key|secret|token|password et 24 caracteres sans ponctuation : un `PFXPWD` court passait partout.
Owner : « la sovereign membrane devrait empecher tous ces genre de fuites ». La membrane ne voit que ce qui part vers un
modele : le crochet de commit et `governed_edit` portent donc la meme definition, verifiee ici.
Les valeurs sont FICTIVES et assemblees a l'execution, sinon ce fichier serait lui-meme refuse.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_secret_guard as G  # noqa: E402
from nokido_agent.app.forge_semantic_firewall import redact_tool_output  # noqa: E402
from nokido_agent.app.forge_sovereign_membrane import SovereignMembrane  # noqa: E402

pytestmark = pytest.mark.timeout(60)
VALEUR = "fictif" + "!" + "2099"
GUILLEMET = chr(34)
EN_CLAIR = [
    "PFX" + "PWD = " + GUILLEMET + VALEUR + GUILLEMET,
    "PW" + "D = " + GUILLEMET + VALEUR + GUILLEMET,
    "cert_pass" + "word: " + GUILLEMET + VALEUR + GUILLEMET,
    "signtool sign /fd SHA256 /f a.pfx " + "/p " + VALEUR + " b.msix",
]
ANODINS = [
    "PW" + "D = get_secret(" + GUILLEMET + "XBOX_PFX_PASSWORD" + GUILLEMET + ")",
    "PW" + "D = " + GUILLEMET + "<mot>" + GUILLEMET,
    "signtool sign /f a.pfx " + "/p <mot de passe> b.msix",
    "signtool sign /f a.pfx " + "/p $env:MOT b.msix",
    "password_hash = compute(value)",
]


def _hook():
    spec = importlib.util.spec_from_file_location("precommit_secret_scan_nr", RACINE / "scripts" / "precommit_secret_scan.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _governed():
    from nokido_agent.tools.forge_governed_edit import _scan_secrets
    return _scan_secrets


@pytest.mark.parametrize("texte", EN_CLAIR)
def test_le_crochet_de_commit_le_voit(texte):
    assert any(re.search(p, texte) for _l, p, _s in _hook().PATTERNS)


@pytest.mark.parametrize("texte", EN_CLAIR)
def test_governed_edit_le_refuse(texte):
    assert _governed()(texte)


@pytest.mark.parametrize("texte", EN_CLAIR)
def test_une_sortie_d_outil_le_masque(texte):
    sortie, _bilan = redact_tool_output(texte, "nr", journal=False)
    assert VALEUR not in sortie


@pytest.mark.parametrize("texte", EN_CLAIR)
def test_la_membrane_l_aliase_et_le_restitue(texte, tmp_path):
    m = SovereignMembrane(mission_id="nr_mdp", db_path=str(tmp_path / "m.db"), hmac_secret=b"n" * 32)
    sortie = m.wrap_objet(texte)
    assert VALEUR not in sortie and m.unwrap_objet(sortie, "x") == texte
    assert VALEUR not in m.wrap(texte).content


@pytest.mark.parametrize("texte", ANODINS)
def test_une_reference_au_coffre_ou_un_gabarit_passe(texte):
    assert not any(re.search(p, texte) for _l, p, _s in _hook().PATTERNS if "Mot de passe" in _l)
    assert not any(re.search(p, texte) for _l, p in G.MOTS_DE_PASSE_EN_CLAIR)


def test_le_crochet_porte_exactement_la_definition_commune():
    """Le crochet n'importe rien de l'application : une copie, tenue egale par ce test."""
    copie = {(l, p) for l, p, _s in _hook().PATTERNS if "Mot de passe" in l}
    assert copie == set(G.MOTS_DE_PASSE_EN_CLAIR)
    assert all(s == "HIGH" for l, _p, s in _hook().PATTERNS if "Mot de passe" in l)


def test_le_crochet_refuse_si_la_liste_des_fichiers_est_illisible(monkeypatch):
    h = _hook()

    class Refus:
        returncode = 128
        stdout = ""
    monkeypatch.setattr(h.subprocess, "run", lambda *a, **k: Refus())
    with pytest.raises(SystemExit) as e:
        h.staged_files()
    assert e.value.code not in (0, None)


def test_plus_aucune_valeur_en_clair_dans_le_code_xbox():
    for nom in ("xbox_deploy.py", "xbox_sign_diag.py"):
        t = (RACINE / "_attic" / "xbox" / nom).read_text(encoding="utf-8")
        assert not any(re.search(p, t) for _l, p in G.MOTS_DE_PASSE_EN_CLAIR), nom
