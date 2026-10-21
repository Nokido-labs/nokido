"""NR -- executeur Mistral Vibe partie 2 : binaire ABSOLU dans le harness, job harness sur le patron Codex (16/10).

RED ecrit par Claude AVANT le code. Mesure 16/10 : forge_cli_harness.agent_bin rend `shutil.which(name)` pour un agent
inconnu ; or DEUX `vibe` sont sur le PATH de l'owner (~/.local/bin/vibe.exe = mistral_vibe 2.24.5, et npm\\vibe.cmd) :
le premier trouve gagnerait. Le binaire se designe donc par LAFORGE_VIBE_BIN, sinon ~/.local/bin/vibe.exe sous
LAFORGE_AGENT_HOME (ou le profil) -- jamais une recherche dans le PATH.
"""
import json
import os
import sys
from pathlib import Path

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import forge_task_executor as T  # noqa: E402
from nokido_agent.app import forge_cli_harness as H  # noqa: E402


def test_agent_bin_vibe_honore_l_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_VIBE_BIN", str(tmp_path / "x" / "vibe.exe"))
    assert H.agent_bin("vibe") == str(tmp_path / "x" / "vibe.exe")


def test_agent_bin_vibe_ne_cherche_pas_dans_le_path(monkeypatch, tmp_path):
    monkeypatch.delenv("LAFORGE_VIBE_BIN", raising=False)
    home = tmp_path / "home"
    vrai = home / ".local" / "bin" / "vibe.exe"
    vrai.parent.mkdir(parents=True)
    vrai.write_text("", encoding="utf-8")
    leurre = tmp_path / "npm"
    leurre.mkdir()
    (leurre / "vibe.cmd").write_text("@echo leurre", encoding="utf-8")
    monkeypatch.setenv("LAFORGE_AGENT_HOME", str(home))
    monkeypatch.setenv("PATH", str(leurre) + os.pathsep + os.environ.get("PATH", ""))
    assert Path(H.agent_bin("vibe")) == vrai


def test_la_delegation_ecrit_un_job_harness_vibe_borne(monkeypatch, tmp_path):
    wt = tmp_path / "wt"
    (wt / ".git").mkdir(parents=True)
    monkeypatch.setenv("LAFORGE_VIBE_WORKDIR", str(wt))
    monkeypatch.setattr(T, "_HARNESS_JOBS", tmp_path / "jobs")
    (tmp_path / "jobs").mkdir()
    vus = {}

    def _attendre(job, delai, attente_file_s=None, task_id=None):  # vrai contrat (d8abd05aa : battement par task_id)
        vus["job"] = json.loads(Path(job).read_text(encoding="utf-8"))
        vus["task_id"] = task_id
        return {"ok": True, "output": '{"intent":"OK_DONE","pointer_ref":"x"}'}

    monkeypatch.setattr(T, "_attendre_harness", _attendre)
    monkeypatch.setattr(T, "_etat_git", lambda wt_: None)
    monkeypatch.setattr(T, "_committer_pour_agent", lambda *a, **k: None)
    monkeypatch.setattr(T, "_juger_livraison", lambda ok, detail, wt_, avant: (ok, "commits produits : 1", None))
    monkeypatch.setattr(T, "_clore_delegation", lambda *a, **k: vus.setdefault("clos", (a, k)))
    T._delegate_to_vibe({"id": "t1", "description": "fais X"}, "jeton-factice")
    job = vus["job"]
    assert job["agent"] == "vibe", job
    # Contrat revu le 17/10 (e25440612 / 6e688cb7f) : le prompt part dans un FICHIER (--prompt-file), plus sur stdin --
    # sur stdin, Vibe ouvrait sa TUI (autopsie du job spool). L'intention du NR est gardee : job borne, dans son worktree,
    # qui porte bien la tache.
    prompt = Path(job["args"][job["args"].index("--prompt-file") + 1])
    assert job["args"] == T._args_vibe(str(wt), prompt_file=prompt), job
    assert job["cwd"] == str(wt) and not job.get("send") and "fais X" in prompt.read_text(encoding="utf-8"), job
    assert "clos" in vus
    assert vus["task_id"] == "t1", "la delegation Vibe doit passer son task_id pour battre pendant l'attente"
