"""NR -- juge d'ancrage : l'UNITE compte, les plages sont typees, les arguments d'outils sont des sources.

Mesure 29/10 10 h 15 : la synthese fabriquee de la recette 10 h 02 (« -15-20 % », « 12 % », « -30 % ») passait
ANCREE parce que 15, 20, 12, 30 apparaissaient NUS ailleurs (« 30 s ») ; et « positions 6000-16000 » (bornes de
lecture, dans les ARGUMENTS d'appel d'outil) etait marque sans source. Sources factices, aucun reseau."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_cli_swarm as S  # noqa: E402


def test_pourcentage_exige_un_pourcentage():
    """« 30 % » n'est pas ancre par « 30 s »."""
    assert S._juger_ancrage("gain de 30 %", ["timeout 30 s"])["sans_source"] == ["30%"]


def test_pourcentage_ancre_par_pourcentage():
    """« 30 % » ancre par « 30% » (espaces et signe indifferents)."""
    assert S._juger_ancrage("gain de −30 %", ["baisse de 30% mesuree"])["sans_source"] == []


def test_plage_de_pourcentages_typee():
    """« 15–20 % » = deux pourcentages ; 15 fichiers / 20 tests ne les ancrent pas."""
    j = S._juger_ancrage("reduction de 15–20 %", ["mesure : 15 fichiers, 20 tests"])
    assert sorted(j["sans_source"]) == ["15%", "20%"]


def test_multiplicateur_suffixe_x():
    """« 1,25× » ancre par « 1.25x » (x suffixe)."""
    assert S._juger_ancrage("cache write 1,25× base", ["Cache write : 1.25x base"])["sans_source"] == []


def test_arguments_d_appel_d_outil_sont_des_sources():
    """Les bornes lues (arguments de lire_fichier) ancrent « positions 6000–16000 »."""
    msgs = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "1", "function": {"name": "lire_fichier", "arguments": '{"chemin": "x.md", "debut": 6000, "fin": 16000}'}}]},
            {"role": "tool", "name": "lire_fichier", "content": "texte"}]
    j = S._juger_ancrage("lu les positions 6000–16000", S._extraits(msgs))
    assert j["sans_source"] == []
