"""NR — l'installateur de dependances n'installe que ce que le depot DECLARE.

Audit securite du 2026-09-18, finding #11. Chaine mesuree :

    forge_mcp_registry:5678   regex ```python sur le TEXTE DE RESULTAT d'une tache
    forge_mcp_registry:5680   ecriture dans un .py temporaire
    forge_mcp_registry:5684   manage(..., dry_run=False)
    forge_dep_manager:46      pip install <nom>  avec sys.executable = L'INTERPRETEUR DU HUB

Un nom absent du disque partait sur PyPI, et un paquet execute du code A
L'INSTALLATION : le producteur d'un resultat de tache choisissait ce qui
s'execute dans l'environnement du hub, en ecrivant `import <nom>`.

Le garde vit dans l'organe qui INSTALLE, pas au site d'appel : `forge_dep_manager`
est cite par quatre modules, et un garde pose sur un seul appelant laisse les
autres ouverts tout en se relisant comme une protection generale.

MORSURES (controles negatifs), deux, parce que ce garde peut echouer des DEUX
cotes : trop permissif (il laisse passer un paquet inconnu) et trop strict (il
refuse tout, casse les appelants legitimes, et se fait desarmer).
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app.forge_dep_manager import (  # noqa: E402
    _nom_de_spec,
    filtrer_autorises,
    install_missing,
    paquets_declares,
)


def test_le_depot_declare_bien_des_paquets():
    """MORSURE 1 — un garde qui refuse TOUT casse ses appelants legitimes.

    Sans ce controle, une allowlist vide passerait tous les autres tests au vert
    en n'autorisant jamais rien.
    """
    declares, illisibles = paquets_declares()
    assert not illisibles, f"declarations illisibles : {illisibles}"
    assert len(declares) > 30, (
        f"seulement {len(declares)} paquet(s) declare(s) lus — le parseur est casse, "
        "et le garde refuserait des dependances legitimes"
    )


def test_un_paquet_declare_est_autorise():
    autorises, refuses = filtrer_autorises(["requests", "fastapi", "numpy"])
    assert sorted(autorises) == ["fastapi", "numpy", "requests"]
    assert not refuses


def test_un_paquet_inconnu_est_refuse_avec_son_motif():
    autorises, refuses = filtrer_autorises(["evil-typosquat-xyz"])
    assert autorises == []
    assert "evil-typosquat-xyz" in refuses
    motif = refuses["evil-typosquat-xyz"]
    assert "NON DECLARE" in motif, "le refus ne dit pas POURQUOI"
    assert "declaration" in motif.lower(), "le refus ne dit pas comment l'autoriser"


def test_morsure_le_bruit_toml_n_entre_pas_dans_l_allowlist():
    """MORSURE 2 — la version qui lisait pyproject.toml LIGNE A LIGNE faisait
    entrer 31 clefs TOML dans l'allowlist, dont `jax`, `mcp`, `h11`, `git`, `rag`
    — des noms REELS sur PyPI. Une allowlist polluee par la syntaxe du fichier
    qu'elle lit autorise ce que personne n'a declare."""
    declares, _ = paquets_declares()
    bruit = {"addopts", "filterwarnings", "name", "version", "dependencies", "all", "dev", "]", "{name"}
    intrus = sorted(bruit & declares)
    assert not intrus, f"des clefs TOML sont prises pour des paquets : {intrus}"


@pytest.mark.parametrize(
    "spec,attendu",
    [
        ("requests>=2.0", "requests"),
        ("PyYAML==6.0.1", "pyyaml"),
        ("uvicorn[standard]", "uvicorn"),
        ("pkg ; python_version<'3.12'", "pkg"),
        ("-r autre.txt", ""),
        ("# commentaire", ""),
        ("addopts = \"-q\"", "addopts"),
        ("]", ""),
    ],
)
def test_lecture_d_une_spec_de_requirement(spec, attendu):
    assert _nom_de_spec(spec) == attendu


def test_le_chemin_reel_n_installe_rien_d_inconnu(monkeypatch):
    """Traverse `install_missing` et prouve qu'AUCUN subprocess n'est lance
    pour un paquet non declare. Un espion, pas une relecture de code."""
    appels = []

    def _espion(cmd, **kw):  # noqa: ARG001
        appels.append(cmd)
        raise AssertionError(
            "pip a ete invoque pour un paquet NON DECLARE : " + " ".join(map(str, cmd))
        )

    import app.forge_dep_manager as M

    monkeypatch.setattr(M.subprocess, "run", _espion)
    resultats = install_missing(["evil-typosquat-xyz", "autre-inconnu-42"])
    assert appels == [], "aucun subprocess ne devait partir"
    assert resultats == {"evil-typosquat-xyz": False, "autre-inconnu-42": False}


def test_le_refus_remonte_a_l_appelant(tmp_path):
    """`manage()` rend `refuses` : un appelant qui ne lit que `success` ne
    saurait pas distinguer « rien a faire » de « la moitie a ete refusee »."""
    from app.forge_dep_manager import manage

    f = tmp_path / "extrait.py"
    f.write_text("import evil_typosquat_xyz_42\n", encoding="utf-8")
    res = manage(str(f), dry_run=True)
    assert "refuses" in res, "le contrat de retour ne porte pas les refus"
    assert "evil_typosquat_xyz_42" in res["refuses"]
