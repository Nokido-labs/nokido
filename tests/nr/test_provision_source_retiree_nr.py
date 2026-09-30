"""NR -- le provisionnement du coffre reserve ne crie plus « NON provisionnees » a tort.

Mesure du 2026-09-28 : une fois un nom reserve FERME, sa copie du coffre machine est RETIREE
(c'est le but : les comptes bac a sable la lisaient). L'outil prenait alors cette source absente
pour « SOURCE_ABSENTE » sans regarder le coffre reserve, et le bilan listait en « NON
provisionnees » des cles qui y etaient bien -- faux signal lu comme une panne.

Contrat : source absente + coffre reserve TROUVE = EN PLACE (source retiree), compte comme tel ;
source absente + coffre reserve sans la cle = SOURCE_ABSENTE, toujours dit. Chemin reel main().
Valeurs factices ; aucun coffre reel n'est touche.
"""
from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _outil():
    spec = importlib.util.spec_from_file_location("nr_provision", ROOT / "tools/forge_coffre_reserve_provision.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_source_retiree_mais_reserve_trouvee_est_en_place():
    m = _outil()
    mv = m.mv
    plan = m.planifier({"NOM_FERME": (None, "coffre machine"), "NOM_ABSENT": (None, "coffre machine")},
                       lire_reserve=lambda n: ("valeur-test", mv.RESERVE_TROUVE) if n == "NOM_FERME"
                       else (None, mv.RESERVE_CLE_ABSENTE))
    assert plan["NOM_FERME"] == m.EN_PLACE_SOURCE_RETIREE
    assert plan["NOM_ABSENT"] == m.SOURCE_ABSENTE


def test_le_bilan_du_point_d_entree_ne_liste_plus_les_noms_fermes(monkeypatch, tmp_path, capsys):
    m = _outil()
    mv = m.mv
    monkeypatch.setattr(mv, "_sid_courant", lambda: mv.RESERVE_COMPTE_SID)
    monkeypatch.setattr(mv, "RESERVE_PATH", tmp_path / "coffre_reserve.dat")
    monkeypatch.setattr(mv, "reserve_list", lambda: ([], mv.RESERVE_TROUVE))
    monkeypatch.setattr(mv, "reserve_lire", lambda n: ("valeur-test", mv.RESERVE_TROUVE))
    monkeypatch.setattr(m, "calculer_cibles", lambda: {n: (None, "coffre machine") for n in (*m.COPIES, *m.DEDIEES)})
    monkeypatch.setattr(m, "planifier_nouvelles", lambda rotation=False: {n: m.DEJA_EN_PLACE for n in m.NOUVELLES})
    rc = m.main([])
    sortie = capsys.readouterr().out
    assert rc == 0, sortie
    assert "NON provisionnees" not in sortie and m.EN_PLACE_SOURCE_RETIREE in sortie
