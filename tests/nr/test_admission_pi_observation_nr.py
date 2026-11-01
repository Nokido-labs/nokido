"""NR point 4 de l'homeostasie (owner 29/10) : controleur PI d'admission, EN OBSERVATION (ne decide rien).

Technique : senpai (github:facebookincubator/senpai, README) -- boucle fermee, avance lente (max_probe 1 %), recul
rapide (max_backoff 10 %), terme integral. Physiologie : retroaction negative autour d'un point de consigne
(OpenStax A&P 2e, m45989). Mesure 29/10 : une reserve FIXE de 4 Go refusait pour 13-74 Mo des jobs alors que la marge
etait confortable juste avant. Doctrine « observer avant d'enforcer » : la decision PI est JOURNALISEE a cote de la
decision actuelle, jamais appliquee, jusqu'a la decision owner.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _la():
    nom = "forge_lane_admission_nr_pi"
    if nom in sys.modules:
        return sys.modules[nom]
    sys.path[:0] = [str(ROOT.parent), str(ROOT), str(ROOT / "app")]
    spec = importlib.util.spec_from_file_location(nom, ROOT / "app" / "forge_lane_admission.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[nom] = m
    spec.loader.exec_module(m)
    return m


def _suite(m, libres, pas_s=5.0, consigne=4.0):
    etat, t, decisions = {"I": 0.0, "t": None}, 0.0, []
    for libre in libres:
        t += pas_s
        adm, etat = m.decision_pi(etat, libre, t, consigne_go=consigne)
        decisions.append(adm)
    return decisions, etat


def test_marge_soutenue_puis_petit_creux_admis():
    m = _la()
    d, _ = _suite(m, [5.5] * 20 + [3.95])          # 13 a 74 Mo sous la consigne apres une marge confortable
    assert d[-1] is True


def test_deficit_soutenu_puis_petit_mieux_refuse():
    m = _la()
    d, _ = _suite(m, [2.5] * 20 + [4.05])
    assert d[-1] is False


def test_recul_plus_rapide_que_l_avance():
    m = _la()
    _, e_plus = _suite(m, [5.0])                    # +1 Go pendant un pas
    _, e_moins = _suite(m, [3.0])                   # -1 Go pendant un pas
    assert abs(e_moins["I"]) > abs(e_plus["I"])


def test_integrale_bornee():
    m = _la()
    _, e = _suite(m, [20.0] * 500)
    assert abs(e["I"]) <= m.PI_INTEGRALE_MAX


def test_observation_ne_change_jamais_le_verdict(tmp_path, monkeypatch):
    m = _la()
    monkeypatch.setattr(m, "_FICHIER_OBSERVATION_PI", tmp_path / "obs.jsonl")
    monkeypatch.setattr(m, "_check_ressources_brut", lambda heavy=True: {"ok": False, "reason": "reserve"})
    monkeypatch.setattr(m, "_libre_instant_go", lambda: 3.95)
    assert m.check_ressources(heavy=True) == {"ok": False, "reason": "reserve"}
    ligne = json.loads((tmp_path / "obs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["decision_actuelle"] is False and "decision_pi" in ligne and "libre_go" in ligne


def test_observer_decision_publique_note_la_voie(tmp_path, monkeypatch):
    m = _la()
    monkeypatch.setattr(m, "_FICHIER_OBSERVATION_PI", tmp_path / "obs.jsonl")
    monkeypatch.setattr(m, "_libre_instant_go", lambda: 5.0)
    res = {"ok": True, "reason": "plage normale", "voie": "legere"}
    m.observer_decision(res)
    assert res == {"ok": True, "reason": "plage normale", "voie": "legere"}   # jamais modifie
    ligne = json.loads((tmp_path / "obs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["voie"] == "legere" and ligne["decision_actuelle"] is True and ligne["motif_actuel"] == "plage normale"


def test_la_voie_lourde_note_sa_lane(tmp_path, monkeypatch):
    m = _la()
    monkeypatch.setattr(m, "_FICHIER_OBSERVATION_PI", tmp_path / "obs.jsonl")
    monkeypatch.setattr(m, "_check_ressources_brut", lambda heavy=True: {"ok": True})
    monkeypatch.setattr(m, "_libre_instant_go", lambda: 5.0)
    assert m.check_ressources(heavy=True, lane="auto:x.py") == {"ok": True}
    ligne = json.loads((tmp_path / "obs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["lane"] == "auto:x.py" and ligne["voie"] == "lourde"


def test_observateur_en_panne_n_altere_rien(monkeypatch):
    m = _la()
    monkeypatch.setattr(m, "_check_ressources_brut", lambda heavy=True: {"ok": True})

    def boom():
        raise RuntimeError("capteur casse")
    monkeypatch.setattr(m, "_libre_instant_go", boom)
    assert m.check_ressources(heavy=True) == {"ok": True}
