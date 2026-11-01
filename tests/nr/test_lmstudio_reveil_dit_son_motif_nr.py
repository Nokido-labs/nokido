"""NR : un reveil LM Studio dont le CANAL est refuse remonte un refus nomme, jamais un 10061 muet (30/10).

Mesure du 30/10 (job_ef945fbc1d1f, diag job_9cd200f1e067) : RAM 68 % (sous le plafond), tache `Nokido-LMStudio-Start`
« refusee » vue du compte du bac. `_lmstudio` attendait 30 s un port qui ne pouvait pas s'ouvrir puis rendait
« port muet apres start » SANS `refus` ; le proxy laissait alors l'appel mourir en URLError 10061 (« injoignable »).
Le contrat existant reste : un demarrage LANCE dont le port tarde n'est pas un refus
(test_ensure_service_lmstudio_nr::test_echec_sans_refus_laisse_l_appel_trancher).
"""
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app"), str(RACINE / "tools")]
from nokido_agent.app import forge_agent_proxy as P  # noqa: E402
from nokido_agent.tools import forge_ensure_service as E  # noqa: E402


def _canal_refuse(monkeypatch):
    monkeypatch.setattr(E, "_lms_bin", lambda: None)
    monkeypatch.setattr(E, "_sonde_lmstudio", lambda **k: False)
    monkeypatch.setattr(E, "_ram_libre_go", lambda: 8.0)
    monkeypatch.setattr(E, "_jouer", lambda b, o, d: "[tache Nokido-LMStudio-Start] %s (ACL). Compte MESURE ici : "
                                                   "'LaForgeSbxOnline'." % E._MARQUE_TACHE_INVISIBLE)

    def _interdit(*a, **k):
        raise AssertionError("attente du port alors que rien n'a ete lance")
    monkeypatch.setattr(E, "_attendre_port", _interdit)


def test_canal_invisible_est_un_refus_nomme_sans_attente(monkeypatch):
    _canal_refuse(monkeypatch)
    r = E._lmstudio("running")
    assert r["success"] is False and r["refus"] == "canal_invisible" and "INVISIBLE" in r["detail"]


def test_le_proxy_remonte_le_refus_du_canal(monkeypatch):
    _canal_refuse(monkeypatch)
    monkeypatch.setattr(E, "_admission", lambda s, st: None, raising=False)
    monkeypatch.setattr(P, "_lmstudio_pilotage", lambda: E)
    monkeypatch.setattr(E, "ensure", lambda s, st: E._lmstudio(st))
    with pytest.raises(RuntimeError, match="canal_invisible"):
        P._lmstudio_reveiller_si_besoin()


def test_tache_desactivee_rc_non_nul_est_un_refus_sans_attente(monkeypatch):
    """30/10 04 h 02, vu du hub : « [tache Nokido-LMStudio-Start rc=1] ERREUR : ... elle est desactivee » -- rien
    n'a ete lance, mais _lmstudio attendait 30 s puis rendait « port muet apres start » sans refus."""
    _canal_refuse(monkeypatch)
    monkeypatch.setattr(E, "_jouer", lambda b, o, d: "[tache Nokido-LMStudio-Start rc=1] ERREUR : la tache planifiee "
                                                   "n'a pas pu s'executer, car elle est desactivee.")
    r = E._lmstudio("running")
    assert r["success"] is False and r["refus"] == "canal_echec" and "rc=1" in r["detail"]


def test_tache_lancee_rc_zero_garde_l_attente(monkeypatch):
    _canal_refuse(monkeypatch)
    monkeypatch.setattr(E, "_jouer", lambda b, o, d: "[tache Nokido-LMStudio-Start rc=0] OPERATION REUSSIE")
    monkeypatch.setattr(E, "_attendre_port", lambda vise, s: False)
    r = E._lmstudio("running")
    assert r["success"] is False and "refus" not in r      # lance mais lent : contrat existant, l'appel tranche


def test_la_marque_est_celle_qu_emet_le_lanceur_de_tache(monkeypatch):
    monkeypatch.setattr(E, "_etat_tache", lambda nom: "refusee")
    assert E._MARQUE_TACHE_INVISIBLE in (E.declencher_tache("Nokido-LMStudio-Start") or "")
