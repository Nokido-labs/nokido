"""Non-regression : le balayage de retrieval ne laisse JAMAIS un total inconnu.

DEFAUT MESURE le 2026-09-12, en conditions reelles, sur le terme `ShinkaEvolve`.

`forge_retrieval_sweep.PLAFOND = 500` borne chaque surface par un `LIMIT`, puis
compte les lignes RENDUES. Le compteur affiche donc 500 quel que soit le volume
reel, et rien ne permet d'aller voir au-dela : le plafond est en dur, sans option.

Mesure comparee (COUNT sans LIMIT, meme base, meme terme) :

    surface `rag_chunks_fts`   affichait 500 (plafonne)   REEL  7 747   x15,5
    surface `sources`          affichait 53 distinctes    REEL    301   x5,7

L'owner l'a dit sans detour : « les plafonds tronquaient l'information,
l'essentiel de l'information est rate ». Il avait raison, et le cout n'est pas
theorique : un agent lit « 500 » et « 53 sources », en tire une conclusion sur la
profondeur d'une ingestion, et se trompe d'un facteur 15.

DEUX defauts distincts, pas un :

  D1  AUCUN TOTAL. Les surfaces `rag_fts` / `rag_chunks_fts` posent bien
      `plafonne: True` — c'est honnete — mais le total reel n'est calcule NULLE
      PART. Or un `COUNT(*)` sur un `MATCH` FTS5 est peu couteux : rien
      n'obligeait a laisser le volume inconnu. Un drapeau `plafonne` dit qu'on
      ne sait pas ; il ne dispense pas d'aller savoir.

  D2  LA SURFACE `sources` TRONQUE EN SILENCE. Sa branche applique le meme
      `LIMIT PLAFOND` mais **ne pose jamais `plafonne`**, et pire, elle calcule
      `distinctes = len(srcs)` SUR l'echantillon tronque. Elle affiche donc un
      nombre de sources distinctes qui est un PLANCHER presente comme un total,
      sans le moindre marqueur. Les deux autres surfaces disent au moins
      « (plafonne) ».

C'est l'instrument meme de la regle owner du 2026-09-03 — « retrieval
INDEFECTIBLE, balayer toutes les surfaces », ecrite apres trois affirmations
d'absence fausses. Un instrument de non-absence qui sous-compte d'un facteur 15
rend des verdicts de PRESENCE tout aussi faux.

Contrat verrouille ici : le plafond peut rester pour borner l'ECHANTILLON, mais
le TOTAL doit toujours etre su, et tout chiffre derive d'un echantillon doit se
declarer comme tel.

Ecrit ROUGE avant le correctif.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))


# Lignes par fichier source dans la fixture. Choisi pour que l'echantillon borne
# par le plafond ne couvre qu'une FRACTION des sources, comme en conditions reelles.
SOURCES_PAR_FICHIER = 12


def _sweep():
    import forge_retrieval_sweep  # type: ignore

    return forge_retrieval_sweep


def _sources_attendues(n: int) -> int:
    return (n + SOURCES_PAR_FICHIER - 1) // SOURCES_PAR_FICHIER


def _base_au_dela_du_plafond(chemin: Path, n: int) -> None:
    """Fixture a la forme REELLE du schema, lu le 2026-09-12 :
        rag_chunks_fts(text, source, domain)   -- content= externe
        rag_fts(..., chunk_id UNINDEXED)       -- FTS5 autonome
    On fabrique volontairement PLUS de lignes que le plafond.

    ⚠️ Les sources sont SEQUENTIELLES (`i // SOURCES_PAR_FICHIER`), pas cycliques.
    Premiere version de cette fixture : `i % 137` — chaque source apparaissait des
    les 137 premieres lignes, donc l'echantillon tronque a 500 les voyait TOUTES
    et le test des `distinctes` PASSAIT sur le code defectueux. Un test vert qui
    ne reproduit pas le defaut ne garde rien : c'est la fixture qui mentait, pas
    le code qui etait sain. En sequentiel, l'echantillon ne couvre que le debut
    du corpus — ce qui est le cas reel (7747 chunks, 301 sources, 53 vues).
    """
    con = sqlite3.connect(chemin)
    con.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain)")
    con.execute(
        "CREATE VIRTUAL TABLE rag_fts USING fts5(text, source, domain, chunk_id UNINDEXED)"
    )
    for i in range(n):
        src = f"termetemoin/fichier_{i // SOURCES_PAR_FICHIER:04d}.md"
        con.execute(
            "INSERT INTO rag_chunks_fts(text, source, domain) VALUES (?,?,?)",
            (f"contenu termetemoin numero {i}", src, "veille"),
        )
        con.execute(
            "INSERT INTO rag_fts(text, source, domain, chunk_id) VALUES (?,?,?,?)",
            (f"contenu termetemoin numero {i}", src, "veille", f"c{i}"),
        )
    con.commit()
    con.close()


@pytest.fixture()
def base_gonflee(tmp_path, monkeypatch):
    mod = _sweep()
    chemin = tmp_path / "embeddings.db"
    _base_au_dela_du_plafond(chemin, mod.PLAFOND * 3 + 41)
    monkeypatch.setattr(mod, "_db", lambda: chemin, raising=True)
    return mod, chemin, mod.PLAFOND * 3 + 41


def _surface(surfaces, nom):
    for s in surfaces:
        if s.get("surface") == nom:
            return s
    raise AssertionError(f"surface {nom!r} absente : {[s.get('surface') for s in surfaces]}")


# ------------------------------------------------------------------ D1
@pytest.mark.parametrize("nom", ["rag_fts", "rag_chunks_fts"])
def test_une_surface_qui_plafonne_rend_quand_meme_son_TOTAL(base_gonflee, nom):
    mod, _, attendu = base_gonflee
    s = _surface(mod._fts("termetemoin"), nom)
    assert s.get("plafonne") is True, (
        f"{nom} devrait se declarer plafonne sur {attendu} lignes : {s}"
    )
    assert "n_total" in s, (
        f"{nom} plafonne SANS rendre de total : {s}. Un COUNT(*) sur un MATCH FTS5 "
        "est peu couteux — rien n'oblige a laisser le volume inconnu."
    )
    assert s["n_total"] == attendu, (
        f"total faux pour {nom} : {s.get('n_total')} au lieu de {attendu}"
    )
    assert s["n"] <= mod.PLAFOND, "l'echantillon doit rester borne par le plafond"


# ------------------------------------------------------------------ D2
def test_la_surface_sources_ne_tronque_plus_EN_SILENCE(base_gonflee):
    """Le defaut le plus couteux : cette branche applique le meme LIMIT que les
    autres mais ne pose aucun drapeau, donc rien dans la sortie ne signale que
    le chiffre est un plancher."""
    mod, _, attendu = base_gonflee
    s = _surface(mod._fts("termetemoin"), "sources")
    assert s.get("plafonne") is True, (
        f"la surface `sources` tronque a {mod.PLAFOND} sans le dire : {s}"
    )
    assert s.get("n_total") == attendu, (
        f"`sources` ne rend pas son total reel : {s.get('n_total')} != {attendu}"
    )


def test_le_nombre_de_sources_DISTINCTES_n_est_pas_un_plancher_deguise(base_gonflee):
    """`distinctes` etait calcule sur l'echantillon tronque puis affiche comme un
    total. Mesure reelle : 53 affichees pour 301 existantes."""
    mod, _, total = base_gonflee
    attendu = _sources_attendues(total)
    s = _surface(mod._fts("termetemoin"), "sources")
    assert s.get("distinctes") == attendu, (
        f"distinctes = {s.get('distinctes')} au lieu des {attendu} sources "
        "reellement presentes : le compte est fait sur l'echantillon tronque"
    )


# ------------------------------------------- contre-epreuve du detecteur
def test_sans_troncature_aucun_drapeau_de_plafond_n_est_leve(tmp_path, monkeypatch):
    """Symetrie : ne pas remplacer une sous-estimation par une alarme permanente.
    Sous le plafond, rien ne doit se declarer tronque, et le total doit egaler
    l'echantillon."""
    mod = _sweep()
    chemin = tmp_path / "petite.db"
    _base_au_dela_du_plafond(chemin, 12)
    monkeypatch.setattr(mod, "_db", lambda: chemin, raising=True)
    for nom in ("rag_fts", "rag_chunks_fts", "sources"):
        s = _surface(mod._fts("termetemoin"), nom)
        assert not s.get("plafonne"), f"{nom} se declare plafonne sur 12 lignes : {s}"
        assert s.get("n_total", s.get("n")) == s.get("n"), (
            f"{nom} : total et echantillon doivent coincider hors troncature — {s}"
        )
