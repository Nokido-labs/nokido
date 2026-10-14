# -*- coding: utf-8 -*-
"""NR -- l'integration WSL cassee de Docker Desktop declenche le cycle prouve, une fois par episode (2026-10-13).

Owner : « a chaque mise a jour de docker j'ai ce probleme ». Le journal de Docker Desktop porte la signature
(« waiting 1m0s for the backend socket … DockerDesktop/Wsl/ExecError ») toutes les ~75 s ; le moteur repond, donc
le keeper se disait « ok » et ne faisait rien. Remede prouve (wsl --shutdown) deja dans le keeper, jamais declenche
par ce symptome. Proprietes : signal = journal de l'organe ; une ligne ancienne ne declenche rien ; un journal
illisible n'est pas « pas de panne » ; un seul cycle par refractaire (jamais de boucle) ; rien si Docker n'est pas
reclame.
"""
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

k = pytest.importorskip("forge_docker_keeper")

SIG = ("[{ts}.536099300Z][com.docker.backend.exe.wslintegration] distro agent Debian exited unexpectedly: running "
       "wsl distro proxy in Debian distro: waiting 1m0s for the backend socket: running wslexec: An error occurred "
       "while running the command. DockerDesktop/Wsl/ExecError: c:\\windows\\system32\\wsl.exe -d debian -u root -e "
       "test -s /mnt/wsl/docker-desktop/shared-sockets/host-services/backend.sock: exit status 1\n")


def _ligne(il_y_a_s: float) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(seconds=il_y_a_s)).strftime("%Y-%m-%dT%H:%M:%S")
    return SIG.format(ts=ts)


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    p = tmp_path / "com.docker.backend.exe.log"
    p.write_text("[2026-01-01T00:00:00.0Z][x] demarrage\n", encoding="utf-8")
    monkeypatch.setenv("DOCKER_KEEPER_DESKTOP_LOG", str(p))
    monkeypatch.setattr(k, "_INTEGRATION", {"fichier": None, "pos": None, "dernier_cycle": 0.0,
                                            "sans_effet_dit": False})
    monkeypatch.setattr(k, "_audit", lambda *a, **kw: None)
    cycles = []
    monkeypatch.setattr(k, "_force_recycle_docker", lambda *a, **kw: cycles.append(a) or False)
    monkeypatch.setattr(k, "_docker_wanted", lambda: True)
    monkeypatch.setitem(k._STATE, "last_boot_ok_ts", 0.0)
    # Jamais la VRAIE moelle depuis un test : l'afference est remplacee et ses emissions comptees.
    afferent = types.ModuleType("forge_organ_afferent")
    afferent.emissions = []
    afferent.emettre = lambda prod, organe, mesures, **kw: afferent.emissions.append(mesures) or (True, "")
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_organ_afferent", afferent)
    return p, cycles


def _ajouter(p, texte):
    with open(p, "a", encoding="utf-8") as f:
        f.write(texte)


def test_seules_les_signatures_recentes_comptent(journal):
    p, _ = journal
    _ajouter(p, _ligne(3600) + _ligne(30) + _ligne(5))
    assert k._integration_wsl_cassee() == 2


def test_une_ligne_deja_lue_n_est_pas_recomptee(journal):
    p, _ = journal
    _ajouter(p, _ligne(10))
    assert k._integration_wsl_cassee() == 1
    assert k._integration_wsl_cassee() == 0


def test_journal_illisible_n_est_pas_pas_de_panne(journal, monkeypatch, tmp_path):
    _, cycles = journal
    monkeypatch.setenv("DOCKER_KEEPER_DESKTOP_LOG", str(tmp_path / "absent.log"))
    assert k._surveiller_integration_wsl() == {"integration_wsl": "ILLISIBLE"}
    assert cycles == []


def test_un_seul_cycle_par_refractaire(journal):
    p, cycles = journal
    _ajouter(p, _ligne(20))
    st = k._surveiller_integration_wsl()
    assert st["integration_wsl"] == "CASSEE" and len(cycles) == 1
    _ajouter(p, _ligne(1))
    st = k._surveiller_integration_wsl()
    assert len(cycles) == 1, "un remede sans effet ne doit pas boucler"
    assert st["integration_wsl_refractaire_s"] > 0


def test_aucun_cycle_si_docker_n_est_pas_reclame(journal, monkeypatch):
    p, cycles = journal
    monkeypatch.setattr(k, "_docker_wanted", lambda: False)
    _ajouter(p, _ligne(20))
    st = k._surveiller_integration_wsl()
    assert st["integration_wsl"] == "CASSEE" and cycles == []


AJOUT = "[{ts}.698623600Z][com.docker.backend.exe.wslintegration] adding a wsl agent for new distro Debian\n"


def _ajout(il_y_a_s: float) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(seconds=il_y_a_s)).strftime("%Y-%m-%dT%H:%M:%S")
    return AJOUT.format(ts=ts)


def test_journal_sans_preuve_dit_inconnu_jamais_ok(journal):
    # 2026-10-13 : mon premier cablage concluait « ok » d'un journal MUET -- Docker Desktop peut avoir cesse de
    # reessayer. Sans ligne d'ajout d'agent, aucune preuve de sante.
    assert k._surveiller_integration_wsl() == {"integration_wsl": "INCONNU"}


def test_agent_ajoute_sans_erreur_depuis_90_s_dit_ok(journal):
    p, _ = journal
    _ajouter(p, _ligne(900) + _ajout(200))  # erreur ANCIENNE (hors fenetre), puis agent ajoute sans erreur
    assert k._surveiller_integration_wsl() == {"integration_wsl": "ok"}


def test_agent_ajoute_trop_recemment_reste_inconnu(journal):
    p, _ = journal
    _ajouter(p, _ajout(20))
    assert k._surveiller_integration_wsl() == {"integration_wsl": "INCONNU"}


def test_une_mise_a_jour_declenche_le_cycle_preventif(journal):
    # Owner 13/10 : « plus reactif ». La version du serveur change AVANT que la distro ne casse.
    _, cycles = journal
    k._surveiller_integration_wsl("29.7.2")
    st = k._surveiller_integration_wsl("29.8.2")
    assert st["integration_wsl"] == "MISE_A_JOUR" and st["docker_mise_a_jour"] == "29.7.2 -> 29.8.2"
    assert len(cycles) == 1 and "PREVENTIF" in cycles[0][0]


def test_pas_de_cycle_preventif_si_le_keeper_a_relance_docker_lui_meme(journal):
    _, cycles = journal
    k._surveiller_integration_wsl("29.7.2")
    k._STATE["last_boot_ok_ts"] = time.monotonic() + 1  # son lancement fait deja wsl --shutdown
    k._surveiller_integration_wsl("29.8.2")
    assert cycles == []


def test_la_moelle_recoit_chaque_transition_une_seule_fois():
    afferent = sys.modules["nokido_agent.app.forge_organ_afferent"]
    k._surveiller_integration_wsl()
    k._surveiller_integration_wsl()
    assert [e["integration_wsl"] for e in afferent.emissions] == ["INCONNU"]


@pytest.fixture(autouse=True)
def _toujours_isole(journal):
    # Garantit l'isolation (journal simule, moelle simulee) pour CHAQUE test, y compris ceux sans argument.
    yield
