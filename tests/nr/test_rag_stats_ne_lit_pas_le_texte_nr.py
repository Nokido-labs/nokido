r"""NR — une colonne de trop casse le COVERING INDEX, et la route devient inutilisable.

MESURE DU 2026-09-21 sur la base reelle (27,3 Go), en lecture seule stricte :

    SELECT domain,COUNT(*),SUM(LENGTH(text)) ... GROUP BY domain
        PLAN  SCAN rag_chunks USING INDEX idx_domain          87,149 s
    SELECT domain,COUNT(*)                   ... GROUP BY domain
        PLAN  SCAN rag_chunks USING COVERING INDEX idx_domain  0,147 s

    SELECT COUNT(*) FROM rag_chunks                            0,015 s
    SELECT COUNT(*) FROM rag_chunks WHERE embedding IS NULL    0,032 s

RATIO 593x, POUR UNE SEULE COLONNE. `SUM(LENGTH(text))` force SQLite a quitter
l'index pour aller lire la LIGNE, donc le BLOB de texte de chaque enregistrement.

CE QUE CETTE MESURE A CORRIGE DANS MA PROPRE DESCRIPTION
========================================================
Le commentaire laisse dans `nokido_hub.rag_stats` au commit precedent disait
« trois scans complets ». C'ETAIT FAUX : deux des trois coutent 0,047 s a eux
deux, sur des index adaptes (un couvrant, un partiel). Un seul terme, dans une
seule requete, portait 87,1 s des 87,3 s.

Meme faute de methode que « trois coupables pour un seul reel », payee le matin
meme : on accuse l'ensemble quand on n'a pas isole. La mesure par requete, avec
son PLAN, est ce qui separe.

CE QUI EST CABLE, ET POURQUOI PAS UNE SUPPRESSION
=================================================
`chars` n'est pas retire : la clef reste, avec la valeur `None` quand elle n'a
pas ete mesuree, et le calcul complet reste atteignable par `?chars=1`.

  * `None` et pas `0` -- une valeur NON MESUREE n'est pas ZERO. Remplir a 0
    ferait lire « ce domaine ne contient aucun caractere », ce qui est FAUX et
    indetectable. C'est `UNKNOWN != NO` applique a un chiffre.
  * la capacite reste ATTEIGNABLE : on ne supprime pas une mesure parce qu'elle
    est chere, on cesse de l'imposer a qui ne la demande pas.

DEUX MESURES QUI ONT GUIDE LE CHOIX, plutot qu'une intuition :

  * le JUMEAU `:7400` (`app/web_hub/wired_routes.py:250`) rend deja
    `{"name", "chunks"}` SANS `chars`. Le choix avait donc deja ete fait d'un
    cote du corps et pas de l'autre ;
  * le consommateur `app/web_hub/rag_dashboard.html:115` ecrit
    `x.chars ? (x.chars/1e6).toFixed(1)+'M' : ''` -- il TOLERE deja l'absence.

Et ce qui reste INCERTAIN, dit comme tel : aucun consommateur de `chars` n'a
ete trouve AU DEPOT. Cela ne prouve pas qu'il n'en existe aucun -- un client
hors depot est invisible a cette recherche. C'est precisement pourquoi la clef
survit et pourquoi le calcul reste appelable.
"""
from __future__ import annotations

import ast
import sqlite3
from pathlib import Path

import pytest


def _racine() -> Path:
    for base in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
        if (base / "tools" / "nokido_hub.py").exists():
            return base
    raise AssertionError("racine du depot introuvable")


def _handler_rag_stats() -> ast.FunctionDef:
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "rag_stats":
            return n
    raise AssertionError("handler `rag_stats` introuvable dans nokido_hub")


def _sql_du_handler() -> list[str]:
    return [n.value for n in ast.walk(_handler_rag_stats())
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "rag_chunks" in n.value]


# ─────────  LA CAUSE, REPRODUITE SANS DEPENDRE DE LA GROSSE BASE  ─────────

