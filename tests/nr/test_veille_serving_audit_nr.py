"""Une veille n'est ingeree que si Nokido sait la RETROUVER.

DIRECTIVE OWNER 2026-09-07, apres revue de l'etat du depot :

    « Nokido sait deja beaucoup mieux ingerer la veille qu'il ne sait encore
      l'exploiter comme carburant cognitif. [...] La prochaine mesure utile est de
      prouver, source par source, ingeree -> vectorisee -> recuperable -> servie
      -> effectivement utilisee. »

Et le critere d'acceptation, au niveau SOURCE et non au niveau job :

    VEILLE_SERVABLE = contenu valide + chunks + embeddings + index lexical
                    + provenance + fraicheur + RECUPERABILITE

CE QUI A ETE MESURE LE MEME SOIR, et qui motive ce fichier. Interroge sur une
question REELLE de la session (une doublure de test incapable d'echouer), le RAG rend
le code de Nokido et zero chunk de veille. La meme question RESTREINTE aux sources
academiques rend en premier resultat « An Empirical Study of Flaky Tests in Python »
(22 352 projets, 876 186 tests) -- exactement le sujet. Le savoir est donc PRESENT et
PERTINENT, mais NOYE : 591 chunks de veille du jour contre 2,18 M chunks en base.
`n_stored > 0` ne prouve rien sur la recuperabilite.

CE FICHIER NE CREE PAS DE MOTEUR. `forge_epistemic_retrieve` classe deja consensus /
minorite / conflit / temporalite, `forge_vec_coverage` audite deja la couverture
vectorielle. Il manque le passage du COVERAGE AUDIT au SERVING AUDIT : un verdict par
source, avec ses manques NOMMES.

TROIS ETATS, jamais deux : SERVABLE · NON_SERVABLE(raisons) · INDETERMINE (on n'a pas
pu voir). Confondre les deux derniers ferait passer une base illisible pour une base
vide -- le defaut que la constitution semantique interdit.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _il_y_a(jours: float) -> str:
    """Un age RELATIF a maintenant, jamais une date absolue.

    Mesure du 2026-09-22 : le defaut de `_base` etait `2026-09-07T15:00:00`, pose
    le jour ou ce test a ete ecrit -- il valait alors « frais ». Quinze jours plus
    tard la meme donnee avait 14,58 jours, la classe est passee VEILLE ->
    HISTORIQUE, et le test est devenu ROUGE SANS QU'UNE LIGNE DE CODE CHANGE.

        UN TEST QUI FIXE UNE DATE MESURE LE CALENDRIER, PAS LA PROPRIETE

    Il n'a pas trouve de regression : il a fini de pourrir. La propriete visee --
    une veille recente est VEILLE, une ancienne devient HISTORIQUE sans cesser
    d'etre servable -- ne depend pas du jour ou on la joue, donc l'age non plus.
    """
    return (datetime.now(timezone.utc) - timedelta(days=jours)).isoformat()

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

DDL = """
CREATE TABLE rag_chunks (
    id TEXT PRIMARY KEY, source TEXT, text TEXT, embedding BLOB,
    domain TEXT, role_hint TEXT, created_at TEXT);
CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id UNINDEXED, source UNINDEXED, text);
"""

URL = "https://arxiv.org/abs/2101.09077v1"
TEXTE = ("An Empirical Study of Flaky Tests in Python. We analysed 876186 test cases "
         "from 22352 projects to understand flakiness and how to avoid it.")


_SEQ = [0]


def _base(tmp_path, *, embedding=b"\x00" * 8, fts=True, provenance=True,
          texte=TEXTE, created=None):
    """Base fabriquee au schema reel, chaque invariant activable separement.

    Un nom UNIQUE par appel : plusieurs bases coexistent dans un meme test (compare
    frais/ancien, question pertinente/hors sujet) et se marchaient dessus.
    """
    # Par defaut : FRAICHE au moment ou le test tourne. Une constante de date
    # rendait ce defaut de moins en moins vrai chaque jour (cf. `_il_y_a`).
    created = created or _il_y_a(0)
    _SEQ[0] += 1
    p = tmp_path / ("rag_%d.db" % _SEQ[0])
    conn = sqlite3.connect(p)
    conn.executescript(DDL)
    conn.execute(
        "INSERT INTO rag_chunks VALUES (?,?,?,?,?,?,?)",
        ("watch_abc_00", URL, texte, embedding,
         "watch_veille" if provenance else None,
         "veille:flaky tests" if provenance else None, created))
    if fts:
        conn.execute("INSERT INTO rag_fts VALUES (?,?,?)", ("watch_abc_00", URL, texte))
    conn.commit()
    conn.close()
    return p


def _audit(base, **kw):
    import forge_veille_serving_audit as a  # noqa: PLC0415

    return a.auditer_source(URL, db_path=str(base), **kw)


def test_une_source_COMPLETE_est_SERVABLE(tmp_path):
    """PROPRIETE 1. Le cas nominal : tous les invariants tenus -> SERVABLE."""
    r = _audit(_base(tmp_path))
    assert r["verdict"] == "SERVABLE", r
    assert not r["manques"], r


def test_des_chunks_STOCKES_ne_suffisent_PAS(tmp_path):
    """PROPRIETE 2 -- le coeur de la directive. `n_stored > 0` ne prouve rien.

    Un chunk present, sans vecteur, ne sera jamais rendu par le dense. Le declarer
    servi parce qu'il est STOCKE est precisement la confusion a fermer.
    """
    r = _audit(_base(tmp_path, embedding=None))
    assert r["verdict"] == "NON_SERVABLE", r
    assert any("embedding" in m for m in r["manques"]), r["manques"]
    assert r["chunks"] == 1, "le chunk EXISTE -- c'est bien le stockage qui ne suffit pas"


def test_un_index_lexical_DESYNCHRONISE_est_nomme(tmp_path):
    """PROPRIETE 3. Le lexical PRIME : sans lui, BM25 ne retrouvera jamais la source."""
    r = _audit(_base(tmp_path, fts=False))
    assert r["verdict"] == "NON_SERVABLE", r
    assert any("lexical" in m or "fts" in m for m in r["manques"]), r["manques"]


def test_une_provenance_ABSENTE_interdit_de_servir(tmp_path):
    """PROPRIETE 4. Sans domaine ni role_hint, un passage entre au contexte sans que
    l'on puisse dire d'ou il vient -- le contraire d'un verdict remontable."""
    r = _audit(_base(tmp_path, provenance=False))
    assert r["verdict"] == "NON_SERVABLE", r
    assert any("provenance" in m for m in r["manques"]), r["manques"]


def test_la_RECUPERABILITE_est_eprouvee_pour_de_vrai(tmp_path):
    """PROPRIETE 5 -- LE TEST DECISIF de la directive.

    « une veille n'est reellement ingeree que si Nokido sait la retrouver ». On pose
    donc une question de controle et on exige qu'elle ramene un chunk DE CETTE SOURCE.
    Un contenu present mais introuvable n'est pas servi.
    """
    r = _audit(_base(tmp_path), question="flaky tests python")
    assert r["recuperable"] is True, r

    # Meme base, question sans rapport : la source ne doit PAS etre declaree
    # recuperable par complaisance.
    r2 = _audit(_base(tmp_path), question="photosynthese chlorophylle")
    assert r2["recuperable"] is False, r2
    assert r2["verdict"] == "NON_SERVABLE", r2


def test_une_veille_ANCIENNE_reste_servable_mais_change_de_CLASSE(tmp_path):
    """PROPRIETE 6. « une veille ancienne ne doit pas disparaitre ; elle doit cesser
    d'etre confondue avec l'etat present. »

    La demi-vie epistemique de `watch_veille` est d'environ 1,5 jour : une veille de
    trois semaines reste une trace valide, mais elle n'est plus l'etat courant.
    """
    r = _audit(_base(tmp_path, created=_il_y_a(30)))
    assert r["verdict"] == "SERVABLE", "l'anciennete n'invalide pas : elle requalifie"
    assert r["classe"] == "HISTORIQUE", r
    assert r["age_j"] is not None and r["age_j"] > 20, r

    frais = _audit(_base(tmp_path))
    assert frais["classe"] == "VEILLE", frais


def test_une_base_ILLISIBLE_rend_INDETERMINE_jamais_NON_SERVABLE(tmp_path):
    """PROPRIETE 7. « pas pu voir » n'est pas « rien a voir ».

    Rendre NON_SERVABLE sur une base injoignable fabriquerait des sources declarees
    mortes par centaines, sur un simple probleme d'acces.
    """
    r = _audit(tmp_path / "inexistante.db")
    assert r["verdict"] == "INDETERMINE", r
    assert r["manques"] and any("illisible" in m or "absente" in m for m in r["manques"])


def test_l_audit_DELEGUE_la_qualification_epistemique(tmp_path):
    """PROPRIETE 8. Cablage, pas duplication.

    `forge_epistemic_retrieve` classe deja consensus / minorite / conflit et sait
    dater. L'auditeur mesure la SERVABILITE ; il ne refait pas ce jugement.
    """
    src = (ROOT / "tools" / "forge_veille_serving_audit.py").read_text(
        encoding="utf-8", errors="replace")
    for interdit in ("def cluster_aware_retrieve", "def qualifier_resultats"):
        assert interdit not in src, (
            "l'auditeur reimplemente %r au lieu de laisser le cortex epistemique "
            "faire son travail" % interdit)
