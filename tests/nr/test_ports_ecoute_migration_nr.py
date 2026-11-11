"""NR 6/11 : Migration des capteurs de ports vers ecouteurs_tcp (forge_ports_ecoute).

Verifie les 5 sites migres :
1. forge_proxy_reload.reload_proxy : ne tue QUE les listeners locaux ecouteurs_tcp()[port],
   ne tue jamais un client avec port distant matchant :port, et ne tue personne si ecouteurs_tcp rend None.
2. forge_process_manager.port_pid : retourne le PID listener issu de ecouteurs_tcp.
3. forge_resource_manager._preuve_port_coder : OUI si port dans ecouteurs_tcp, NON si absent, sans psutil faux.
4. forge_service_watchdog._get_pid_by_port : retourne le PID listener issu de ecouteurs_tcp prioritairement.
5. forge_inspector._sys_metrics : utilise _check_ports() relie a ecouteurs_tcp plutot que psutil.net_connections.
"""
from __future__ import annotations

import types
import pytest


def test_site1_proxy_reload_ne_tue_pas_client_distant_et_gere_none(monkeypatch):
    import tools.forge_proxy_reload as fpr

    killed = []
    def faux_sh(cmd: str) -> str:
        if "taskkill" in cmd:
            killed.append(cmd)
            return "SUCCESS"
        return ""

    monkeypatch.setattr(fpr, "_sh", faux_sh)
    monkeypatch.setattr(fpr.time, "sleep", lambda s: None)
    monkeypatch.setattr(fpr.urllib.request, "urlopen", lambda *a, **k: types.SimpleNamespace(read=lambda: b'{"status": "ok"}'))

    # Cas 1 : ecouteurs_tcp rend None -> ne tue personne
    monkeypatch.setattr("app.forge_ports_ecoute.ecouteurs_tcp", lambda: None, raising=False)
    monkeypatch.setattr("forge_ports_ecoute.ecouteurs_tcp", lambda: None, raising=False)
    try:
        import nokido_agent.app.forge_ports_ecoute as npe
        monkeypatch.setattr(npe, "ecouteurs_tcp", lambda: None)
    except ImportError:
        pass

    res = fpr.reload_proxy(7777, "dummy_script.py")
    assert killed == []
    assert res.get("listen_pids") == []
    assert "error" in res

    # Cas 2 : Un client avec port distant 7777 n'est pas dans ecouteurs_tcp (qui ne liste que les listeners locaux)
    # Seul le listener local port 7777 (pid 9999) est dans la table
    def faux_ecouteurs():
        return {7777: {9999}, 8888: {1111}}

    monkeypatch.setattr("app.forge_ports_ecoute.ecouteurs_tcp", faux_ecouteurs, raising=False)
    monkeypatch.setattr("forge_ports_ecoute.ecouteurs_tcp", faux_ecouteurs, raising=False)
    try:
        import nokido_agent.app.forge_ports_ecoute as npe
        monkeypatch.setattr(npe, "ecouteurs_tcp", faux_ecouteurs)
    except ImportError:
        pass

    killed.clear()
    res2 = fpr.reload_proxy(7777, "dummy_script.py")
    assert res2.get("listen_pids") == [9999]
    assert len(killed) == 1
    assert "9999" in killed[0]

    # Cas 3 : port absent de la table -> aucun kill
    killed.clear()
    res3 = fpr.reload_proxy(5555, "dummy_script.py")
    assert killed == []
    assert res3.get("listen_pids") == []


def test_site2_process_manager_port_pid(monkeypatch):
    import tools.forge_process_manager as fpm

    def faux_ecouteurs():
        return {8766: {4321}}

    monkeypatch.setattr("app.forge_ports_ecoute.ecouteurs_tcp", faux_ecouteurs, raising=False)
    monkeypatch.setattr("forge_ports_ecoute.ecouteurs_tcp", faux_ecouteurs, raising=False)
    try:
        import nokido_agent.app.forge_ports_ecoute as npe
        monkeypatch.setattr(npe, "ecouteurs_tcp", faux_ecouteurs)
    except ImportError:
        pass

    assert fpm.port_pid(8766) == 4321
    assert fpm.port_pid(9999) is None