def test_la_colonne_texte_fait_perdre_le_covering_index(tmp_path):
    """LA CAUSE, isolee sur une base JETABLE : le plan change, et c'est le plan
    qui explique les 87 s -- pas le volume, pas la machine.

    Mesurer le TEMPS ici serait une sonde sur la machine ; on mesure le PLAN,
    qui est une propriete de la requete et de l'index.
    """
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE rag_chunks (id INTEGER PRIMARY KEY, domain TEXT, text TEXT)")
    con.execute("CREATE INDEX idx_domain ON rag_chunks(domain)")
    con.executemany("INSERT INTO rag_chunks(domain,text) VALUES(?,?)",
                    [("d%d" % (i % 7), "x" * 64) for i in range(500)])
    con.commit()
    con.execute("ANALYZE")

    def plan(sql):
        return " | ".join(str(r[-1]) for r in con.execute("EXPLAIN QUERY PLAN " + sql))

    sans = plan("SELECT domain,COUNT(*) FROM rag_chunks GROUP BY domain")
    avec = plan("SELECT domain,COUNT(*),SUM(LENGTH(text)) FROM rag_chunks GROUP BY domain")
    con.close()

    assert "COVERING INDEX" in sans, (
        "la requete sans `text` n'utilise plus un index couvrant : la mesure "
        "de reference ne tient plus, re-mesurer avant de conclure (%r)" % sans)
    assert "COVERING INDEX" not in avec, (
        "ajouter `SUM(LENGTH(text))` ne casse plus le covering index dans ce "
        "runtime : la cause mesuree le 2026-09-21 a change (%r)" % avec)


# ────────────  LE CHEMIN PAR DEFAUT NE LIT PLUS LE TEXTE  ─────────────────

def test_le_chemin_par_defaut_du_hub_ne_lit_pas_la_colonne_texte():
    """LE COEUR. Au moins une requete du handler doit grouper SANS toucher
    `text` : c'est le chemin emprunte quand l'appelant ne demande rien."""
    sqls = _sql_du_handler()
    assert sqls, "aucune requete `rag_chunks` dans le handler : re-mesurer"
    groupes = [s for s in sqls if "GROUP BY" in s.upper()]
    assert groupes, "le handler ne groupe plus par domaine : re-mesurer"
    sans_texte = [s for s in groupes if "LENGTH(TEXT)" not in s.upper()]
    assert sans_texte, (
        "toutes les requetes groupees du handler lisent `text` : le chemin par "
        "defaut refait le scan de 87 s mesure le 2026-09-21 -- %r" % groupes)


def test_le_calcul_couteux_reste_atteignable_explicitement():
    """On ne supprime pas une mesure parce qu'elle est chere. Contre-epreuve du
    test precedent : sans elle, le correctif serait un DECLASSEMENT."""
    sqls = _sql_du_handler()
    couteuses = [s for s in sqls if "LENGTH(TEXT)" in s.upper()]
    assert couteuses, (
        "`SUM(LENGTH(text))` a DISPARU du handler : la capacite a ete "
        "supprimee au lieu d'etre rendue optionnelle -- un declassement")


def test_une_valeur_non_mesuree_n_est_jamais_rendue_comme_zero():
    """`chars: c or 0` transformerait « non mesure » en « zero caractere » :
    un chiffre FAUX, et indetectable en aval. UNKNOWN != NO, y compris pour un
    nombre."""
    fn = _handler_rag_stats()
    fautifs = [
        ast.dump(n) for n in ast.walk(fn)
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or)
        and any(isinstance(v, ast.Constant) and v.value == 0 for v in n.values)
    ]
    assert not fautifs, (
        "le handler rabat une valeur absente sur 0 : une valeur NON MESUREE "
        "serait lue comme un zero mesure")


def test_l_instrument_lit_bien_le_handler_et_pas_le_fichier_entier():
    """Un detecteur qui scanne tout `nokido_hub.py` trouverait `LENGTH(text)`
    dans n'importe quelle autre route et rendrait un verdict sur le mauvais
    objet. On verifie qu'il est borne au handler."""
    fn = _handler_rag_stats()
    assert fn.name == "rag_stats"
    tout = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    assert len(ast.dump(fn)) < len(tout), "l'instrument n'est pas borne au handler"
