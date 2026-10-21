"""NR -- disjoncteur d'impulsion et anti-polling de hook_capability_gate (GO owner 16/10, « refus au-dela »).

RED ecrit par Claude, implementation par un autre agent (le garde contraint Claude ; l'interrupteur reste a l'owner).
Mesure du 16/10 : ~8 sondes `run` fines en serie sur un meme diagnostic, et 4 lectures du `.progress.json` d'un job
deja surveille par un Monitor. Chaque tour refacture tout l'historique.

Interface attendue (chemin REEL : sous-processus, JSON sur stdin, code de sortie) :
  NOKIDO_GATE_ETAT     fichier d'etat JSON (rafales, monitors armes)
  NOKIDO_GATE_MODE     observer | refuser   (defaut production : observer)
  NOKIDO_GATE_HORLOGE  epoch simule (tests)
  NOKIDO_GATE_JOBS     dossier des jobs (defaut : sandbox/jobs du depot) ; <job>.rc present = job TERMINE
Refus = exit 2 + raison sur stderr ; avertissement = exit 0 + texte dans la sortie.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(os.environ.get("NOKIDO_GATE_HOOK_FICHIER")
            or Path(__file__).resolve().parents[2] / "tools" / "hook_capability_gate.py")


def _appel(tmp_path, t, tool_name, tool_input, mode="refuser"):
    (tmp_path / "jobs").mkdir(exist_ok=True)
    env = {**os.environ, "NOKIDO_GATE_ETAT": str(tmp_path / "etat.json"), "NOKIDO_GATE_MODE": mode,
           "NOKIDO_GATE_HORLOGE": str(t), "NOKIDO_GATE_JOBS": str(tmp_path / "jobs"), "PYTHONNOUSERSITE": "1",
           # 18/10 : sans lui, chaque passage ecrivait dans le VRAI journal de mesure du bruit
           "NOKIDO_GATE_JOURNAL": str(tmp_path / "journal.jsonl")}
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_name": tool_name, "tool_input": tool_input}),
                       capture_output=True, text=True, errors="replace", env=env, timeout=60)
    return r.returncode, r.stdout + r.stderr


RUN = "mcp__laforge-sovereign-hub__run"


def _sonde(code="print(1)"):
    return {"action": "python", "code": code}


def test_la_troisieme_sonde_fine_en_rafale_est_refusee(tmp_path):
    t0 = 1_800_000_000
    assert _appel(tmp_path, t0, RUN, _sonde())[0] == 0
    assert _appel(tmp_path, t0 + 10, RUN, _sonde())[0] == 0
    rc, sortie = _appel(tmp_path, t0 + 20, RUN, _sonde())
    assert rc == 2, sortie
    assert "UN script" in sortie or "run_job" in sortie, sortie


def test_des_appels_paralleles_d_un_meme_message_comptent_un_seul_tour(tmp_path):
    t0 = 1_800_000_000
    rcs = [_appel(tmp_path, t0 + d, RUN, _sonde())[0] for d in (0, 0.5, 1.0)]
    assert rcs == [0, 0, 0]


def test_une_edition_remet_le_compteur_a_zero(tmp_path):
    t0 = 1_800_000_000
    _appel(tmp_path, t0, RUN, _sonde())
    _appel(tmp_path, t0 + 10, RUN, _sonde())
    _appel(tmp_path, t0 + 15, "mcp__laforge-sovereign-hub__governed_edit", {"path": "tools/x.py", "blocks": "..."})
    assert _appel(tmp_path, t0 + 20, RUN, _sonde())[0] == 0


def test_en_mode_observer_la_rafale_est_dite_sans_refus(tmp_path):
    t0 = 1_800_000_000
    for d in (0, 10):
        _appel(tmp_path, t0 + d, RUN, _sonde(), mode="observer")
    rc, sortie = _appel(tmp_path, t0 + 20, RUN, _sonde(), mode="observer")
    assert rc == 0
    assert "rafale" in sortie.lower() or "impulsion" in sortie.lower(), sortie


def test_un_job_surveille_par_un_monitor_ne_se_relit_pas(tmp_path):
    t0 = 1_800_000_000
    mon = {"command": '"python.exe" "tools/forge_job_watch_cli.py" --job job_abc123 --max-s 1780',
           "description": "x", "timeout_ms": 1800000}
    assert _appel(tmp_path, t0, "Monitor", mon)[0] == 0
    rc, sortie = _appel(tmp_path, t0 + 60, RUN, {"action": "job_status", "job_id": "job_abc123"})
    assert rc == 2, sortie
    rc, _ = _appel(tmp_path, t0 + 120, "Read", {"file_path": "C:/x/Nokido/sandbox/jobs/job_abc123.progress.json"})
    assert rc == 2
    # Monitor expire (30 min) : la lecture redevient permise
    assert _appel(tmp_path, t0 + 1900, RUN, {"action": "job_status", "job_id": "job_abc123"})[0] == 0


def test_un_job_termine_se_lit_meme_sous_monitor(tmp_path):
    """Le Monitor annonce la FIN : lire le verdict est alors le geste voulu, pas du polling (revue 16/10)."""
    t0 = 1_800_000_000
    mon = {"command": "x --job job_fini42 --max-s 1780", "description": "x", "timeout_ms": 1800000}
    _appel(tmp_path, t0, "Monitor", mon)
    (tmp_path / "jobs" / "job_fini42.rc").write_text("0", encoding="utf-8")
    assert _appel(tmp_path, t0 + 60, RUN, {"action": "job_status", "job_id": "job_fini42"})[0] == 0


def test_les_verdicts_existants_du_hook_sont_conserves():
    """Garde contre une REECRITURE du hook (revue 16/10, la proposition Gemini remplacait le fichier entier) : les
    verdicts existants restent et main() les appelle toujours."""
    import importlib.util
    import inspect

    spec = importlib.util.spec_from_file_location("hook_sous_test", str(HOOK))
    H = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(H)
    corps_main = inspect.getsource(H.main)
    for nom in ("verdict_forme", "verdict_compte", "verdict_ci_en_cours", "verdict_depense"):
        assert hasattr(H, nom), "verdict existant efface : %s" % nom
        assert nom in corps_main, "verdict existant plus appele par main() : %s" % nom


def test_un_autre_job_reste_lisible(tmp_path):
    t0 = 1_800_000_000
    mon = {"command": "x --job job_abc123 --max-s 1780", "description": "x", "timeout_ms": 1800000}
    _appel(tmp_path, t0, "Monitor", mon)
    assert _appel(tmp_path, t0 + 60, RUN, {"action": "job_status", "job_id": "job_zzz999"})[0] == 0
