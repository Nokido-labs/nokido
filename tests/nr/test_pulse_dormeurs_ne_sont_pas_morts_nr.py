"""NR 6/11 : Faux diagnostic d'embolie sur daemons endormis par délestage RAM.

Constitution : DISABLED_BY_POLICY n'est pas DEAD.
- Des dormeurs seuls donnent WARN, jamais EMBOLIE ni CLEAR.
- 5 morts non dormeurs donnent EMBOLIE.
- Superviseur illisible ou muet -> EMBOLIE comme avant (aucun dormeur soustrait sans preuve).
- Le détail affiche N endormi(s) avec leurs noms sans rien masquer.
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

# Ajout du chemin tools/ pour importer forge_organ_pulse
_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import forge_organ_pulse as op


def _mock_env(monkeypatch, tmp_path: Path, sup_services: dict, toml_services: list[dict], hb_timestamps: dict):
    """Prépare un environnement isolé sans réseau pour tester _check_daemon_heartbeats."""
    hb_dir = tmp_path / "sandbox"
    hb_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(op, "ROOT", tmp_path)

    # Écriture du toml
    toml_path = tmp_path / "proxy_deno" / "core" / "services.toml"
    toml_path.parent.mkdir(parents=True, exist_ok=True)
    toml_lines = []
    for s in toml_services:
        toml_lines.append("[[service]]")
        toml_lines.append(f'name = "{s["name"]}"')
        if "heartbeat" in s:
            toml_lines.append(f'heartbeat = "{s["heartbeat"]}"')
        if s.get("disabled"):
            toml_lines.append("disabled = true")
        if "interval" in s:
            toml_lines.append(f'args = ["--interval", "{s["interval"]}"]')
        toml_lines.append("")
    toml_path.write_text("\n".join(toml_lines), encoding="utf-8")

    # Écriture des fichiers de heartbeat existants
    now = time.time()
    for hb_name, age_s in hb_timestamps.items():
        p = hb_dir / f"{hb_name}.heartbeat"
        p.write_text("{}", encoding="utf-8")
        if age_s is not None:
            mtime = now - age_s
            # modification mtime
            import os
            os.utime(str(p), (mtime, mtime))

    # Mock _body_phase pour être en régime établi ("steady")
    monkeypatch.setattr(op, "_body_phase", lambda: "steady")

    # Mock urllib.request.urlopen pour _SUPERVISOR_STATUS
    def faux_urlopen(req, timeout=3):
        url = req if isinstance(req, str) else req.get_full_url()
        if "/supervisor/status" in url:
            if sup_services is None:
                raise ConnectionRefusedError("Superviseur injoignable")
            payload = json.dumps({"ts": "2026-11-06T22:00:00Z", "services": sup_services}).encode("utf-8")
            return io.BytesIO(payload)
        raise ValueError(f"URL inattendue : {url}")

    monkeypatch.setattr(op.urllib.request, "urlopen", faux_urlopen)


def test_dormeurs_seuls_donnent_warn(monkeypatch, tmp_path):
    """Des daemons stale qui sont prouvés 'sleeping' par le superviseur donnent WARN, pas EMBOLIE ni CLEAR."""
    # 6 daemons supervisés, tous périmés (stale), mais tous 'sleeping'
    toml_services = [
        {"name": f"Svc_{i}", "heartbeat": f"sandbox/hb_{i}.heartbeat"}
        for i in range(6)
    ]
    sup_services = {
        f"Svc_{i}": {"status": "sleeping"}
        for i in range(6)
    }
    # Aucun heartbeat sur le disque -> tous stale (> limit)
    _mock_env(monkeypatch, tmp_path, sup_services, toml_services, {})

    verdict, detail = op._check_daemon_heartbeats()
    assert verdict == op.WARN
    assert "0/6 daemons déclarés stale" in detail
    assert "6 endormi(s): ['hb_0', 'hb_1', 'hb_2', 'hb_3', 'hb_4', 'hb_5']" in detail


def test_cinq_morts_non_dormeurs_donnent_embolie(monkeypatch, tmp_path):
    """5 morts non dormeurs donnent EMBOLIE."""
    toml_services = [
        {"name": f"Svc_{i}", "heartbeat": f"sandbox/hb_{i}.heartbeat"}
        for i in range(5)
    ]
    # Superviseur indique qu'ils sont 'stopped' ou 'running' (pas 'sleeping')
    sup_services = {
        f"Svc_{i}": {"status": "running"}
        for i in range(5)
    }
    _mock_env(monkeypatch, tmp_path, sup_services, toml_services, {})

    verdict, detail = op._check_daemon_heartbeats()
    assert verdict == op.EMBOLIE
    assert "5/5 daemons déclarés stale" in detail
    assert "endormi" not in detail


def test_superviseur_illisible_donne_embolie_comme_avant(monkeypatch, tmp_path):
    """Si le superviseur est muet ou illisible, aucun dormeur n'est déduit : 5 morts = EMBOLIE."""
    toml_services = [
        {"name": f"Svc_{i}", "heartbeat": f"sandbox/hb_{i}.heartbeat"}
        for i in range(5)
    ]
    # sup_services = None -> faux_urlopen lève ConnectionRefusedError
    _mock_env(monkeypatch, tmp_path, None, toml_services, {})

    verdict, detail = op._check_daemon_heartbeats()
    assert verdict == op.EMBOLIE
    assert "5/5 daemons déclarés stale" in detail
    assert "endormi" not in detail


def test_detail_cite_les_dormeurs_et_les_morts(monkeypatch, tmp_path):
    """Mix de dormeurs et de morts : le détail cite distinctement les dormeurs et morts."""
    toml_services = [
        {"name": "SvcSleep1", "heartbeat": "sandbox/hb_sleep1.heartbeat"},
        {"name": "SvcSleep2", "heartbeat": "sandbox/hb_sleep2.heartbeat"},
        {"name": "SvcDead1", "heartbeat": "sandbox/hb_dead1.heartbeat"},
        {"name": "SvcAlive", "heartbeat": "sandbox/hb_alive.heartbeat"},
    ]
    sup_services = {
        "SvcSleep1": {"status": "sleeping"},
        "SvcSleep2": {"status": "sleeping"},
        "SvcDead1": {"status": "stopped"},
        "SvcAlive": {"status": "running"},
    }
    # hb_alive est tout récent (10s), les autres absents -> stale
    hb_timestamps = {
        "hb_alive": 10
    }
    _mock_env(monkeypatch, tmp_path, sup_services, toml_services, hb_timestamps)

    verdict, detail = op._check_daemon_heartbeats()
    # 1 mort (<5) et 2 dormeurs -> WARN
    assert verdict == op.WARN
    assert "1/4 daemons déclarés stale: ['hb_dead1']" in detail
    assert "2 endormi(s): ['hb_sleep1', 'hb_sleep2']" in detail
