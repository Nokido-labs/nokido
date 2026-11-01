"""NR : la primitive `Mesure` ne rend jamais un booleen ou un 0 nu (chantier P0 phase A, 24/10).

Trois avis externes convergent : un 0 sans temoin, un 401 pris pour un score, un « [ERR x] HTTP 401 »
sous HTTP 200 sont des LECTURES IMPOSSIBLES, pas des mesures. Chemin reel, aucun mock.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tools.forge_cli_swarm import (  # noqa: E402
    Mesure, MesureIllisible, agreger_sain, depuis_http,
)


def test_un_zero_sans_temoin_est_ILLISIBLE():
    m = Mesure(statut="ZERO", valeur=0)
    assert m.statut == "ILLISIBLE"
    assert "instrument non étalonné" in m.motif


def test_un_absent_sans_temoin_est_ILLISIBLE():
    assert Mesure(statut="ABSENT", temoin_positif=False).statut == "ILLISIBLE"


def test_un_zero_avec_temoin_reste_ZERO():
    assert Mesure(statut="ZERO", valeur=0, temoin_positif=True).statut == "ZERO"


def test_un_401_est_AUTH_ERROR_pas_zero():
    m = depuis_http(401, "")
    assert m.statut == "AUTH_ERROR" and m.valeur is None
    assert depuis_http(403, "x").statut == "AUTH_ERROR"


def test_429_5xx_timeout_sont_TRANSPORT_ERROR():
    assert depuis_http(429, "").statut == "TRANSPORT_ERROR"
    assert depuis_http(503, "").statut == "TRANSPORT_ERROR"
    assert depuis_http(None, "").statut == "TRANSPORT_ERROR"


def test_un_texte_d_erreur_sous_HTTP_200_est_TRANSPORT_ERROR():
    m = depuis_http(200, "[ERR x] HTTP 401")
    assert m.statut == "TRANSPORT_ERROR"


def test_un_200_avec_vraie_reponse_est_VALEUR():
    m = depuis_http(200, "42 reponses reelles")
    assert m.statut == "VALEUR" and m.valeur == "42 reponses reelles"


def test_une_mesure_perimee_se_lit_STALE():
    m = Mesure(statut="VALEUR", valeur=1, mesure_le=1000.0, ttl_s=10)
    assert m.statut_lu(maintenant=1005.0) == "VALEUR"
    assert m.statut_lu(maintenant=1011.0) == "STALE"
    with pytest.raises(MesureIllisible):
        m.valeur_ou_leve(maintenant=1011.0)


def test_valeur_ou_leve_sur_ILLISIBLE_leve():
    with pytest.raises(MesureIllisible):
        Mesure(statut="ZERO", valeur=0).valeur_ou_leve()
    for s in ("UNKNOWN", "STALE", "INSUFFISANT", "TRANSPORT_ERROR", "AUTH_ERROR", "ECHEC_METIER",
              "NON_APPLICABLE"):
        with pytest.raises(MesureIllisible):
            Mesure(statut=s).valeur_ou_leve()


def test_valeur_ou_leve_rend_VALEUR_et_ZERO_etalonne():
    assert Mesure(statut="VALEUR", valeur=7).valeur_ou_leve() == 7
    assert Mesure(statut="ZERO", valeur=0, temoin_positif=True).valeur_ou_leve() == 0


def test_agreger_sain_liste_blanche():
    ok = Mesure(statut="VALEUR", valeur=1)
    assert agreger_sain([ok, ok]) is True
    assert agreger_sain([ok, Mesure(statut="UNKNOWN")]) is False
    assert agreger_sain([ok, Mesure(statut="ILLISIBLE")]) is False
    assert agreger_sain([ok, Mesure(statut="VALEUR", mesure_le=1.0, ttl_s=1)]) is False  # STALE
    assert agreger_sain([ok, Mesure(statut="ZERO", valeur=0)]) is False  # ZERO non etalonne
    assert agreger_sain([]) is False  # rien de prouve n'est pas sain


def test_un_statut_inconnu_est_refuse():
    with pytest.raises(ValueError):
        Mesure(statut="OK")


def test_la_mesure_est_gelee():
    with pytest.raises(Exception):
        Mesure(statut="VALEUR", valeur=1).valeur = 2
