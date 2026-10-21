# -*- coding: utf-8 -*-
"""NR -- une fuite de handles HORS corps est nommee, mesuree dans le temps, et son remede arrive a l'owner sans
console administrateur (owner 2026-10-19 : « faut solutionner ca durablement »).

Mesure du 19/10 : RAM a 83 %, verdict d'attribution NON_SOI -- juste. Mais 1 067 230 handles systeme dont
audiodg.exe 690 705 (+~200/min, vivant depuis le boot) et SwUSB.exe 195 394 (utilitaire Realtek XP-8.1 lance par le
service RunSwUSB). Le journal portait « ... | handles: » et RIEN apres : `resume_attribution` nomme les detenteurs
EN FIN de ligne et l'audit tronque vers 200 caracteres. Le remede (relancer Audiosrv) a echoue une fois en
console non administrateur avant de passer en auto-elevation. Remede applique : RunSwUSB desactive, audio relance
-> 182 409 handles, RAM 68 %.

Contrat :
  1. `resume_attribution` nomme le premier detenteur de handles dans ses 180 premiers caracteres ;
  2. `pente_handles(historique, fenetre_s)` : handles/min par pid sur la fenetre ; un seul point ou une duree
     couverte < fenetre/2 -> ABSENT (pas 0 : une pente non mesuree n'est pas une pente nulle) ;
  3. `fuyards_hors_corps(top_handles, pentes, ...)` : NON_SOI au-dessus d'un seuil de handles OU d'une pente ;
     le corps n'y figure jamais (ses fuites relevent de l'executif Hamilton) ;
  4. `forge_ordres_bureau` porte l'ordre `audio-relancer` (confirme par l'owner, execute par le tray avec UAC) et
     `remede_hors_corps` / `proposer_remedes` : audiodg -> cet ordre, en M2M NEED_HUMAN_APPROVAL ; inconnu -> rien
     d'invente ;
  5. `attribuer_pression` mesure la pente et le gestionnaire de ressources propose le remede.
"""
import inspect
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_ordres_bureau as ob  # noqa: E402
import forge_resource_manager as rm  # noqa: E402

pytestmark = pytest.mark.timeout(60)

ATTRIB_19_10 = {
    "verdict": "NON_SOI", "soi_gb": 11.7, "non_soi_gb": 15.7, "incertain_gb": 0.0, "illisibles": 0,
    "noyau_pagine_gb": 3.4, "noyau_non_pagine_gb": 1.8, "handles_systeme": 1069554,
    "top_non_soi": [{"name": "firefox.exe", "pid": 1, "gb": 2.1}, {"name": "audiodg.exe", "pid": 5252, "gb": 1.2},
                    {"name": "firefox.exe", "pid": 2, "gb": 0.9}],
    "top_handles": [{"name": "audiodg.exe", "pid": 5252, "handles": 690705, "classe": "non_soi"},
                    {"name": "SwUSB.exe", "pid": 7756, "handles": 195394, "classe": "non_soi"},
                    {"name": "System", "pid": 4, "handles": 10525, "classe": "non_soi"}],
}


def test_le_resume_nomme_le_fuyard_avant_la_coupe_du_journal():
    s = rm.resume_attribution(ATTRIB_19_10)
    assert "audiodg.exe 690705" in s[:180], s


def test_pente_mesuree_sur_une_fenetre_jamais_supposee():
    hist = {5252: [(0.0, 600000), (300.0, 603000), (600.0, 606000)],
            7756: [(600.0, 195394)],                         # un seul point
            42: [(500.0, 1000), (600.0, 5000)]}              # 100 s couvertes sur 600 : trop court
    p = rm.pente_handles(hist, fenetre_s=600.0)
    assert p[5252] == pytest.approx(600.0)
    assert 7756 not in p and 42 not in p


def test_seul_le_hors_corps_est_un_fuyard():
    top = ATTRIB_19_10["top_handles"] + [{"name": "python.exe", "pid": 9, "handles": 400000, "classe": "soi"}]
    f = rm.fuyards_hors_corps(top, {5252: 200.0}, seuil_handles=100000, seuil_pente=100.0)
    assert [x["name"] for x in f] == ["audiodg.exe", "SwUSB.exe"]
    assert f[0]["pente_min"] == pytest.approx(200.0) and f[1].get("pente_min") is None


def test_ordre_audio_relancer_confirme_et_execute_par_le_tray():
    assert "audio-relancer" in ob.ACTIONS and "audio-relancer" not in ob.SANS_CONFIRMATION
    lanceur = (RACINE / "tools" / "nokido_launcher.py").read_text(encoding="utf-8")
    tray = (RACINE / "tools" / "nokido_tray.py").read_text(encoding="utf-8")
    assert '"audio-relancer"' in lanceur and "Audiosrv" in lanceur
    assert '"audio-relancer"' in tray


def test_remede_connu_propose_inconnu_seulement_nomme():
    assert ob.remede_hors_corps({"name": "audiodg.exe"}) == "audio-relancer"
    assert ob.remede_hors_corps({"name": "SwUSB.exe"}) is None
    props = ob.proposer_remedes([{"name": "audiodg.exe", "pid": 5252, "handles": 690705, "pente_min": 200.0},
                                 {"name": "SwUSB.exe", "pid": 7756, "handles": 195394}])
    assert len(props) == 1
    assert props[0]["intent"] == "NEED_HUMAN_APPROVAL" and props[0]["pointer_ref"] == "ordre:audio-relancer"


def test_le_corps_mesure_la_pente_et_propose_le_remede():
    assert "pente_handles" in inspect.getsource(rm.attribuer_pression)
    assert "proposer_remedes" in inspect.getsource(rm)
