"""NR -- en fin de swarm pointeur, une demande de synthese declenche UN passage du lanceur (choix owner 29/10).

Le lanceur ne marche qu'en job (401 sous le compte owner) : il s'enchaine donc au job du swarm. Une erreur du lanceur ne
casse jamais le swarm. Sous pytest, inactif sauf LAFORGE_SECOURS_EXECUTEURS=1. Faux swarm, faux lanceur, tmp_path."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import forge_cli_swarm as S  # noqa: E402


def _faux_swarm(res):
    async def faux(*_a, **_k):
        return res
    return faux


def _monde(monkeypatch, tmp_path, res):
    appels = []
    monkeypatch.setattr(S, "SORTIE_DIR", tmp_path)
    monkeypatch.setattr(S, "swarm_pointeur", _faux_swarm(res))
    monkeypatch.setattr(S, "_passer_lanceur", lambda d: appels.append(Path(d)))
    c = tmp_path / "consigne.md"
    c.write_text("q", encoding="utf-8")
    return appels, ["--pointeur", str(c)]


def test_demande_declenche_un_passage(monkeypatch, tmp_path):
    """demande_synthese ecrite -> un passage du lanceur sur le dossier des resultats."""
    monkeypatch.setenv("LAFORGE_SECOURS_EXECUTEURS", "1")
    appels, argv = _monde(monkeypatch, tmp_path, {"answers": [], "demande_synthese": {"pointeur": "x"}})
    assert S.main(argv) == 0
    assert appels == [tmp_path]


def test_synthese_presente_aucun_passage(monkeypatch, tmp_path):
    """Synthese deja faite -> aucun passage."""
    monkeypatch.setenv("LAFORGE_SECOURS_EXECUTEURS", "1")
    appels, argv = _monde(monkeypatch, tmp_path, {"answers": [], "synthesis": "x" * 200})
    assert S.main(argv) == 0 and appels == []


def test_erreur_du_lanceur_ne_casse_pas_le_swarm(monkeypatch, tmp_path, capsys):
    """Le lanceur leve -> swarm rc 0, motif imprime."""
    monkeypatch.setenv("LAFORGE_SECOURS_EXECUTEURS", "1")
    _appels, argv = _monde(monkeypatch, tmp_path, {"answers": [], "demande_synthese": {"pointeur": "x"}})

    def boum(_d):
        raise RuntimeError("hub absent")

    monkeypatch.setattr(S, "_passer_lanceur", boum)
    assert S.main(argv) == 0
    assert "lanceur" in capsys.readouterr().out


def test_inactif_sous_pytest_sans_variable(monkeypatch, tmp_path):
    """Sans LAFORGE_SECOURS_EXECUTEURS sous pytest -> aucun passage (jamais de vrai depot depuis une suite)."""
    monkeypatch.delenv("LAFORGE_SECOURS_EXECUTEURS", raising=False)
    appels, argv = _monde(monkeypatch, tmp_path, {"answers": [], "demande_synthese": {"pointeur": "x"}})
    assert S.main(argv) == 0 and appels == []
