"""NR (owner 29/10 : « lance en priorite les veilles sur l'auto-regulation ») : une veille declaree PRIORITAIRE passe
avant l'ordre d'arrivee ; sans fichier de priorite, l'ordre d'arrivee (27/10) est inchange."""
import json

import pytest

import nokido_agent.app.forge_chain_executor as ce


@pytest.fixture()
def executeur(tmp_path, monkeypatch):
    monkeypatch.setattr(ce, "_ram_en_satiete", lambda: False)
    monkeypatch.setenv("LAFORGE_VEILLES_MAX", "2")
    monkeypatch.setattr(ce, "_FICHIER_VEILLES_PRIORITAIRES", tmp_path / "veilles_prioritaires.json")
    ex = ce.ChainExecutor.__new__(ce.ChainExecutor)

    class _Conn:
        def execute(self, *a, **k):
            class _R:
                def fetchall(self):
                    return []
            return _R()

        def close(self):
            pass

    ex._get_conn = lambda: _Conn()
    return ex, tmp_path / "veilles_prioritaires.json"


def _chaines():
    return {"wj_secu1": [{"created_at": "2026-10-29T14:16:00"}],
            "wj_secu2": [{"created_at": "2026-10-29T14:16:01"}],
            "wj_homeo1": [{"created_at": "2026-10-29T14:28:00"}],
            "wj_homeo2": [{"created_at": "2026-10-29T14:28:01"}]}


def test_sans_fichier_ordre_d_arrivee(executeur):
    ex, _ = executeur
    assert set(ex._etaler_veilles(_chaines())) == {"wj_secu1", "wj_secu2"}


def test_prioritaires_passent_en_premier(executeur):
    ex, fichier = executeur
    fichier.write_text(json.dumps({"chains": ["wj_homeo2", "wj_homeo1"]}), encoding="utf-8")
    assert set(ex._etaler_veilles(_chaines())) == {"wj_homeo1", "wj_homeo2"}


def test_fichier_illisible_ordre_d_arrivee(executeur):
    ex, fichier = executeur
    fichier.write_text("{pas du json", encoding="utf-8")
    assert set(ex._etaler_veilles(_chaines())) == {"wj_secu1", "wj_secu2"}
