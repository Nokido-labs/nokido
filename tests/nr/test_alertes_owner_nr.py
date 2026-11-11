# -*- coding: utf-8 -*-
"""NR owner 4/11 : COAGULATION et ORGAN_PULSE envoyaient ~480 NEED_HUMAN_APPROVAL par jour a personne.

`HubClient.notify` sans destinataire finit dans EVENTBUS_ARCHIVE, et l'emetteur journalisait « delivree ». Choix owner, sur
volume mesure : resume quotidien des flaps + hors flap une alerte par sujet avec 24 h de silence, soit ~4 par jour, au
demarrage et au tray pour high et critical. Une gravite qui monte est un changement d'etat : elle passe le silence.
"""
import importlib
import sys
import types
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]
sys.path.append(str(RACINE / "tools"))
S = importlib.import_module("nokido_agent.app.forge_critical_events")   # le module que les emetteurs importent reellement

JOUR = 86400.0
T0 = 1_800_000_000.0   # un instant fixe : la coupure de jour se calcule, jamais l'horloge du test


@pytest.fixture(autouse=True)
def base(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "DB_PATH", tmp_path / "critical_events.db")
    monkeypatch.setattr(S, "_INITIALIZED", False)


def _sujets(surface="demarrage", **k):
    return [a["sujet"] for a in S.alertes_en_attente(surface, maintenant=k.get("maintenant", T0), **{x: v for x, v in k.items() if x != "maintenant"})]


def test_une_alerte_hors_flap_est_emise_puis_silencieuse_24_h():
    assert S.alerter_owner("algedonic:delivery_integrity", "high", "d", "COAGULATION", maintenant=T0) == "emise"
    assert S.alerter_owner("algedonic:delivery_integrity", "high", "d", "COAGULATION", maintenant=T0 + 3600) == "silence"
    assert len(_sujets()) == 1
    assert S.alerter_owner("algedonic:delivery_integrity", "high", "d", "COAGULATION", maintenant=T0 + JOUR + 1) == "emise"


def test_une_gravite_qui_monte_passe_le_silence():
    S.alerter_owner("self_care", "warn", "d", "X", maintenant=T0)
    assert S.alerter_owner("self_care", "critical", "pire", "X", maintenant=T0 + 60) == "emise"


def test_les_flaps_sont_regroupes_en_un_resume_du_jour_passe():
    for service in ("NokidoA", "NokidoB", "NokidoA"):
        assert S.alerter_owner("flap:%s" % service, "warn", "d", "COAGULATION", maintenant=T0) == "regroupee"
    assert _sujets(maintenant=T0) == [], "le jour n'est pas fini, le resume n'existe pas encore"
    alertes = S.alertes_en_attente("demarrage", maintenant=T0 + JOUR + 1)
    assert len(alertes) == 1, "un seul resume, quel que soit le nombre de flaps"
    assert alertes[0]["sujet"].startswith("flaps:")
    assert "2 services" in alertes[0]["detail"]
    assert "NokidoA" in alertes[0]["detail"] and "NokidoB" in alertes[0]["detail"]
    assert S.alertes_en_attente("demarrage", maintenant=T0 + JOUR + 2)[0]["id"] == alertes[0]["id"], "pas de second resume"


def test_le_detail_est_borne():
    for i in range(60):
        S.alerter_owner("flap:Service%02d" % i, "warn", "d", "X", maintenant=T0)
    d = S.alertes_en_attente("demarrage", maintenant=T0 + JOUR + 1)[0]["detail"]
    assert "60 services" in d and len(d) < 600


def test_chaque_surface_a_sa_lecture():
    S.alerter_owner("a", "high", "d", "X", maintenant=T0)
    S.alerter_owner("b", "warn", "d", "X", maintenant=T0)
    tout = S.alertes_en_attente("demarrage", maintenant=T0)
    assert len(tout) == 2
    S.marquer_vues([a["id"] for a in tout], "demarrage", maintenant=T0)
    assert S.alertes_en_attente("demarrage", maintenant=T0) == []
    assert [a["sujet"] for a in S.alertes_en_attente("tray", gravite_min="high", maintenant=T0)] == ["a"], "le tray : high et critical"


