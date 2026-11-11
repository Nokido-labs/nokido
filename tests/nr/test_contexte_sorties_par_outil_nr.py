"""NR : la mesure des sorties d'outils dit la CONCENTRATION, par le vrai point d'entree.

Une moyenne ne dit pas si un plafond servirait : seul l'excedent au-dessus du plafond est
gagnable. Une sortie sans appel connu reste comptee, sous ILLISIBLE, jamais perdue.
"""
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))

import forge_contexte_par_source as F  # noqa: E402


def _appel(id_, nom):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": id_, "name": nom, "input": {}}]}}


def _sortie(id_, taille):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": id_, "content": "x" * taille}]}}


def _entrees():
    return [_appel("a", "run"), _sortie("a", 100), _appel("b", "run"), _sortie("b", 6000),
            _appel("c", "Read"), _sortie("c", 500), _sortie("orpheline", 300)]


def test_excedent_au_dessus_du_plafond_seul_compte():
    lignes = {x["outil"]: x for x in F.sorties_par_outil(_entrees())}
    run = lignes["run"]
    assert run["n"] == 2
    assert run["max"] == 6002  # json.dumps ajoute les guillemets : meme mesure que volume_par_demande
    assert run["gain_plafond"]["2000"] == 4002
    assert run["gain_plafond"]["5000"] == 1002
    assert lignes["Read"]["gain_plafond"]["2000"] == 0


def test_sortie_sans_appel_connu_reste_comptee():
    lignes = {x["outil"]: x for x in F.sorties_par_outil(_entrees())}
    assert lignes["ILLISIBLE"]["n"] == 1


def test_sortie_rejouee_apres_compaction_comptee_une_fois():
    # Les messages conserves apres une compaction reapparaissent dans la transcription :
    # 454 sorties de run comptees pour 255 reelles le 5/11.
    entrees = _entrees() + [_appel("b", "run"), _sortie("b", 6000)]
    lignes = {x["outil"]: x for x in F.sorties_par_outil(entrees)}
    assert lignes["run"]["n"] == 2
    assert lignes["run"]["total"] == 102 + 6002


def test_le_plus_lourd_d_abord():
    assert F.sorties_par_outil(_entrees())[0]["outil"] == "run"


def test_chemin_reel_par_le_drapeau(tmp_path, capsys):
    t = tmp_path / "session.jsonl"
    t.write_text("\n".join(json.dumps(e) for e in _entrees()), encoding="utf-8")
    assert F.main(["--sorties-outils", str(t)]) == 0
    sortie = capsys.readouterr().out
    assert "run" in sortie and "ILLISIBLE" in sortie and "6002" in sortie
