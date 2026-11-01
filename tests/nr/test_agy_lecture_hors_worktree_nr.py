"""NR -- une lecture hors du worktree de tache ne tue plus une delegation AGY en silence.

31/10 (job_b2738b35, etude UI OmniRoute) : read_file soft-denied en headless (allow = nokido_worktrees\\** + 2 docs),
agy s'arrete, et ni denied_actions, ni stderr, ni --log-file ne nomment le chemin vise. Deux reparations :
(1) la consigne FIXE dit a AGY de lire toute source externe (depot ingere, doc, RAG) par les outils MCP du hub ;
(2) l'executeur releve AVANT le lancement les chemins absolus de la consigne hors du bac et les NOMME au journal.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_task_executor as T  # noqa: E402

WD = r"C:\U\nokido_worktrees\taches\antigravity_abc"


def test_la_consigne_dit_de_lire_l_externe_par_le_hub():
    c = T._consigne_agy(WD)
    assert "rag" in c and "hors de ce repertoire" in c.lower()


def test_le_texte_hors_worktree_est_fixe_avant_la_partie_variable():
    c = T._consigne_agy(WD)
    assert c.index(T._CONSIGNE_HORS_WORKTREE_AGY.strip()[:40]) < c.index(WD)


def test_chemins_hors_bac_nommes():
    desc = (r"Lis C:\tmp\laforge_jobs\x.py puis %s\app\forge_ssot.py et %USERPROFILE%/.gemini/settings.json ; "
            r"source github:cheaper-inference/OmniRoute") % WD
    hors = T._chemins_hors_bac(desc, WD)
    assert any("laforge_jobs" in h for h in hors) and any(".gemini" in h for h in hors)
    assert not any("forge_ssot" in h for h in hors)


def test_worktree_a_espaces_n_est_pas_hors_bac():
    # 31/10 08:02 (job_f74513a2) : « C:\...\Script python IA\nokido_worktrees\... » coupe a l'espace -> faux positif
    wd = r"C:\Users\N\Script python IA\nokido_worktrees\taches\antigravity_f7"
    desc = r"Lis %s\app\web_hub\index.html puis C:\Users\N\Script python IA\Nokido\tools\x.py" % wd
    hors = T._chemins_hors_bac(desc, wd)
    assert hors == [r"C:\Users\N\Script python IA\Nokido\tools\x.py"]


def test_aucun_chemin_hors_bac():
    assert T._chemins_hors_bac(r"Corrige %s\tools\a.py ; voir https://x.org/a/b" % WD, WD) == []
