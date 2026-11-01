# -*- coding: utf-8 -*-
"""NR (31/10, choix owner) : un ordre de redemarrage EXECUTE se solde au boot du hub, et son demandeur est prevenu.

Mesure 31/10 : ordre-a30d00a73512 (restart-hub, demande par CLAUDE) valide par l'owner a ~12:27, hub reparti a
12:28:14 -- aucun compte rendu : ni message dans la boite du demandeur, ni evenement « atteint » au journal des
ordres. REQUESTED != ACCEPTED != ACHIEVED : le demandeur devait aller verifier seul. Owner : « le hub notifie ».
Au boot, `solder_redemarrages(boot_ts)` retrouve les restart/restart-hub PRIS avant ce boot (fenetre 1 h), non
soldes et non refuses, consigne « atteint » avec la preuve (heure de boot, pid) et previent le demandeur (M2M
OK_DONE, pointer_ref ordre:<id>). Idempotent. Un echec de notification est DIT, jamais tu.
"""
# pylint: disable=missing-function-docstring
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_ordres_bureau as ob  # noqa: E402


def _journal(tmp_path, monkeypatch, lignes):
    p = tmp_path / "ordres_bureau.jsonl"
    p.write_text("".join(json.dumps(l) + "\n" for l in lignes), encoding="utf-8")
    monkeypatch.setattr(ob, "JOURNAL", p)
    return p


def _restart(ident="ordre-x", action="restart-hub", pris=1050.0, demandeur="CLAUDE"):
    return [{"ts": pris - 50, "evenement": "depose", "id": ident, "action": action, "demandeur": demandeur},
            {"ts": pris, "evenement": "pris", "id": ident, "action": action, "consommateur": "TRAY"}]


def _evts(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_restart_pris_avant_le_boot_est_solde_et_le_demandeur_prevenu(tmp_path, monkeypatch):
    j = _journal(tmp_path, monkeypatch, _restart())
    recus = []
    r = ob.solder_redemarrages(1100.0, notifier=lambda dest, msg: recus.append((dest, msg)) or True)
    assert [o["id"] for o in r] == ["ordre-x"] and r[0]["notifie"] is True
    assert recus and recus[0][0] == "CLAUDE"
    m = json.loads(recus[0][1])
    assert m["intent"] == "OK_DONE" and m["pointer_ref"] == "ordre:ordre-x"
    dernier = _evts(j)[-1]
    assert dernier["evenement"] == "atteint" and dernier["id"] == "ordre-x"
    assert dernier["preuve"]["boot_hub_ts"] == 1100.0 and "pid" in dernier["preuve"]


def test_idempotent(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, _restart())
    recus = []
    ob.solder_redemarrages(1100.0, notifier=lambda d, m: recus.append(d) or True)
    assert ob.solder_redemarrages(1100.0, notifier=lambda d, m: recus.append(d) or True) == []
    assert recus == ["CLAUDE"]


def test_pris_apres_le_boot_n_est_pas_solde(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, _restart(pris=1200.0))
    assert ob.solder_redemarrages(1100.0, notifier=lambda d, m: True) == []


def test_trop_ancien_ignore(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, _restart(pris=1000.0))
    assert ob.solder_redemarrages(1000.0 + ob.FENETRE_SOLDE_S + 10, notifier=lambda d, m: True) == []


def test_refuse_par_l_owner_jamais_solde(tmp_path, monkeypatch):
    lignes = _restart() + [{"ts": 1060.0, "evenement": "refuse_owner", "id": "ordre-x", "action": "restart-hub"}]
    _journal(tmp_path, monkeypatch, lignes)
    assert ob.solder_redemarrages(1100.0, notifier=lambda d, m: True) == []


def test_autre_ordre_non_concerne(tmp_path, monkeypatch):
    _journal(tmp_path, monkeypatch, _restart(action="dev-armer"))
    assert ob.solder_redemarrages(1100.0, notifier=lambda d, m: True) == []


def test_echec_de_notification_dit(tmp_path, monkeypatch, caplog):
    j = _journal(tmp_path, monkeypatch, _restart())
    r = ob.solder_redemarrages(1100.0, notifier=lambda d, m: False)
    assert r and r[0]["notifie"] is False
    assert _evts(j)[-1]["evenement"] == "atteint" and _evts(j)[-1]["notifie"] is False


def test_le_compte_rendu_va_dans_la_boite_que_le_demandeur_lit():
    """Mesure 31/10 14:02:43 : ordre-39ab7300011c solde « atteint, notifie: true » -- mais depose pour to_agent
    « CLAUDE » alors que la boite relevee est « agt_claude » (claude_inbox_tick, SessionStart) : jamais lu. La boite se
    resout par le registre (forge_videur.mailbox_de), chemin reel."""
    assert ob._boite_du_demandeur("CLAUDE") == "agt_claude"
    assert ob._boite_du_demandeur("agt_claude") == "agt_claude"
    assert ob._boite_du_demandeur("INCONNU_XYZ") == "agt_inconnu_xyz"


def test_le_hub_solde_au_boot():
    src = (ROOT / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    assert "solder_redemarrages(" in src
