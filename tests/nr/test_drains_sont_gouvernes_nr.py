# -*- coding: utf-8 -*-
"""NR — un DRAIN de file doit etre relevable par la route gouvernee.

    UN SERVICE NON DECLARE NE REVIENT JAMAIS (mesure 2026-09-14).

CE QUI A ETE PAYE LE 2026-09-22
    `task action=assign agent=ANTIGRAVITY` ecrit dans `tasks.db`, depile par
    `NokidoTaskExecutorAntigravity`. Ce drain s'est arrete a 10:32 -- heartbeat
    PROUVE de 60 s, puis 3 h 53 de silence. Aucun nom gouverne ne permettait de
    le relever : l'owner a du le relancer a la main.

    Deposer une tache oblige a verifier que le drain tourne. Encore faut-il
    POUVOIR le relever quand il ne tourne pas -- sinon la verification ne mene
    qu'a un constat d'impuissance, et les messages s'empilent sans destinataire
    (>=48 non delivrables, mesure du 2026-09-20).

CE QUE CE TEST GARDE
    La presence des drains dans la table de la route gouvernee. Il ne teste ni
    leur sante ni leur reveil : un service peut etre declare et arrete, et c'est
    une autre question. Ici on verifie seulement qu'il est ATTEIGNABLE.

        DECLARE != VIVANT — mais NON DECLARE est sans recours.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_RACINE = Path(__file__).resolve().parents[2]
for _p in (_RACINE, _RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_ensure_service as es  # noqa: E402 — livrable, jamais d'importorskip


def _table() -> dict:
    for nom in dir(es):
        val = getattr(es, nom)
        if isinstance(val, dict) and "llamacpp_chat" in val:
            return val
    raise AssertionError("table des services gouvernes introuvable — re-mesurer")


@pytest.mark.parametrize("convivial,service", [
    ("taskexec_antigravity", "NokidoTaskExecutorAntigravity"),
    ("taskexec_agy", "NokidoTaskExecutorAgy"),
])
def test_le_drain_est_atteignable_par_la_route_gouvernee(convivial, service):
    table = _table()
    assert convivial in table, (
        "`%s` n'est plus dans la route gouvernee : un agent qui constate le "
        "drain arrete ne peut PLUS le relever, et toute tache deposee part "
        "dans une file sans destinataire" % convivial)
    assert table[convivial] == service, (
        "`%s` pointe vers %r au lieu de %r : le nom gouverne ne mene plus au "
        "bon service" % (convivial, table[convivial], service))


def test_la_table_ne_perd_pas_ses_autres_capacites():
    """Contre-epreuve : l'ajout ne doit pas avoir ecrase la table."""
    table = _table()
    for attendu in ("hub", "docker", "webhub", "llamacpp_chat"):
        assert attendu in table, (
            "`%s` a disparu de la route gouvernee : l'ajout des drains a "
            "ecrase des capacites existantes" % attendu)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
