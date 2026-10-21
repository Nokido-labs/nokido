"""NR -- Vibe autonome se lance en mode PROGRAMMATIQUE (--prompt-file), jamais dans sa TUI (17/10).

Autopsie du job spool (tache job_d8f73edb, 5,6 M car. de sortie, worktree vierge apres 25 min) : la sortie est un ECRAN
de TUI (ecran alterne ANSI, 1 262 trames de spinner, « Retrying », « Run /retry ... ») -- le prompt partait sur stdin et
aucun drapeau programmatique n'etait passe. METADATA de mistral_vibe 2.26.1 (mesure 17/10) : « --prompt-file PATH : Read
the prompt from a file instead of --prompt » ; --max-turns / --output / --time-limit sont des options du mode --prompt.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as E  # noqa: E402


def test_les_arguments_portent_le_fichier_de_prompt():
    args = E._args_vibe(Path("W"), Path("P.prompt.md"))
    assert args[args.index("--prompt-file") + 1] == "P.prompt.md", args


def test_la_delegation_ecrit_le_prompt_et_n_envoie_rien_sur_stdin(tmp_path, monkeypatch):
    jobs = tmp_path / "harness_jobs"
    monkeypatch.setattr(E, "_HARNESS_JOBS", jobs)
    monkeypatch.setattr(E, "_workdir_vibe", lambda: tmp_path / "wt")
    monkeypatch.setattr(E, "_config_mcp_vibe", lambda wt: None)
    monkeypatch.setattr(E, "_etat_git", lambda wt: ("h", 0))
    monkeypatch.delenv("LAFORGE_VIBE_EXEC_ARGS", raising=False)
    vus = {}

    def _attendre(job, delai_s, **_k):
        vus["job"] = json.loads(Path(job).read_text(encoding="utf-8"))
        return {"ok": False, "error": "arret du test"}

    monkeypatch.setattr(E, "_attendre_harness", _attendre)
    monkeypatch.setattr(E, "_juger_livraison", lambda ok, detail, wt, avant, *a, **k: (ok, "effet", None))
    monkeypatch.setattr(E, "_clore_delegation", lambda *a, **k: None)
    E._delegate_to_vibe({"id": "t-vibe", "description": "zorglub repeint les quokkas"}, "jeton-de-test")
    job = vus["job"]
    assert not job.get("send"), "le prompt ne part plus sur stdin (Vibe ouvrait sa TUI)"
    prompt = Path(job["args"][job["args"].index("--prompt-file") + 1])
    assert prompt.exists() and "zorglub repeint les quokkas" in prompt.read_text(encoding="utf-8")
