"""NR — Savoir Census : migration vers la primitive Mesure et execution en point d'entree.

Test pur sans reseau ni base reelle.
Vérifie que :
1. forge_savoir_census.py s'execute correctement en point d'entree par sous-processus
   (sans ModuleNotFoundError suite a un import premature).
2. L'integrite et la fraicheur d'un magasin sont rendues comme Mesure typee.
3. La sortie de `atlas_donnees()` est serialisable en JSON (aucun crash TypeError: Object of type Mesure is not JSON serializable).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.forge_mesure import Mesure, MesureIllisible, agreger_sain

_spec = importlib.util.spec_from_file_location("census_atlas", ROOT / "tools" / "forge_savoir_census.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def _base(p, index=True):
    c = sqlite3.connect(str(p))
    c.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, source TEXT)")
    if index:
        c.execute("CREATE INDEX ix ON t(source)")
    c.execute("INSERT INTO t(source) VALUES('a')")
    c.commit()
    c.close()


def _decl(p):
    return {"nom": "test_magasin", "chemin": str(p), "declare_par": "test_unit", "requete": ("t", "source")}


def test_point_dentree_sous_processus():
    """Le script doit pouvoir etre execute directement en point d'entree sans PYTHONPATH predefini."""
    script_path = ROOT / "tools" / "forge_savoir_census.py"
    # Env epure sans PYTHONPATH vers ROOT pour reproduire l'execution par chemin
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    # Lancement avec --atlas pour verifier le chargement et l'execution sans ecriture dans sandbox/
    res = subprocess.run([sys.executable, str(script_path), "--atlas"],
                         capture_output=True, text=True, env=env)
    assert res.returncode == 0, f"Le point d'entree a echoue : {res.stderr}"


def test_evaluer_magasin_produit_mesures(tmp_path):
    p = tmp_path / "ok.db"
    _base(p)
    f = C.evaluer_magasin(_decl(p))

    assert "integrite_mesure" in f
    assert "fraicheur_mesure" in f
    assert isinstance(f["integrite_mesure"], Mesure)
    assert isinstance(f["fraicheur_mesure"], Mesure)

    assert f["integrite_mesure"].statut == "VALEUR"
    assert f["fraicheur_mesure"].statut == "VALEUR"
    assert agreger_sain([f["integrite_mesure"], f["fraicheur_mesure"]]) is True

    # Compatibilite des chaines conservee
    assert f["integrite"] == "integrite controlee: ok"
    assert f["fraicheur"].startswith("frais")
    assert f["lacunes"] == []


def test_evaluer_magasin_base_illisible_non_saine(tmp_path):
    p = tmp_path / "corrupt.db"
    p.write_bytes(b"ceci n'est pas une base sqlite valide" * 20)
    f = C.evaluer_magasin(_decl(p))

    assert isinstance(f["integrite_mesure"], Mesure)
    assert f["integrite_mesure"].statut in ("ILLISIBLE", "UNKNOWN")
    assert agreger_sain([f["integrite_mesure"]]) is False
    assert any("integrite" in x for x in f["lacunes"])


def test_evaluer_magasin_base_absente(tmp_path):
    p = tmp_path / "absente.db"
    f = C.evaluer_magasin(_decl(p))

    assert isinstance(f["integrite_mesure"], Mesure)
    assert isinstance(f["fraicheur_mesure"], Mesure)
    assert f["integrite_mesure"].statut in ("ABSENT", "ILLISIBLE", "UNKNOWN")
    assert f["fraicheur_mesure"].statut in ("ABSENT", "ILLISIBLE", "UNKNOWN")
    assert agreger_sain([f["integrite_mesure"]]) is False


def test_evaluer_magasin_perime(tmp_path):
    p = tmp_path / "perime.db"
    _base(p)
    maintenant = p.stat().st_mtime + 90 * 86400  # 90 jours plus tard
    f = C.evaluer_magasin(_decl(p), maintenant=maintenant)

    assert isinstance(f["fraicheur_mesure"], Mesure)
    assert f["fraicheur_mesure"].statut == "STALE"
    assert agreger_sain([f["fraicheur_mesure"]]) is False
    assert any("fraicheur" in x for x in f["lacunes"])


def test_atlas_donnees_serialisable_json(tmp_path):
    """Verifie que atlas_donnees() et evaluer_magasin() se serialisent en JSON sans erreur."""
    p = tmp_path / "test.db"
    _base(p)
    res = C.atlas_donnees([_decl(p)])
    # Doit pouvoir se dumper sans lever TypeError
    raw = json.dumps(res)
    charge = json.loads(raw)
    assert len(charge["magasins"]) == 1
    m = charge["magasins"][0]
    assert "integrite_mesure" in m
    assert "fraicheur_mesure" in m
