"""NR (owner 2/11) : la soif se NOURRIT des manques constates dans tout Nokido -- collecteur, 2 premieres sources.

« La soif doit se nourrir des manques constates partout dans le code de Nokido, sinon le RSI [...] ne pourra jamais
nourrir l'auto-amelioration. » Recensement du 2/11 : seule la source « diagnostic de sante » alimentait la soif.
Ici, par LISTE BLANCHE (une lacune n'entre que MESUREE par un instrument deterministe qui sait la fermer) :
- BANCS d'amelioration : meilleur prouve du registre -> lacune « depasser ce meilleur » (instrument banc existant) ;
- DETTES ouvertes citant un NR : seulement si ce NR est MESURE ROUGE -> lacune fermee quand il passe vert.
Les manques sans instrument sont DITS (rapport), jamais ouverts. Et le defaut latent trouve en route : l'instrument
banc rendait « banc_amelioration » sans la cible -> la remesure refusait a vie (instrument different)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

N = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(N))
from nokido_agent.app import forge_epistemic_veille as ev  # noqa: E402

BANC = {"juge": {"commande": "python j.py", "metrique": "f1", "sens": "max"}, "perimetre": ["a.py"],
        "garde_tests": ["t.py"], "axes": [{"nom": "mots_vides", "description": "ecarter les mots vides FR/EN"}]}


def _monde(tmp_path, monkeypatch, metrique=0.6):
    bancs = tmp_path / "bancs"
    (bancs / "cible").mkdir(parents=True)
    if metrique is not None:
        (bancs / "cible" / "registre.jsonl").write_text(
            json.dumps({"statut": "REFERENCE", "metrique": metrique, "empreinte": "e0"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(ev, "_BANCS", bancs)
    monkeypatch.setattr(ev, "LACUNES", tmp_path / "soif_lacunes.json")


def test_instrument_banc_rend_son_nom_complet(tmp_path, monkeypatch):
    _monde(tmp_path, monkeypatch)
    cov = ev.mesurer_selon_instrument({"instrument": "banc_amelioration:cible", "critere": {"seuil": 0.7}})
    assert cov["instrument"] == "banc_amelioration:cible", "sinon la remesure refuse a vie (instrument different)"


def test_collecte_bancs_ouvre_une_lacune_mesuree_et_idempotente(tmp_path, monkeypatch):
    _monde(tmp_path, monkeypatch)
    r = ev.collecter_bancs({"cible": BANC})
    assert r["ouvertes"] == ["cible"]
    lac = next(iter(json.loads((tmp_path / "soif_lacunes.json").read_text(encoding="utf-8")).values()))
    assert lac["instrument"] == "banc_amelioration:cible" and lac["critere"]["sens"] == "max"
    assert lac["critere"]["seuil"] > 0.6 and lac["critere"]["n_impossible"] >= 5
    assert any("mots vides" in p for p in lac.get("pistes", ()))
    assert ev.collecter_bancs({"cible": BANC})["ouvertes"] == [], "deuxieme passage : deja ouverte"


def test_banc_sans_mesure_est_dit_pas_ouvert(tmp_path, monkeypatch):
    _monde(tmp_path, monkeypatch, metrique=None)
    r = ev.collecter_bancs({"cible": BANC})
    assert r["ouvertes"] == [] and r["refus"] and "cible" in r["refus"][0]


def test_dette_avec_nr_rouge_seulement(tmp_path, monkeypatch):
    _monde(tmp_path, monkeypatch)
    dettes = [{"cle": "d_rouge", "texte": "bug mesure, NR tests/nr/test_rouge_nr.py a faire passer"},
              {"cle": "d_vert", "texte": "partiel, voir tests/nr/test_vert_nr.py"},
              {"cle": "d_sans", "texte": "dette sans aucun test cite"}]
    rouge = {"tests/nr/test_rouge_nr.py": True, "tests/nr/test_vert_nr.py": False}
    r = ev.collecter_dettes(dettes, nr_rouge=lambda p: rouge[p])
    assert r["ouvertes"] == ["d_rouge"]
    motifs = {x["cle"]: x["motif"] for x in r["refus"]}
    assert "vert" in motifs["d_vert"] and "sans instrument" in motifs["d_sans"]
    lac = next(v for v in json.loads((tmp_path / "soif_lacunes.json").read_text(encoding="utf-8")).values())
    assert lac["instrument"] == "nr:tests/nr/test_rouge_nr.py"


def test_collecteur_periodique_par_source(tmp_path, monkeypatch):
    _monde(tmp_path, monkeypatch)
    monkeypatch.setattr(ev, "COLLECTEUR_ETAT", tmp_path / "soif_collecteur.json")
    appels = {"bancs": 0, "dettes": 0}

    def cb():
        appels["bancs"] += 1
        return {"cible": BANC}

    def cd():
        appels["dettes"] += 1
        return [{"cle": "d", "texte": "voir tests/nr/test_r_nr.py"}]

    r = ev.collecter_sources(1000.0, charger_bancs=cb, charger_dettes=cd, nr_rouge=lambda p: True)
    assert r["bancs"]["ouvertes"] == ["cible"] and r["dettes"]["ouvertes"] == ["d"]
    r2 = ev.collecter_sources(1000.0 + 3600, charger_bancs=cb, charger_dettes=cd, nr_rouge=lambda p: True)
    assert r2["bancs"] == "refractaire" and r2["dettes"] == "refractaire" and appels == {"bancs": 1, "dettes": 1}
    r3 = ev.collecter_sources(1000.0 + 7 * 3600, charger_bancs=cb, charger_dettes=cd, nr_rouge=lambda p: True)
    assert r3["bancs"] != "refractaire" and r3["dettes"] == "refractaire", "bancs 6 h, dettes 24 h"


def test_un_horodatage_futur_ne_rend_pas_le_collecteur_muet_a_vie(tmp_path, monkeypatch):
    """2/11 : un test a ecrit {bancs: 1e10, dettes: 1e10} dans l'etat REEL -> collecteur refractaire jusqu'en 2286.
    Un dernier passage DANS LE FUTUR est une trace corrompue : la source est a refaire, jamais refractaire."""
    _monde(tmp_path, monkeypatch)
    etat = tmp_path / "soif_collecteur.json"
    etat.write_text(json.dumps({"bancs": 1e10, "dettes": 1e10}), encoding="utf-8")
    monkeypatch.setattr(ev, "COLLECTEUR_ETAT", etat)
    r = ev.collecter_sources(1000.0, charger_bancs=lambda: {"cible": BANC}, charger_dettes=lambda: [],
                             nr_rouge=lambda p: True)
    assert r["bancs"] != "refractaire" and r["dettes"] != "refractaire"


def test_instrument_nr_ferme_quand_le_test_passe(monkeypatch):
    monkeypatch.setattr(ev, "_executer_nr", lambda chemin: 0)
    cov = ev.mesurer_selon_instrument({"instrument": "nr:tests/nr/test_x_nr.py"})
    assert cov["ok"] and cov["gap"] is False and cov["instrument"] == "nr:tests/nr/test_x_nr.py"
    monkeypatch.setattr(ev, "_executer_nr", lambda chemin: 1)
    assert ev.mesurer_selon_instrument({"instrument": "nr:tests/nr/test_x_nr.py"})["gap"] is True
