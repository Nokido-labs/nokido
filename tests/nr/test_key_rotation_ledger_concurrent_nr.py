"""NR — le registre de sante des cles ne se corrompt pas et ne perd rien sous ecrivains concurrents.

MESURE du 2026-09-23 22:39 : `sandbox/key_health.json` illisible (« Extra data »). Cause lue dans le
code le 2026-09-24 :
  - `_save_health` ecrivait TOUJOURS le meme temporaire (`key_health.json.tmp`) avant `os.replace` :
    deux processus qui marquent au meme moment ecrivent dans ce fichier COMMUN, et l'un peut publier
    le melange des deux ;
  - `mark()` relit-modifie-ecrit SANS exclusion entre processus : la marque posee par l'autre entre
    la lecture et l'ecriture est perdue (5 appelants hors du module).
Or un ledger illisible est relu comme VIDE : toutes les revocations sont levees en silence
(docstring de `_relire_du_disque`). La corruption n'est donc pas cosmetique.

Patron retenu (veilles lot_B_31 / lot_B_32) : REUTILISER la primitive de `forge_state_manager`
— `filelock.FileLock` — autour de TOUTE la sequence lire-modifier-ecrire, et un temporaire UNIQUE
par ecriture (defense en profondeur : meme un ecrivain sans verrou ne peut plus melanger).

Niveau « chemin reel » : de VRAIS processus concurrents, pas des threads ni un mock.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python x6 (l.65)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "app" / "forge_key_rotation.py"


def _charger(nom="forge_key_rotation_ledger_nr"):
    if not MODULE.exists():
        pytest.fail("app/forge_key_rotation.py absent : le livrable a disparu")
    spec = importlib.util.spec_from_file_location(nom, MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ECRIVAIN = r'''
import importlib.util, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("kr_ecrivain", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod._HEALTH = Path(sys.argv[2])
depart = Path(sys.argv[3])
while not depart.exists():          # barriere : tous partent ensemble
    time.sleep(0.005)
for i in range(int(sys.argv[5])):
    mod.mark("NR_API_KEY", "cle-%s-%d" % (sys.argv[4], i), "bad", "nr")
'''


def test_ecrivains_concurrents_ni_corruption_ni_perte(tmp_path):
    ecrivain = tmp_path / "ecrivain.py"
    ecrivain.write_text(_ECRIVAIN, encoding="utf-8")
    ledger = tmp_path / "key_health.json"
    depart = tmp_path / "go"
    n_proc, n_marques = 6, 25
    procs = [subprocess.Popen([sys.executable, str(ecrivain), str(MODULE), str(ledger),
                               str(depart), str(w), str(n_marques)],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for w in range(n_proc)]
    time.sleep(1.5)                      # laisser chaque processus importer le module
    depart.write_text("go", encoding="utf-8")
    for p in procs:
        _out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode("utf-8", "replace")[-800:]
    texte = ledger.read_text(encoding="utf-8")
    donnees = json.loads(texte)          # corrompu => JSONDecodeError (« Extra data »)
    attendu = n_proc * n_marques
    assert len(donnees) == attendu, (
        "%d marques sur %d : %d perdue(s) par ecriture concurrente — une revocation "
        "perdue ne laisse aucune trace" % (len(donnees), attendu, attendu - len(donnees)))
    restes = sorted(x.name for x in tmp_path.glob("key_health.json*.tmp"))
    assert not restes, "temporaires abandonnes : %s" % restes


class _Verrou:
    """Doublure qui enregistre l'ordre des evenements."""

    def __init__(self, journal, echoue=False):
        self.journal, self.echoue = journal, echoue

    def acquire(self, *a, **k):
        if self.echoue:
            raise TimeoutError("verrou tenu ailleurs")
        self.journal.append("prise")

    def release(self, *a, **k):
        self.journal.append("liberation")


def test_le_verrou_couvre_toute_la_sequence(tmp_path, monkeypatch):
    mod = _charger()
    monkeypatch.setattr(mod, "_HEALTH", tmp_path / "key_health.json")
    journal = []
    monkeypatch.setattr(mod, "_verrou_ledger", lambda: _Verrou(journal))
    lire, sauver = mod._relire_du_disque, mod._save_health
    monkeypatch.setattr(mod, "_relire_du_disque", lambda: (journal.append("lecture"), lire())[1])
    monkeypatch.setattr(mod, "_save_health", lambda h: (journal.append("ecriture"), sauver(h))[1])
    mod.mark("NR_API_KEY", "k", "bad", "nr")
    assert journal == ["prise", "lecture", "ecriture", "liberation"], journal


def test_set_key_relit_le_disque_sous_verrou(tmp_path, monkeypatch):
    """`set_key` partait du CACHE (jusqu'a 60 s) : il pouvait effacer une marque posee entre-temps."""
    mod = _charger()
    ledger = tmp_path / "key_health.json"
    monkeypatch.setattr(mod, "_HEALTH", ledger)
    journal = []
    monkeypatch.setattr(mod, "_verrou_ledger", lambda: _Verrou(journal))
    mod._health_cache = (time.monotonic(), {})            # cache vide et « frais »
    ledger.write_text(json.dumps({"autre": {"env": "X", "status": "revoked", "ts": 1}}),
                      encoding="utf-8")                     # marque posee par un AUTRE process
    import types
    faux = types.ModuleType("nokido_agent.app.forge_secrets")
    faux.set_secret = lambda n, v: None
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", faux)
    mod.set_key("NR_API_KEY", "nouvelle", 1)
    garde = json.loads(ledger.read_text(encoding="utf-8"))
    assert "autre" in garde, "set_key a efface une revocation posee par un autre processus"
    assert journal[:1] == ["prise"] and journal[-1:] == ["liberation"], journal


def test_verrou_indisponible_ecrit_quand_meme_et_le_dit(tmp_path, monkeypatch, caplog):
    """Un verrou tenu trop longtemps ne doit ni bloquer l'appelant ni perdre la marque en silence."""
    mod = _charger()
    ledger = tmp_path / "key_health.json"
    monkeypatch.setattr(mod, "_HEALTH", ledger)
    monkeypatch.setattr(mod, "_verrou_ledger", lambda: _Verrou([], echoue=True))
    with caplog.at_level(logging.ERROR):
        mod.mark("NR_API_KEY", "k", "bad", "nr")
    assert len(json.loads(ledger.read_text(encoding="utf-8"))) == 1
    assert any("verrou" in r.getMessage().lower() for r in caplog.records), (
        "une ecriture sans exclusion doit etre DITE")


def test_temporaire_unique_par_ecriture(tmp_path, monkeypatch):
    mod = _charger()
    monkeypatch.setattr(mod, "_HEALTH", tmp_path / "key_health.json")
    vus = []
    vrai = mod.os.replace
    monkeypatch.setattr(mod.os, "replace", lambda a, b: (vus.append(Path(a).name), vrai(a, b))[1])
    mod._save_health({"a": 1})
    mod._save_health({"b": 2})
    assert len(vus) == 2 and vus[0] != vus[1], vus
    assert "key_health.json.tmp" not in vus, "temporaire FIXE : deux ecrivains s'y melangent"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
