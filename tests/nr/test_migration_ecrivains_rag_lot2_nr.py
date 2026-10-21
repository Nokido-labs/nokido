"""NR 18/10 -- lot 2 de migration des ecrivains RAG NUS de app/ (decision owner C_06 : cliquet + migrer app/).

Quatre modules (une instruction INSERT nue chacun, mesuree par le cliquet) doivent ecrire par le
chemin gouverne : `forge_db_path.write_retry(lambda c: ...)` (ecriture isolee) ou
`forge_db_path.open_writer(path=...)` (boucle par lot), comme le lot 1 (94ce5f320).
Ce test reutilise l'instrument du cliquet (meme definition de « nu ») ; au GREEN, le plafond
app du cliquet descend de 32 a 28 dans le meme commit. Livraison OPENCODE_GPTOSS 38e25d514, relue.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOT2 = ("app/forge_dialogue_outcome.py", "app/forge_mailbox.py",
        "app/forge_postal.py", "app/forge_knowledge_distiller.py")


def _cliquet():
    spec = importlib.util.spec_from_file_location(
        "cliquet_ecrivains_nr", ROOT / "tests" / "nr" / "test_cliquet_ecrivains_rag_nus_nr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_le_lot2_n_a_plus_aucun_ecrivain_nu():
    nus = [s for s in _cliquet()._nus("app") if s.rsplit(":", 1)[0] in LOT2]
    assert not nus, "ecrivain(s) RAG encore nu(s) dans le lot 2 : %s" % nus


def test_le_plafond_du_cliquet_suit_la_migration():
    assert _cliquet().PLAFOND["app"] <= 28, "lot 2 migre : abaisser PLAFOND['app'] a 28 dans le cliquet"
