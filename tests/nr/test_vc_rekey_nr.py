"""NR -- CHANGEMENT du fichier-cle VeraCrypt de V: : plus JAMAIS par l'interface graphique.

Historique. Le 2026-09-28 (go owner), le changement de cle passait par trois phases dont une
etape dans l'interface graphique de VeraCrypt (« Ajouter/Supprimer des fichiers cles »). Cette
etape a reecrit les deux en-tetes de V: avec un verrou inconnu : V: inaccessible ~2 h, restaure
depuis les cliches VSS du 27/09. Consigne owner du meme jour : plus aucune manipulation VeraCrypt
a la main. Version graphique gelee dans l'historique git (35edce8c8).

Contrat :
  --rekey-preparer / --rekey-verifier : RETIRES -- refusent, ne creent rien, le disent.
  --rekey-finaliser (SYSTEM) : inchange -- exige SYSTEM et une nouvelle cle VERIFIEE ; range au
                    coffre reserve, retire la copie du coffre machine, efface les temporaires.
  --rekey-abandonner : n'efface que si l'ANCIENNE cle ouvre l'en-tete ACTUEL, prouve HORS
                    VeraCrypt en lecture seule (plus de montage) ; NON ou ILLISIBLE = refus.
"""
from __future__ import annotations

import base64
import importlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ANCIENNE = b"A" * 64
NOUVELLE = b"N" * 64


def _outil():
    spec = importlib.util.spec_from_file_location("nr_vc_rekey", ROOT / "tools/forge_at_rest_veracrypt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def vc(tmp_path, monkeypatch):
    m = _outil()
    monkeypatch.setattr(m, "REKEY_DIR", tmp_path / "vc_rekey")
    monkeypatch.setattr(m, "_is_admin", lambda: True)
    monkeypatch.setattr(m, "_is_mounted", lambda: False)
    commandes = []
    monkeypatch.setattr(m.subprocess, "run",
                        lambda cmd, **kw: commandes.append(list(cmd)) or type("R", (), {"returncode": 0})())
    return m, commandes


def _preparation(m, phase):
    m.REKEY_DIR.mkdir(parents=True)
    (m.REKEY_DIR / "ancien.kf").write_bytes(ANCIENNE)
    (m.REKEY_DIR / "nouveau.kf").write_bytes(NOUVELLE)
    m._rekey_ecrire_etat(phase)


def test_la_voie_graphique_est_retiree(vc, capsys):
    m, commandes = vc
    rc = (m.cmd_rekey_preparer(), m.cmd_rekey_verifier())
    sortie = capsys.readouterr().out
    assert rc == (1, 1)
    assert not m.REKEY_DIR.exists() and commandes == []
    assert "RETIRE" in sortie


def test_finaliser_exige_system_et_une_verification(vc, monkeypatch, capsys):
    m, _commandes = vc
    mv = importlib.import_module("nokido_agent.app.forge_machine_vault")
    ecrit, retire = {}, []
    monkeypatch.setattr(mv, "reserve_set", lambda k, v: ecrit.__setitem__(k, v) or True)
    monkeypatch.setattr(mv, "vault_delete", lambda k: retire.append(k) or True)
    monkeypatch.setattr(mv, "_sid_courant", lambda: "S-1-5-21-1-2-3-1001")
    _preparation(m, "prepare")
    rc_pas_system = m.cmd_rekey_finaliser()
    monkeypatch.setattr(mv, "_sid_courant", lambda: mv.RESERVE_COMPTE_SID)
    rc_pas_verifie = m.cmd_rekey_finaliser()
    m._rekey_ecrire_etat("verifie")
    rc_ok = m.cmd_rekey_finaliser()
    capsys.readouterr()
    ok = (rc_pas_system, rc_pas_verifie, rc_ok, ecrit.get(m.VAULT_KEY) == base64.b64encode(NOUVELLE).decode(),
          retire, m.REKEY_DIR.exists())
    assert ok == (1, 1, 0, True, [m.VAULT_KEY], False)


@pytest.mark.parametrize("verdict, efface", [("NON", False), ("ILLISIBLE", False), ("OUVRE", True)])
def test_abandonner_seulement_sur_preuve_hors_veracrypt(vc, monkeypatch, capsys, verdict, efface):
    m, commandes = vc
    _preparation(m, "prepare")
    vus = []

    def _verdict(cle, conteneur=None):
        vus.append(cle)
        return {"principal": verdict, "secours": verdict, "motif": "test" if verdict == "ILLISIBLE" else ""}

    monkeypatch.setattr(m, "verdict_cle_entete", _verdict)
    rc = m.cmd_rekey_abandonner()
    capsys.readouterr()
    assert (rc == 0, not m.REKEY_DIR.exists()) == (efface, efface)
    assert vus == [ANCIENNE]                    # c'est l'ANCIENNE cle qui est prouvee
    assert not any(c and c[0] == "VeraCrypt.exe" for c in commandes)   # aucun montage
