# -*- coding: utf-8 -*-
"""NR — le recenseur de surfaces ne compte que ce qui est a NOUS, et le prouve.

`forge_npsc_decouverte` repond a « qu'est-ce que le code manipule reellement ? »
pour que l'elargissement du registre NPSC soit une consequence de la mesure et
non d'une liste ecrite de memoire. Il ne juge rien.

Proprietes gardees, chacune adossee a une erreur payee le 2026-09-04 :

1. Un module INTERNE (`forge_*`, `app`, `tools`) n'est pas une dependance a
   auditer. Le compter en gonflerait l'inventaire de faux protocoles.
2. Un module de la stdlib PROTOCOLAIRE (ssl, hashlib, base64...) compte, lui :
   c'est par la que passent la plupart des surfaces normees de Nokido.
3. Les extracteurs rendent des schemes, media types et en-tetes REELS, pas des
   fragments de mots. C'est le test d'EFFET du recenseur.
4. Index git indisponible -> aucun inventaire, jamais un inventaire vide.
   « je n'ai pas pu regarder » n'est pas « il n'y a rien ».
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.69)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_npsc_decouverte as reco  # noqa: E402


def test_modules_internes_ne_sont_pas_des_dependances():
    """Un `forge_*` est du code Nokido, pas une bibliotheque de protocole."""
    for interne in ("forge_rag_engine", "forge_npsc_scan", "app", "tools", "netcfg"):
        assert reco._est_tiers(interne) is False, "%s compte a tort comme tiers" % interne


def test_stdlib_protocolaire_compte_comme_surface():
    """ssl, hashlib, base64... portent des surfaces normees : ils doivent compter."""
    for module in ("ssl", "hashlib", "base64", "uuid", "sqlite3", "socket"):
        assert module in reco._STDLIB_PROTOCOLAIRE, "%s absent de la stdlib protocolaire" % module
    for tiers in ("fastapi", "httpx", "qdrant_client"):
        assert reco._est_tiers(tiers) is True, "%s devrait compter comme tiers" % tiers


def test_extracteurs_rendent_des_valeurs_reelles():
    """EFFET : les regex extraient des surfaces, pas des fragments de mots."""
    temoin = ("connect('ssh://hote:22') puis 'socks5h://proxy' et 'otpauth://totp/x' ; "
              "headers = {'Content-Type': 'application/json', 'X-Agent-Name': 'CLAUDE'} ; "
              "flux 'text/event-stream' et 'multipart/form-data'")
    schemes = set(reco._RX_SCHEME.findall(temoin.lower()))
    assert {"ssh", "socks5h", "otpauth"} <= schemes, schemes
    medias = set(reco._RX_MEDIA.findall(temoin.lower()))
    assert {"application/json", "text/event-stream", "multipart/form-data"} <= medias, medias
    entetes = set(reco._RX_ENTETE.findall(temoin))
    assert {"Content-Type", "X-Agent-Name"} <= entetes, entetes


def test_extracteurs_ne_fabriquent_pas_de_scheme():
    """Une prose sans URI ne doit produire aucun scheme : sinon tout devient surface."""
    assert not reco._RX_SCHEME.findall("ce texte parle de ssh et de tls sans aucune uri")
    assert not reco._RX_MEDIA.findall("il est question de json et de html en general")


def test_index_git_indisponible_ne_rend_pas_un_inventaire_vide():
    """EFFET : sans index, `decouvrir` rend None, jamais des compteurs a zero.

    Un inventaire vide se lirait « Nokido ne manipule aucun protocole » — la
    conclusion exactement inverse de la realite.
    """
    inventaire, diag = reco.decouvrir(ROOT / "_repertoire_inexistant_npsc")
    assert inventaire is None, "un chemin non-depot a produit un inventaire"
    assert diag.get("instrument_ok") is False
    assert diag.get("erreur_index"), "echec silencieux : aucune erreur nommee"


def test_ports_connus_sont_nommes():
    """Un port sans signification n'aide personne a juger d'une surface."""
    for port in ("8766", "11434", "6334", "443"):
        assert port in reco._PORTS_CONNUS, "port %s sans libelle" % port
    assert reco._PORTS_CONNUS["6334"].startswith("Qdrant"), "le port gRPC de Qdrant doit etre nomme"
