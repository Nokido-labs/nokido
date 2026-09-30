"""
tests/nr/test_process_identity_nr.py - NR d'EFFET de app/forge_process_identity.py.

Decision owner 2026-08-21 : plus jamais `ps | grep python` - identite d'un
process du hub = signature env + REGISTRE (pid + start_time). On mesure les
EFFETS : la signature posee dans l'env d'un enfant, l'inscription au registre,
l'identification de NOTRE propre pid (vrai psutil, vrai start_time), et le
demasquage d'un pid reutilise (start_time decale).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
for p in (str(ROOT), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import forge_process_identity as FPI  # noqa: E402


@pytest.fixture
def registre_tmp(tmp_path, monkeypatch):
    """Registre isole : le test ne touche jamais sandbox/process_registry.jsonl."""
    reg = tmp_path / "process_registry.jsonl"
    monkeypatch.setattr(FPI, "_REG", reg)
    monkeypatch.setattr(FPI, "_RUN_ID_FILE", tmp_path / "hub_run_id")
    monkeypatch.setattr(FPI, "_run_id", None)
    monkeypatch.delenv("NOKIDO_HUB_RUN_ID", raising=False)
    return reg


class TestRunId:
    def test_stable_pour_la_vie_du_process(self, registre_tmp):
        assert FPI.get_hub_run_id() == FPI.get_hub_run_id()

    def test_respecte_l_env_preexistant(self, registre_tmp, monkeypatch):
        monkeypatch.setattr(FPI, "_run_id", None)
        monkeypatch.setenv("NOKIDO_HUB_RUN_ID", "run-herite-42")
        assert FPI.get_hub_run_id() == "run-herite-42"

    def test_ecrit_le_fichier_de_visibilite(self, registre_tmp, tmp_path):
        rid = FPI.get_hub_run_id()
        assert (tmp_path / "hub_run_id").read_text(encoding="utf-8") == rid


class TestSignatureEnfant:
    def test_stamp_env_pose_la_signature(self, registre_tmp):
        env = FPI.stamp_env({}, "svc-test", instance="7")
        assert env["NOKIDO_SERVICE_ID"] == "svc-test"
        assert env["NOKIDO_INSTANCE"] == "7"
        assert env["NOKIDO_HUB_RUN_ID"] == FPI.get_hub_run_id()


class TestRegistreEtIdentification:
    def test_mon_propre_pid_est_identifie(self, registre_tmp):
        """Effet complet : record -> registre -> identify (vrai start_time psutil)."""
        FPI.record(os.getpid(), "svc-moi", instance="a")
        ident = FPI.identify_process(os.getpid())
        assert ident["known"] is True, f"pid non retrouve : {ident}"
        assert ident["service_id"] == "svc-moi"

    def test_pid_reutilise_demasque_par_start_time(self, registre_tmp):
        """Une ligne au bon pid mais au start_time decale (>2 s) ne doit PAS
        identifier : c'est un pid recycle par l'OS."""
        FPI.record(os.getpid(), "svc-fantome")
        lignes = registre_tmp.read_text(encoding="utf-8").splitlines()
        row = json.loads(lignes[-1])
        row["start_time"] = (row["start_time"] or 0) - 10.0
        registre_tmp.write_text(json.dumps(row) + "\n", encoding="utf-8")
        ident = FPI.identify_process(os.getpid())
        assert ident["known"] is False, "un pid recycle a ete identifie a tort"

    def test_record_best_effort_ne_leve_jamais(self, registre_tmp, monkeypatch):
        """Le registre ne doit jamais faire echouer un spawn (contrat du module)."""
        monkeypatch.setattr(FPI, "_REG", Path("Z:/inexistant/registry.jsonl"))
        FPI.record(os.getpid(), "svc-sans-registre")  # ne doit pas lever
