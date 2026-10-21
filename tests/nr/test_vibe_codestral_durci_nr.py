"""NR -- Vibe autonome sur codestral, durci (decision owner 20/10 : « Codestral durci + j'ouvre un acces »).

Mesure 20/10 sous Vibe 3.0.1 / codestral-latest (seul modele ouvert sur nos cles, census du 20/10) :
- job_499ed100 : `Stopped: turn_limit` a 30 tours, 6 effets, aucun message ; rejeu : 21 effets dont 6 `vibe.todo`,
  6 `search_tool_functions` et un appel `skill` REFUSE (le --disabled-tools de 3.0.1 refuse a l'appel, il ne retire
  plus l'outil) -- les tours partent en bruit ;
- le rejeu a modifie un fichier EXISTANT par `write_file` : indentation cassee, fonction demandee absente, OK_DONE.
Durcissement : la consigne impose `search_replace` pour un fichier existant et interdit todo / skill ; la borne de tours
passe de 30 a 60 (la limite de duree reste le garde-fou).
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402


def test_la_borne_de_tours_par_defaut_est_60(monkeypatch, tmp_path):
    monkeypatch.delenv("LAFORGE_VIBE_MAX_TURNS", raising=False)
    args = T._args_vibe(tmp_path)
    assert args[args.index("--max-turns") + 1] == "60", args


def test_la_consigne_envoyee_a_vibe_impose_search_replace(tmp_path, monkeypatch):
    """Chemin reel : la consigne est lue dans le fichier de prompt que `_delegate_to_vibe` ecrit pour le harness."""
    monkeypatch.setattr(T, "_modele_hors_quota", lambda *_a: None)
    monkeypatch.setattr(T, "_workdir_vibe", lambda: tmp_path / "wt")
    monkeypatch.setattr(T, "_HARNESS_JOBS", tmp_path / "jobs")
    monkeypatch.setattr(T, "_config_mcp_vibe", lambda _wt: None)
    monkeypatch.setattr(T, "_etat_git", lambda _wt: None)
    monkeypatch.setattr(T, "_chemins_status", lambda _wt: frozenset())
    monkeypatch.setattr(T, "_battement_delegation", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(T, "_attendre_harness", lambda *_a, **_k: {"ok": False, "output": "Error: arret du NR"})
    monkeypatch.setattr(T, "_juger_livraison", lambda ok, detail, wt, avant: (ok, "commits produits : 0", None))
    monkeypatch.setattr(T, "_consigner_verdict_auto", lambda *_a, **_k: None)
    monkeypatch.setattr(T, "_motif_reaffectation_apres", lambda *_a, **_k: None)
    monkeypatch.setattr(T, "_clore_delegation", lambda *_a, **_k: None)
    T._delegate_to_vibe({"id": "job_vibe_durci_nr", "description": "modifie app/x.py"}, "tok")
    (prompt,) = list((tmp_path / "jobs").glob("*.prompt.md"))
    texte = prompt.read_text(encoding="utf-8")
    assert "search_replace" in texte, texte[-600:]
    assert "write_file" in texte and "todo" in texte and "skill" in texte, texte[-600:]
