"""NR : facture reelle par segment de compaction (champ usage des transcriptions).

Le debat tokens opposait des parts de contexte sans jamais separer ce que coute l'ouverture d'un
segment, ce qu'on relit de sa base, et ce que le modele ecrit. Ces trois postes se lisent ici.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_contexte_par_source as F  # noqa: E402


def _reponse(mid, ecriture, lecture, sortie, **extra):
    return dict({
        "type": "assistant",
        "message": {"id": mid, "usage": {
            "input_tokens": 0,
            "cache_creation_input_tokens": ecriture,
            "cache_read_input_tokens": lecture,
            "output_tokens": sortie,
        }},
    }, **extra)


FRONTIERE = {"type": "system", "subtype": "compact_boundary"}


def test_chaque_compaction_ouvre_un_segment_et_son_ecriture_est_isolee():
    r = F.facture_par_segment([
        _reponse("a", 100, 0, 10),
        _reponse("b", 20, 100, 10),
        FRONTIERE,
        _reponse("c", 50, 30, 5),
        _reponse("d", 0, 80, 5),
        _reponse("e", 10, 80, 5),
    ])
    assert len(r["segments"]) == 2
    s = r["segments"][1]
    assert s["reponses"] == 3
    assert s["ctx_debut"] == 80
    assert s["ecriture_ouverture"] == 50
    assert s["ecriture"] == 60
    assert s["lecture"] == 190
    assert s["sortie"] == 15
    assert s["base_relue"] == 160  # 80 de base, relus aux 2 reponses suivantes


def test_une_reponse_en_flux_ne_compte_qu_une_fois_sa_derniere_ligne():
    r = F.facture_par_segment([_reponse("a", 1, 2, 3), _reponse("a", 10, 20, 30)])
    s = r["segments"][0]
    assert (s["reponses"], s["ecriture"], s["lecture"], s["sortie"]) == (1, 10, 20, 30)


def test_un_sous_agent_ne_gonfle_pas_le_segment_principal():
    r = F.facture_par_segment([_reponse("a", 5, 5, 5), _reponse("x", 900, 900, 900, isSidechain=True)])
    assert r["segments"][0]["reponses"] == 1
    assert r["segments"][0]["ecriture"] == 5


def test_la_base_relue_ne_depasse_jamais_la_lecture_mesuree():
    # Cache expire en cours de segment : on a reecrit au lieu de relire.
    r = F.facture_par_segment([_reponse("a", 100, 0, 1), _reponse("b", 100, 0, 1)])
    assert r["segments"][0]["base_relue"] == 0


def test_les_quatre_postes_somment_a_un():
    r = F.facture_par_segment([_reponse("a", 100, 0, 10), _reponse("b", 20, 100, 10)])
    parts = r["total"]["parts"]
    assert set(parts) == {"ouverture", "base_relue", "croissance", "sortie"}
    assert abs(sum(parts.values()) - 1.0) < 0.01
    assert parts["ouverture"] > 0 and parts["sortie"] > 0


def test_segment_sans_usage_reste_visible_et_ne_vaut_pas_zero_cout_prouve():
    r = F.facture_par_segment([FRONTIERE, {"type": "user", "message": {"content": "x"}}])
    assert [s["reponses"] for s in r["segments"]] == [0, 0]
    assert r["total"]["parts"] is None


def test_chemin_reel_par_le_drapeau_cli(tmp_path, capsys):
    t = tmp_path / "session.jsonl"
    lignes = [_reponse("a", 100, 0, 10), FRONTIERE, _reponse("b", 50, 30, 5)]
    t.write_text("\n".join(json.dumps(x) for x in lignes), encoding="utf-8")
    assert F.main([str(t), "--facture-segments"]) == 0
    sortie = capsys.readouterr().out
    assert "2 segment(s)" in sortie
    assert "ouverture" in sortie and "base_relue" in sortie