def test_une_surface_inconnue_est_refusee():
    with pytest.raises(ValueError):
        S.alertes_en_attente("autre", maintenant=T0)


def test_la_coagulation_ecrit_au_registre_par_son_chemin_reel(monkeypatch):
    C = importlib.import_module("forge_coagulation")
    monkeypatch.setattr(C, "_log", lambda *_a: None)
    C._escalate({"kind": "algedonic:delivery_integrity", "severity": "high"}, "raison")
    a = S.alertes_en_attente("demarrage")
    assert [x["sujet"] for x in a] == ["algedonic:delivery_integrity"] and a[0]["gravite"] == "high"
    assert a[0]["emetteur"] == "COAGULATION"


def test_les_emetteurs_n_appellent_plus_notify_sans_destinataire():
    for nom in ("forge_coagulation.py", "forge_organ_pulse.py"):
        src = (RACINE / "tools" / nom).read_text(encoding="utf-8")
        assert ".notify(json.dumps" not in src, nom
        assert "alerter_owner(" in src, nom


class _FilFaux:
    lances = []

    def __init__(self, target, args, name, daemon):
        self.target, self.args, self.daemon = target, args, daemon

    def start(self):
        _FilFaux.lances.append(self)


def test_le_tray_montre_high_et_critical_une_seule_fois_sans_bloquer():
    """pystray est absent des jobs : la fonction du tray est extraite par le helper deja utilise pour la validation."""
    sys.path.append(str(RACINE / "tests" / "nr"))
    extraire = importlib.import_module("test_restart_fenetre_de_validation_nr")._fonction_du_tray
    _FilFaux.lances = []
    etat = {}
    releve = extraire("_relever_alertes", {"_state": etat, "threading": types.SimpleNamespace(Thread=_FilFaux),
                                           "_fenetre_alertes": lambda _a: None})
    S.alerter_owner("grave", "critical", "d", "X")
    S.alerter_owner("banal", "warn", "d", "X")
    releve()
    assert len(_FilFaux.lances) == 1 and _FilFaux.lances[0].daemon is True, "la fenetre vit dans son propre fil"
    assert [a["sujet"] for a in _FilFaux.lances[0].args[0]] == ["grave"]
    releve()
    assert len(_FilFaux.lances) == 1, "deja montree, pas de seconde fenetre"
    assert etat["alertes_why"] == ""


def test_les_tables_d_alertes_sont_purgees_sans_perdre_le_non_vu(monkeypatch):
    """Le gate anti-firehose l'a signale au commit : une table sans purge croit sans limite."""
    S.alerter_owner("vieille_vue", "warn", "d", "X", maintenant=T0)
    S.alerter_owner("vieille_non_vue", "warn", "d", "X", maintenant=T0)
    S.alerter_owner("recente", "warn", "d", "X", maintenant=T0 + 89 * JOUR)
    vues = [a["id"] for a in S.alertes_en_attente("demarrage", maintenant=T0) if a["sujet"] == "vieille_vue"]
    S.marquer_vues(vues, "demarrage", maintenant=T0)
    S.marquer_vues(vues, "tray", maintenant=T0)
    assert S.purger_alertes(jours=30, maintenant=T0 + 90 * JOUR) == 1
    restants = [a["sujet"] for a in S.alertes_en_attente("demarrage", maintenant=T0 + 90 * JOUR)]
    assert "vieille_non_vue" in restants and "recente" in restants, "une alerte jamais vue n'est jamais purgee"


def test_un_echec_de_base_se_dit_et_ne_leve_pas(monkeypatch):
    def refus():
        raise S.sqlite3.OperationalError("verrouillee")
    monkeypatch.setattr(S, "_conn", refus)
    assert S.alerter_owner("a", "high", "d", "X", maintenant=T0) == "echec"
