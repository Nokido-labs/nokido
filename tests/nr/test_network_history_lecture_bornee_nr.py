# -*- coding: utf-8 -*-
"""NR — l'historique reseau ne charge pas 100 Mo pour rendre 200 lignes.

MESURE DU 2026-09-22
    `GET /api/network/history` est une route NUE (aucune garde, 200 sans
    jeton). Elle appelle `net_history(limit)`, qui retombe sur
    `net_history_from_audit(limit)` des que l'historique en memoire est vide --
    c'est-a-dire APRES CHAQUE REDEMARRAGE du hub.

    Et ce repli fait :

        lines = AUDIT_LOG.read_text(...).splitlines()
        for line in lines[-limit:]:

    Le fichier est lu EN ENTIER ; le `[-limit:]` s'applique APRES.

        LA BORNE PROTEGE LA SORTIE, JAMAIS LA LECTURE

    Taille mesuree de `mcp_audit.log` le 2026-09-22 : **107 840 003 octets**,
    soit 102,8 Mo charges en memoire pour rendre 200 lignes -- et le cout
    croit avec le journal, sans plafond.

    C'est le motif de l'incident 47 Go que `forge_firehose_guard` surveille
    deja (« readTextFile-whole ») -- mais seulement dans les `.ts`. Le meme
    geste en Python n'etait capte par personne.

CE QUE CE FICHIER VERROUILLE
    La PROPRIETE « la lecture est bornee », eprouvee en rendant la lecture
    integrale IMPOSSIBLE : le journal substitue leve si on appelle
    `read_text()` dessus. Un test qui lirait le source chercherait une FORME ;
    celui-ci mesure un COMPORTEMENT.

CE QU'IL N'EST PAS
    Un correctif d'autorisation. La route reste nue -- c'est une decision
    separee. Ici on retire seulement ce qu'un appelant anonyme peut declencher
    comme travail.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (str(_RACINE), str(_RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class _JournalPiege:
    """Un journal qui REFUSE d'etre lu en entier.

    `read_text()` leve : toute lecture integrale devient une erreur visible au
    lieu d'un cout invisible.
    """

    def __init__(self, chemin: Path):
        self._p = chemin
        self.lectures_integrales = 0

    def exists(self) -> bool:
        return True

    def read_text(self, *a, **k):
        self.lectures_integrales += 1
        raise AssertionError(
            "LECTURE INTEGRALE du journal : 102,8 Mo charges pour rendre "
            "quelques lignes. La borne doit s'appliquer a la LECTURE.")

    # ce qu'une lecture bornee utilise
    def open(self, *a, **k):
        return self._p.open(*a, **k)

    def stat(self):
        return self._p.stat()

    def __fspath__(self):
        return str(self._p)

    def __str__(self):
        return str(self._p)


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    """Un journal de 5 000 lignes, substitue a la SOURCE reelle."""
    p = tmp_path / "mcp_audit.log"
    p.write_text("\n".join(
        "2026-09-22T00:00:%02d | HUB:outil_%d | ok" % (i % 60, i)
        for i in range(5000)), encoding="utf-8")
    piege = _JournalPiege(p)
    for nom in ("nokido_agent.app.forge_mcp_security", "app.forge_mcp_security",
                "forge_mcp_security"):
        try:
            mod = sys.modules.get(nom) or importlib.import_module(nom)
        except Exception:  # noqa: BLE001 — un nom absent n'invalide pas l'autre
            continue
        monkeypatch.setattr(mod, "AUDIT_LOG", piege, raising=False)
    return piege


def _fn():
    m = importlib.import_module("forge_network_logger")
    return m


def test_la_lecture_du_journal_est_BORNEE(journal):
    """LE COEUR. Avant correctif : `read_text()` sur 102,8 Mo."""
    m = _fn()
    res = m.net_history_from_audit(limit=10)
    assert journal.lectures_integrales == 0, (
        "le journal est lu EN ENTIER pour rendre 10 lignes")
    assert isinstance(res, list)


def test_le_resultat_reste_JUSTE(journal):
    """Une lecture bornee qui rend n'importe quoi ne vaut rien.

    Les lignes doivent etre les DERNIERES, et en bon nombre.
    """
    m = _fn()
    res = m.net_history_from_audit(limit=10)
    assert len(res) == 10, "%d lignes rendues au lieu de 10" % len(res)
    assert "outil_4999" in str(res[-1]), (
        "la derniere ligne du journal n'est pas la derniere rendue : la "
        "lecture bornee a pris le mauvais bout du fichier")


def test_une_limite_plus_grande_que_le_journal_ne_casse_pas(journal):
    """CONTRE-EPREUVE : demander plus que ce qui existe rend ce qui existe."""
    m = _fn()
    res = m.net_history_from_audit(limit=999_999)
    assert journal.lectures_integrales == 0
    assert 0 < len(res) <= 5000


def test_un_journal_absent_rend_une_liste_vide(journal, monkeypatch):
    """`UNKNOWN != panne` : un journal absent n'est pas une erreur 500."""
    monkeypatch.setattr(journal, "exists", lambda: False)
    assert _fn().net_history_from_audit(limit=5) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
