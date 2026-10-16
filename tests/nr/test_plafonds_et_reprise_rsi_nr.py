"""NR — plafonds et reprise des actes interrompus de l'auto-amelioration (debat RSI 15/10).

Codex, tour 2 : les plafonds (50/jour, 30 min) n'etaient ecrits nulle part ; un acte applique
puis interrompu avant sa mesure restait sans retour. AGY : les valider dans les NR, pas les
decouvrir a l'armement. Registre, magasin L1 et frein sont simules : rien de reel n'est touche.
"""
import json
import time

import pytest

from nokido_agent.app import forge_mutation_controller as ctl
from nokido_agent.app import forge_proposal_applier as app

T = time.mktime(time.strptime("2026-10-15T12:00:00", "%Y-%m-%dT%H:%M:%S"))


def _ts(delta_s):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T - delta_s))


def _app(i, delta_s, close=True):
    out = [{"kind": "application", "status": "EN_COURS", "exp_id": "A%d" % i, "cible": "param:x",
            "ts": _ts(delta_s)}]
    if close:
        out.append({"kind": "post_application", "application_id": "A%d" % i, "verdict": "CONSERVE"})
    return out


def test_registre_vide_rien_ne_bloque():
    assert ctl.garde_plafonds(maintenant=T, entrees=[]) is None


def test_intervalle_minimal():
    r = ctl.garde_plafonds(maintenant=T, entrees=_app(1, 600))
    assert r["verdict"] == "PLAFOND" and "intervalle" in r["pourquoi"]


def test_acte_ancien_ne_bloque_pas():
    assert ctl.garde_plafonds(maintenant=T, entrees=_app(1, 7200)) is None


def test_plafond_journalier():
    entrees = []
    for i in range(ctl.PLAFOND_ACTES_JOUR):
        entrees += _app(i, 3600 + i * 60)
    r = ctl.garde_plafonds(maintenant=T, entrees=entrees)
    assert r["verdict"] == "PLAFOND" and "24 h" in r["pourquoi"]


def test_un_orphelin_bloque_tout():
    r = ctl.garde_plafonds(maintenant=T, entrees=_app(1, 99999, close=False))
    assert r["verdict"] == "ORPHELIN_A_REPRENDRE"


def test_le_controleur_refuse_sans_agir(monkeypatch):
    monkeypatch.setattr(ctl, "_porte", lambda: {"autorisee": True, "etat": "ARMEE"})
    monkeypatch.setattr(ctl, "garde_plafonds", lambda: {"verdict": "PLAFOND", "pourquoi": "test"})
    r = ctl.appliquer_et_mesurer("L1", "param:x", None, appliquer=lambda: pytest.fail("acte fait"),
                                 reverter=lambda: None, mesurer=lambda: {"a": 1.0},
                                 empreinte=lambda: "e", bruit={})
    assert r["verdict"] == "PLAFOND" and r["applique"] is False


@pytest.fixture
def magasin(monkeypatch, tmp_path):
    f = tmp_path / "parametres_l1.json"
    f.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app, "PARAMS_L1_FICHIER", f)
    inscrits, freins = [], []
    monkeypatch.setattr(ctl, "_inscrire", lambda rec: inscrits.append(rec) or "P")
    monkeypatch.setattr(ctl, "_poser_frein", lambda motif: freins.append(motif))
    return f, inscrits, freins


def _orphelin(monkeypatch, avant, ref="E1"):
    monkeypatch.setattr(ctl, "actes_orphelins", lambda entrees=None: [
        {"niveau": "L1", "cible": "param:embed.batch_size", "empreinte_avant": avant,
         "ref_exp": ref, "exp_id": "A1"}])


def test_reprise_d_un_acte_applique(monkeypatch, magasin):
    f, inscrits, freins = magasin
    avant = app.empreinte_l1()
    f.write_text(json.dumps({"embed.batch_size": {"valeur": 40, "precedente": None, "exp_id": "E1"}}),
                 encoding="utf-8")
    _orphelin(monkeypatch, avant)
    assert app.reprendre_orphelins_l1() == [{"cible": "param:embed.batch_size", "verdict": "REPRIS_REVERTE"}]
    assert json.loads(f.read_text(encoding="utf-8")) == {} and not freins
    assert inscrits[0]["kind"] == "post_application" and inscrits[0]["application_id"] == "A1"


def test_reprise_d_un_acte_jamais_ecrit(monkeypatch, magasin):
    _, inscrits, freins = magasin
    _orphelin(monkeypatch, app.empreinte_l1())
    assert app.reprendre_orphelins_l1()[0]["verdict"] == "REPRIS_NON_APPLIQUE" and not freins


def test_reprise_non_prouvee_pose_le_frein(monkeypatch, magasin):
    f, inscrits, freins = magasin
    avant = app.empreinte_l1()
    f.write_text(json.dumps({"embed.batch_size": {"valeur": 40, "precedente": None, "exp_id": "AUTRE"}}),
                 encoding="utf-8")
    _orphelin(monkeypatch, avant)
    assert app.reprendre_orphelins_l1()[0]["verdict"] == "REPRISE_NON_PROUVEE"
    assert freins and "NON prouvee" in freins[0]


def test_une_reprise_ne_compte_pas_comme_un_revert(monkeypatch):
    lignes = [json.dumps({"kind": "post_application", "verdict": v})
              for v in ("REVERTE", "REPRIS_REVERTE", "REVERTE")]
    monkeypatch.setattr(ctl.Path, "read_text", lambda self, **k: "\n".join(lignes))
    from nokido_agent.app import forge_autonomous_loops as al
    monkeypatch.setattr(al, "_EVOLUTION_LEDGER", "registre_factice.jsonl")
    assert ctl._reverts_consecutifs() == 2
