"""NR -- une delegation en vol DECLARE son intention a la regulation RAM : Hamilton ne tue plus l'executeur.

Mesure 2026-10-24 (deux observateurs) : `sandbox/supervisor_ordres.jsonl` porte 13 POST /supervisor/sleep/
NokidoTaskExecutor* signes RESOURCE_MANAGER a 20:27, 20:32, 20:38 et 20:48 ; le journal du superviseur, a la meme
seconde, `exited code=1` puis `wake` ~5 min plus tard, et `requalifier_orphelines` remettait la tache en pending.
Aucune delegation ne pouvait aboutir. Hamilton respecte deja les vetos de sommeil (`vetos_sommeil_actifs`, opposes
dans `regulation_hamilton_ram` et `_candidats_bail`) : l'executeur n'en posait jamais. Owner 24/10 : « l'intention
est plus forte que la regulation ». Contrat : pendant `_battement_delegation`, un veto existe pour le SERVICE
superviseur de l'executeur (deduit de son `--agent`, comme services.toml le declare), renouvele a chaque battement,
leve a la sortie.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_task_executor as T  # noqa: E402
import nokido_agent.app.forge_heartbeat as HB  # noqa: E402
import nokido_agent.app.forge_resource_manager as RM  # noqa: E402  (le nom d'import qu'utilise l'executeur)


def _prepare(tmp_path, monkeypatch, argv):
    monkeypatch.setattr(HB, "_ROOT", tmp_path)
    monkeypatch.setattr(RM, "_VETO_SOMMEIL_DIR", tmp_path / "veto_sommeil")
    monkeypatch.setattr(T, "_PROGRES_TOUTES_S", 0.05)
    monkeypatch.setattr(T, "touch_progress", lambda tid, checkpoint="": None)
    monkeypatch.setattr(sys, "argv", argv)


def test_service_de_l_executeur_deduit_de_son_agent(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["forge_task_executor.py", "--agent", "OPENCODE_GLM"])
    assert T._mon_service_superviseur() == "NokidoTaskExecutorOpencodeGlm"
    monkeypatch.setattr(sys, "argv", ["forge_task_executor.py", "--agent", "CLAUDE_HEADLESS"])
    assert T._mon_service_superviseur() == "NokidoTaskExecutorClaude"
    monkeypatch.setattr(sys, "argv", ["forge_task_executor.py"])
    assert T._mon_service_superviseur() == "NokidoTaskExecutor"


def test_le_veto_existe_pendant_la_delegation_puis_est_leve(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch, ["forge_task_executor.py", "--agent", "OPENCODE_GLM"])
    with T._battement_delegation("OPENCODE_GLM", "t_veto"):
        pendant = RM.vetos_sommeil_actifs()
        time.sleep(0.2)
        renouvele = RM.vetos_sommeil_actifs()
    assert "NokidoTaskExecutorOpencodeGlm" in pendant, pendant
    assert "t_veto" in pendant["NokidoTaskExecutorOpencodeGlm"]
    assert "NokidoTaskExecutorOpencodeGlm" in renouvele, renouvele
    assert "NokidoTaskExecutorOpencodeGlm" not in RM.vetos_sommeil_actifs()


def test_hamilton_epargne_l_executeur_qui_porte_une_intention(tmp_path, monkeypatch):
    """Chemin reel de la decision : le veto pose par le battement ecarte le service du plan de delestage."""
    _prepare(tmp_path, monkeypatch, ["forge_task_executor.py", "--agent", "OPENCODE_GLM"])
    plan = {"verdict": "SOI", "motif": "pression SOI", "delester": [
        {"service": "NokidoTaskExecutorOpencodeGlm", "classe": "DIFFERABLE", "rss_mb": 300.0},
        {"service": "NokidoRSSWatcher", "classe": "DIFFERABLE", "rss_mb": 100.0}]}
    with T._battement_delegation("OPENCODE_GLM", "t_h"):
        r = RM.regulation_hamilton_ram(plan, 95.0, 16.0, {}, time.time(), vetos=RM.vetos_sommeil_actifs())
    assert "NokidoTaskExecutorOpencodeGlm" not in r["choisis"], r
    assert "NokidoRSSWatcher" in r["choisis"], r


def test_un_veto_impossible_a_poser_ne_casse_pas_la_delegation(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch, ["forge_task_executor.py", "--agent", "OPENCODE_GLM"])
    monkeypatch.setattr(RM, "poser_veto_sommeil", lambda *a, **k: (_ for _ in ()).throw(OSError("acces refuse")))
    fait = []
    with T._battement_delegation("OPENCODE_GLM", "t_ko"):
        fait.append(1)
    assert fait == [1]
