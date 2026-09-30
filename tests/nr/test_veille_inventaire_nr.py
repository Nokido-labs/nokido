"""NR — identification d'un depot de veille (`forge_veille_inventaire`).

Chaque test encode un defaut REELLEMENT paye le 2026-09-08, pas une hypothese :

  * `test_un_fichier_du_code_local_n_est_pas_un_depot` — sans ce filtre, 678 des
    899 « depots » etaient des modules du code de Nokido (`forge_rag_warmup.py`,
    `forge_docker_monitor.py`...), chacun compte comme un depot a un seul fichier,
    donc classe A_REFAIRE. L'owner l'a dit : la veille EXTERNE, pas l'ingestion du
    code de Nokido.
  * `test_les_deux_conventions_designent_le_meme_depot` — `github:o/r/f` et
    `o_r/chemin` coexistaient sans vue commune, ce qui faisait lire deux
    patrimoines la ou il n'y en a qu'un.
  * `test_un_nom_de_depot_peut_contenir_un_point` — le filtre ne doit pas rejeter
    `llama.cpp` ni `OBOFoundry.github.io` : on rejette sur une EXTENSION connue,
    jamais sur la presence d'un point.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "app"))

inv = pytest.importorskip("forge_veille_inventaire")


def test_un_fichier_du_code_local_n_est_pas_un_depot():
    """Defaut mesure : 678 faux depots, tous des fichiers du code de Nokido."""
    for source in ("forge_rag_warmup.py", "forge_docker_monitor.py",
                   "gemini_poll_daemon.py", "mcp_nr.py"):
        assert inv.depot(source, "veille_code") is None, source
    # et les autres extensions courantes, pour que le filtre ne soit pas
    # une correction ponctuelle sur `.py`
    for source in ("ENDPOINTS_INVENTORY.md", "config.json", "index.ts",
                   "notes.txt", "manuel.pdf"):
        assert inv.depot(source, "ext_repo") is None, source


def test_les_deux_conventions_designent_un_depot():
    assert inv.depot("github:earendil-works/pi/src/a.rs", "ext_repo") == "earendil-works/pi"
    assert inv.depot("gh:nengo/nengo/README.md", "ext_repo") == "nengo/nengo"
    assert inv.depot("berriai_litellm/litellm/proxy/x.py", "sdk_gitingest") == "berriai_litellm"


def test_un_nom_de_depot_peut_contenir_un_point():
    """Le filtre rejette une EXTENSION connue, pas un point."""
    assert inv.depot("github:ggml-org/llama.cpp/README.md", "ext_repo") == "ggml-org/llama.cpp"
    assert inv.depot("github:OBOFoundry/OBOFoundry.github.io/x.md",
                     "ext_repo") == "OBOFoundry/OBOFoundry.github.io"


def test_le_prefixe_gitingest_veille_est_retire():
    """`gitingest_veille_veracrypt_veracrypt.txt` designe le depot veracrypt."""
    d = inv.depot("gitingest_veille_veracrypt_veracrypt.txt#section2", "sdk_gitingest")
    assert d == "veracrypt_veracrypt", d


def test_un_domaine_hors_veille_ne_produit_pas_de_depot():
    assert inv.depot("app/forge_rag_engine.py", "nokido_code") is None
    assert inv.depot("conv_claude/abc/12", "conv") is None


def test_une_famille_regroupe_par_emetteur():
    assert inv.famille("https://arxiv.org/abs/2503.21676") == "arxiv.org"
    assert inv.famille("github:owner/repo/f.py") == "github"
    assert inv.famille("") == "(vide)"


def test_les_prefixes_non_depot_sont_ecartes():
    """`docset` pese 912 809 chunks : sans cette liste il passerait pour le plus
    gros depot GitHub de la base."""
    for tete in ("docset", "claude_docs", "mcp_result", "session"):
        assert inv.depot("%s/quelque/chose" % tete, "veille_code") is None, tete
