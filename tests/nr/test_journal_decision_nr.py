# -*- coding: utf-8 -*-
"""NR — A0-4b : la decision d'arbitrage doit etre OBSERVABLE et ATTRIBUABLE.

Mesure du 2026-09-05 : sur 5,7 jours, 24 043 etats physiologiques et 8 647 actions
de cycle de vie, le corps portait **zero** arbitrage journalise -- sans qu'on puisse
dire si l'arbitre avait seulement ete appele. Et le journal vital, seul historique
dense, ne contient AUCUNE des onze entrees de `arbitrer_pression` : six sont
absentes, dont les quatre qui declenchent la protection. Une baseline reconstruite
la-dessus aurait mesure le contrat d'incertitude, pas la politique.

Trois pieges que ce garde ferme, chacun deja paye ailleurs :

1. **Une inconnue serialisee en `false` / `0` contamine tout rejeu futur.** C'est
   exactement ce qui a pollue les episodes du learner : le bug `float(ts)` rendait
   `inutile_s=None`, l'arbitre s'abstenait « par prudence », et l'abstention a ete
   enregistree comme une politique. On enregistre donc la valeur brute ET la liste
   des entrees NON MESUREES.
2. **`rules_v1` n'est pas cette politique.** `forge_regulation_proposer` la declare
   `evict=75 / wake=65` ; le code reel n'a ni l'un ni l'autre, et `wake` n'existe
   meme pas comme seuil. Les 24 episodes du ledger etiquettent pourtant
   `politique: rules_v1` sans qu'aucune action n'y soit observee. L'identifiant est
   donc ancre sur le COMMIT, jamais sur ce nom.
3. **Melanger les denominateurs fait lire « 0 action » comme « 0 occasion ».** Les
   ticks OU L'ARBITRE N'A PAS ETE APPELE sont consignes comme `saut` : sans eux,
   `ticks_decision_observes` n'a pas de denominateur.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

rm = pytest.importorskip("forge_resource_manager")
audit = pytest.importorskip("forge_arbitre_entrees_audit")

BASE = dict(rhythm="CONSERVE", coder_up=True, coder_conns=0, chains_active=0,
            embed_wanted=True, backlog=86454, embedder_up=False, coder_ram_gb=4.65,
            free_gb=1.0, demande_active=False, inutile_s=999)


@pytest.mark.parametrize("mod,attendue", [
    ({"coder_conns": -1}, "coder_conns"),
    ({"demande_active": None}, "demande_active"),
    ({"inutile_s": None}, "inutile_s"),
    ({"backlog": -1}, "backlog"),
])
def test_chaque_entree_non_mesuree_est_NOMMEE(mod, attendue):
    d = rm.arbitrer_pression(**{**BASE, **mod})
    assert attendue in d["inconnues"], \
        "une entree non mesuree n'est pas declaree : le rejeu la lira comme mesuree"


def test_tout_mesure_ne_declare_aucune_inconnue():
    """Le symetrique : un garde qui crie a faux se fait desarmer."""
    assert rm.arbitrer_pression(**BASE)["inconnues"] == []


def test_les_derives_sont_exposes_et_non_recalcules():
    """La fonction rend ce qu'elle a calcule pour decider. Les recalculer chez
    l'appelant aurait donne deux verites de la meme regle."""
    d = rm.arbitrer_pression(**BASE)
    assert set(d["derive"]) == {"grace_s", "embed_affame", "protection_active",
                                "assez_inactif"}
    assert d["derive"]["embed_affame"] is True
    assert d["derive"]["protection_active"] is False


def test_sortie_precoce_rend_des_derives_NON_CALCULES_pas_faux():
    """Coder absent : on sort avant tout calcul de tolerance. `None` dit « non
    calcule » ; `False` aurait dit « calcule, et negatif »."""
    d = rm.arbitrer_pression(**{**BASE, "coder_up": False})
    assert d["action"] == "noop"
    assert all(v is None for v in d["derive"].values())