def test_site3_resource_manager_preuve_port_coder(monkeypatch):
    import app.forge_resource_manager as frm

    def faux_ecouteurs():
        return {frm._LLAMACPP_NATIVE_PORT: {5678}}

    monkeypatch.setattr("app.forge_ports_ecoute.ecouteurs_tcp", faux_ecouteurs, raising=False)
    monkeypatch.setattr("forge_ports_ecoute.ecouteurs_tcp", faux_ecouteurs, raising=False)
    try:
        import nokido_agent.app.forge_ports_ecoute as npe
        monkeypatch.setattr(npe, "ecouteurs_tcp", faux_ecouteurs)
    except ImportError:
        pass

    etat, pid = frm._preuve_port_coder()
    assert etat == "OUI"
    assert pid == 5678

    # Port absent
    monkeypatch.setattr("app.forge_ports_ecoute.ecouteurs_tcp", lambda: {}, raising=False)
    monkeypatch.setattr("forge_ports_ecoute.ecouteurs_tcp", lambda: {}, raising=False)
    try:
        import nokido_agent.app.forge_ports_ecoute as npe
        monkeypatch.setattr(npe, "ecouteurs_tcp", lambda: {})
    except ImportError:
        pass

    etat2, pid2 = frm._preuve_port_coder()
    assert etat2 == "NON"
    assert pid2 == 0


def test_site4_service_watchdog_get_pid_by_port(monkeypatch):
    import app.forge_service_watchdog as fsw
    watchdog = fsw.ServiceWatchdog.__new__(fsw.ServiceWatchdog)

    def faux_ecouteurs():
        return {8080: {8899}}

    monkeypatch.setattr("app.forge_ports_ecoute.ecouteurs_tcp", faux_ecouteurs, raising=False)
    monkeypatch.setattr("forge_ports_ecoute.ecouteurs_tcp", faux_ecouteurs, raising=False)
    try:
        import nokido_agent.app.forge_ports_ecoute as npe
        monkeypatch.setattr(npe, "ecouteurs_tcp", faux_ecouteurs)
    except ImportError:
        pass

    pid = watchdog._get_pid_by_port({"url": "http://127.0.0.1:8080"})
    assert pid == 8899


def test_site5_inspector_sys_metrics(monkeypatch):
    import app.forge_inspector as fi

    def interdit():
        raise AssertionError("_check_ports sonde et journalise : pas deux fois par cycle")

    monkeypatch.setattr(fi, "_check_ports", interdit)
    monkeypatch.setattr(fi, "ecouteurs_tcp", lambda: {8765: {1}, 8766: {2}, 11434: {3, 4}})
    metrics = fi._sys_metrics()
    assert metrics.get("port_8765") == "OK"
    assert metrics.get("port_8767") == "DOWN"
    assert metrics.get("port_11434") == "OK", "un doublon ecoute : Ollama n'est pas hors ligne"


def test_site5_table_illisible_est_inconnue(monkeypatch):
    import app.forge_inspector as fi

    monkeypatch.setattr(fi, "ecouteurs_tcp", lambda: None)
    assert fi._sys_metrics().get("port_8766") == "INCONNU"


def test_pid_ambigu_n_est_jamais_rendu(monkeypatch):
    """Deux Ollama ecoutent sur :11434 : en rendre un au hasard ferait tuer le mauvais par kill_port."""
    import tools.forge_process_manager as fpm

    try:
        import nokido_agent.app.forge_ports_ecoute as npe
        monkeypatch.setattr(npe, "ecouteurs_tcp", lambda: {11434: {17984, 19736}})
    except ImportError:
        pass
    monkeypatch.setattr("app.forge_ports_ecoute.ecouteurs_tcp", lambda: {11434: {17984, 19736}}, raising=False)
    assert fpm.port_pid(11434) is None
