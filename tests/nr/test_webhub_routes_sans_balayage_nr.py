"""NR -- aucune route du portail ne balaie la grosse base, et /health ne s'affame pas.

DEUX DEFAUTS MESURES le 2026-09-18, dans le meme fichier, et de la meme famille :
une route qui prend du temps dans un serveur dont les routes synchrones se
partagent un threadpool borne.

1. `/api/hub/overview` -- l'« intention longue » -- ouvrait `RAG/embeddings.db`
   (la base GELEE de 24,9 Go) pour :

       SELECT text FROM rag_chunks WHERE lower(source) LIKE '%roadmap%'
       ORDER BY created_at DESC LIMIT 1

   `lower()` sur la colonne et un joker en tete interdisent tout index : c'est un
   BALAYAGE COMPLET, suivi d'un TRI de tout le resultat -- le `LIMIT 1` arrive
   apres et ne sauve rien. Mesure : la route DEPASSE 12 secondes. C'est la
   sixieme incarnation du meme balayage sur cette base (GROUP BY source le
   23/08, COUNT(*) le 03/09...), et le `timeout=3` passe a `sqlite3.connect` n'y
   peut rien : c'est un delai de VERROU, jamais une echeance de requete.

   L'etat de la roadmap est deja publie par son producteur dans
   `docs/roadmap_state.json` -- dix-neuf kilo-octets, regeneres en continu. On
   LIT le snapshot du producteur, on ne reconstruit pas l'etat.

2. `/health` etait declare `def`, donc execute dans le threadpool. Sous charge,
   il partait en file derriere les routes lentes et se taisait -- une SATURATION
   qui se lit comme une PANNE, mesuree a 5 359 ms le 2026-09-17. Une sonde de
   sante doit repondre meme quand le reste est occupe : c'est toute sa raison
   d'etre.

CE QUE CE NR FIGE. Il lit la SOURCE du portail : aucune route ne doit nommer la
grosse base ni la table de chunks, et la sonde de sante doit etre asynchrone. Il
ne mesure pas un temps -- un seuil de duree serait instable sur une machine
chargee, alors que la presence d'un balayage, elle, est un fait.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
APP = RACINE / "app" / "web_hub" / "app.py"

# CE QUE CE GARDE VISE, ET CE QU'IL NE VISE PAS -- corrige le 2026-09-18 apres
# mesure. Ma premiere version interdisait de NOMMER `embeddings.db`, et elle
# accusait deux routes innocentes : `ui_auto_veille_summary` interroge
# `watch_jobs` (petite table) et `reports_page` filtre sur une colonne INDEXEE.
# `EXPLAIN QUERY PLAN` sur la base reelle a tranche en une milliseconde :
#
#     overview       SCAN rag_chunks                            <- le coupable
#     reports_page   SEARCH rag_chunks USING INDEX idx_domain   <- correct
#     veille         SCAN watch_jobs                            <- petite table
#
# Compter le vocabulaire au lieu de mesurer le PLAN, c'est exactement le defaut
# que ce depot paie ailleurs. Le garde vise donc le MOTIF DE BALAYAGE, pas le
# nom du fichier : un joker en tete de `LIKE` interdit tout index, et une
# fonction appliquee a la colonne filtree aussi.
INTERDITS = ("rag_chunks",)
# Motifs qui rendent un index inutilisable, quelle que soit la table.
BALAYAGES = ("like '%", 'like "%', "lower(source)", "upper(source)")


def _arbre() -> ast.AST:
    assert APP.exists(), "app.py introuvable : ce test passerait sur du vide"
    return ast.parse(APP.read_text(encoding="utf-8", errors="replace"))


def _fonction(nom: str):
    for n in ast.walk(_arbre()):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    return None


def _texte(noeud) -> str:
    """Corps de la fonction, COMMENTAIRES RETIRES.

    Piege paye en ecrivant ce NR : il accusait `api_hub_overview` a cause du
    commentaire qui CITE le SQL supprime pour expliquer pourquoi il l'a ete. Un
    instrument ne doit jamais lire son propre vocabulaire, ni celui de la
    doctrine qui le documente -- c'est une MENTION, pas une STRUCTURE. Meme
    regle que `_sans_commentaires` dans le NR du superviseur.

    Les docstrings restent, elles : un SQL cache dans une docstring serait
    toujours du code mort a signaler, et personne n'y explique un correctif.
    """
    lignes = APP.read_text(encoding="utf-8", errors="replace").splitlines()
    brut = lignes[noeud.lineno - 1:(noeud.end_lineno or noeud.lineno)]
    return "\n".join(l for l in brut if not l.lstrip().startswith("#"))


def test_le_depouillage_des_commentaires_MORD():
    """Sans lui, un commentaire qui explique le correctif ferait echouer le garde.

    C'est arrive : le NR accusait la route au motif du commentaire qui decrit le
    SQL retire. On verifie donc que le depouillage retire bien une ligne de
    commentaire ET conserve le code.
    """
    src = "    # SELECT x FROM rag_chunks WHERE lower(source) LIKE '%y%'\n    return 1"
    net = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "rag_chunks" not in net and "return 1" in net


def test_l_instrument_mord():
    """Sans cette morsure, un detecteur qui ne trouve jamais rien serait vert."""
    faux = "con.execute(\"SELECT t FROM rag_chunks WHERE lower(source) LIKE '%x%'\")"
    assert any(i in faux for i in INTERDITS)
    assert any(b in faux.lower() for b in BALAYAGES), (
        "le detecteur ne reconnait meme pas un balayage ecrit en toutes lettres")


def test_l_instrument_ACQUITTE_une_requete_indexee():
    """Contre-epreuve, et elle a servi : un garde qui accuse tout n'apprend rien.

    Cette requete filtre sur une colonne indexee -- le plan reel dit
    `SEARCH ... USING INDEX idx_domain`. Elle ne doit PAS etre signalee.
    """
    saine = ("cur.execute(\"SELECT source FROM t WHERE domain IN ('ctf') \"\n"
             "            \"ORDER BY created_at DESC LIMIT 50\")")
    assert not any(b in saine.lower() for b in BALAYAGES), (
        "le garde accuse une requete indexee : il compte du vocabulaire au lieu "
        "de viser le motif qui empeche l'index")


def test_l_intention_longue_ne_balaie_plus_la_grosse_base():
    f = _fonction("api_hub_overview")
    assert f is not None, (
        "`api_hub_overview` introuvable : le contrat ne peut pas etre verifie, "
        "donc ILLISIBLE -- ni vrai ni faux")
    corps = _texte(f)
    trouves = [i for i in INTERDITS if i in corps]
    assert not trouves, (
        "/api/hub/overview nomme encore %s : c'est le balayage qui faisait "
        "depasser 12 secondes a la vue « intention longue ». L'etat de la "
        "roadmap se lit dans docs/roadmap_state.json, publie par son producteur."
        % ", ".join(trouves))


def test_l_intention_longue_lit_le_SSOT():
    """Contre-epreuve : retirer le SQL sans mettre de source rendrait le test
    precedent vert sur une route qui n'affiche plus rien."""
    corps = _texte(_fonction("api_hub_overview"))
    assert "roadmap_state" in corps, (
        "la route ne lit aucun etat de roadmap : on aurait retire le balayage "
        "en retirant aussi l'information")


