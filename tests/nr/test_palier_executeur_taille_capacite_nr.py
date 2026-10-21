"""NR 18/10 -- routage des executeurs par TAILLE et CAPACITE (decision owner, choix multiple, 18/10 ~16 h 25).

Mesures du 18/10 : AGY sous sandbox ne lit ni n'ecrit de fichier (3 non-livraisons « SUCCESS ») ; WORKER_CODE rend la
meme forme ; GPTOSS est l'executeur d'ecriture le plus fiable ; Codex n'a quasiment plus de quota (owner). Decision :
  * S (ecriture ou lecture) -> instances OpenCode gratuites ;
  * M ECRITURE de code -> OPENCODE_GPTOSS d'abord, puis les autres OpenCode ;
  * M LECTURE (juge, carto, enquete via le hub) -> ANTIGRAVITY d'abord ;
  * jamais ANTIGRAVITY ni WORKER_CODE pour une tache qui ecrit ; Codex hors chaine jusqu'a nouvel ordre.
`_palier_executeurs(taille, ecrit)` rend l'ORDRE de preference ; l'escalade sur echec verifie reste a `_reaffecter`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_task_executor as te  # noqa: E402

NE_SAIT_PAS_ECRIRE = {"ANTIGRAVITY", "WORKER_CODE"}


def test_m_ecriture_va_d_abord_a_gptoss_et_jamais_aux_executeurs_sans_ecriture():
    ordre = te._palier_executeurs("M", ecrit=True)
    assert ordre and ordre[0] == "OPENCODE_GPTOSS", ordre
    assert not NE_SAIT_PAS_ECRIRE & set(ordre), ordre


def test_m_lecture_va_d_abord_a_agy():
    assert te._palier_executeurs("M", ecrit=False)[0] == "ANTIGRAVITY"


def test_s_reste_chez_opencode_et_l_ecriture_n_atteint_jamais_un_executeur_sans_ecriture():
    for taille in ("S", "M"):
        ordre = te._palier_executeurs(taille, ecrit=True)
        assert all(a.startswith("OPENCODE_") for a in ordre), (taille, ordre)
    assert all(a.startswith("OPENCODE_") for a in te._palier_executeurs("S", ecrit=False))


def test_codex_hors_chaine_jusqu_a_nouvel_ordre():
    for taille in ("S", "M"):
        for ecrit in (True, False):
            assert "CODEX" not in te._palier_executeurs(taille, ecrit=ecrit)
