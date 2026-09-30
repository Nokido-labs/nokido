"""Tests NR de `tools/forge_knowledge_overlap.py` -- detecteur de nouveaute.

Tests d'EFFET et PURS : aucune connexion base, aucun etat de working tree. Ce
qui est verrouille ici, ce sont les proprietes qui rendent le verdict honnete --
en particulier le refus de trancher quand on n'a pas pu voir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.forge_knowledge_overlap import (  # noqa: E402
    DOUBLON_EXACT,
    ILLISIBLE_VECTORIEL,
    NEUF,
    QUASI_DOUBLON,
    blob_vers_vecteur,
    cosinus,
    hash_texte,
    modeles_comparables,
    normaliser,
    requete_fts,
    verdict,
)

np = pytest.importorskip("numpy")


# --- normalisation / hash ---------------------------------------------------
def test_normaliser_absorbe_casse_espaces_et_forme_unicode():
    """Meme savoir, ecriture differente -> MEME hash, sinon la couche 1 rate."""
    a = "Le  RAG\test\nhybride"
    b = "le rag est hybride"
    assert normaliser(a) == normaliser(b)
    assert hash_texte(a) == hash_texte(b)


def test_normaliser_recompose_les_accents_decomposes():
    """NFD vs NFC : `complexite` decompose doit hasher comme sa forme composee.

    Piege reel : les PDF LaTeX sortent avec des accents decomposes. Sans NFC,
    deux textes identiques a l'oeil produisent deux chunks distincts.
    """
    compose = "complexité"  # e + accent combinant
    precompose = "complexité"
    assert normaliser(compose) == normaliser(precompose)


def test_hash_distingue_deux_savoirs_differents():
    assert hash_texte("le rag est hybride") != hash_texte("le rag est lexical")


# --- blocking lexical -------------------------------------------------------
def test_requete_fts_neutralise_la_syntaxe_fts5():
    """Un texte porteur de guillemets/operateurs ne doit pas fabriquer de syntaxe."""
    q = requete_fts('un "chunk" OR NEAR(x) AND -foo')
    assert q.count('"') % 2 == 0
    # aucun terme nu : chaque terme est cite, donc jamais interprete en operateur
    for morceau in q.split(" OR "):
        assert morceau.startswith('"') and morceau.endswith('"')


def test_requete_fts_vide_quand_aucun_terme_exploitable():
    """Rend "" -- l'appelant doit lire « pas de blocking », pas « aucun voisin »."""
    assert requete_fts("!! ?? ..") == ""
    assert requete_fts("") == ""


def test_requete_fts_borne_le_nombre_de_termes():
    q = requete_fts(" ".join(f"terme{i}" for i in range(50)), max_termes=5)
    assert len(q.split(" OR ")) == 5


# --- decodage vectoriel -----------------------------------------------------
def test_blob_vers_vecteur_decode_un_float32_valide():
    v = np.array([0.5, -0.25, 1.0, 0.0], dtype=np.float32)
    out = blob_vers_vecteur(v.tobytes())
    assert out is not None and out.size == 4
    assert np.allclose(out, v)


def test_blob_taille_non_multiple_de_4_est_illisible_pas_approxime():
    """Un blob tronque rendrait un cosinus plausible et FAUX -> None impose."""
    assert blob_vers_vecteur(b"\x00\x01\x02") is None


def test_blob_de_mauvaise_dimension_est_refuse():
    v = np.array([1.0, 2.0], dtype=np.float32)
    assert blob_vers_vecteur(v.tobytes(), dim_attendue=1024) is None
    assert blob_vers_vecteur(v.tobytes(), dim_attendue=2) is not None


def test_blob_non_fini_est_illisible():
    v = np.array([1.0, np.nan], dtype=np.float32)
    assert blob_vers_vecteur(v.tobytes()) is None


def test_blob_vide_ou_non_binaire_est_illisible():
    assert blob_vers_vecteur(b"") is None
    assert blob_vers_vecteur("pas des octets") is None
    assert blob_vers_vecteur(None) is None


# --- cosinus ----------------------------------------------------------------
def test_cosinus_identique_vaut_un():
    v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert cosinus(v, v) == pytest.approx(1.0, abs=1e-6)


def test_cosinus_dimensions_differentes_rend_none_pas_zero():
    """0.0 se lirait « tres different » ; la verite est « incomparable »."""
    a = np.array([1.0, 2.0], dtype=np.float32)
    b = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    assert cosinus(a, b) is None


def test_cosinus_vecteur_nul_rend_none():
    a = np.zeros(3, dtype=np.float32)
    b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert cosinus(a, b) is None


# --- comparabilite des espaces ---------------------------------------------
def test_modeles_declares_differents_sont_incomparables():
    assert modeles_comparables("bge-m3", "e5-large") is False


def test_modele_inconnu_reste_comparable():
    """91 % des lignes ont embedding_model NULL : l'inconnu ne disqualifie pas."""
    assert modeles_comparables(None, "bge-m3") is True
    assert modeles_comparables("bge-m3", None) is True
    assert modeles_comparables(None, None) is True


def test_meme_modele_declare_est_comparable():
    assert modeles_comparables("bge-m3", "bge-m3") is True


# --- verdict : trois etats, jamais deux ------------------------------------
def test_hash_identique_tranche_avant_tout_le_reste():
    assert verdict(True, None, 0) == DOUBLON_EXACT


def test_aucun_voisin_compare_rend_illisible_et_non_neuf():
    """LE test central : « je n'ai pas pu voir » ne doit jamais sortir NEUF."""
    assert verdict(False, None, 0) == ILLISIBLE_VECTORIEL
    assert verdict(False, 0.99, 0) == ILLISIBLE_VECTORIEL


def test_cosinus_absent_malgre_des_voisins_rend_illisible():
    assert verdict(False, None, 7) == ILLISIBLE_VECTORIEL


def test_au_dessus_du_seuil_est_quasi_doublon():
    assert verdict(False, 0.95, 3, seuil=0.93) == QUASI_DOUBLON


def test_seuil_est_inclusif_et_en_dessous_est_neuf():
    assert verdict(False, 0.93, 3, seuil=0.93) == QUASI_DOUBLON
    assert verdict(False, 0.9299, 3, seuil=0.93) == NEUF


def test_seuil_est_parametrable_et_non_code_en_dur():
    """Le seuil se calibre : un verdict ne doit pas dependre d'une constante figee."""
    assert verdict(False, 0.80, 2, seuil=0.75) == QUASI_DOUBLON
    assert verdict(False, 0.80, 2, seuil=0.90) == NEUF