def test_la_sonde_de_sante_est_asynchrone():
    f = _fonction("health")
    assert f is not None, "`health` introuvable dans app.py"
    assert isinstance(f, ast.AsyncFunctionDef), (
        "/health est declare `def` : il passe par le threadpool et part en file "
        "derriere les routes lentes. Mesure du 2026-09-17 : 5 359 ms sous "
        "charge, c'est-a-dire une saturation lue comme une panne.")


def test_aucune_route_du_portail_ne_BALAIE():
    """Le defaut est de CLASSE, pas propre a une route : on verifie tout le
    fichier, pour qu'une prochaine route ne refasse pas le meme chemin.

    On vise le motif qui empeche l'index, pas l'usage de la base : une requete
    indexee sur une grosse table est legitime, un balayage ne l'est pas.
    """
    coupables = []
    for n in ast.walk(_arbre()):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        corps = _texte(n).lower()
        motifs = [b for b in BALAYAGES if b in corps]
        if motifs:
            coupables.append("%s (L%d) : %s" % (n.name, n.lineno, " ".join(motifs)))
    assert not coupables, (
        "ces fonctions du portail contiennent un motif qui interdit tout index : "
        "%s. Chacune est un gel en puissance, parce que les routes synchrones "
        "partagent un threadpool borne." % " | ".join(coupables))
