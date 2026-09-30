"""Un motif de PREFIXE en `LIKE` neutralise l'index — garde contre la recidive.

Mesure du 2026-09-04, a l'origine de ce garde. `anchor_solution` dedupliquait par
`SELECT id FROM rag_chunks WHERE id LIKE 'lesson_sol_<empreinte>_%'`. Plan reel :
`SCAN rag_chunks`, soit **24,9 Go lus a chaque ancrage de lecon**. Le test
`test_self_correction_roundtrip_nr` expirait donc au timeout de 30 s, ce qui tuait
la suite pytest **sans verdict** : le gate CI sortait rouge sans une seule ligne
d'echec, et ce rouge a bloque la publication de 27 commits.

La table n'etait pas mal indexee -- c'est la REQUETE qui empechait d'utiliser son
index : `LIKE` est INSENSIBLE a la casse par defaut, donc SQLite ne peut pas le
reecrire en bornes (`id >= 'x' AND id < 'y'`). `GLOB` est sensible a la casse, donc
il l'est. Mesure apres correction : `SEARCH ... USING INDEX`, **x3509** sur le COUNT
des lecons (2,543 s -> 0,0007 s), pour un resultat identique (6937 = 6937).

Ce que ce garde N'exige PAS, volontairement :
  - `LIKE '%motif%'` (joker en TETE) reste tolere : aucun index ne peut le servir,
    son remede est le FTS (regle d'or n1 du projet), pas `GLOB`. Mesure a l'appui :
    le plan reste `SCAN` dans les deux formes.
  - `NOT LIKE` et les requetes sur `sqlite_master` (table systeme, quelques
    dizaines de lignes) sont hors sujet.
Un garde qui crie a faux se fait desarmer : il ne signale que ce qu'il a mesure.
"""

import re
import sqlite3
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + lecture
#   (l.46)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]

# Un motif litteral de prefixe : au moins un caractere, puis '%' final, et AUCUN '%'
# avant -- c'est exactement le cas ou GLOB rend le plan indexable.
_LIKE_PREFIXE = re.compile(r"\bLIKE\s+'([^'%]+)%'", re.I)
_HORS_SUJET = re.compile(r"NOT\s+LIKE|sqlite_master", re.I)


def _balayer():
    """Rend (fichiers_lus, illisibles, sites). Le denominateur est RENDU : un
    balayage qui n'a pas pu lire ne doit pas se lire comme un balayage propre."""
    lus, illisibles, sites = 0, [], []
    for dossier in ("app", "tools"):
        base = ROOT / dossier
        if not base.is_dir():
            illisibles.append((dossier, "dossier absent"))
            continue
        for f in sorted(base.rglob("*.py")):
            if "_attic" in f.parts:
                continue  # code archive : hors chemin d'execution
            try:
                src = f.read_text(encoding="utf-8", errors="strict")
            except Exception as exc:  # illisible != conforme
                illisibles.append((str(f.relative_to(ROOT)), repr(exc)[:120]))
                continue
            lus += 1
            for num, ligne in enumerate(src.split("\n"), 1):
                # Une ligne de COMMENTAIRE n'execute rien. Les corrections posees le
                # 2026-09-04 citent le motif fautif pour expliquer pourquoi il l'etait
                # (« `LIKE 'file:%'` rendait 13 sources ») : sans ce filtre, le garde
                # se declencherait sur sa propre documentation, et un garde qui crie a
                # faux finit desarme.
                if ligne.lstrip().startswith("#"):
                    continue
                if "rag_chunks" not in ligne and "rag_fts" not in ligne:
                    continue
                if _HORS_SUJET.search(ligne):
                    continue
                trouve = _LIKE_PREFIXE.search(ligne)
                if trouve:
                    sites.append(
                        "%s:%d  LIKE '%s%%'  -> ecrire GLOB '%s*'"
                        % (f.relative_to(ROOT), num, trouve.group(1), trouve.group(1))
                    )
    return lus, illisibles, sites


