"""NR -- `nokido-doctor --vivant` : ce qui BAT sur cette machine, organe par organe.

Owner 2026-10-01 : « tu ne mesures pas un etat fige mais un corps vivant ». Le README
ne porte plus d'instantane (« daemon running » au 30/09) : il designe la commande qui
demande l'etat au corps, sur la machine du lecteur. Source : forge_nervous_map.autorites()
(pouls brut ET inference, quatre etats, jamais deux).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _doctor():
    chemin = ROOT / "tools" / "nokido_doctor.py"
    spec = importlib.util.spec_from_file_location("nokido_doctor_vivant", chemin)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nokido_doctor_vivant"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fiche(organe, vivant, preuve="p", service=None, eteint=None, age=12.0, superviseur=None):
    return {"organe": organe, "service": service, "producteur_vivant": vivant,
            "producteur_preuve": preuve, "eteint_par_decision": eteint, "age_s": age,
            "supervisor": {"valeur": superviseur or "superviseur services.toml", "etat": "declare"}}


def _autorites(*fiches, sources=None):
    return {"organes": list(fiches), "n": len(fiches),
            "sources": sources or {"services.toml": "ok (3 services)", "pouls_disque": "ok (3)"}}


def test_les_quatre_etats_sont_distincts():
    m = _doctor()
    txt = m.rendre_vivant(_autorites(
        _fiche("hormones", "OUI", service="NokidoHormonesListener"),
        _fiche("veille", "INCERTAIN", "heartbeat_frais_sans_pid (identity_unbound)"),
        _fiche("orphelin", "NON", "heartbeat_frais_pid_mort (ORPHELIN)"),
        _fiche("muet", "INCONNU", "aucun_pouls")))
    for organe in ("hormones", "veille", "orphelin", "muet"):
        assert organe in txt
    assert "VIVANT" in txt and "INCERTAIN" in txt and "NE BAT PLUS" in txt and "ILLISIBLE" in txt


def test_un_organe_coupe_par_politique_n_est_jamais_dit_mort():
    """DISABLED_BY_POLICY != DEAD : un choix ne se repare pas."""
    m = _doctor()
    txt = m.rendre_vivant(_autorites(
        _fiche("a2a", "NON", "heartbeat_stale", service="NokidoA2A",
               superviseur="eteint par decision (disabled=true)")))
    bloc_coupe = txt.split("COUPE PAR POLITIQUE")[1]
    assert "a2a" in bloc_coupe
    bloc_mort = txt.split("NE BAT PLUS")[1].split("COUPE PAR POLITIQUE")[0]
    assert "a2a" not in bloc_mort


def test_un_organe_a_la_demande_REVEILLE_est_vivant_pas_coupe():
    """Mesure reelle 2026-10-01 : NokidoIngestDaemon (disabled = a la demande) battait,
    pid present, et le premier rendu le rangeait « coupe par politique ». Une politique
    ne masque jamais un pouls frais."""
    m = _doctor()
    txt = m.rendre_vivant(_autorites(
        _fiche("ingestion", "OUI", "heartbeat_frais_pid_present", service="NokidoIngestDaemon",
               superviseur="eteint par decision (disabled=true)")))
    bloc_vivant = txt.split("VIVANT (")[1].split("INCERTAIN (")[0]
    assert "ingestion" in bloc_vivant and "a la demande" in bloc_vivant
    assert "ingestion" not in txt.split("COUPE PAR POLITIQUE")[1].split("ILLISIBLE")[0]


def test_les_sources_illisibles_sont_DITES():
    m = _doctor()
    txt = m.rendre_vivant(_autorites(sources={"services.toml": "ok (3 services)",
                                              "pouls_disque": "PermissionError: refuse"}))
    assert "PermissionError" in txt


def test_vivant_passe_par_autorites_et_rend_zero(monkeypatch, capsys):
    """Le chemin reel du drapeau : main() -> autorites(), et une observation n'echoue pas."""
    m = _doctor()
    monkeypatch.setattr(m, "_autorites", lambda: _autorites(_fiche("pulse", "OUI")))
    assert m.main(["--vivant"]) == 0
    assert "pulse" in capsys.readouterr().out


def test_vivant_json(monkeypatch, capsys):
    m = _doctor()
    monkeypatch.setattr(m, "_autorites", lambda: _autorites(_fiche("pulse", "OUI")))
    assert m.main(["--vivant", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["organes"][0]["organe"] == "pulse"


def test_une_source_qui_casse_est_ILLISIBLE_pas_un_succes(monkeypatch, capsys):
    m = _doctor()

    def panne():
        raise RuntimeError("superviseur injoignable")
    monkeypatch.setattr(m, "_autorites", panne)
    assert m.main(["--vivant"]) == 2
    assert "ILLISIBLE" in capsys.readouterr().out
