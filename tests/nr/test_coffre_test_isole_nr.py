"""NR 18/10 -- coffre de TEST isole pour forge_secrets (decision owner : « surcharge sous pytest seul »).

test_hub_n::test_stream_headers lancait un vrai hub avec un jeton de test en environnement, mais get_secret lit le
COFFRE avant l'environnement : le hub prenait le vrai jeton -> login 401. Contrat de la source de test :
- servie UNIQUEMENT si PYTEST_CURRENT_TEST est pose ET NOKIDO_COFFRE_TEST_DIR est sous le dossier temporaire ;
- prioritaire sur toutes les sources quand elle est active (sinon le coffre reel gagne encore) ;
- ignoree hors pytest ou hors du dossier temporaire : un service ne peut pas etre redirige.
Assertions booleennes : aucune valeur de secret n'est affichee.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_secrets as S  # noqa: E402

CLE = "NOKIDO_TEST_COFFRE_ISOLE_SONDE"


def _semer(dossier: Path, valeur: str) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "coffre_test.json").write_text(json.dumps({CLE: valeur}), encoding="utf-8")


def _purger_cache():
    for d in (S._cache, S._CACHE_TS, S._SOURCE_DU_CACHE, S._MISS_TS):
        d.pop(CLE, None)
    S._cache_miss.discard(CLE)


def test_servi_sous_pytest_dans_le_dossier_temporaire_et_prioritaire(tmp_path, monkeypatch):
    _purger_cache()
    _semer(tmp_path / "coffre", "valeur-de-test")
    monkeypatch.setenv("NOKIDO_COFFRE_TEST_DIR", str(tmp_path / "coffre"))
    monkeypatch.setenv(CLE, "valeur-environnement")
    assert (S.get_secret(CLE) == "valeur-de-test") is True


def test_ignore_hors_pytest(tmp_path, monkeypatch):
    _purger_cache()
    _semer(tmp_path / "coffre", "valeur-de-test")
    monkeypatch.setenv("NOKIDO_COFFRE_TEST_DIR", str(tmp_path / "coffre"))
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert S._coffre_test(CLE) is None


def test_ignore_hors_du_dossier_temporaire(monkeypatch):
    _purger_cache()
    # Hors du dossier temporaire PAR CONSTRUCTION : sous le compte du hub, ROOT lui-meme vit sous TEMP (worktree de la
    # CI de reference dans sandbox/workspace/tmp, e6642dcf1) -- ROOT/sandbox n'en sortait pas et la premisse cassait.
    hors = Path(tempfile.gettempdir()).resolve().parent / "coffre_test_refuse_nr"
    monkeypatch.setenv("NOKIDO_COFFRE_TEST_DIR", str(hors))
    assert not str(hors.resolve()).lower().startswith(str(Path(tempfile.gettempdir()).resolve()).lower())
    assert S._coffre_test(CLE) is None
