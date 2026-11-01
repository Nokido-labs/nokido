"""NR -- arret effectif de Docker (24/10) : sans vrai Docker, avec un faux client.

Mesures du 24/10 : `docker desktop stop` rend rc=0 mais le daemon repond encore ; crawl4ai (restart=always a la
creation) redemarrait seul. Garde : politique restart=no posee A L'ARRET, drapeau crawl4ai.wanted retire, arret
du moteur VERIFIE (REQUESTED != ACHIEVED), escalade bornee a la seule distribution docker-desktop, verdict honnete.
Verification d'etat reel : Docker repond-il ? distributions WSL docker-desktop* arretees ?
Rend ARRETE / ENCORE_VIVANT / ILLISIBLE (ILLISIBLE n'est jamais interprete comme ARRETE).
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)
RACINE = Path(__file__).resolve().parents[2]


def _charger_keeper():
    spec = importlib.util.spec_from_file_location("keeper_arret_nr", RACINE / "tools" / "forge_docker_keeper.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _keeper(monkeypatch, tmp_path, moteur_meurt_apres):
    """moteur_meurt_apres : fragment de commande dont l'execution eteint le moteur (None = jamais)."""
    m = _charger_keeper()
    etat = {"up": True}
    appels: list[list[str]] = []

    def run(cmd, *a, **k):
        appels.append(list(cmd))
        out = ""
        if cmd[:2] == ["docker", "ps"]:
            out = "laforge-crawl4ai-1\n"
        if moteur_meurt_apres and moteur_meurt_apres in " ".join(cmd):
            etat["up"] = False
        return subprocess.CompletedProcess(cmd, 0, out, "")
    monkeypatch.setattr(m.subprocess, "run", run)
    monkeypatch.setattr(m.time, "sleep", lambda s: None)
    monkeypatch.setattr(m, "_moteur_repond", lambda: etat["up"], raising=False)
    monkeypatch.setattr(m, "_distros_wsl_docker_arretees", lambda: True, raising=False)
    flag = tmp_path / "crawl4ai.wanted"
    flag.write_text("1")
    monkeypatch.setattr(m, "CRAWL4AI_FLAG", flag)
    return m, appels, flag


def test_conteneur_a_la_demande_ne_redemarre_pas_sans_reclamation(monkeypatch, tmp_path):
    m, appels, flag = _keeper(monkeypatch, tmp_path, "desktop stop")
    m._release_docker()
    assert not flag.exists(), "la reclamation crawl4ai doit etre retiree a la relache"
    assert any(c[:2] == ["docker", "update"] and "--restart=no" in c for c in appels), appels
    assert m._demarrer_crawl4ai(1e12) is None


def test_arret_verifie_apres_desktop_stop(monkeypatch, tmp_path):
    m, appels, _ = _keeper(monkeypatch, tmp_path, "desktop stop")
    r = m._release_docker()
    assert r["engine_verdict"].startswith("ARRETE"), r
    assert r.get("etat_reel") == "ARRETE", r
    assert not any("--terminate" in c for c in appels)


def test_escalade_ne_touche_que_docker_desktop(monkeypatch, tmp_path):
    m, appels, _ = _keeper(monkeypatch, tmp_path, "--terminate docker-desktop")
    r = m._release_docker()
    assert r["engine_verdict"].startswith("ARRETE"), r
    assert r.get("etat_reel") == "ARRETE", r
    terms = [c for c in appels if "--terminate" in c]
    assert terms and all(c[-1].startswith("docker-desktop") for c in terms), terms
    assert not any("--shutdown" in c for c in appels)


def test_moteur_tenace_verdict_non_arrete_avec_raison(monkeypatch, tmp_path):
    m, _, _ = _keeper(monkeypatch, tmp_path, None)
    r = m._release_docker()
    assert r["engine_verdict"].startswith("NON ARRETE"), r
    assert "repond encore" in r["engine_verdict"]
    assert r.get("etat_reel") == "ENCORE_VIVANT", r