def test_le_balayage_est_representatif():
    """Sans denominateur, « 0 site trouve » ne se distingue pas de « je n'ai pas pu
    regarder ». C'est le defaut qui a coute le plus cher a ce projet."""
    lus, illisibles, _ = _balayer()
    assert lus > 500, "balayage non representatif : seulement %d fichiers lus" % lus
    assert not illisibles, "fichiers illisibles (couverture surestimee) : %r" % (illisibles[:5],)


def test_aucun_like_de_prefixe_sur_les_tables_rag():
    """Le garde proprement dit."""
    _, _, sites = _balayer()
    assert not sites, (
        "%d requete(s) utilisent un motif de PREFIXE en LIKE sur une table rag_* : "
        "l'index de la cle ne peut pas servir, la table entiere est balayee.\n  %s"
        % (len(sites), "\n  ".join(sites))
    )


def test_glob_est_indexable_la_ou_like_ne_l_est_pas(tmp_path):
    """Test d'EFFET, hermetique : c'est la propriete SQLite dont depend le garde.

    Si une version future de SQLite rendait `LIKE 'prefixe%'` indexable, ce test
    echouerait et le garde ci-dessus deviendrait inutile -- il faut alors le savoir,
    pas continuer a imposer une reecriture devenue sans objet.
    """
    con = sqlite3.connect(str(tmp_path / "t.db"))
    con.execute("CREATE TABLE rag_chunks(id TEXT PRIMARY KEY, text TEXT)")

    def plan(sql):
        return " | ".join(r[3] for r in con.execute("EXPLAIN QUERY PLAN " + sql))

    p_like = plan("SELECT id FROM rag_chunks WHERE id LIKE 'lesson_sol_%'")
    p_glob = plan("SELECT id FROM rag_chunks WHERE id GLOB 'lesson_sol_*'")
    assert "SEARCH" not in p_like, "LIKE serait devenu indexable : %s" % p_like
    assert "SEARCH" in p_glob, "GLOB n'est plus indexable : %s" % p_glob


def test_glob_ne_perd_aucun_ancrage_existant(tmp_path):
    """Le seul risque du passage LIKE->GLOB etait un rappel plus etroit.

    Mesure du 2026-09-04 sur les 6936 ancrages en base : tous en hexadecimal
    minuscule, aucun rate. Ce que GLOB retire, ce sont trois classes de FAUX
    positifs -- casse differente, '_' pris comme joker, empreinte prolongee.
    """
    con = sqlite3.connect(str(tmp_path / "t.db"))
    con.execute("CREATE TABLE rag_chunks(id TEXT PRIMARY KEY, text TEXT)")
    attendu = "lesson_sol_a1b2c3_1700000000"
    faux_positifs = [
        "lessonXsolYa1b2c3Z1700000000",  # '_' est un JOKER en LIKE
        "LESSON_SOL_A1B2C3_1700000000",  # LIKE est insensible a la casse
        "lesson_sol_a1b2c3x_170",        # empreinte prolongee
    ]
    for ident in [attendu] + faux_positifs:
        con.execute("INSERT INTO rag_chunks VALUES(?,?)", (ident, "T"))

    lus_like = {r[0] for r in con.execute(
        "SELECT id FROM rag_chunks WHERE id LIKE ?", ("lesson_sol_a1b2c3_%",))}
    lus_glob = {r[0] for r in con.execute(
        "SELECT id FROM rag_chunks WHERE id GLOB ?", ("lesson_sol_a1b2c3_*",))}

    assert attendu in lus_glob, "GLOB rate le vrai positif -- la dedup serait cassee"
    assert not (lus_glob - lus_like), "GLOB matche des ids que LIKE ignorait : %r" % (lus_glob - lus_like)
    assert lus_like - lus_glob == set(faux_positifs), (
        "les faux positifs retires ne sont pas ceux attendus : %r" % (lus_like - lus_glob,))
