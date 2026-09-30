"""NR -- `nokido_ensure_service` casse depuis 13a8d7383 (2026-09-28), et une boucle latente.

Mesure du 2026-09-28 : `nokido_ensure_service{NokidoRSSWatcher, restarted}` -> « forbidden ...
exige ring <= 2 ... ring 4 ». Chaine : le hub (`_handle_ensure_service`, ring de l'appelant
DEJA verifie) lance `tools/forge_ensure_service.py` sous LaForgeTrusted, qui lance
`forge_supervisor_ctl restart`. Hors SYSTEM, ctl repassait ses mutations PAR LE HUB
(`nokido_ensure_service`, identite SUPERVISOR_CTL non provisionnee, ring 4) : refus -- et
si l'identite avait ete provisionnee, RECURSION sans fin hub -> ctl -> hub.
Le refus arrivait en minuscules (`forbidden`) ; ctl ne reconnaissait que `Forbidden` : pas de
repli, la relance gouvernee des services etait cassee.

Contrats :
  1. lance PAR le hub (`NOKIDO_CTL_DIRECT=1`, pose par forge_ensure_service), ctl parle au
     superviseur directement et ne rappelle JAMAIS le hub ;
  2. forge_ensure_service pose ce marqueur quand il lance ctl ;
  3. un refus explicite du hub est reconnu quelle que soit sa casse (repli dit).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _charger(rel: str, nom: str):
    spec = importlib.util.spec_from_file_location(nom, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_lance_par_le_hub_ctl_ne_rappelle_jamais_le_hub(monkeypatch, capsys):
    ctl = _charger("tools/forge_supervisor_ctl.py", "nr_ctl_sans_boucle")
    appels_hub: list = []
    appels_directs: list = []
    monkeypatch.setattr(ctl, "_sous_system", lambda: False)
    monkeypatch.setattr(ctl, "_via_hub", lambda a, s: appels_hub.append((a, s)))
    monkeypatch.setattr(ctl, "_call", lambda path, method="GET": appels_directs.append((path, method)) or (200, "ok"))
    monkeypatch.setenv("NOKIDO_CTL_DIRECT", "1")
    monkeypatch.setattr(sys, "argv", ["forge_supervisor_ctl.py", "restart", "NokidoNrService"])
    rc = ctl.main()
    capsys.readouterr()
    # Un restart direct peut faire plusieurs appels au superviseur ; le contrat est : aucun
    # appel au hub, et le superviseur appele pour CE service.
    ok = (rc, appels_hub, any("NokidoNrService" in p for p, _m in appels_directs))
    assert ok == (0, [], True)


def test_forge_ensure_service_pose_le_marqueur_en_lancant_ctl(monkeypatch):
    es = _charger("tools/forge_ensure_service.py", "nr_ensure_service_marqueur")
    vus: dict = {}

    class _R:
        returncode, stdout, stderr = 0, "", ""

    def _run(cmd, **kw):
        vus.update(kw.get("env") or {})
        vus["_cmd"] = cmd
        return _R()

    monkeypatch.setattr(es.subprocess, "run", _run)
    es._supervisor("restart", "NokidoNrService")
    ok = (vus.get("NOKIDO_CTL_DIRECT"), any("forge_supervisor_ctl" in str(x) for x in vus["_cmd"]))
    assert ok == ("1", True)


def test_un_refus_du_hub_est_reconnu_quelle_que_soit_sa_casse(monkeypatch):
    ctl = _charger("tools/forge_supervisor_ctl.py", "nr_ctl_refus_casse")
    hc = importlib.import_module("nokido_agent.app.forge_hub_client")
    refus = ("{'error': 'forbidden', 'reason': 'SECURITY: nokido_ensure_service exige ring <= 2 "
             "(TRUSTED)', 'ring': 4}")
    monkeypatch.setattr(hc, "_resoudre_jeton", lambda agent: ("", "AUCUN"))   # aucun vrai jeton lu
    monkeypatch.setattr(hc.HubClient, "tool", lambda self, nom, args: refus)
    assert ctl._via_hub("restart", "NokidoNrService") is None
