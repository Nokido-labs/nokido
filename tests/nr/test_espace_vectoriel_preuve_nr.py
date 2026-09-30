"""NR — la preuve d'espace vectoriel ne balaie pas la base, et sa lecture est BORNÉE.

Mesure 2026-09-06 : `Qwen3-Embedding-0.6B` rend 1024 dimensions comme `bge-m3`, et la
similarité entre les vecteurs du MÊME texte vaut **-0,015** — orthogonalité pure. Même
dimension, espaces sans relation : écrire l'un à côté de l'autre ne lève aucune erreur,
ça rend les recherches silencieusement fausses. L'outil qui le démontre ne doit pas
lui-même devenir un balayeur : la première version déclenchait `SCAN rag_chunks` sur une
base de 24,9 Go pour six lignes (`LENGTH(text) BETWEEN` n'est pas indexable).

Trois garanties :
  1. la sélection est bornée par `rowid` et par un cap de lignes lues, jamais un filtre
     non indexable ;
  2. le nombre de lignes réellement lues est DIT (une borne muette surestime la couverture) ;
  3. le verdict d'espaces distincts se déclenche sur la mesure, pas sur une constante.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

SRC = (ROOT / "tools" / "forge_espace_vectoriel_preuve.py").read_text(encoding="utf-8",
                                                                     errors="replace")

# UN INSTRUMENT NE LIT JAMAIS SON PROPRE VOCABULAIRE (6e occurrence du motif, 2026-09-06).
# Ce test a d'abord echoue sur le COMMENTAIRE qui explique le piege -- « LENGTH(text)
# BETWEEN n'est pas indexable » -- en le prenant pour le piege lui-meme. On inspecte donc
# le CODE seul : commentaires et docstring retires.
def _code_seul(src: str) -> str:
    sans_doc = re.sub(r'"""[\s\S]*?"""', "", src)
    return "\n".join(l for l in sans_doc.splitlines() if not l.lstrip().startswith("#"))


CODE = _code_seul(SRC)

# 2026-09-06 : la lecture bornee et le cosinus ont ete REMONTES dans la brique commune
# (`forge_embed_lot_commun`) parce qu'une seconde sonde en portait une copie et que le
# cliquet de duplication l'a attrapee. Un NR garde une primitive LA OU ELLE VIT : il suit
# le code, sinon il devient vert sur un fichier qui ne fait plus rien.
SRC_COMMUN = (ROOT / "tools" / "forge_embed_lot_commun.py").read_text(encoding="utf-8",
                                                                     errors="replace")
CODE_COMMUN = _code_seul(SRC_COMMUN)


def test_la_selection_est_bornee_par_rowid_et_non_par_un_filtre_non_indexable():
    assert "WHERE rowid > ?" in CODE_COMMUN, "selection non bornee par rowid"
    assert "lu_max" in CODE_COMMUN, "aucun cap de lignes lues"
    # le filtre de longueur doit etre applique en Python, pas en SQL
    assert "LENGTH(text) BETWEEN" not in CODE_COMMUN, (
        "filtre non indexable revenu dans le SQL")
    assert "LENGTH(text) BETWEEN" not in CODE, (
        "l'outil de preuve ne doit pas le reintroduire non plus")


def test_l_outil_de_preuve_consomme_le_commun_au_lieu_d_en_garder_une_copie():
    """Anti-dup : la primitive est importee, jamais recopiee."""
    assert "from nokido_agent.tools.forge_embed_lot_commun import" in CODE, (
        "l'outil doit consommer la brique commune")
    assert "def _echantillon(" not in CODE, "copie locale de l'echantillonneur revenue"


def test_le_test_ne_lit_pas_les_commentaires_du_module():
    """Le garde du garde : si `_code_seul` cessait de retirer les commentaires, le test
    precedent se declencherait sur la prose qui documente le piege."""
    assert "LENGTH(text) BETWEEN" in SRC_COMMUN, "le commentaire explicatif a disparu"
    assert "n'est pas indexable" not in CODE_COMMUN, "les commentaires ne sont pas retires"


def test_le_nombre_de_lignes_lues_est_dit():
    assert re.search(r"\[lecture\].*ligne\(s\) lues", CODE_COMMUN), (
        "la couverture n'est pas dite")


def test_le_cosinus_detecte_l_orthogonalite():
    import forge_espace_vectoriel_preuve as P

    a = [1.0, 0.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0, 0.0]
    assert abs(P._cos(a, b)) < 1e-9
    assert P._cos(a, a) > 0.999


def test_le_cosinus_supporte_des_longueurs_differentes():
    import forge_espace_vectoriel_preuve as P

    # deux modeles peuvent rendre des dimensions differentes : on compare sur la
    # partie commune plutot que de lever, et le rapport imprime les deux dimensions.
    assert -1.0 <= P._cos([1.0, 2.0, 3.0], [1.0, 2.0]) <= 1.0


def test_le_seuil_de_verdict_est_ecrit_et_conservateur():
    # 0,30 : au-dela, on n'affirme rien et on demande une instruction — un resultat
    # inattendu ne doit pas se transformer en conclusion.
    assert "abs(moy) < 0.30" in CODE
    assert "a instruire avant toute conclusion" in CODE
