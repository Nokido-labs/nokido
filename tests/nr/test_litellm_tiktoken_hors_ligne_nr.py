# -*- coding: utf-8 -*-
"""NR — litellm doit s'importer HORS LIGNE : le garde tiktoken reste posé.

__FORGE_COLOR__ = "metabolisme/llm : non-regression de l import litellm hors ligne"

CE QUI A ÉTÉ PAYÉ (2026-09-07). Monter `litellm` 1.83.7 → 1.96.0 a fermé 7 CVE dont les 4
critiques, et introduit une régression d'import : depuis 1.96, litellm charge l'encodage
tiktoken `cl100k_base` **à l'import** (chaîne `compression` → `token_counter` →
`default_encoding`). Deux pièges, mesurés l'un après l'autre :

1. **litellm ÉCRASE `TIKTOKEN_CACHE_DIR`** par son dossier interne — son
   `default_encoding.py` fait `os.environ["TIKTOKEN_CACHE_DIR"] = cache_dir` sans
   `setdefault`. La seule variable qu'il respecte est **`CUSTOM_TIKTOKEN_CACHE_DIR`**.
   Poser l'autre ne sert à RIEN : vérifié, l'import échouait toujours.
2. **Le fichier livré dans le paquet porte le bon NOM mais pas le bon CONTENU** : le nom
   est bien `sha1(url)` = `9b5ad71b…`, mais son `sha256` vaut `59d2daf6…` là où tiktoken
   0.12 attend `223921b7…`. tiktoken le rejette donc et RETÉLÉCHARGE.

Sans garde, l'import casse sur les **deux** comptes du hub, de deux façons différentes —
`WinError 10013` sous le compte sans egress, `PermissionError` sous celui qui a le réseau
mais pas le droit d'écrire dans `site-packages`. C'est-à-dire : tout appel litellm.

RÉGÉNÉRER LE CACHE s'il a disparu (il vit hors du dépôt, dans `sandbox/`) :
télécharger `https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken`
dans `sandbox/tiktoken_cache/9b5ad71b2ce5302211f9c61530b329a4922fc6a4`, en VÉRIFIANT que
son sha256 vaut `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7` — un
cache non vérifié rendrait le même symptôme, en silence.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PORTEURS = (
    ROOT / "app" / "forge_llm_router.py",
    ROOT / "app" / "forge_litellm_bridge.py",
)


@pytest.mark.parametrize("chemin", PORTEURS, ids=lambda p: p.name)
def test_le_garde_pose_la_variable_que_litellm_respecte(chemin: Path) -> None:
    src = chemin.read_text(encoding="utf-8", errors="replace")
    assert "CUSTOM_TIKTOKEN_CACHE_DIR" in src, (
        f"{chemin.name} doit poser CUSTOM_TIKTOKEN_CACHE_DIR : litellm ecrase "
        "TIKTOKEN_CACHE_DIR, la poser ne sert a rien")


@pytest.mark.parametrize("chemin", PORTEURS, ids=lambda p: p.name)
def test_le_garde_est_conditionnel_donc_n_ajoute_aucun_echec(chemin: Path) -> None:
    """Si le cache n'est pas la, on ne pose RIEN et litellm retombe sur son comportement
    d'origine. Un garde qui imposerait un dossier inexistant transformerait une absence
    de cache en panne seche."""
    src = chemin.read_text(encoding="utf-8", errors="replace")
    # On vise la LIGNE DE CODE, pas la premiere mention : le commentaire qui explique le
    # garde cite forcement le nom de la variable, et un `find()` naif s'y arrete. C'est le
    # meme piege que la declaration `__FORGE_COLOR__` confondue avec sa mention dans une
    # regex -- paye le 2026-09-06, re-paye ici en ecrivant ce test.
    ancre = 'setdefault("CUSTOM_TIKTOKEN_CACHE_DIR"'
    i = src.find(ancre)
    assert i > 0, f"{chemin.name} : aucune POSE de la variable, seulement des mentions"
    avant = src[max(0, i - 400):i]
    assert "is_dir()" in avant, (
        f"{chemin.name} : la pose doit etre gardee par une verification d'existence")


def test_le_chemin_du_cache_est_calcule_depuis_le_module():
    """Un chemin absolu code en dur suivrait le depot d'une seule machine."""
    for chemin in PORTEURS:
        src = chemin.read_text(encoding="utf-8", errors="replace")
        i = src.find("_CACHE_TIKTOKEN")
        assert "Path(__file__)" in src[i:i + 200], (
            f"{chemin.name} : le cache se resout depuis __file__, pas en dur")


def test_les_deux_pieges_restent_ecrits():
    """Retirer l'explication, c'est condamner le prochain a re-mesurer deux heures."""
    src = (ROOT / "app" / "forge_llm_router.py").read_text(encoding="utf-8",
                                                           errors="replace")
    assert "ECRASE" in src or "ecrase" in src, "le piege de la variable ecrasee doit rester"
    assert "223921b7" in src, "l'empreinte attendue par tiktoken doit rester citee"
