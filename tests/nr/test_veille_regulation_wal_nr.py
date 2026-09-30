"""NR -- l'ingestion de veille REGULE le WAL au lieu de l'empiler (2026-09-23).

Mesure du jour : un lecteur long exterieur a fige le repere de checkpoint (pages reversees
bloquees a 888 149 pendant ~4 min 20) ; l'ingestion a continue d'ecrire et le WAL est passe de
151 Mo a 21 375 Mo en 18 min, jusqu'au garde disque. Le TRUNCATE entre depots rendait busy=1
et l'ingestion repartait aussitot.

Contrat : entre deux depots, si le WAL depasse le seuil ET que le repere est en retard (ou
busy), l'ingestion ATTEND que le checkpoint rattrape, bornee dans le temps ; au-dela, elle
s'arrete en le DISANT (GEL_PERSISTANT) au lieu de nourrir le WAL.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _charger():
    sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location(
        "ci_regulation_wal", ROOT / "tools" / "forge_veille_clone_ingest.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ci = _charger()

SOUS_SEUIL = {"fait": False, "wal_mo": 12.0, "raison": "sous le seuil"}
FIGE = {"fait": True, "mode": "PASSIVE", "busy": 0, "pages": 900_000, "verses": 400_000,
        "wal_mo_avant": 3500.0, "wal_mo_apres": 3500.0}
OCCUPE = {"fait": True, "mode": "PASSIVE", "busy": 1, "pages": -1, "verses": -1,
          "wal_mo_avant": 3500.0, "wal_mo_apres": 3500.0}
RATTRAPE = {"fait": True, "mode": "PASSIVE", "busy": 0, "pages": 900_000, "verses": 900_000,
            "wal_mo_avant": 3500.0, "wal_mo_apres": 3500.0}


def test_decision_pure():
    assert ci.decision_regulation(SOUS_SEUIL) == "CONTINUER"
    assert ci.decision_regulation(RATTRAPE) == "CONTINUER"
    assert ci.decision_regulation(FIGE) == "ATTENDRE"
    assert ci.decision_regulation(OCCUPE) == "ATTENDRE"


def test_illisible_ne_bloque_pas_mais_se_dit():
    # Un WAL illisible n'est pas un WAL sain : on ne bloque pas la campagne sur une mesure
    # absente (le garde disque reste le filet), mais la decision le NOMME.
    assert ci.decision_regulation({"fait": False, "raison": "wal illisible: X"}) == "INCONNU"


def test_attend_puis_repart_quand_le_repere_rattrape():
    suite = iter([FIGE, OCCUPE, RATTRAPE])
    sommes = []
    r = ci._reguler_wal(checkpoint=lambda *a, **k: next(suite), dormir=sommes.append,
                        horloge=lambda: 0.0)
    assert r["etat"] == "LIBRE" and r["essais"] == 2 and len(sommes) == 2


def test_gel_persistant_est_borne_et_nomme():
    t = [0.0]

    def horloge():
        t[0] += 60.0
        return t[0]

    r = ci._reguler_wal(checkpoint=lambda *a, **k: FIGE, dormir=lambda s: None, horloge=horloge)
    assert r["etat"] == "GEL_PERSISTANT"
    assert r["attente_s"] >= ci.ATTENTE_REPERE_MAX_S


def test_regulation_passive_jamais_truncate():
    vus = []

    def ck(seuil, truncate=False, attente_s=None):
        vus.append(truncate)
        return RATTRAPE
    ci._reguler_wal(checkpoint=ck, dormir=lambda s: None, horloge=lambda: 0.0)
    assert vus == [False]   # PASSIVE : ne bloque ni lecteurs ni ecrivains
