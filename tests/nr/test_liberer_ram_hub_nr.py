"""NR choix owner 9/11 : « Exposer la primitive ».

La primitive d'endormissement par utilité (`request_resources`) n'était joignable hors hub que par
POST /api/resource/request avec un jeton d'organe du coffre : aucun CLI ne pouvait l'appeler sans
exposer le secret. L'action `hub action=liberer_ram` l'appelle DANS le hub, via
`liberer_ram_pour_hub` : identité prouvée exigée, bornes, et jamais de délégation au hub lui-même.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import forge_resource_manager as rm  # noqa: E402


def test_identite_non_prouvee_refusee(monkeypatch):
    appels = []
    monkeypatch.setattr(rm, "request_resources", lambda *a, **k: appels.append((a, k)) or {"ok": True})
    r = rm.liberer_ram_pour_hub(4.5, prouve=False)
    assert r["ok"] is False and "identite" in r["error"]
    assert appels == []


def test_bornes(monkeypatch):
    monkeypatch.setattr(rm, "request_resources", lambda *a, **k: {"ok": True})
    for mauvais in (0, -1, 13, "abc", None):
        assert rm.liberer_ram_pour_hub(mauvais, prouve=True)["ok"] is False


def test_appel_dans_le_hub_sans_delegation(monkeypatch):
    vus = {}

    def faux(needed_ram_gb, allow_evict=False, deleguer=True, proteger_docker=False):
        vus.update(needed=needed_ram_gb, evict=allow_evict, deleguer=deleguer)
        return {"ok": True, "action": ["ollama:x"]}

    monkeypatch.setattr(rm, "request_resources", faux)
    r = rm.liberer_ram_pour_hub(4.5, prouve=True)
    assert r["ok"] is True and r["action"] == ["ollama:x"]
    assert vus == {"needed": 4.5, "evict": True, "deleguer": False}


def test_action_cablee_dans_le_schema_et_le_routage():
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    assert '"liberer_ram",' in src
    assert re.search(r'action == "liberer_ram".*?liberer_ram_pour_hub', src, re.S)
