"""NR -- une delegation longue DECLARE son travail dans le pouls de l'executeur : le superviseur ne la tue plus a 60 min.

Mesure 2026-10-17 : pouls de NokidoTaskExecutorAntigravity fige a 15:20:49 (il ne bat qu'en tete de boucle), relance
par le superviseur a 16:20:55 -- palier `slow`, stale_restart_s = 3600 (proxy_deno/core/supervisor.ts:294) -- en
pleine instruction R6 (job_b8b7befd orpheline). Le superviseur sait deja s'abstenir : « l'organe declare un travail en
cours » (raw.travail_en_cours + travail_depuis_s, supervisor.ts:3162-3183, plafond 4 x 3600 s). Personne ne le
declarait. Contrat : `_battement_delegation(agent, task_id)` bat, pendant la delegation, le bail de MISSION
(touch_progress) ET le pouls de l'EXECUTEUR (travail_en_cours, travail_depuis_s, tache), puis redeclare la fin.
OpenCode, qui n'avait aucun battement pendant prompt(), en beneficie aussi.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402
import nokido_agent.app.forge_heartbeat as HB  # noqa: E402  (le nom d'import qu'utilise l'executeur)


def _pouls(tmp_path, agent):
    return json.loads((tmp_path / "sandbox" / ("task_executor_%s.heartbeat" % agent.lower())).read_text(encoding="utf-8"))


def test_le_battement_declare_le_travail_puis_sa_fin(tmp_path, monkeypatch):
    monkeypatch.setattr(HB, "_ROOT", tmp_path)
    monkeypatch.setattr(T, "_PROGRES_TOUTES_S", 0.05)
    progres = []
    monkeypatch.setattr(T, "touch_progress", lambda tid, checkpoint="": progres.append(tid))
    with T._battement_delegation("ANTIGRAVITY", "t1"):
        time.sleep(0.3)
        pendant = _pouls(tmp_path, "ANTIGRAVITY")
    assert pendant.get("travail_en_cours") is True and pendant.get("tache") == "t1", pendant
    assert isinstance(pendant.get("travail_depuis_s"), (int, float))
    assert progres and set(progres) == {"t1"}
    apres = _pouls(tmp_path, "ANTIGRAVITY")
    assert apres.get("travail_en_cours") is False, apres


def test_le_pouls_est_declare_des_l_entree_meme_si_le_bail_est_lent(tmp_path, monkeypatch):
    """CI de reference 8a10f34da : test_opencode_declare_son_travail_pendant_le_tour ROUGE sous xdist (4 workers), vert
    seul. Cause : le 1er battement partait dans un THREAD ; sous charge il arrivait apres la lecture du pouls (0,2 s).
    La docstring promet « la declaration existe des l'entree » : le 1er battement doit etre emis AVANT de rendre la main.
    Deterministe : un bail de mission lent (0,5 s) et une lecture IMMEDIATE du pouls a l'entree."""
    monkeypatch.setattr(sys.modules["nokido_agent.app.forge_heartbeat"], "_ROOT", tmp_path)
    monkeypatch.setattr(T, "_PROGRES_TOUTES_S", 0.05)
    monkeypatch.setattr(T, "touch_progress", lambda tid, checkpoint="": time.sleep(0.5))
    with T._battement_delegation("ANTIGRAVITY", "t_entree"):
        pouls = _pouls(tmp_path, "ANTIGRAVITY")
    assert pouls.get("travail_en_cours") is True and pouls.get("tache") == "t_entree", pouls


class PromptQuiRegardeLePouls:
    """Doublure au contrat REEL d'ACPClient ; son prompt() releve le pouls de l'executeur PENDANT le tour."""

    vu = None

    def __init__(self, cmd=None, cwd=None, on_log=None, agent="gemini", env=None):
        self.chemin = None

    def start(self):
        return None

    def initialize(self):
        return {}

    def session_new(self):
        return "sid-1"

    def request(self, method, params, timeout=30):
        return {}

    def prompt(self, sid, text, timeout=30):
        time.sleep(0.2)
        PromptQuiRegardeLePouls.vu = json.loads(PromptQuiRegardeLePouls.chemin.read_text(encoding="utf-8"))
        return {"text": 'fait {"intent":"OK_DONE","pointer_ref":"x"}'}

    def close(self):
        return None


def test_opencode_declare_son_travail_pendant_le_tour(tmp_path, monkeypatch):
    monkeypatch.setattr(HB, "_ROOT", tmp_path)
    monkeypatch.setattr(T, "_PROGRES_TOUTES_S", 0.05)
    monkeypatch.setattr(T, "touch_progress", lambda tid, checkpoint="": None)
    PromptQuiRegardeLePouls.chemin = tmp_path / "sandbox" / "task_executor_opencode_glm.heartbeat"
    monkeypatch.setattr(T, "ACPClient", PromptQuiRegardeLePouls)
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_OPENCODE_GLM_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: "commit ok")
    monkeypatch.setattr(T, "_juger_livraison",
                        lambda ok, detail, wt_, avant, autorises=None: (ok, "commits produits : 1", "OK_DONE"))
    monkeypatch.setattr(T, "_jeton_opencode_instance", lambda inst: "jeton_coffre_%s" % inst)
    monkeypatch.setattr(T, "_clore_delegation", lambda *a, **k: None)
    T._delegate_to_opencode({"id": "job_pouls_01", "agent": "OPENCODE_GLM",
                             "description": "Consigne de test assez longue pour etre extraite par l'executeur."}, "jx")
    vu = PromptQuiRegardeLePouls.vu or {}
    assert vu.get("travail_en_cours") is True and vu.get("tache") == "job_pouls_01", vu


def test_agy_et_harness_passent_par_le_meme_battement():
    import inspect
    for fn in (T._delegate_to_agy, T._delegate_to_codex, T._delegate_to_vibe):
        assert "_battement_delegation(" in inspect.getsource(fn), fn.__name__
