"""NR -- un arret VOLONTAIRE de Docker (relache, fin de TTL) n'est pas une « vie courte » (10/11 soir).

Mesure : journal de cycle de vie (sandbox/lifecycle_actions.jsonl), a partir de 16:48 toutes les 30 s
« boucle | relance suspendue apres 3 vies courtes » : les reveils/relaches de l'apres-midi (Gordon, recherches,
ensure_service ; une relache immediate tourne dans le processus du CONSOMMATEUR, que le keeper ne voit pas) ont
ete comptes comme trois morts precoces -> Docker suspendu, 8 veilles bloquees sur SearXNG. Contrats :
  1. `_release_docker` laisse une trace `docker.arret_volontaire` (tout processus) ;
  2. un arret dont la trace est POSTERIEURE au dernier boot reussi n'est pas compte en vie courte ;
  3. sans trace, une mort en moins de _VIE_COURTE_S reste une vie courte (contrat anterieur).
"""
# pylint: disable=protected-access,wrong-import-position,import-error  # NR de l'interne du keeper, chemin amorce
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_docker_keeper as K  # noqa: E402


def _isoler(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "WANT_FLAG", tmp_path / "docker.wanted")
    monkeypatch.setattr(K, "_vies_courtes", [])
    monkeypatch.setitem(K._STATE, "last_boot_ok_ts", time.monotonic() - 30)


def test_arret_volontaire_apres_boot_pas_compte(monkeypatch, tmp_path):
    """Arret trace apres le boot : pas une vie courte."""
    _isoler(monkeypatch, tmp_path)
    K._marquer_arret_volontaire("release_claim:gordon")
    K._noter_fin_de_vie()
    assert K._vies_courtes == []


def test_mort_sans_trace_reste_vie_courte(monkeypatch, tmp_path):
    """Mort precoce sans trace : vie courte (contrat anterieur)."""
    _isoler(monkeypatch, tmp_path)
    K._noter_fin_de_vie()
    assert len(K._vies_courtes) == 1


def test_trace_anterieure_au_boot_ne_couvre_pas(monkeypatch, tmp_path):
    """Trace plus vieille que le boot : ne couvre pas la mort suivante."""
    _isoler(monkeypatch, tmp_path)
    K._marquer_arret_volontaire("vieux")
    vieux = time.time() - 3600
    os.utime(K._arret_volontaire_path(), (vieux, vieux))
    K._noter_fin_de_vie()
    assert len(K._vies_courtes) == 1
