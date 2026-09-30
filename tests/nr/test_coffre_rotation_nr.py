"""NR -- ROTATION des secrets exposes du coffre (etape 3, go owner 2026-09-28).

Toutes ces valeurs ont ete lisibles par les comptes bac a sable (coffre machine, registre
NSSM) : seule une rotation ferme la faille pour les valeurs deja lues. L'outil, sous SYSTEM :
  1. refuse hors SYSTEM ; sans --appliquer, n'ecrit RIEN ;
  2. chaque nom recoit une valeur NEUVE (distincte de l'ancienne et des autres), au format
     que ses consommateurs attendent (firewall_log_hmac = base64 de 32 octets) ;
  3. nom encore en TRANSITION : coffre reserve ET coffre machine (ses lecteurs hors SYSTEM y
     lisent) ; nom FERME : coffre reserve seulement, et la copie du coffre machine RETIREE ;
  4. chaque ecriture est RELUE ; aucune valeur n'est jamais affichee ;
  5. tout nom reserve a une decision : tourne ici, ou exclu avec son motif (cliquet).
"""
from __future__ import annotations

import base64
import importlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = "S-1-5-18"


def _outil():
    spec = importlib.util.spec_from_file_location("nr_rotation", ROOT / "tools/forge_coffre_rotation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def banc(monkeypatch):
    o = _outil()
    mv = importlib.import_module("nokido_agent.app.forge_machine_vault")
    reserve = {n: "ancienne-" + n for n in o.GENERATEURS}
    machine = {n: "ancienne-" + n for n in o.GENERATEURS}
    appels: list = []

    def vault_set(k, v):
        appels.append(("vault_set", k))
        reserve[k] = v
        machine[k] = v
        return True

    def reserve_set(k, v):
        appels.append(("reserve_set", k))
        reserve[k] = v
        return True

    def vault_delete(k):
        appels.append(("vault_delete", k))
        machine.pop(k, None)
        return True

    monkeypatch.setattr(mv, "_sid_courant", lambda: SYSTEM)
    monkeypatch.setattr(mv, "vault_set", vault_set)
    monkeypatch.setattr(mv, "reserve_set", reserve_set)
    monkeypatch.setattr(mv, "vault_delete", vault_delete)
    monkeypatch.setattr(mv, "reserve_lire", lambda k: (reserve.get(k), "TROUVE"))
    monkeypatch.setattr(o, "_journaliser", lambda noms: None)
    return o, mv, reserve, machine, appels


def test_hors_system_refus_et_sans_appliquer_rien_n_est_ecrit(banc, monkeypatch, capsys):
    o, mv, reserve, _machine, appels = banc
    avant = dict(reserve)
    monkeypatch.setattr(mv, "_sid_courant", lambda: "S-1-5-21-1-2-3-1001")
    rc_hors = o.main([])
    monkeypatch.setattr(mv, "_sid_courant", lambda: SYSTEM)
    rc_plan = o.main([])
    capsys.readouterr()
    assert (rc_hors, rc_plan, appels, reserve == avant) == (2, 0, [], True)


def test_appliquer_tourne_tout_selon_transition_ou_fermeture(banc, capsys):
    o, _mv, reserve, machine, appels = banc
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    rc = o.main(["--appliquer"])
    sortie = capsys.readouterr()
    transition = set(o.GENERATEURS) & fs.RESERVES_EN_TRANSITION
    fermes = set(o.GENERATEURS) - fs.RESERVES_EN_TRANSITION
    ok = (rc,
          all(("vault_set", n) in appels for n in transition),
          all(("reserve_set", n) in appels and ("vault_delete", n) in appels for n in fermes),
          all(n not in machine for n in fermes),
          all(not reserve[n].startswith("ancienne-") for n in o.GENERATEURS),
          len({reserve[n] for n in o.GENERATEURS}) == len(o.GENERATEURS),
          any(reserve[n] in sortie.out + sortie.err for n in o.GENERATEURS))
    assert ok == (0, True, True, True, True, True, False)


def test_les_formats_attendus_par_les_consommateurs(banc):
    o, *_ = banc
    ok = (len(base64.b64decode(o.GENERATEURS["firewall_log_hmac"]())),
          all(len(o.GENERATEURS[n]()) >= 43 for n in o.GENERATEURS))
    assert ok == (32, True)


def test_une_ecriture_non_relue_est_un_echec(banc, monkeypatch, capsys):
    o, mv, *_ = banc
    monkeypatch.setattr(mv, "reserve_lire", lambda k: ("autre-chose", "TROUVE"))
    rc = o.main(["--appliquer"])
    capsys.readouterr()
    assert rc == 1


def test_tout_nom_reserve_a_une_decision():
    o = _outil()
    fs = importlib.import_module("nokido_agent.app.forge_secrets")
    sans_decision = fs.NOMS_RESERVES - set(o.GENERATEURS) - set(o.HORS_ROTATION)
    assert sans_decision == set()
