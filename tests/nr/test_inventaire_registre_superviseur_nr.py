"""NR hermetique (consigne owner 8/11 : LE SUPERVISEUR PUBLIE).

Verifie que :
1. Un pid publie dans le registre du superviseur est identifie avec son service, son intention et sa cmdline
   AVANT de tenter proc.cmdline() (meme sous un compte sans SeDebugPrivilege ou cmdline() leve AccessDenied).
2. Les descendants d'un pid publie heritent a toute profondeur (logique d'ancetre commit 9cb92a322).
3. Un pid absent du registre et non herite reste ILLISIBLE nomme dans la liste des ILLISIBLE, jamais compte sain.
4. Un registre illisible (absent, tronque ou JSON corrompu) rend ILLISIBLE, jamais 0.
5. Le superviseur Deno (proxy_deno/core/supervisor.ts + service_loader.ts) publie a chaque lancement et a chaque fin
   dans startService : pid, ppid, cmdline, service, intention, objectif, compte, heure de facon atomique.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools import forge_process_inventory as inv

ROOT = Path(__file__).resolve().parents[2]


def test_pid_publie_identifie_avec_intention_avant_cmdline(tmp_path, monkeypatch):
    """Un pid publie dans le registre est lu AVANT proc.cmdline() et identifie avec son intention."""
    reg_file = tmp_path / "health.json"
    reg_file.write_text(
        json.dumps(
            {
                "ts": 1762600000,
                "services": {
                    "NokidoMCP": {
                        "status": "running",
                        "pid": 100,
                        "ppid": 10,
                        "cmdline": "C:/miniforge3/python.exe -s app/nokido_mcp_server.py",
                        "service": "NokidoMCP",
                        "intention": "Fournir le bus nerveux HTTP MCP central de Nokido.",
                        "objectif": "Servir les outils MCP sur :8766.",
                        "compte": "user",
                        "heure": "2026-11-08T11:00:00.000Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    appels_cmdline = []

    class _FakeProc:
        def __init__(self, pid, ppid, name, user):
            self.info = {
                "pid": pid,
                "ppid": ppid,
                "name": name,
                "create_time": 1000.0,
                "memory_info": None,
                "username": user,
            }

        def cmdline(self):
            appels_cmdline.append(self.info["pid"])
            raise PermissionError("AccessDenied sans SeDebugPrivilege")

    import psutil

    monkeypatch.setattr(
        psutil,
        "process_iter",
        lambda _attrs: [_FakeProc(100, 10, "python.exe", "SYSTEM"), _FakeProc(999, 4, "inconnu.exe", "SYSTEM")],
    )
    monkeypatch.setattr(inv, "REGISTRE_SUPERVISEUR", reg_file)
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_ports", lambda: {})
    monkeypatch.setattr(inv, "_jobs_par_pid", lambda: {})
    monkeypatch.setattr(inv, "_battements_par_pid", lambda: {})

    rapport = inv.collect()

    # proc.cmdline() n'est meme pas tente pour le pid 100 publie au registre :
    assert 100 not in appels_cmdline
    assert 999 in appels_cmdline

    assert rapport["etat_registre"] == "OK"
    assert rapport["totaux"]["identifies"] == 1
    assert rapport["totaux"]["herites"] == 0
    assert rapport["totaux"]["illisibles"] == 1
    assert rapport["totaux"]["ILLISIBLE"] == 1

    ident_100 = rapport["identifies"]["100"]
    assert ident_100["service"] == "NokidoMCP"
    assert ident_100["intention"] == "Fournir le bus nerveux HTTP MCP central de Nokido."
    assert ident_100["objectif"] == "Servir les outils MCP sur :8766."
    assert ident_100["cmdline"] == "C:/miniforge3/python.exe -s app/nokido_mcp_server.py"
    assert ident_100["compte"] == "user"


def test_descendant_herite_et_pid_absent_reste_illisible(tmp_path, monkeypatch):
    """Les descendants d'un pid publie heritent ; un pid absent et non herite reste ILLISIBLE nomme."""
    reg_file = tmp_path / "health.json"
    reg_file.write_text(
        json.dumps(
            {
                "ts": 1762600000,
                "services": {
                    "NokidoDockerMcpGateway": {
                        "status": "running",
                        "pid": 500,
                        "ppid": 10,
                        "cmdline": "python tools/forge_docker_mcp_gateway.py",
                        "service": "NokidoDockerMcpGateway",
                        "intention": "Maintenir la passerelle MCP Docker.",
                        "objectif": "Exposer les conteneurs MCP sur :8811.",
                        "compte": "LaForgeSbxOnline",
                        "heure": "2026-11-08T11:05:00.000Z",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    vivants = {
        500: {"nom": "python.exe", "ppid": 10, "rss_mo": 30.0, "age_min": 5, "cree": 100.0, "user": "LaForgeSbxOnline", "cmd": None},
        501: {"nom": "docker.exe", "ppid": 500, "rss_mo": 20.0, "age_min": 5, "cree": 101.0, "user": "LaForgeSbxOnline", "cmd": None},
        502: {"nom": "docker-mcp.exe", "ppid": 501, "rss_mo": 45.0, "age_min": 5, "cree": 102.0, "user": "LaForgeSbxOnline", "cmd": None},
        888: {"nom": "ombre.exe", "ppid": 4, "rss_mo": 12.0, "age_min": 9, "cree": 90.0, "user": "SYSTEM", "cmd": None},
    }
    monkeypatch.setattr(inv, "REGISTRE_SUPERVISEUR", reg_file)
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_vivants", lambda: (vivants, 4))
    monkeypatch.setattr(inv, "_ports", lambda: {8811: 502})
    monkeypatch.setattr(inv, "_jobs_par_pid", lambda: {})
    monkeypatch.setattr(inv, "_battements_par_pid", lambda: {})

    rapport = inv.collect()

    assert rapport["totaux"]["identifies"] == 1
    assert rapport["totaux"]["herites"] == 2
    assert rapport["totaux"]["illisibles"] == 1
    assert rapport["totaux"]["ILLISIBLE"] == 1

    assert rapport["identifies"]["500"]["service"] == "NokidoDockerMcpGateway"
    assert rapport["identifies"]["500"]["intention"] == "Maintenir la passerelle MCP Docker."
    assert rapport["identifies"]["500"]["cmdline"] == "python tools/forge_docker_mcp_gateway.py"

    assert rapport["herites"]["501"]["service"] == "NokidoDockerMcpGateway"
    assert rapport["herites"]["501"]["intention"] == "Maintenir la passerelle MCP Docker."
    assert rapport["herites"]["501"]["profondeur"] == 1

    assert rapport["herites"]["502"]["service"] == "NokidoDockerMcpGateway"
    assert rapport["herites"]["502"]["intention"] == "Maintenir la passerelle MCP Docker."
    assert rapport["herites"]["502"]["profondeur"] == 2

    # Le pid 888 absent et sans ancetre publie reste ILLISIBLE nomme, jamais compte sain :
    assert len(rapport["illisibles"]) == 1
    ill = rapport["illisibles"][0]
    assert ill["pid"] == 888
    assert ill["nom"] == "ombre.exe"
    assert ill["statut"] == "ILLISIBLE"


def test_registre_illisible_rend_illisible_jamais_zero(tmp_path, monkeypatch):
    """Un registre absent, vide ou corrompu rend ILLISIBLE dans les totaux et l'etat, jamais 0."""
    vivants = {
        100: {"nom": "python.exe", "ppid": 10, "rss_mo": 25.0, "age_min": 2, "cree": 100.0, "user": "SYSTEM", "cmd": None},
    }
    monkeypatch.setattr(inv, "_prevus", lambda: {})
    monkeypatch.setattr(inv, "_vivants", lambda: (vivants, 1))
    monkeypatch.setattr(inv, "_ports", lambda: {})
    monkeypatch.setattr(inv, "_jobs_par_pid", lambda: {})
    monkeypatch.setattr(inv, "_battements_par_pid", lambda: {})

    # 1. Fichier absent
    absent = tmp_path / "absent.json"
    monkeypatch.setattr(inv, "REGISTRE_SUPERVISEUR", absent)
    r_absent = inv.collect()
    assert r_absent["etat_registre"] == "ILLISIBLE"
    assert r_absent["totaux"]["identifies"] == "ILLISIBLE"
    assert r_absent["totaux"]["herites"] == "ILLISIBLE"
    assert r_absent["totaux"]["illisibles"] == "ILLISIBLE"
    assert r_absent["totaux"]["ILLISIBLE"] == "ILLISIBLE"
    assert r_absent["identifies"] == "ILLISIBLE"
    assert r_absent["illisibles"][0]["statut"] == "ILLISIBLE"
    assert r_absent["illisibles"][0]["pid"] == 100

    # 2. Fichier JSON corrompu
    corrompu = tmp_path / "corrompu.json"
    corrompu.write_text("{json_tronque", encoding="utf-8")
    monkeypatch.setattr(inv, "REGISTRE_SUPERVISEUR", corrompu)
    r_corrompu = inv.collect()
    assert r_corrompu["etat_registre"] == "ILLISIBLE"
    assert r_corrompu["totaux"]["identifies"] == "ILLISIBLE"
    assert r_corrompu["totaux"]["ILLISIBLE"] == "ILLISIBLE"


def test_superviseur_deno_publie_intention_et_registre_atomique():
    """Verification statique sur proxy_deno/core/supervisor.ts et service_loader.ts."""
    loader_txt = (ROOT / "proxy_deno" / "core" / "service_loader.ts").read_text(encoding="utf-8")
    sup_txt = (ROOT / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8")

    assert "intention?: string;" in loader_txt
    assert "objectif?: string;" in loader_txt
    assert "svc.intention = s.intention.trim()" in loader_txt
    assert "svc.objectif = s.objectif.trim()" in loader_txt

    assert "function construireRegistreServices()" in sup_txt
    assert "function publierRegistreSuperviseur()" in sup_txt
    assert "Deno.writeTextFileSync(tmp," in sup_txt
    assert "Deno.renameSync(tmp, REGISTRE_FICHIER)" in sup_txt
    assert "LaForgeTrusted:(R)" in sup_txt
    assert "intention: state.def.intention ?? null" in sup_txt
    assert "objectif: state.def.objectif ?? null" in sup_txt
    assert "cmdline: state.cmdline ?? cmdDefaut" in sup_txt
