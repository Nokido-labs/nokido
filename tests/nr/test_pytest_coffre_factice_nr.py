"""NR (COF-1, choix owner 30/10 « coffre factice en test ») : un pytest du bac ne lit plus aucune VRAIE identite.

Mesure du 30/10 (journal sandbox/logs/coffre_cloisonne_observations.jsonl, job_2faa12d2b650) : 1 406 premieres lectures
`aurait_refuse:bac_ring_le_3`, dont 82 % par des pytest (nokido_hub._load_agent_tokens 1 155, forge_auth_tokens 165,
compte LaForgeSbxOffline). Le refus du coffre au bac aurait casse ces tests ; l'isolation est cote HARNAIS
(tests/conftest.py, `_coffre_factice_identites`) via le coffre de test DEJA servi par forge_secrets._coffre_test.
Assertions booleennes seulement : aucune valeur n'est affichee, meme factice.
"""
import json
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "app")]


def _coffre():
    dossier = os.environ.get("NOKIDO_COFFRE_TEST_DIR")
    assert dossier, "aucun coffre de test pose : un pytest lirait le VRAI coffre"
    return json.loads((Path(dossier) / "coffre_test.json").read_text(encoding="utf-8"))


def test_toutes_les_identites_declarees_ont_un_jeton_factice():
    data = _coffre()
    declarees = json.loads((RACINE / "config" / "agent_identities.json").read_text(encoding="utf-8"))["agents"]
    manquants = [a for a, m in declarees.items()
                 if not (isinstance(m, dict) and m.get("jeton_direct") is False) and "FORGE_TOKEN_%s" % a not in data]
    assert not manquants, "identites sans jeton factice : %s" % manquants


def test_get_secret_sert_le_factice_sans_atteindre_le_vrai_coffre():
    data = _coffre()
    from nokido_agent.app import forge_secrets as fs

    cle = sorted(k for k in data if k.startswith("FORGE_TOKEN_"))[0]
    journal = Path(fs._JOURNAL_OBSERVATIONS)
    avant = journal.stat().st_size if journal.exists() else 0
    assert (fs.get_secret(cle) == data[cle]) is True
    assert (journal.stat().st_size if journal.exists() else 0) == avant, "l'observation du coffre a ete atteinte"


def test_le_factice_n_est_pas_une_constante_du_depot():
    data = _coffre()
    src = (RACINE / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert all(v not in src for v in data.values()), "jeton factice ecrit en dur"
