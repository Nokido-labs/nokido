"""NR — la synchronisation refuse, et NOMME son motif.

`git merge` echoue sous le compte sandbox (`unable to unlink … Invalid argument`)
parce que `LaForgeSbxOffline` est en (R) sur l'arbre et `LaForgeTrusted` en (M).
L'outil existe donc pour passer par `trusted_script` -- le privilege est du code
revu. Ce fichier garde sa DECISION, qui est pure : aucun git n'est lance ici.

Les trois refus sont des choix, pas des defauts : rien a integrer, des conflits
(qui se tranchent a la main), et le dry-run par defaut.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))


@pytest.fixture()
def mod():
    try:
        import forge_sync_branche
    except Exception as exc:  # noqa: BLE001
        pytest.fail("forge_sync_branche ne s'importe pas : %s: %s"
                    % (type(exc).__name__, exc))
    return forge_sync_branche


def test_rien_a_integrer_est_un_refus_explicite(mod):
    ok, motif = mod.decider_sync(0, [], True)
    assert ok is False
    assert "a jour" in motif.lower(), motif


def test_un_conflit_NOMME_les_fichiers_et_refuse(mod):
    ok, motif = mod.decider_sync(3, ["a.py", "b.py"], True)
    assert ok is False
    assert "a.py" in motif, "les conflits doivent etre nommes : %s" % motif


def test_le_dry_run_ne_fusionne_pas_et_dit_comment(mod):
    ok, motif = mod.decider_sync(5, [], False)
    assert ok is False
    assert "--apply" in motif, motif


def test_le_cas_nominal_autorise_la_fusion(mod):
    """CONTRE-EPREUVE : sans elle, tout refuser passerait les trois tests."""
    ok, motif = mod.decider_sync(5, [], True)
    assert ok is True
    assert "5" in motif, motif


def test_l_outil_ne_propose_AUCUN_rebase_ni_force(mod):
    """Un rebase reecrirait des sha deja certifies ; un force publierait sans
    integrer. Ni l'un ni l'autre ne doit etre atteignable depuis cet outil."""
    source = (RACINE / "tools" / "forge_sync_branche.py").read_text(encoding="utf-8")
    for interdit in ('"rebase"', '"--force"', '"-f"'):
        assert interdit not in source, "l'outil expose %s" % interdit