def test_journal_ecrit_valeur_brute_ET_liste_des_inconnues(tmp_path, monkeypatch):
    """Le piege central : jamais de `false` a la place d'un « pas su »."""
    monkeypatch.setattr(rm, "_DECISIONS_PATH", tmp_path / "d.jsonl")
    ent = {**BASE, "coder_conns": -1, "demande_active": None, "inutile_s": None}
    rm.observer_decision(dict(ent), rm.arbitrer_pression(**ent))
    ligne = json.loads((tmp_path / "d.jsonl").read_text(encoding="utf-8").splitlines()[0])
    for nom in ("coder_conns", "demande_active", "inutile_s"):
        assert nom in ligne["inconnues"]
    assert ligne["inputs"]["demande_active"] is None, "None ecrase en false"
    assert ligne["inputs"]["inutile_s"] is None, "None ecrase en 0"
    assert ligne["inputs"]["coder_conns"] == -1, "sentinelle d'absence ecrasee en 0"


def test_un_verdict_INCERTAIN_du_coder_remonte_comme_inconnue(tmp_path, monkeypatch):
    """`arbitrer_pression` recoit un booleen : l'etat INCERTAIN est deja perdu
    quand elle decide. Seul l'appelant le sait encore."""
    monkeypatch.setattr(rm, "_DECISIONS_PATH", tmp_path / "d.jsonl")
    rm.observer_decision(dict(BASE), rm.arbitrer_pression(**BASE),
                         coder_verdict="INCERTAIN")
    ligne = json.loads((tmp_path / "d.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert "coder_up" in ligne["inconnues"]
    assert ligne["coder_verdict"] == "INCERTAIN"


def test_policy_id_ancre_sur_le_commit_et_jamais_rules_v1():
    pid = rm._policy_id()
    assert pid.startswith("arbitrer_pression/current@")
    assert "rules_v1" not in pid, \
        "rules_v1 designe les seuils 75/65 du proposeur, pas cette politique"


def test_les_ticks_sans_arbitrage_sont_consignes(tmp_path, monkeypatch):
    """Sans eux, `ticks_decision_observes` n'a pas de denominateur et « 0 action »
    devient indistinguable de « 0 occasion »."""
    monkeypatch.setattr(rm, "_DECISIONS_PATH", tmp_path / "d.jsonl")
    rm.observer_decision(saut="cooldown")
    rm.observer_decision(saut="arbitrage_desactive")
    rm.observer_decision(dict(BASE), rm.arbitrer_pression(**BASE))
    j = audit.journal(str(tmp_path / "d.jsonl"))
    assert j["ticks_all"] == 3
    assert j["ticks_sautes"] == 2
    assert j["ticks_decision_observes"] == 1
    assert j["ticks_with_action"] == 1
    assert j["sauts"] == {"cooldown": 1, "arbitrage_desactive": 1}


def test_journal_absent_n_est_pas_journal_vide(tmp_path):
    j = audit.journal(str(tmp_path / "jamais_ecrit.jsonl"))
    assert j.get("absent") is True
    assert j["ticks_all"] == 0


def test_les_lignes_illisibles_ont_leur_denominateur(tmp_path):
    p = tmp_path / "d.jsonl"
    p.write_text('{"ts": 1, "saut": "cooldown"}\nPAS DU JSON\n', encoding="utf-8")
    j = audit.journal(str(p))
    assert j["illisibles"] == 1 and j["ticks_all"] == 1


def test_observer_decision_ne_leve_jamais(monkeypatch):
    """Un journal qui casse la regulation serait pire que le trou qu'il laisse."""
    monkeypatch.setattr(rm, "_DECISIONS_PATH", Path("Z:/inexistant/x/d.jsonl"))
    rm.observer_decision(dict(BASE), rm.arbitrer_pression(**BASE))
    rm.observer_decision(saut="cooldown")


def test_le_journal_de_decision_est_une_surface_DISTINCTE():
    """Etat physiologique et entrees de decision ne sont pas la meme surface : les
    melanger melangerait aussi leurs denominateurs."""
    assert rm._DECISIONS_PATH != rm._VITALS_HISTORY_PATH
    assert rm._DECISIONS_PATH.name == "decision_observations.jsonl"
