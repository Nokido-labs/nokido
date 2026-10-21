"""NR -- un job detache passe par la MEME admission, quelle que soit la voie (16/10).

RED ecrit par Claude, trou signale par claude.ai (chantier A, inventaire Hamilton) et
VERIFIE sur alpha c781664df : la voie MCP `run action=run_job` (forge_mcp_registry
~L4005-4060) deduit une lane par defaut (`auto:<fichier>`), appelle
`forge_lane_admission.check_ressources(heavy=True)` (FAIL-CLOSED, anti-embolie du
2026-08-02) hors de la boucle, puis refuse une lane occupee. La voie REST
`POST /admin/run_job` (nokido_hub.admin_run_job) passe bien par `launch_job` mais ne
fait AUCUN des trois : un job lourd lance par REST sur une machine a 96 % de RAM
n'est pas refuse, et deux lancements du meme travail s'empilent.

Le controle vit dans l'organe qui lance (forge_job_runner), appele par les DEUX
voies : un garde qu'on franchit en changeant de porte ne garde rien.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
HUB = RACINE / "tools" / "nokido_hub.py"
REGISTRE = RACINE / "app" / "forge_mcp_registry.py"


def _modules():
    jr = importlib.import_module("nokido_agent.app.forge_job_runner")
    la = importlib.import_module("nokido_agent.app.forge_lane_admission")
    if not hasattr(jr, "admettre_lancement"):
        pytest.fail("forge_job_runner.admettre_lancement absent : l'admission vit encore dans un seul appelant")
    return jr, la


def _admettre(monkeypatch, ressources=None, occupee=None, **kw):
    jr, la = _modules()
    monkeypatch.setattr(la, "check_ressources", lambda heavy=True: ressources or {"ok": True})
    monkeypatch.setattr(la, "current", lambda lane: occupee)
    return jr.admettre_lancement(**kw)


def test_la_lane_par_defaut_porte_le_nom_du_fichier(monkeypatch):
    v = _admettre(monkeypatch, script="C:/tmp/x/mesure.py", online=False, lane="")
    assert v["ok"] is True and v["lane"] == "auto:mesure.py", v
    v = _admettre(monkeypatch, script="C:/tmp/x/mesure.py", online=True, lane="")
    assert v["lane"] == "auto:mesure.py@online", v
    v = _admettre(monkeypatch, script="C:/tmp/x/mesure.py", online=False, lane="gpu8091")
    assert v["lane"] == "gpu8091", v


def test_une_machine_saturee_refuse_le_lancement(monkeypatch):
    v = _admettre(monkeypatch, ressources={"ok": False, "reason": "RISQUE EMBOLIE", "freed_gb": 0.0},
                  script="C:/tmp/x/lourd.py", online=False, lane="")
    assert v["ok"] is False and v.get("admit") is False, v
    assert "EMBOLIE" in str(v.get("reason")), v


def test_une_lane_occupee_refuse_le_lancement(monkeypatch):
    v = _admettre(monkeypatch, occupee={"holder": "job_autre"},
                  script="C:/tmp/x/lourd.py", online=False, lane="")
    assert v["ok"] is False and v.get("busy_by") == "job_autre", v


def test_la_lane_est_rendue_a_la_fin_du_job(monkeypatch, tmp_path):
    """launch_job enregistre la lane sans prendre de bail ; la voie MCP le prend puis le rend par un
    veilleur asyncio. Une route qui prend le bail sans le rendre bloque le meme travail 2 h (TTL)."""
    import asyncio

    jr, la = _modules()
    rendus = []
    monkeypatch.setattr(jr, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(la, "release", lambda lane, jid: rendus.append((lane, jid)))
    (tmp_path / "job_x.rc").write_text("0", encoding="utf-8")
    asyncio.run(jr.liberer_lane_a_la_fin("job_x", "auto:x.py", pas_s=0.01))
    assert rendus == [("auto:x.py", "job_x")], rendus


def _corps(src: str, entete: str) -> str:
    d = re.search(entete, src)
    assert d, f"{entete} introuvable : la forme du fichier a change"
    suite = re.search(r"\n    async def \w+|\n    def \w+", src[d.end():])
    return src[d.start():d.end() + (suite.start() if suite else 6000)]


def test_la_route_rest_passe_par_l_admission_hors_de_la_boucle():
    corps = _corps(HUB.read_text(encoding="utf-8", errors="replace"), r"async def admin_run_job\(request\):")
    assert "admettre_lancement" in corps, "POST /admin/run_job lance sans admission (ni embolie ni lane)"
    # check_ressources mesure et libere : appele en direct, il a fige la boucle du hub 567 s en 7 jours.
    assert re.search(r"to_thread\(\s*admettre_lancement|run_in_executor\([^)]*admettre_lancement", corps), \
        "l'admission doit tourner hors de la boucle (asyncio.to_thread)"
    assert "acquire" in corps and "veiller_liberation" in corps, \
        "la route REST doit prendre le bail de lane ET le rendre a la fin du job"


def test_la_voie_mcp_appelle_la_meme_admission():
    src = REGISTRE.read_text(encoding="utf-8", errors="replace")
    assert "admettre_lancement" in src, "la voie MCP garde sa propre copie du controle : deux admissions divergeront"
