"""NR -- un reveil vers un port RETIRE PAR POLITIQUE n'est pas une panne (2026-10-13).

Mesure : chaque commit (ancrage forge_self_correction) imprimait « [nudge] personne n'ecoute :5557 » en WARNING.
`:5557` (brain_worker) est retire par politique depuis le 03/06 : DISABLED_BY_POLICY != RESOURCE_UNAVAILABLE.

Invariants :
- port retire SANS ecouteur -> etat `desactive_par_politique`, dit en INFO (pas WARNING), rattrapage nomme ;
- port NON retire sans ecouteur -> toujours `aucun_ecouteur` en WARNING (la vraie panne reste criee) ;
- port retire AVEC ecouteur -> le reveil part (l'ecouteur est sonde en premier : si :5557 revit, ca marche).
"""
# pylint: disable=protected-access
import logging
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_nudge_embed as N  # noqa: E402


def _neuf(monkeypatch, ecoute):
    monkeypatch.setattr(N, "_DERNIER_ETAT", {})
    monkeypatch.setattr(N, "_ecouteur_present", lambda port: ecoute)


def test_port_retire_sans_ecouteur_est_une_politique_dite_en_info(monkeypatch, caplog):
    """Le cas mesure : :5557 ferme -> desactive_par_politique, aucun WARNING."""
    _neuf(monkeypatch, False)
    with caplog.at_level(logging.INFO, logger=N.logger.name):
        r = N.nudge_embed(source="nr")
    assert r["etat"] == "desactive_par_politique" and r["delivre"] is False
    assert r["rattrapage"] == "NokidoDeportEmbed"
    assert not [x for x in caplog.records if x.levelno >= logging.WARNING]
    assert any("retire par politique" in x.getMessage() for x in caplog.records)


def test_port_non_retire_sans_ecouteur_reste_une_panne_criee(monkeypatch, caplog):
    """Controle negatif : un port non retire et muet est toujours une panne, en WARNING."""
    _neuf(monkeypatch, False)
    with caplog.at_level(logging.INFO, logger=N.logger.name):
        r = N.nudge_embed(port=59999, source="nr")
    assert r["etat"] == "aucun_ecouteur"
    assert any(x.levelno == logging.WARNING for x in caplog.records)


def test_port_retire_qui_revit_recoit_le_reveil(monkeypatch):
    """L'ecouteur est sonde en premier : si :5557 revient, le reveil part comme avant."""
    _neuf(monkeypatch, True)
    envoyes = []

    class _Socket:
        def setsockopt(self, *_a):
            """Option sans effet."""

        def connect(self, adresse):
            """Memorise l'adresse."""
            envoyes.append(adresse)

        def send(self, donnees, *_a):
            """Memorise l'envoi."""
            envoyes.append(donnees)

        def close(self):
            """Fermeture sans effet."""

    faux_zmq = types.SimpleNamespace(PUSH=8, LINGER=17, NOBLOCK=1,
                                     Context=types.SimpleNamespace(instance=lambda: types.SimpleNamespace(
                                         socket=lambda _t: _Socket())))
    faux_msgpack = types.SimpleNamespace(packb=lambda obj, **_k: repr(obj).encode())
    monkeypatch.setitem(sys.modules, "zmq", faux_zmq)
    monkeypatch.setitem(sys.modules, "msgpack", faux_msgpack)
    r = N.nudge_embed(source="nr")
    assert r["etat"] == "ok" and r["delivre"] is True
    assert len(envoyes) == 2
