"""NR 18/10 -- audit Gemini web verifie sur pieces + decision owner : la regle L1 gardait un changement NEUTRE.

`mesurer_apres` ne posait qu'une question (« a-t-on RECULE au-dela du bruit ? ») : sinon CONSERVE. Registre du 15/10 :
32 -> 40 (+0,42 txt/s) et 32 -> 24 (+1,70 txt/s) pour un bruit de 5,0 : CONSERVE les deux fois -- le reglage derivait
dans la bande de bruit. Le juge L2 applique deja la doctrine inverse (SURVIT != AMELIORE). Contrat aligne :
  * gain > +bruit sur au moins une dimension, aucun recul -> CONSERVE ;
  * aucun recul MAIS aucun gain hors bruit -> SURVIT_SANS_GAIN : l'acte est DEFAIT et le retour PROUVE (comme REVERTE),
    sans compter pour le frein des reverts consecutifs (ce n'est pas une degradation) ;
  * recul -> REVERTE (inchange).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_mutation_controller as m  # noqa: E402

BRUIT = {"textes_par_seconde": 5.0, "taux_succes": 0.0}
REF = {"textes_par_seconde": 49.148, "taux_succes": 1.0}


def _jouer(monkeypatch, apres):
    inscrits, freins, reverts = [], [], []
    monkeypatch.setattr(m, "_inscrire", lambda rec: inscrits.append(rec) or "id_test")
    monkeypatch.setattr(m, "_poser_frein", lambda motif: freins.append(motif) or {"pose": True})
    monkeypatch.setattr(m, "_generation_avant", lambda: None)
    monkeypatch.setattr(m, "_reverts_consecutifs", lambda: 0)
    mesures = iter([apres, dict(REF)])        # apres l'acte, puis apres le retour
    r = m.mesurer_apres("L1", "param:embed.batch_size", "exp", dict(REF), "E0",
                        mesurer=lambda: next(mesures), reverter=lambda: reverts.append(1) or {"ok": True},
                        empreinte=lambda: "E0", bruit=BRUIT)
    return r, inscrits, freins, reverts


def test_un_gain_dans_le_bruit_est_defait_sans_frein(monkeypatch):
    r, inscrits, freins, reverts = _jouer(monkeypatch, {"textes_par_seconde": 50.847, "taux_succes": 1.0})
    assert r["verdict"] == "SURVIT_SANS_GAIN", r
    assert reverts == [1], "un changement neutre doit etre DEFAIT"
    assert r.get("preuve", {}).get("empreinte_identique") is True, "le retour doit etre PROUVE"
    assert freins == [], "un retour sans gain n'est pas une degradation : pas de frein"
    assert inscrits and inscrits[-1].get("verdict") == "SURVIT_SANS_GAIN"


def test_un_gain_hors_bruit_est_conserve(monkeypatch):
    r, _, freins, reverts = _jouer(monkeypatch, {"textes_par_seconde": 55.0, "taux_succes": 1.0})
    assert r["verdict"] == "CONSERVE" and reverts == [] and freins == []


def test_un_recul_reste_reverte(monkeypatch):
    r, _, _, reverts = _jouer(monkeypatch, {"textes_par_seconde": 40.0, "taux_succes": 1.0})
    assert r["verdict"] == "REVERTE" and reverts == [1]
