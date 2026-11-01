"""NR -- mesure des regressions potentielles du scope de role (lecture seule)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

import forge_scope_role_mesure as m  # noqa: E402

CAT = {"run", "hub", "github", "memory", "read_function_body", "query"}


def L(ts, ch, agent):
    return (ts + " | NetworkChannel." + ch + ' | {"direction": "Direction.IN", "trace_id": "x", '
            '"agent": "' + agent + '", "ring": "1"} | OK')


def test_parse_ligne():
    r = m.parse_line(L("2026-10-20T10:00:00", "STDIO_CLAUDE:run", "claude"))
    assert r == ("2026-10-20T10:00:00", "run", "CLAUDE")


def test_parse_ignore_bruit():
    assert m.parse_line("[TRUNCATED par forge_log_guard]") is None
    assert m.parse_line('trace_id": "x", "agent": "TRAY" | OK') is None
    assert m.parse_line("2026-10-20T10:00:00 | pas_de_canal | {} | OK") is None


def test_usage_filtre_fenetre_et_catalogue():
    lines = [
        L("2026-10-20T10:00:00", "HTTP_DIRECT:github", "CLAUDE"),
        L("2026-10-20T10:00:01", "HTTP_DIRECT:github", "CLAUDE"),
        L("2026-10-01T10:00:00", "HTTP_DIRECT:github", "CLAUDE"),      # hors fenetre
        L("2026-10-20T10:00:02", "HTTP_DIRECT:tools/list", "CLAUDE"),  # pas un outil
        L("2026-10-20T10:00:03", "HTTP_DIRECT:run", "GEMINI"),
    ]
    u = m.usage_par_agent(lines, since="2026-10-17T00:00:00", catalogue=CAT)
    assert u == {"CLAUDE": {"github": 2}, "GEMINI": {"run": 1}}


def test_regressions():
    usage = {"CLAUDE": {"github": 5, "run": 9, "memory": 1}, "LIBRE": {"github": 4}}
    scope = {"CLAUDE": {"run", "hub", "query"}}
    rep = m.regressions(usage, lambda a: scope.get(a), min_calls=3)
    c = rep["CLAUDE"]
    assert c["scope"] is True
    assert c["disparaissent"] == {"github": 5, "memory": 1}
    assert c["regressions_apres_usage"] == {"memory": 1}   # github >= N est reintegre
    assert c["reintegres"] == {"github": 5}
    assert rep["LIBRE"]["scope"] is False and rep["LIBRE"]["disparaissent"] == {}
