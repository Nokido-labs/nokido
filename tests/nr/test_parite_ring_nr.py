"""tests/nr/test_parite_ring_nr.py — Non-regression audit parite Ring 1.

Verifie :
1. Agregat par liste blanche : FAUX interdit global VRAI (un ILLISIBLE ou FAUX rend le global FAUX).
2. Chemin invisible / inaccessible / sous C:\\Users\\Default = ILLISIBLE, jamais FAUX.
3. Dimension non lue = ILLISIBLE et non saine (non OK).
4. Exception sans source / non AGY sandbox = A_CONFIRMER_OWNER (seul AGY sandbox est EXCEPTION_VALIDEE).
5. CLI --check retourne rc=1 en presence d'ecart ou dimension non lue/invalide, et affiche dimensions non lues.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from tools.forge_parite_ring import (
    STATUT_VRAI,
    STATUT_FAUX,
    STATUT_ILLISIBLE,
    STATUT_EXCEPTION_VALIDEE,
    STATUT_A_CONFIRMER_OWNER,
    est_chemin_illisible_ou_default,
    analyser_services_toml,
    analyser_bash_guard_ast,
    evaluer_exceptions,
    auditer_parite,
)


def test_chemin_invisible_est_illisible(tmp_path: Path):
    """Un chemin sous Default ou illisible doit donner ILLISIBLE, jamais FAUX."""
    chemin_default = Path("C:/Users/Default/test_file.txt")
    assert est_chemin_illisible_ou_default(chemin_default) is True

    # Analyse d'un chemin default ou inexistant
    res_services = analyser_services_toml(chemin_default)
    assert res_services["statut"] == STATUT_ILLISIBLE


def test_faux_interdit_global_vrai(tmp_path: Path):
    """Regle 1: statut global VRAI seulement si TOUS les champs sont VRAI.
    Un FAUX ou un ILLISIBLE l'interdit.
    """
    profil = {
        "dimensions": {
            "dim1": {"source": "s1"},
            "dim2": {"source": "s2"},
        },
        "exceptions": {},
    }
    profil_file = tmp_path / "profil.json"
    profil_file.write_text(json.dumps(profil), encoding="utf-8")

    # Si les dimensions ne sont pas lues, elles sont ILLISIBLE
    res = auditer_parite(tmp_path, profil_file)
    assert res["statut_global"] == STATUT_FAUX
    assert res["dimensions"]["dim1"]["statut"] == STATUT_ILLISIBLE


def test_dimension_non_lue_non_saine(tmp_path: Path):
    """Regle 3: une dimension non lue reste ILLISIBLE, pas OK."""
    profil = {
        "dimensions": {
            "token_vault": {"source": "config/agent_identities.json"},
        },
        "exceptions": {},
    }
    profil_file = tmp_path / "profil.json"
    profil_file.write_text(json.dumps(profil), encoding="utf-8")

    res = auditer_parite(tmp_path, profil_file)
    assert res["dimensions"]["token_vault"]["statut"] == STATUT_ILLISIBLE
    assert res["dimensions_non_lues"] == 1
    assert res["statut_global"] == STATUT_FAUX


def test_exception_sans_source_a_confirmer_owner():
    """Regle 4: EXCEPTION_VALIDEE seulement pour AGY --sandbox (tools/forge_task_executor.py:1688).
    Toutes les autres deviennent A_CONFIRMER_OWNER.
    """
    exceptions_cfg = {
        "agy_sandbox": {
            "agent": "antigravity",
            "motif": "AGY --sandbox",
            "source": "tools/forge_task_executor.py:1688",
        },
        "cline_yolo": {
            "agent": "cline",
            "motif": "Cline --yolo execution libre",
            "source": "tools/forge_task_executor.py",
        },
        "autre_inconnue": {
            "agent": "autre",
            "motif": "sans motif valide",
            "source": "",
        },
    }

    eval_res = evaluer_exceptions(exceptions_cfg)
    res_map = {e["cle"]: e["statut"] for e in eval_res}

    assert res_map["agy_sandbox"] == STATUT_EXCEPTION_VALIDEE
    assert res_map["cline_yolo"] == STATUT_A_CONFIRMER_OWNER
    assert res_map["autre_inconnue"] == STATUT_A_CONFIRMER_OWNER


def test_check_cli_comportement(tmp_path: Path, monkeypatch, capsys):
    """Regle 5: --check doit echouer s'il y a un ecart ou une dimension non lue."""
    from tools.forge_parite_ring import main

    profil = {
        "dimensions": {
            "non_lue": {"source": "inconnue"},
        },
        "exceptions": {},
    }
    profil_file = tmp_path / "profil.json"
    profil_file.write_text(json.dumps(profil), encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        ["forge_parite_ring.py", "--check", "--profil", str(profil_file), "--racine", str(tmp_path)],
    )

    rc = main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "Dimensions non lues: 1" in captured.out
    assert "Statut global: FAUX" in captured.out