# ── Tests de verification d'etat reel (REQUESTED != ACHIEVED) ───────────────

def test_verifier_etat_arret_atteint_arrete():
    """Cas 1 : Docker ne repond pas ET distros WSL docker-desktop* arretees -> ARRETE."""
    m = _charger_keeper()
    verdict = m.verifier_etat_arret(sonde_docker=lambda: False, sonde_wsl=lambda: True)
    assert verdict == "ARRETE"


def test_verifier_etat_arret_encore_vivant_si_docker_ou_wsl_actif():
    """Cas 2 : Docker repond encore OU distro WSL docker-desktop* active -> ENCORE_VIVANT."""
    m = _charger_keeper()
    # Docker repond encore
    assert m.verifier_etat_arret(sonde_docker=lambda: True, sonde_wsl=lambda: True) == "ENCORE_VIVANT"
    assert m.verifier_etat_arret(sonde_docker=lambda: True, sonde_wsl=lambda: False) == "ENCORE_VIVANT"

    # Docker ne repond pas mais distribution WSL docker-desktop encore active
    assert m.verifier_etat_arret(sonde_docker=lambda: False, sonde_wsl=lambda: False) == "ENCORE_VIVANT"
    assert m.verifier_etat_arret(sonde_docker=lambda: False, sonde_wsl=lambda: ["docker-desktop"]) == "ENCORE_VIVANT"


def test_verifier_etat_arret_illisible_nest_jamais_arrete():
    """Cas 3 : Sonde Docker ou WSL indisponible / exception -> ILLISIBLE, jamais ARRETE."""
    m = _charger_keeper()

    def _crash():
        raise RuntimeError("sonde indisponible / communication interrompue")

    # Sonde Docker illisible ou crashante : ne doit JAMAIS donner ARRETE
    v1 = m.verifier_etat_arret(sonde_docker=lambda: None, sonde_wsl=lambda: True)
    assert v1 == "ILLISIBLE"
    assert v1 != "ARRETE"

    v2 = m.verifier_etat_arret(sonde_docker=_crash, sonde_wsl=lambda: True)
    assert v2 == "ILLISIBLE"
    assert v2 != "ARRETE"

    # Sonde WSL illisible ou crashante alors que Docker ne repond pas : ne doit JAMAIS donner ARRETE
    v3 = m.verifier_etat_arret(sonde_docker=lambda: False, sonde_wsl=lambda: None)
    assert v3 == "ILLISIBLE"
    assert v3 != "ARRETE"

    v4 = m.verifier_etat_arret(sonde_docker=lambda: False, sonde_wsl=_crash)
    assert v4 == "ILLISIBLE"
    assert v4 != "ARRETE"

    # Les deux sondes en defaut
    v5 = m.verifier_etat_arret(sonde_docker=_crash, sonde_wsl=_crash)
    assert v5 == "ILLISIBLE"
    assert v5 != "ARRETE"


def test_verifier_etat_arret_monkeypatch_et_aliases(monkeypatch):
    """Verifie le fonctionnement sans sondes explicites (monkeypatching) et la presence des alias."""
    m = _charger_keeper()

    # Aliases exposes
    assert callable(m.verifier_etat_reel)
    assert callable(m.verifier_arret_effectif)
    assert callable(m.verifier_fin_de_vie)

    # Monkeypatching des sondes internes
    monkeypatch.setattr(m, "_moteur_repond", lambda: False)
    monkeypatch.setattr(m, "_distros_wsl_docker_arretees", lambda: True)
    assert m.verifier_etat_arret() == "ARRETE"
    assert m.verifier_etat_reel() == "ARRETE"

    monkeypatch.setattr(m, "_moteur_repond", lambda: True)
    assert m.verifier_etat_arret() == "ENCORE_VIVANT"

    monkeypatch.setattr(m, "_moteur_repond", lambda: False)
    monkeypatch.setattr(m, "_distros_wsl_docker_arretees", lambda: None)
    v = m.verifier_etat_arret()
    assert v == "ILLISIBLE"
    assert v != "ARRETE"
