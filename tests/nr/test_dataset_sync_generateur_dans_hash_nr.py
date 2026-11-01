"""NR -- un golden de data_nr/ se regenere quand son GENERATEUR change, pas seulement ses modules sources.

Mesure 29/10 : gen_behavior_gold corrige (CMD-08 emis apres la revocation, forge_integrity revoque par instant
d'emission depuis le 02/09), mais behavior_gold.json reste celui de 08 h 34 : le hash de peremption ne couvrait que
les modules testes, jamais forge_dataset_sync.py. Une correction du generateur n'atteignait donc jamais le golden."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "app")]

from app import forge_dataset_sync as ds  # noqa: E402


def test_le_hash_couvre_le_generateur():
    """Sans aucun module source, le hash depend encore du generateur (il n'est pas le hash vide)."""
    assert ds._src_hash() != hashlib.sha256().hexdigest()[:12]


def test_meme_entree_meme_hash():
    """Determinisme : le generateur et la verification de peremption calculent le meme hash."""
    src = ROOT / "app" / "forge_integrity.py"
    assert ds._src_hash(src) == ds._src_hash(src)


def test_generateur_cmd08_emet_le_nouveau_jeton_apres_la_revocation():
    """Le golden CMD-08 tient l'invariant : ancien jeton refuse, nouveau (emis apres revoke) accepte."""
    eb = ds.gen_behavior_gold()["CMD-08_REVOKE_SEQ"]["expected_behavior"]
    assert eb == {"old_token_passes": False, "new_token_passes": True, "invariant_holds": True}
