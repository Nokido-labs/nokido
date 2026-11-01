"""NR : au-dessus de 90 % de RAM, l'eviction CUMULE des candidats ordonnes par cout jusqu'a couvrir le manque.

Mesure 25/10 : « eviction tentee sans succes (['sleep:NokidoLlamaEmbed(~1.02GB)'], manque 2.58 GB) » -- un
seul candidat, aucun cumul. Jamais un service sous veto, jamais un VITAL ; le non-couvert se DIT."""
from nokido_agent.app import forge_resource_manager as rm


def _plan():
    cands = [
        {"service": "A", "classe": "DIFFERABLE", "rss_mb": 2048.0},
        {"service": "B", "classe": "DIFFERABLE", "rss_mb": 1024.0},
        {"service": "C", "classe": "DIFFERABLE", "rss_mb": 512.0},
    ]
    return rm.ordre_delestage(cands, "SOI")["delester"]


def test_seuil_nomme():
    assert rm._EVICT_CUMUL_SEUIL_PCT == 90.0


def test_cumule_jusqu_a_couvrir():
    endormis = []
    r = rm.delester_jusqu_au_manque(2.58, _plan(), {}, lambda s: (endormis.append(s) or (True, "ACCEPTE")), 92.9)
    assert endormis == ["A", "B"]  # 2 + 1 >= 2.58 ; C epargne
    assert r["reste_gb"] == 0.0 and r["couvert_gb"] >= 2.58


def test_reste_non_couvert_dit():
    r = rm.delester_jusqu_au_manque(10.0, _plan(), {}, lambda s: (True, "ACCEPTE"), 95.0)
    assert r["reste_gb"] == 6.5  # 10 - 3.5
    assert len(r["actions"]) == 3


def test_veto_et_vital_jamais_endormis():
    endormis = []
    plan = _plan() + [{"service": "V", "classe": "VITAL", "rss_mb": 9000.0}]
    r = rm.delester_jusqu_au_manque(10.0, plan, {"A": "acte en cours"},
                                    lambda s: (endormis.append(s) or (True, "ACCEPTE")), 95.0)
    assert "A" not in endormis and "V" not in endormis
    assert {e["service"] for e in r["ecartes"]} == {"A", "V"}


def test_sous_le_seuil_ne_fait_rien():
    def jamais(s):
        raise AssertionError("ne doit pas dormir")
    r = rm.delester_jusqu_au_manque(2.0, _plan(), {}, jamais, 85.0)
    assert r["actions"] == [] and r["reste_gb"] == 2.0


def test_refus_politique_nomme_et_continue():
    def dormir(s):
        return (False, "REFUS_POLITIQUE") if s == "A" else (True, "ACCEPTE")
    r = rm.delester_jusqu_au_manque(1.4, _plan(), {}, dormir, 95.0)
    assert any(e["service"] == "A" and "REFUS" in e["motif"] for e in r["ecartes"])
    assert r["reste_gb"] == 0.0
