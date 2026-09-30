# -*- coding: utf-8 -*-
"""NR — findings #1 et #3 de l'audit securite du 2026-09-18.

`forge_docker_agent.decide` est cite par 7 modules et n'avait AUCUN test.

#1 — Les IMAGES etaient en liste blanche, les OPTIONS en liste NOIRE. Une option
absente des deux tombait en ALLOW. Contournement NOMME qui l'a demontre :
`_bad_volume` n'examinait que `-v` et `--volume` ; la forme
`--mount type=bind,source=C:\\,target=/host` n'etait examinee par PERSONNE.
Une liste noire protege les formes qu'on a pensees, pas la CAPACITE.

#3 — L'appel sortant du client de lot partait sans echeance : un pair muet
suspendait l'appelant sans borne, et `raise_for_status` n'etait jamais atteint.

Le correctif de #1 utilise `PARK`, pas `DENY` : une option inconnue n'est pas
hostile, elle est NON INSTRUITE. La refuser casserait un usage legitime au
premier flag nouveau. On retient, un humain tranche.

MORSURE CENTRALE : l'appel REEL du depot (`forge_docker_transient:61`) doit
rester ALLOW. Sans ce controle, une liste blanche trop etroite passerait tous
les autres tests en bloquant le seul usage qui existe.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/docker : les options en liste blanche, l'inconnu retenu"

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app.forge_docker_agent import _bad_volume, decide  # noqa: E402

# L'invocation REELLE, relevee dans forge_docker_transient.py:61 le 2026-09-18.
APPEL_REEL = ["run", "-d", "--rm", "--init", "--name", "nokido-transient",
              "-v", "vol_ws:/workspace", "-w", "/workspace",
              "ghcr.io/nokido/base", "sleep", "infinity"]


def test_MORSURE_l_appel_reel_du_depot_reste_autorise():
    """Le controle qui empeche la liste blanche d'etre trop etroite."""
    etat, motif = decide(APPEL_REEL)
    assert etat == "ALLOW", (
        f"l'unique invocation reelle du depot est {etat} ({motif}) — la liste "
        "blanche casse l'usage qu'elle doit permettre"
    )


@pytest.mark.parametrize("option", [
    "--privileged", "--pid=host", "--network=host", "--cap-add=SYS_ADMIN",
    "--device=/dev/mem", "--userns=host", "--security-opt=seccomp=unconfined",
    "--cgroupns=host", "--runtime=runsc", "--volumes-from=autre",
])
def test_les_evasions_connues_sont_REFUSEES(option):
    etat, motif = decide(["run", option, "ghcr.io/nokido/base"])
    assert etat == "DENY", f"{option} n'est pas refuse : {etat} ({motif})"


@pytest.mark.parametrize("option", ["--inconnue-du-jour", "--futur-flag=1", "--xyz"])
def test_une_option_NON_INSTRUITE_est_RETENUE_pas_acceptee(option):
    """Le coeur du finding : l'inconnu tombait du cote sain."""
    etat, motif = decide(["run", option, "ghcr.io/nokido/base"])
    assert etat == "PARK", f"{option} rend {etat} au lieu d'etre retenue ({motif})"
    assert "liste blanche" in motif or "instruite" in motif


def test_MORSURE_le_temoin_inconnu_est_bien_hors_liste_noire():
    """CONTROLE NEGATIF — prouve que le test precedent mesure la liste BLANCHE.

    Si le temoin figurait dans la liste noire, il serait refuse pour une autre
    raison et le test ne dirait rien du changement de politique.
    """
    from app.forge_docker_agent import _BLOCK_RUN_FLAGS

    for t in ("--inconnue-du-jour", "--futur-flag", "--xyz"):
        assert t not in _BLOCK_RUN_FLAGS, f"{t} est en liste noire : mauvais temoin"


@pytest.mark.parametrize("argv", [
    ["run", "--mount", "type=bind,source=C:\\,target=/host", "ghcr.io/nokido/base"],
    ["run", "--mount", "type=bind,src=/,target=/host", "ghcr.io/nokido/base"],
    ["run", "--mount=type=bind,source=/var/run,target=/x", "ghcr.io/nokido/base"],
])
def test_le_montage_par_mount_est_vu_comme_celui_par_v(argv):
    """L'angle mort nomme : `--mount` n'etait examine par personne."""
    assert _bad_volume(argv), f"bind-mount hote non detecte : {argv[1:3]}"
    etat, motif = decide(argv)
    assert etat == "DENY", f"{argv[1:3]} rend {etat} ({motif})"


def test_MORSURE_un_mount_anodin_n_est_pas_refuse():
    """CONTROLE NEGATIF — sans lui, un detecteur qui refuse TOUT `--mount`
    passerait le test precedent sans rien distinguer."""
    argv = ["run", "--mount", "type=volume,source=vol_ws,target=/workspace",
            "ghcr.io/nokido/base"]
    assert not _bad_volume(argv), "un volume nomme est refuse a tort"


def test_le_bind_mount_par_v_reste_refuse():
    """Non-regression du controle qui existait deja."""
    assert _bad_volume(["run", "-v", "C:\\:/host", "img"])
    assert _bad_volume(["run", "-v", "/var/run/docker.sock:/x", "img"])


def test_le_verbe_hors_politique_reste_retenu():
    etat, _ = decide(["build", "-t", "x", "."])
    assert etat == "PARK"


def test_la_lecture_seule_reste_autorisee():
    """Non-regression : la politique ne doit pas se durcir sur l'inoffensif."""
    for verbe in ("ps", "images", "logs", "inspect"):
        etat, _ = decide([verbe])
        assert etat == "ALLOW", f"{verbe} (lecture seule) n'est plus autorise"


# ── Finding #3 : l'echeance de l'appel sortant ───────────────────────────────

def test_l_appel_sortant_du_client_de_lot_porte_une_echeance():
    """Lu par AST : ni commentaire ni docstring ne peut faire passer ce test."""
    src = (RACINE / "tools" / "forge_bundle_primitives.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    posts = [n for n in ast.walk(arbre)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "post"]
    assert posts, "aucun appel POST trouve : le fichier a change de forme"
    for n in posts:
        assert any(k.arg == "timeout" for k in n.keywords), (
            f"POST sans echeance ligne {n.lineno} : un pair muet suspend "
            "l'appelant sans borne"
        )


def test_les_deux_bornes_sont_DISTINCTES():
    """Connexion et lecture n'ont pas la meme duree legitime.

    Les confondre obligerait a choisir entre detecter un port mort tard et tuer
    un lot qui travaille.
    """
    from tools.forge_bundle_primitives import CONNEXION_S, LECTURE_S

    assert 0 < CONNEXION_S < LECTURE_S, (
        f"bornes incoherentes : connexion={CONNEXION_S}s lecture={LECTURE_S}s"
    )
    assert CONNEXION_S <= 10, "une connexion locale qui tarde 10 s est deja morte"
