"""NR : le transport signale (meta) survit a la troncature reelle de mcp_audit.log."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_meta_transport_survit_a_la_troncature(tmp_path, monkeypatch):
    from nokido_agent.app import forge_mcp_security as sec
    from nokido_agent.app import forge_network_logger as nl

    log = tmp_path / "mcp_audit.log"
    monkeypatch.setattr(sec, "AUDIT_LOG", log)
    monkeypatch.setattr(nl, "_get_audit", lambda: sec.audit)
    nl.net_log(
        list(nl.NetworkChannel)[0],
        "IN",
        tool="run_x",
        agent="CLAUDE",
        ring=1,
        latency_ms=12.5,
        provider="prov",
        model="mod",
        session_id="sess-123",
        payload_in="A" * 900,
        payload_out="B" * 900,
        meta={"transport_signale": "STDIO_BRIDGE", "canal_contradictoire": True},
    )
    lignes = log.read_text(encoding="utf-8").splitlines()
    assert lignes, "aucune ligne d'audit ecrite"
    assert "transport_signale" in lignes[-1]
    assert "canal_contradictoire" in lignes[-1]


def test_le_ring_reste_lisible_avec_le_transport(tmp_path, monkeypatch):
    """22/10 17 h 39 : 736e8ef76 placait transport_signale AVANT agent/ring ; la coupe a 120 car.
    emportait la VALEUR du ring de TOUTES les lignes (« "ring": " | OK ») -- lue comme ring -1
    par l'instruction des bad_token. Trace reelle caviardee (14 car.) et nom d'agent long."""
    from nokido_agent.app import forge_mcp_security as sec
    from nokido_agent.app import forge_network_logger as nl
    from nokido_agent.app import forge_trace_context as tc

    log = tmp_path / "mcp_audit.log"
    monkeypatch.setattr(sec, "AUDIT_LOG", log)
    monkeypatch.setattr(nl, "_get_audit", lambda: sec.audit)
    monkeypatch.setattr(tc, "get_trace_id", lambda: "[REDACTED:key]")
    nl.net_log(list(nl.NetworkChannel)[0], "IN", tool="hub", agent="OPENCODE_GPTOSS", ring=1,
               latency_ms=12.5, payload_in="A" * 900, payload_out="B" * 900,
               meta={"transport_signale": "STDIO_BRIDGE", "canal_contradictoire": True})
    ligne = log.read_text(encoding="utf-8").splitlines()[-1]
    assert '"ring": "1"' in ligne, ligne
    assert '"transport_signale": "STDIO_BRIDGE"' in ligne, ligne
