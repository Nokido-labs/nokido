"""NR 30/10 : une tache deposee pour un agent dont l'executeur DORT le fait demarrer (intention), sans attendre 82 % RAM.

Mesure (docs/enquetes/reveil_apres_delestage_20261030.md) : le superviseur ne reveille un service deleste que sous
RAM_WAKE_PCT 82 % et sous budget 84 % ; RAM tenue entre 82 et 88 % = executeurs AGY/Mistral/Claude endormis, taches
deposees sans personne pour les reclamer (rendus a la main le 30/10). L'assignation est une INTENTION : le registre
demande au superviseur de demarrer l'executeur ; l'admission RAM reste celle du superviseur (gate should_spawn).
"""
import types

from nokido_agent.app import forge_mcp_registry as mr

TOML = '''
[[service]]
name = "NokidoTaskExecutorAntigravity"
disabled = false
args = ["${NOKIDO_DEPOT}/tools/forge_task_executor.py", "--agent", "ANTIGRAVITY"]

[[service]]
name = "NokidoTaskExecutorCodex"
disabled = true
args = ["${NOKIDO_DEPOT}/tools/forge_task_executor.py", "--agent", "CODEX"]

[[service]]
name = "NokidoTaskExecutor"
args = ["${NOKIDO_DEPOT}/tools/forge_task_executor.py"]
'''


def _registre(tmp_path):
    (tmp_path / "proxy_deno" / "core").mkdir(parents=True)
    (tmp_path / "proxy_deno" / "core" / "services.toml").write_text(TOML, encoding="utf-8")
    reg = mr.ToolRegistry.__new__(mr.ToolRegistry)
    reg.root = tmp_path
    return reg


def test_services_executeurs_de_lit_le_drapeau_agent(tmp_path):
    reg = _registre(tmp_path)
    assert reg._services_executeurs_de("ANTIGRAVITY") == ["NokidoTaskExecutorAntigravity"]
    assert reg._services_executeurs_de("CODEX") == []  # coupe (disabled) : ne pas le reveiller
    assert reg._services_executeurs_de("INCONNU") == []


def test_assignation_demande_le_demarrage_au_superviseur(tmp_path, monkeypatch):
    reg = _registre(tmp_path)
    vus = []

    class _Rep:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mr.urllib.request if hasattr(mr, "urllib") else __import__("urllib.request").request,
                        "urlopen", lambda req, timeout=None: vus.append((req.full_url, req.get_method())) or _Rep())
    monkeypatch.setattr("threading.Thread", lambda target=None, **k: types.SimpleNamespace(start=target))
    reg._reveiller_executeur_de("ANTIGRAVITY")
    assert vus == [("http://127.0.0.1:8765/supervisor/service/start/NokidoTaskExecutorAntigravity", "POST")]


def test_agent_sans_executeur_ne_demande_rien(tmp_path, monkeypatch):
    reg = _registre(tmp_path)
    vus = []
    monkeypatch.setattr(__import__("urllib.request").request, "urlopen", lambda *a, **k: vus.append(a))
    monkeypatch.setattr("threading.Thread", lambda target=None, **k: types.SimpleNamespace(start=target))
    reg._reveiller_executeur_de("INCONNU")
    assert vus == []
