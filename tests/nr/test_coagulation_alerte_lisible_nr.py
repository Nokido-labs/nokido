"""NR 6/11 : trois fenetres d'alerte critiques, aucune panne reelle au moment ou l'owner les lit.

1. `service_crash` de 18:52 re-emis a 19:48 : le curseur du veilleur ne survivait pas au redemarrage.
2. `web_hub DOWN` constate a 19:48:14, 4 s avant son demarrage, remis a 19:53:08 alors qu'il repondait.
3. Le texte disait `cause: ILLISIBLE` (le champ s'appelle `fault`) et `restart=lanceur (humain)` : l'owner a demande
   s'il devait relancer, alors que relancer n'aurait rien corrige.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "tools", ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_coagulation as C  # noqa: E402
import forge_service_crash_watcher as W  # noqa: E402


def _ev(kind, payload, sev="critical"):
    return {"kind": kind, "severity": sev, "payload": json.dumps(payload)}


# ── Curseur du veilleur ──
def test_le_curseur_survit_au_redemarrage(tmp_path, monkeypatch):
    hb = tmp_path / "hb.json"
    hb.write_text(json.dumps({"ts": "x", "pid": 1, "last_record_id": 493426}), encoding="utf-8")
    monkeypatch.setattr(W, "HEARTBEAT", hb)
    assert W._curseur_initial() == 493426


def test_sans_curseur_lisible_seuls_les_crashs_recents_sont_emis(tmp_path, monkeypatch):
    """Curseur absent ou corrompu : rejouer 500 evenements est faux, tout taire aussi. On garde la derniere heure."""
    hb = tmp_path / "hb.json"
    hb.write_text("corrompu", encoding="utf-8")
    monkeypatch.setattr(W, "HEARTBEAT", hb)
    assert W._curseur_initial() == 0
    maintenant = time.time()
    vieux = {"record_id": 1, "service": "NokidoMCP", "time": "2020-01-01T00:00:00+00:00"}
    recent = {"record_id": 2, "service": "NokidoMCP",
              "time": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(maintenant - 60))}
    illisible = {"record_id": 3, "service": "NokidoMCP", "time": "pas une date"}
    garde = W._retenir_au_demarrage([vieux, recent, illisible], maintenant)
    assert [e["record_id"] for e in garde] == [2, 3], "une date illisible n'est pas une preuve d'anciennete"


# ── Sortie d'un enfant de NSSM ──
def test_le_veilleur_voit_la_sortie_du_superviseur(monkeypatch):
    """6/11 : LaForge-Master tue deux fois sans aucune trace dans Nokido. NSSM relance son enfant sans passer par le
    gestionnaire de services : aucun 7034, et le filtre *Nokido* ecartait de toute facon ce service."""
    vus = {}

    def faux_run(cmd, **k):
        vus["script"] = cmd[-1]
        ligne = json.dumps({"record_id": 77, "service": "LaForge-Master", "event_id": 1013, "code": 1,
                            "time": "2026-11-06T19:46:30+01:00"})
        return type("R", (), {"returncode": 0, "stdout": ligne + "\n", "stderr": ""})()

    monkeypatch.setattr(W.subprocess, "run", faux_run)
    ev = W._query_sorties_nssm(50)
    assert ev == [{"record_id": 77, "service": "LaForge-Master", "event_id": 1013, "code": 1, "time": "2026-11-06T19:46:30+01:00"}]
    assert "ProviderName='nssm'" in vus["script"] and "1013" in vus["script"] and "-gt 50" in vus["script"]


def test_sortie_nssm_sans_curseur_n_est_pas_rejouee(tmp_path, monkeypatch):
    hb = tmp_path / "hb.json"
    hb.write_text(json.dumps({"last_record_id": 1, "last_record_id_nssm": 42}), encoding="utf-8")
    monkeypatch.setattr(W, "HEARTBEAT", hb)
    assert W._curseur_initial("last_record_id_nssm") == 42
    assert W._curseur_initial() == 1


def test_arret_propre_n_est_pas_un_crash():
    sorties = [{"record_id": 1, "code": "0"}, {"record_id": 2, "code": "1"}, {"record_id": 3, "code": ""}]
    assert [e["record_id"] for e in W._sorties_anormales(sorties)] == [2, 3], "un code illisible reste signale"


def test_journal_nssm_muet_ne_casse_pas_le_veilleur(monkeypatch):
    def echec(cmd, **k):
        raise OSError("powershell absent")

    monkeypatch.setattr(W.subprocess, "run", echec)
    assert W._query_sorties_nssm(0) == []


# ── Texte de l'alerte ──
def test_la_cause_lit_fault_et_service():
    assert "web_hub" in C._cause_escalade(_ev("self_care", {"fault": "Services CRITIQUES DOWN : ['web_hub']"}))
    cause = C._cause_escalade(_ev("crash_loop_detected", {"service": "NokidoMCP", "crash_count": 4, "window_s": 600}))
    assert "NokidoMCP" in cause and "4" in cause
    cause = C._cause_escalade(_ev("service_crash", {"service": "LaForge-Master", "event_id": 1013, "code": 1}))
    assert "LaForge-Master" in cause and "code 1" in cause
    assert C._cause_escalade(_ev("x", {"autre": 1})) == "cause: ILLISIBLE"


def test_le_texte_ne_prescrit_plus_de_relance():
    voie, raison = C._triage(_ev("service_crash", {"service": "NokidoMCP"}, "error"))
    assert voie == "escalate"
    assert "restart" not in raison.lower() and "diagnostic" in raison.lower()


# ── Revalidation avant de deranger l'owner ──
def _espionner(monkeypatch, sondes):
    remis = []
    monkeypatch.setattr(C, "_log", lambda *a, **k: None)
    monkeypatch.setattr(C, "_sonde_http", lambda url: sondes.get(url))
    import nokido_agent.app.forge_critical_events as E
    monkeypatch.setattr(E, "alerter_owner", lambda *a, **k: remis.append(a) or "remise")
    return remis


def test_panne_disparue_avant_remise_ne_derange_pas(monkeypatch):
    remis = _espionner(monkeypatch, {C._URLS_CRITIQUES["web_hub"]: 200})
    ev = _ev("self_care", {"fault": "Services CRITIQUES DOWN : ['web_hub']"})
    C._escalate(ev, "service degrade")
    assert remis == []


def test_panne_encore_presente_alerte(monkeypatch):
    remis = _espionner(monkeypatch, {C._URLS_CRITIQUES["web_hub"]: 500})
    ev = _ev("self_care", {"fault": "Services CRITIQUES DOWN : ['web_hub']"})
    C._escalate(ev, "service degrade")
    assert len(remis) == 1


def test_sonde_muette_ou_service_inconnu_alerte(monkeypatch):
    """Liste blanche : seul un service PROUVE sain tait l'alerte."""
    remis = _espionner(monkeypatch, {})
    C._escalate(_ev("self_care", {"fault": "Services CRITIQUES DOWN : ['web_hub']"}), "service degrade")
    C._escalate(_ev("self_care", {"fault": "Services CRITIQUES DOWN : ['inconnu_x']"}), "service degrade")
    assert len(remis) == 2


def test_un_seul_service_encore_down_alerte(monkeypatch):
    remis = _espionner(monkeypatch, {C._URLS_CRITIQUES["web_hub"]: 200})
    C._escalate(_ev("self_care", {"fault": "Services CRITIQUES DOWN : ['web_hub', 'ollama']"}), "service degrade")
    assert len(remis) == 1


def test_un_autre_signal_critique_n_est_jamais_revalide(monkeypatch):
    remis = _espionner(monkeypatch, {C._URLS_CRITIQUES["web_hub"]: 200})
    C._escalate(_ev("crash_loop_detected", {"service": "web_hub"}), "service degrade")
    assert len(remis) == 1
