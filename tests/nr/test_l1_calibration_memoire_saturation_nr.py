"""NR 18/10 -- audit Gemini web verifie + decision owner : l'oscillateur L1 n'avait AUCUNE memoire des verdicts.

`pat_l1_calibration` choisissait le sens par `n_actes % 2` (forge_autonomous_loops) : une valeur deja jugee sans
gain pouvait etre reproposee indefiniment. Contrat :
  * une valeur cible deja jugee SURVIT_SANS_GAIN, REVERTE ou REVERT_NON_PROUVE (moins de 30 jours) n'est plus proposee :
    l'autre sens est essaye ;
  * les deux sens deja juges sans gain -> le reglage est SATURE (`out["satures"]`), aucune proposition ;
  * un CONSERVE (gain prouve) ne bloque rien.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_autonomous_loops as al  # noqa: E402
from nokido_agent.app import forge_mutation_controller as ctl  # noqa: E402
from nokido_agent.app import forge_proposal_applier as pa  # noqa: E402

NOM = "embed.batch_size"
DECL = {"type": "int", "min": 8, "max": 128, "defaut": 32, "mesure": "x:y",
        "bruit": {"textes_par_seconde": 5.0}}


def _verdict(valeur, verdict, age_j=1.0):
    ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - age_j * 86400))
    return {"kind": "post_application", "cible": "param:%s" % NOM, "verdict": verdict, "status": verdict,
            "ts": ts, "application": {"param": NOM, "nouvelle": valeur, "ok": True}}


def _jouer(monkeypatch, registre):
    proposes = []
    monkeypatch.setattr(pa, "PARAMS_L1", {NOM: DECL})
    monkeypatch.setattr(pa, "valeur_l1", lambda nom, defaut=None: 32)
    monkeypatch.setattr(ctl, "_lire_registre", lambda: registre)
    monkeypatch.setattr(al, "_proposer", lambda **k: proposes.append(int(k["suggested_value"])))
    out = al.pat_l1_calibration()
    return out, proposes


def test_une_valeur_jugee_sans_gain_n_est_plus_reproposee(monkeypatch):
    out, proposes = _jouer(monkeypatch, [_verdict(40, "SURVIT_SANS_GAIN")])
    assert proposes == [24], "40 deja jugee sans gain : l'autre sens (24) doit etre essaye, pas 40"


def test_les_deux_sens_juges_sans_gain_saturent_le_reglage(monkeypatch):
    out, proposes = _jouer(monkeypatch, [_verdict(40, "SURVIT_SANS_GAIN"), _verdict(24, "REVERTE")])
    assert proposes == [], "les deux sens ont deja ete juges sans gain : rien a proposer"
    assert NOM in out.get("satures", []), out


def test_un_conserve_ou_un_vieux_verdict_ne_bloquent_rien(monkeypatch):
    _, proposes = _jouer(monkeypatch, [_verdict(40, "CONSERVE"), _verdict(24, "SURVIT_SANS_GAIN", age_j=45)])
    assert proposes and proposes[0] in (40, 24), proposes
