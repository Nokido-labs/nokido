"""NR 2026-10-18 : `forge_supervisor_ctl wake` doit appeler la route `/supervisor/service/start/<nom>`.

Mesure : `wake <Service>` rend HTTP 404 (la route /supervisor/wake n'existe pas
dans proxy_deno/core/supervisor.ts ; seules POST /supervisor/service/start/<nom>
et /supervisor/service/stop/<nom> savent creer l'etat d'un service disabled via
etatALaDemande). `restart` marche. (Integre de cafdbae37, NEMOTRON.)

Contrat :
1. `wake <nom>` appelle POST `/supervisor/service/start/<nom>` (meme forme que l'etape start de `restart`)
2. La sortie reste lisible (meme format que les autres appels)
3. Aucun reseau reel (mock de _call)
"""  # noqa: E501

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "forge_supervisor_ctl_wake_nr", ROOT / "tools" / "forge_supervisor_ctl.py"
    )
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(m)
    return m


def test_wake_appelle_service_start(monkeypatch, capsys):
    m = _module()
    appels = []

    def fake_call(path, method="GET"):
        appels.append((path, method))
        return 200, '{"ok": true}'

    monkeypatch.setattr(m, "_call", fake_call)
    monkeypatch.setattr(m, "_sous_system", lambda: True)  # pas de detour par le hub
    monkeypatch.setattr(sys, "argv", ["forge_supervisor_ctl.py", "wake", "NokidoX"])
    rc = m.main()
    assert rc == 0
    assert len(appels) == 1
    assert appels[0][0] == "/supervisor/service/start/NokidoX"
    assert appels[0][1] == "POST"
    out = capsys.readouterr().out
    assert "HTTP 200" in out
