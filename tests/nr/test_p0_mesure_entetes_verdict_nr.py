"""NR -- P0 jetons clients au coffre seul, phase 2 : le verdict de la mesure en profil jetable.

Trois issues distinctes, jamais confondues (UNKNOWN n'est pas NO) : l'en-tete arrive developpe (NATIF_OK),
il arrive LITTERAL (NON_DEVELOPPE : le client envoie `{env:...}` tel quel), ou rien n'arrive (AUCUNE_REQUETE :
le client n'a pas parle au serveur, ce n'est PAS une preuve que la forme est refusee).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_p0_mesure_entetes_clients as M  # noqa: E402

FAUX = "-".join(("faux", "p0", "0000"))


def test_entete_developpe_est_natif_ok():
    assert M.verdict(["Bearer " + FAUX], FAUX) == "NATIF_OK"


def test_entete_litteral_est_non_developpe():
    assert M.verdict(["Bearer {env:%s}" % M.VAR], FAUX) == "NON_DEVELOPPE"
    assert M.verdict(["Bearer ${%s}" % M.VAR], FAUX) == "NON_DEVELOPPE"
    assert M.verdict(["Bearer $%s" % M.VAR], FAUX) == "NON_DEVELOPPE"


def test_aucune_requete_ne_vaut_pas_refus():
    assert M.verdict([], FAUX) == "AUCUNE_REQUETE"


def test_un_silence_dit_sa_cause():
    """Sorties reelles du 25/10 : aucune ne refute la forme, chacune dit pourquoi rien n'est parti."""
    assert M.cause_silence("MCP servers are configured but disabled because this folder is untrusted.") \
        == "DOSSIER_NON_APPROUVE"
    assert M.cause_silence("Error: No authentication information found.") == "AUTH_CLI_REQUISE"
    assert M.cause_silence("Le chemin d'acces specifie est introuvable.") == "BINAIRE_ABSENT"
    assert M.cause_silence("rien de reconnaissable") == "INCONNUE"


def test_requete_sans_en_tete_attendu_est_autre():
    assert M.verdict([""], FAUX) == "SANS_ENTETE"
    assert M.verdict(["Bearer autre-chose"], FAUX) == "AUTRE"
