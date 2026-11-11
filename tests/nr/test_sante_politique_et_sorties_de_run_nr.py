# -*- coding: utf-8 -*-
"""NR (owner 3/11 « bilan de sante a 100/100 », sans maquiller) : deux ecarts mesures n'etaient pas des pannes.

(1) DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE (constitution) : llamacpp_python (:8090) = NokidoLlamaPython
    `disabled = true` -- compte « Services DOWN » (-3). Un service desactive reste LISTE a part, sans penalite ;
    une vraie panne reste penalisee.
(2) L'audit d'horodatage vise les journaux d'ORGANES : sur 1 848 fichiers « sans date », 1 831 etaient des sorties
    de run (sandbox/jobs 1 607, ci_* 109, workspace 88, harness_jobs 27), datees par leur nom ou leurs metadonnees.
    Elles sont ecartees ET COMPTEES ; un vrai journal sans date reste compte.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_health_diagnostic as H  # noqa: E402


def _audit_min(svcs):
    """Audit minimal : seules les sections utiles ; le reste absent est tolere par compute_score_and_gaps ?"""
    return {"services_http": svcs}


def test_service_desactive_par_politique_pas_une_panne():
    svcs = {"llamacpp_python": {"up": False, "err": "URLError", "desactive": True},
            "hub_mcp": {"up": True, "status": 200}}
    pen = H._penalite_services_http(svcs)
    assert pen["points"] == 0 and pen["desactives"] == ["llamacpp_python"] and pen["down"] == [], pen


def test_vraie_panne_reste_penalisee():
    svcs = {"graph_explorer": {"up": False, "err": "URLError"}}
    pen = H._penalite_services_http(svcs)
    assert pen["points"] == 3 and pen["down"] == ["graph_explorer"], pen


def test_le_port_d_un_service_desactive_est_reconnu():
    assert 8090 in H._ports_desactives()   # NokidoLlamaPython, disabled = true dans services.toml


def _journal(p: Path, lignes):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    os.utime(p, (time.time(), time.time()))


def test_sorties_de_run_ecartees_et_comptees(tmp_path):
    sans_date = ["ligne sans date %d" % i for i in range(5)]
    _journal(tmp_path / "logs" / "organe.log", sans_date)                      # vrai journal : COMPTE
    _journal(tmp_path / "sandbox" / "jobs" / "job_x.log", sans_date)           # sortie de run : ecartee
    _journal(tmp_path / "sandbox" / "ci_LaForgeSbxOffline" / "a.err", sans_date)
    _journal(tmp_path / "sandbox" / "workspace" / "banc.log", sans_date)
    _journal(tmp_path / "sandbox" / "harness_jobs" / "x" / "1.jsonl", sans_date)
    r = H.audit_journal_timestamps(tmp_path)
    assert r["undated_count"] == 1 and r["undated"][0]["path"] == "logs/organe.log", r
    assert r["sorties_de_run_ecartees"] == 4, r
