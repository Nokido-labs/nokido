"""NR 2/11 (choix owner « levier durable + vidage maintenant ») -- le keeper vide l'ensemble de travail de Qdrant quand
ses pages de vecteurs mappees saturent la RAM.

Mesure du 2/11 : qdrant.exe 6,34 Go residents dont 0,19 Go PRIVES (collection nokido_sovereign_rag, 1,6 M points,
vecteurs ColBERT on_disk) -> la jauge comptait ce cache comme occupe et refusait les jobs (83-85 %). Geste owner :
EmptyWorkingSet -> 6,34 -> 0,00 Go, service intact. Le levier rend ce geste automatique, avec les memes gardes que le
vidage WSL : mesure illisible = non (UNKNOWN != 0), seuils, refractaire, journal d'audit.
"""
from nokido_agent.tools import forge_docker_keeper as K


def test_decision_vide_si_ram_haute_et_cache_majoritaire():
    vider, motif = K.decider_vidage_qdrant(ram_pct=84.0, rss_go=6.34, prive_go=0.19, dernier=None, maintenant=1000.0)
    assert vider, motif


def test_ram_basse_ne_vide_pas():
    assert not K.decider_vidage_qdrant(70.0, 6.34, 0.19, None, 1000.0)[0]


def test_memoire_privee_majoritaire_ne_vide_pas():
    # 5 Go PRIVES : ce n'est pas du cache de fichiers, le vidage ne rendrait rien (et forcerait des fautes de page)
    assert not K.decider_vidage_qdrant(84.0, 6.0, 5.0, None, 1000.0)[0]


def test_petit_residente_ne_vide_pas():
    assert not K.decider_vidage_qdrant(84.0, 0.8, 0.1, None, 1000.0)[0]


def test_mesure_illisible_ne_vide_pas():
    vider, motif = K.decider_vidage_qdrant(84.0, None, None, None, 1000.0)
    assert not vider and "illisible" in motif


def test_refractaire():
    assert not K.decider_vidage_qdrant(84.0, 6.34, 0.19, dernier=900.0, maintenant=1000.0)[0]


def test_tick_agit_et_journalise(monkeypatch):
    actes, audits = [], []
    monkeypatch.setattr(K, "mesurer_qdrant", lambda: (84.0, 6.34, 0.19, 4242))
    monkeypatch.setattr(K, "_vider_ws_processus", lambda pid: actes.append(pid) or (True, "ok"))
    monkeypatch.setattr(K, "_audit", lambda action, motif="", **kw: audits.append((action, kw)))
    monkeypatch.setattr(K, "_dernier_vidage_qdrant", None)
    r = K._tick_vidage_qdrant(5000.0)
    assert actes == [4242] and r["vidage"] is True
    assert audits and audits[0][0] == "vidage_ws_qdrant" and audits[0][1]["rss_avant_go"] == 6.34
