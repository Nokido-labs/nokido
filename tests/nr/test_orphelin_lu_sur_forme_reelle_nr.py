"""NR - un acte clos n'est jamais lu « orphelin » : le NR emprunte le CHEMIN REEL (15/10).

Mesure du 15/10, 1er acte L1 reel (embed.batch_size 32 -> 40, CONSERVE a 04:08) : garde_plafonds
rendait ORPHELIN_A_REPRENDRE. `actes_orphelins` cherchait `application_id` a la racine de la
post_application, or le chemin normal (mesurer_apres) le range dans `application`. La reprise
du cycle suivant aurait DEFAIT un acte reussi, puis bloque tout nouvel acte. Le NR du matin
etait vert parce qu'il fabriquait des entrees a la forme SUPPOSEE : celui-ci passe par
`appliquer_et_mesurer`. Registre, porte, mesure et etat sont simules dans tmp_path.
"""
from __future__ import annotations

import pytest

from nokido_agent.app import forge_autonomous_loops as al
from nokido_agent.app import forge_mutation_controller as mc


@pytest.fixture
def banc(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "_EVOLUTION_LEDGER", tmp_path / "evolution_experiences.jsonl")
    monkeypatch.setattr(al, "_ensure_ledger_migrated", lambda: None)
    monkeypatch.setattr(mc, "_generation_avant", lambda: None)
    monkeypatch.setattr(mc, "_porte", lambda: {"autorisee": True, "etat": "ARMEE", "motif": ""})
    etat = {"v": 0}

    def appeler(appliquer=None, mesurer=None):
        return mc.appliquer_et_mesurer(
            "L1", "param:x", "exp-test",
            appliquer=appliquer or (lambda: etat.update(v=1) or {"ok": True}),
            reverter=lambda: etat.update(v=0) or {"ok": True},
            # Le score SUIT l'etat (18/10) : un acte garde doit GAGNER hors bruit (SURVIT != AMELIORE).
            mesurer=mesurer or (lambda: {"score": 1.0 + etat["v"]}),
            empreinte=lambda: str(etat["v"]), bruit={"score": 0.1})
    return appeler


def test_un_acte_conserve_n_est_pas_orphelin(banc):
    r = banc()
    assert r["verdict"] == "CONSERVE"
    assert mc.actes_orphelins() == []
    assert (mc.garde_plafonds() or {}).get("verdict") != "ORPHELIN_A_REPRENDRE"


def test_un_process_mort_entre_acte_et_mesure_laisse_un_orphelin(banc, monkeypatch):
    def _mort(*_a, **_k):
        raise RuntimeError("process mort avant la mesure")

    monkeypatch.setattr(mc, "mesurer_apres", _mort)
    with pytest.raises(RuntimeError):
        banc()
    assert len(mc.actes_orphelins()) == 1
    assert mc.garde_plafonds()["verdict"] == "ORPHELIN_A_REPRENDRE"


def test_une_seule_lecture_de_l_identifiant_pour_les_deux_formes():
    """Debat tour 3 (Q2) : cloture et reprise lisent l'identifiant par la MEME fonction."""
    assert mc.application_id_de({"application_id": "a1"}) == "a1"                      # racine
    assert mc.application_id_de({"application": {"application_id": "a2"}}) == "a2"     # imbrique
    assert mc.application_id_de({"application": None}) is None
    assert mc.application_id_de("pas un dict") is None


def test_un_acte_non_applique_n_est_pas_orphelin(banc):
    r = banc(appliquer=lambda: {"ok": False, "detail": "refus"})
    assert r["verdict"] == "NON_APPLIQUE" and mc.actes_orphelins() == []
