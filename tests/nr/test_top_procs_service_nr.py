# -*- coding: utf-8 -*-
"""NR 28/10 : le refus THROTTLED nomme le SERVICE de chaque gros processus (jamais par le nom du binaire)."""
try:
    from nokido_agent.app import forge_resource_manager as rm
except Exception:  # noqa: BLE001
    from app import forge_resource_manager as rm


def test_enfant_de_service_affiche_service():
    vivants = {22840: {"ppid": 100}, 100: {"ppid": 1}}
    out = rm.formater_top_avec_service(
        [{"name": "llama-server.exe", "ram_gb": 5.69, "pid": 22840}], {100: "NokidoOllama"}, vivants)
    assert out == "llama-server.exe(5.69GB,pid=22840, service=NokidoOllama)"


def test_pid_de_service_direct():
    out = rm.formater_top_avec_service([{"name": "x", "ram_gb": 1, "pid": 100}], {100: "NokidoHub"}, {100: {"ppid": 1}})
    assert "service=NokidoHub" in out


def test_sans_ancetre_illisible_pas_devine_par_nom():
    out = rm.formater_top_avec_service(
        [{"name": "ollama.exe", "ram_gb": 2, "pid": 7}], {100: "NokidoOllama"}, {7: {"ppid": 1}})
    assert out.endswith("pid=7, service=ILLISIBLE)")


def test_carte_en_cache_30s_et_timeout_borne(monkeypatch):
    appels = []

    class R:
        def json(self):
            return {"services": [{"name": "NokidoOllama", "pid": 100}]}

    def fake_get(url, **kw):
        appels.append(kw.get("timeout"))
        return R()

    monkeypatch.setattr(rm, "_http_get_superviseur", fake_get)
    rm._CARTE_SERVICES.update(ts=0.0, carte={})
    assert rm.carte_pid_service(now=1000.0) == {100: "NokidoOllama"}
    assert rm.carte_pid_service(now=1020.0) == {100: "NokidoOllama"}
    assert len(appels) == 1 and appels[0] is not None and appels[0] <= 3
    rm.carte_pid_service(now=1031.0)
    assert len(appels) == 2


def test_la_carte_interroge_la_vraie_route_du_superviseur(monkeypatch):
    """Revue d'integration (CLAUDE 28/10) : _SUPERVISOR_URL porte deja « /supervisor ». La livraison demandait
    /supervisor/supervisor/status (404) -> carte toujours vide -> tout « ILLISIBLE » ; le NR simulait l'appel."""
    urls = []

    class R:
        def json(self):
            return {"services": {}}

    monkeypatch.setattr(rm, "_http_get_superviseur", lambda url, **kw: urls.append(url) or R())
    rm._CARTE_SERVICES.update(ts=0.0, carte={})
    rm.carte_pid_service(now=9000.0)
    assert urls == [rm._SUPERVISOR_URL + "/status"]
    assert "/supervisor/supervisor/" not in urls[0]


def test_superviseur_injoignable_donne_carte_vide(monkeypatch):
    def boom(url, **kw):
        raise OSError("down")

    monkeypatch.setattr(rm, "_http_get_superviseur", boom)
    rm._CARTE_SERVICES.update(ts=0.0, carte={})
    assert rm.carte_pid_service(now=5000.0) == {}
