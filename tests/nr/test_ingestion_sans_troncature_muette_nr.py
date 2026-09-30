"""Non-regression : rien n'entre en base AMPUTE sans que personne ne le sache.

DEFAUT MESURE le 2026-09-12 sur le corpus reel (2 240 676 chunks lus).

Question de l'owner apres la decouverte du plafond du sweep : « tu es passe a cote
de l'essentiel des ingestions de veille ? ». Reponse mesuree : non pour 99,3 % du
corpus — mais OUI pour 16 319 chunks, coupes en SILENCE a l'ecriture.

Signature de la troncature : un chunk coupe a une longueur EXACTEMENT egale a la
borne. Un decoupage naturel ne tombe pas au caractere pres, donc un pic sur une
valeur ronde est une preuve, et son amplitude se lit directement :

    longueur exacte      chunks
              512           586
             1000           222
             2000        13 896   <-- app/mcp_server_tools.py:236
             3000           562   <-- incident deja consigne (377 documents)
             4000         1 053   <-- app/forge_ingest_pipeline.py:456
                        --------
                          16 319   = 0,73 % du corpus

Ce que la mesure prouve AUSSI : la longueur maximale observee en base est
**177 479** caracteres. Donc la borne n'est pas une politique du corps — d'autres
chemins d'ecriture n'en ont aucune. C'est une INCOHERENCE ENTRE CHEMINS, meme
famille que `embed()` lisant la politique quand `embed_batch_fast` l'ignorait.

Le gate `borne_trop_serree` le dit depuis mai, et il avait deja compte le prix :
« `text[:3000]` a detruit le corps de 377 documents de veille — le contenu etait
disponible et JETE, en silence ». Le motif a recidive a 2000 pour 13 896 chunks.

CONTRAT VERROUILLE ICI — deux exigences, pas une :
  1. aucun ecrivain de `rag_chunks` ne tronque son texte par une tranche muette ;
  2. `rag_chunks.id` est un TEXT PRIMARY KEY : un INSERT qui ne le fournit pas
     laisse la clef NULLE et casse la deduplication (regle d'or n°3 du projet).
     Le site de `mcp_server_tools` violait les DEUX sur la meme ligne.

Une borne reste permise si elle DIT ce qu'elle jette — on interdit le silence,
pas la limite.

Ecrit ROUGE avant les correctifs.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture + ast de app/ et
#   tools/ (liste SOURCES) (l.135)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

SOURCES = [
    p for d in ("app", "tools") for p in (RACINE / d).rglob("*.py")
    if not ({"_attic", "backups", "legacy"} & set(p.parts))
]

# Ce qui designe une ecriture vers la table des chunks, dans du SQL litteral.
#
# ⚠️ `rag_chunks` est un PREFIXE de `rag_chunks_fts` et de `rag_chunks_fts_docsize`.
# Une premiere version de ce detecteur cherchait la sous-chaine nue et signalait
# `forge_self_correction.py:893` — qui est en realite
# `INSERT INTO rag_chunks_fts(rag_chunks_fts) VALUES('rebuild')`, une commande de
# RECONSTRUCTION de l'index FTS, pas une insertion de chunk. Corriger ce site
# aurait casse le rebuild. La frontiere est donc explicite : le nom de table ne
# doit pas etre suivi d'un caractere de mot.
# En deca, la borne vise une colonne courte (`author`, `role_hint`), pas le texte.
SEUIL_CONTENU = 500

TABLE = r"rag_chunks(?![\w])"
ECRITURES = re.compile(
    r"insert\s+(?:or\s+(?:ignore|replace)\s+)?into\s+" + TABLE
    + r"|update\s+" + TABLE,
    re.I | re.S,
)


def _rel(p: Path) -> str:
    return str(p)[len(str(RACINE)) + 1:].replace("\\", "/")


def _sql_des_appels(fn: ast.AST) -> list[str]:
    """SQL litteral d'un appel execute/executemany.

    Le SQL d'un INSERT long est souvent ECLATE en plusieurs litteraux concatenes
    implicitement ("INSERT INTO x " "(a,b) " "VALUES (?,?)"). On recolle donc les
    morceaux d'un meme argument avant de chercher, sinon la liste de colonnes est
    dans un litteral et le verbe dans un autre, et rien ne matche.
    """
    out = []
    for arg in getattr(fn, "args", [])[:1]:      # args[0] = le SQL
        morceaux = []
        for n in ast.walk(arg):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                morceaux.append(n.value)
        if morceaux:
            out.append(" ".join(morceaux).lower())
    return out


def _ecrit_dans_rag_chunks(appel: ast.Call) -> bool:
    fn = getattr(appel.func, "attr", None)
    if fn not in ("execute", "executemany"):
        return False
    return any(ECRITURES.search(sql) for sql in _sql_des_appels(appel))


def _tranches_litterales(noeud: ast.AST) -> list[tuple[int, int]]:
    """(ligne, borne) des `X[:N]` avec N litteral, sous ce noeud."""
    out = []
    for n in ast.walk(noeud):
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice):
            hi = n.slice.upper
            if isinstance(hi, ast.Constant) and isinstance(hi.value, int):
                out.append((n.lineno, hi.value))
    return out


def _cree_sa_propre_table(texte: str) -> bool:
    """Le module definit-il lui-meme une table `rag_chunks` ?

    `forge_knowledge_distiller` construit une base EXTERNE avec son propre schema
    (`id INTEGER PRIMARY KEY`, autorowid) : y omettre `id` est legitime, SQLite le
    remplit. Signale a tort le 2026-09-12 — un module qui CREE sa table definit
    son propre contrat, et le contrat du corps ne s'y applique pas.
    """
    return bool(re.search(r"create\s+table[^;]*?rag_chunks", texte, re.I | re.S))


def _ecritures_du_depot():
    """[(fichier, noeud d'appel)] pour chaque ecriture vers la table du CORPS."""
    trouve = []
    for p in SOURCES:
        try:
            texte = p.read_text(encoding="utf-8", errors="replace")
            arbre = ast.parse(texte)
        except Exception:
            continue
        if _cree_sa_propre_table(texte):
            continue
        for n in ast.walk(arbre):
            if isinstance(n, ast.Call) and _ecrit_dans_rag_chunks(n):
                trouve.append((_rel(p), n))
    return trouve


def test_l_instrument_trouve_bien_des_ecritures():
    """Contre-epreuve prealable : un detecteur qui ne trouve RIEN rendrait un vert
    rassurant. On exige qu'il voie les ecrivains connus avant de juger."""
    ecritures = _ecritures_du_depot()
    assert len(ecritures) >= 3, (
        f"le detecteur ne voit que {len(ecritures)} ecriture(s) vers rag_chunks — "
        "instrument suspect, aucun verdict ne peut en etre tire"
    )


def test_l_instrument_ne_confond_pas_rag_chunks_avec_rag_chunks_fts():
    """Contre-epreuve symetrique : `rag_chunks` est un PREFIXE de `rag_chunks_fts`.
    Un detecteur trop large accuse le rebuild de l'index FTS — signale a tort le
    2026-09-12 — et le « corriger » casserait la reconstruction."""
    faux = [
        "INSERT INTO rag_chunks_fts(rag_chunks_fts) VALUES('rebuild')",
        "SELECT COUNT(*) FROM rag_chunks_fts_docsize",
        "DELETE FROM rag_chunks_fts WHERE chunk_id=?",
    ]
    for sql in faux:
        assert not ECRITURES.search(sql.lower()), (
            f"faux positif : {sql!r} n'ecrit pas dans rag_chunks"
        )
    vrais = [
        "INSERT OR IGNORE INTO rag_chunks(source,domain,text) VALUES(?,?,?)",
        "INSERT OR REPLACE INTO rag_chunks (id,text,source) VALUES (?,?,?)",
        "UPDATE rag_chunks SET embedding=? WHERE id=?",
    ]
    for sql in vrais:
        assert ECRITURES.search(sql.lower()), f"ecriture manquee : {sql!r}"


def test_aucune_ecriture_en_base_ne_tronque_le_texte_en_silence():
    """Le coeur. Une tranche litterale dans les ARGUMENTS d'un INSERT ampute le
    contenu sans trace : le texte complet etait disponible et il est jete."""
    fautifs = []
    for fichier, appel in _ecritures_du_depot():
        for arg in appel.args[1:]:          # args[0] = le SQL lui-meme
            for ligne, borne in _tranches_litterales(arg):
                # Toutes les bornes ne visent pas le CONTENU : `author` et
                # `role_hint` sont des colonnes courtes, et `title[:100]` y est
                # legitime. Les troncatures de contenu mesurees commencent a 800.
                # Le seuil separe les deux sans avoir a deviner quel argument
                # correspond a quelle colonne.
                if borne < SEUIL_CONTENU:
                    continue
                fautifs.append(f"{fichier}:{ligne} tronque a {borne}")
    assert not fautifs, (
        "troncature MUETTE dans une ecriture vers rag_chunks : "
        + " | ".join(sorted(fautifs))
        + ". Mesure du 12/09 : 16 319 chunks coupes pile sur une borne, dont "
          "13 896 a 2000. Le maximum observe en base etant 177 479 caracteres, "
          "aucune contrainte technique ne justifie ces bornes."
    )


def test_toute_ecriture_fournit_l_identifiant_primaire():
    """`rag_chunks.id` est un TEXT PRIMARY KEY (regle d'or n°3). Un INSERT qui
    ne nomme pas `id` laisse la clef nulle et casse la deduplication — le site
    de `mcp_server_tools` cumulait ce defaut avec la troncature."""
    fautifs = []
    for fichier, appel in _ecritures_du_depot():
        for sql in _sql_des_appels(appel):
            if "insert" not in sql or "rag_chunks" not in sql:
                continue
            # colonnes declarees entre la table et VALUES
            deb = sql.find("rag_chunks")
            fin = sql.find("values", deb)
            if fin == -1:
                continue
            colonnes = sql[deb:fin]
            if "(" in colonnes and "id" not in colonnes.replace("rag_chunks", ""):
                fautifs.append(f"{fichier}:{appel.lineno}")
    assert not fautifs, (
        "INSERT dans rag_chunks SANS colonne `id` (TEXT PRIMARY KEY) : "
        + " | ".join(sorted(set(fautifs)))
        + ". La clef reste NULLE et la deduplication ne peut plus operer."
    )
