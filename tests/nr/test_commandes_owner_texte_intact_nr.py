"""NR -- une commande a taper arrive INTACTE et prete pour PowerShell dans le presse-papier de l'owner (16/10).

RED ecrit par Claude. Vecu 16/10 : la commande deposee `"C:/Users/.../miniforge3/python.exe" "...hook_integrity_check.py"
--capture` est arrivee au presse-papier sous la forme `"C:/[BASE64_SUSPECT_1].exe" ...` -- intacte dans
logs/commandes_owner.jsonl, mais le tray la relevait PAR LE HUB, dont la sortie est caviardee pour les clients cloud.
Et sans l'operateur d'appel `&`, PowerShell rendait une ParserError sur un chemin cite suivi d'arguments.
Convention des NR du tray : l'organe en comportement, le tray par sa SOURCE (pystray n'est pas importe).
"""
from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TRAY = ROOT / "tools" / "nokido_tray.py"


@pytest.fixture()
def ob(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app import forge_ordres_bureau as m
    monkeypatch.setattr(m, "JOURNAL", tmp_path / "ordres.jsonl")
    monkeypatch.setattr(m, "COMMANDES", tmp_path / "commandes_owner.jsonl", raising=False)
    return m


def _deposer(ob, texte):
    asyncio.run(ob.demander_ordre("CLAUDE", "commande-deposer", "x", texte=texte))
    return ob.commandes_en_attente()[-1]["texte"]


def test_un_chemin_cite_en_tete_recoit_l_operateur_d_appel(ob):
    assert _deposer(ob, '"C:/x/python.exe" "C:/y z/t.py" --capture') == '& "C:/x/python.exe" "C:/y z/t.py" --capture'


def test_une_commande_deja_appelee_ou_non_citee_reste_telle_quelle(ob):
    assert _deposer(ob, '& "C:/x/python.exe" t.py') == '& "C:/x/python.exe" t.py'
    assert _deposer(ob, "git status") == "git status"


def test_un_texte_caviarde_se_reconnait(ob):
    assert ob.texte_caviarde('"C:/[BASE64_SUSPECT_1].exe" x.py') is True
    assert ob.texte_caviarde("[PATH_WIN_1]\\Script\\x.py") is True
    assert ob.texte_caviarde('& "C:/Users/a/miniforge3/python.exe" tools\\x.py --capture') is False


def _fonctions():
    arbre = ast.parse(TRAY.read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef)}


def _appels(fonction):
    return {ast.unparse(n.func) for n in ast.walk(fonction) if isinstance(n, ast.Call)}


def test_le_tray_releve_les_commandes_dans_le_journal_et_non_par_le_caviardeur_du_hub():
    appels = _appels(_fonctions()["_relever_commandes"])
    assert any(a.endswith("commandes_en_attente") for a in appels), appels


def test_le_tray_ne_copie_jamais_un_texte_caviarde():
    appels = _appels(_fonctions()["_copier_commande"])
    assert any(a.endswith("texte_caviarde") for a in appels), appels
