# -*- coding: utf-8 -*-
"""NR — A0-4d : association abstention -> detresse, et ce qu'elle N'EST PAS.

L'inference naive etait tentante et fausse : « 1028 abstentions, 406 detresses,
donc s'abstenir coute ». Mesure du 2026-09-05, sur les memes donnees :

    temoin UNIFORME (au hasard dans la periode)   ratio 3.70
    temoin APPARIE sur la RAM libre (+-0,3 Go)    ratio 1.31, IC95 [1.06 ; 1.81]

Environ 60 % de l'association apparente n'etait que le NIVEAU DE PRESSION, commun
aux deux evenements : une charge qui monte declenche des abstentions (capacites
critiques protegees) ET finit en detresse. Sur les trois fenetres testees, deux IC
CONTIENNENT 1. L'association n'est donc pas etablie apres ajustement -- et rien
n'indique qu'une politique moins prudente reduirait les detresses.

Ce garde protege les trois precautions qui ont produit ce resultat. Les retirer
ferait revenir un chiffre spectaculaire et faux.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

fe = pytest.importorskip("forge_regulation_efficacy")


def _ecrire(p: Path, lignes: list) -> None:
    p.write_text("\n".join(json.dumps(x) for x in lignes) + "\n", encoding="utf-8")


def test_une_rafale_d_abstentions_est_UN_episode():
    """`evict_skipped` revient au rythme du tick (~122 s) : c'est la boucle qui
    re-decide « non ». Compter chaque ligne ferait crier au pompage."""
    rafale = [1000.0, 1120.0, 1240.0, 1360.0]
    assert fe._episodes(rafale, gap=300.0) == [(1000.0, 1360.0)]


def test_deux_rafales_espacees_sont_deux_episodes():
    assert len(fe._episodes([1000.0, 1120.0, 9000.0, 9120.0], gap=300.0)) == 2


def test_episodes_vide_ne_leve_pas():
    assert fe._episodes([]) == []


def test_journal_absent_n_est_pas_journal_vide(tmp_path):
    r = fe.association_abstention_detresse(chemin_actions=str(tmp_path / "rien.jsonl"))
    assert r.get("absent")
    assert "fenetres" in r and r["fenetres"] == {}


def test_sources_incompletes_rendent_SANS_MESURE(tmp_path):
    """Pas de verdict fabrique quand une source manque."""
    act = tmp_path / "a.jsonl"
    _ecrire(act, [{"ts": 1000.0, "action": "evict_skipped"}])   # aucune detresse
    r = fe.association_abstention_detresse(chemin_actions=str(act),
                                           chemin_vitals=str(tmp_path / "absent.jsonl"))
    assert "SANS MESURE" in r["verdict"]


def test_les_illisibles_ont_leur_denominateur(tmp_path):
    act = tmp_path / "a.jsonl"
    act.write_text('{"ts": 1000.0, "action": "evict_skipped"}\nPAS DU JSON\n'
                   '{"action": "evict_skipped"}\n', encoding="utf-8")
    r = fe.association_abstention_detresse(chemin_actions=str(act),
                                           chemin_vitals=str(tmp_path / "v.jsonl"))
    # ligne cassee + ligne sans ts : deux facons de « ne pas pouvoir voir »
    assert r["illisibles_actions"] == 2


def test_un_IC_contenant_1_ne_conclut_pas(tmp_path):
    """Le coeur du resultat : « ne conclut pas » n'est pas « pas d'effet », c'est
    « ces donnees ne le distinguent pas de zero ». Un garde qui trancherait quand
    meme reproduirait l'inference naive qu'on vient d'ecarter."""
    act, vit = tmp_path / "a.jsonl", tmp_path / "v.jsonl"
    # Detresses DENSES et regulieres : tout instant est suivi d'une detresse, donc
    # le temoin marque autant que l'observe -> ratio ~1, aucune conclusion.
    lignes = []
    for i in range(60):
        lignes.append({"ts": 1000.0 + i * 600.0, "action": "evict_skipped"})
        lignes.append({"ts": 1100.0 + i * 600.0, "action": "evict_detresse"})
    _ecrire(act, lignes)
    _ecrire(vit, [{"ts": 1000.0 + i * 60.0, "ram_free_gb": 3.0} for i in range(700)])
    r = fe.association_abstention_detresse(chemin_actions=str(act),
                                           chemin_vitals=str(vit))
    if r.get("fenetres"):
        for b in r["fenetres"].values():
            if "ic95" in b:
                assert b["conclut"] is (not (b["ic95"][0] <= 1.0 <= b["ic95"][1]))


def test_le_verdict_refuse_l_efficacite_de_politique(tmp_path):
    """Aucune action n'est observee ici : le module ne doit jamais laisser lire
    ce resultat comme une mesure d'efficacite. Le ledger du learner a montre le
    prix de l'amalgame -- `recovered: true` etiquete `politique: rules_v1`."""
    act, vit = tmp_path / "a.jsonl", tmp_path / "v.jsonl"
    _ecrire(act, [{"ts": 1000.0, "action": "evict_skipped"},
                  {"ts": 1200.0, "action": "evict_detresse"}])
    _ecrire(vit, [{"ts": 1000.0, "ram_free_gb": 3.0}])
    r = fe.association_abstention_detresse(chemin_actions=str(act),
                                           chemin_vitals=str(vit))
    assert "PAS une efficacite" in r.get("avertissement", "") or "SANS MESURE" in r["verdict"]


def test_l_appariement_sur_la_pression_est_declare():
    """Sans temoin apparie, le ratio mesurait la densite des detresses (3,70 au
    lieu de 1,31). La tolerance et la marge doivent rester des constantes NOMMEES,
    pas des nombres enfouis."""
    assert fe.TOLERANCE_RAM_GO > 0
    assert fe.MARGE_TEMOIN_S > 0
    assert fe.BOOTSTRAP_N >= 100, "un tirage unique de temoin n'est pas un resultat"
