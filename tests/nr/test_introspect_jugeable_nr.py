"""NR — la chaine qui rend la REUTILISATION mesurable, et son piege de budget.

Trois niveaux se mesurent separement, et les confondre est le defaut que ces
tests interdisent :

    EXPOSITION     `introspect` est-il appele ?            -> consultations
    PERTINENCE     propose-t-il une piste exploitable ?    -> fichiers_proposes
    REUTILISATION  l'agent ecrit-il DANS cette piste ?     -> reutilisations

MESURE DU 2026-08-31 QUI A MOTIVE CE FICHIER. Le hub rendait `editions_jugeables
= 0` sur 18 editions reelles, ce qui se lit « personne ne reutilise ». La cause
n'etait ni le matcher lexical ni le journal : `enquetes_anterieures` etait
ABSENTE de l'ordre de troncature, donc une section intronquable et de taille
variable affamait `procedures_connues` — que le commentaire du rogneur pretendait
pourtant proteger en dernier. Et `noter_consultation` lisait cette liste videe :
la MESURE heritait d'une decision d'AFFICHAGE. Meme question, meme budget 500,
5 procedures rendues a un appel et 0 a un autre.

Le contrat verrouille ici : le budget peut rogner ce qu'on MONTRE, jamais ce
qu'on COMPTE, et une liste vide doit toujours dire de quel etat elle releve
(rognee / sans resultat / journal absent).

HERMETIQUE : journal, index d'enquetes et trace dans `tmp_path`. Aucun test ne
depend du depot ni de l'historique reel.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# `_voisinage` importe ses organes en TOP-LEVEL : pour que le monkeypatch touche
# LE MEME objet module, `app/` doit etre sur le chemin ici aussi. Sans cela le
# test mesure un second module, et un `raises` ne voit jamais l'exception.
if str(_ROOT / "app") not in sys.path:
    sys.path.insert(0, str(_ROOT / "app"))

from app import forge_callgraph_jit as jit  # noqa: E402
from app import forge_introspect as intro  # noqa: E402

# Une procedure historique PLAUSIBLE : meme forme que celles du journal reel.
_ENTREE = {
    "commit": "abc123def456",
    "date": "2026-08-22",
    "symptome": "trois chemins d erreur muets rendus audibles",
    "scope": "qa",
    "jetons": ["chemin", "erreur", "muet", "audibles"],
    "procedure": {"fichiers": ["tools/forge_exemple.py"], "n_fichiers": 1,
                  "tests_dans_le_commit": []},
    "reutilisable": False,
    "etat": "CONSTATE",
}
_QUESTION = "chemin d erreur muet"


@pytest.fixture()
def banc(tmp_path, monkeypatch):
    """Depot vide, scan d'imports neutralise, trace isolee.

    Le scan reel coute 2,26 s pour 556 modules : le payer par test avait fait
    passer la suite de 2 s a 38 s, et un test lent finit par ne plus etre lance.
    """
    (tmp_path / "pkg").mkdir()
    monkeypatch.setattr(jit, "ROOT", tmp_path)
    monkeypatch.setattr(jit, "_SCAN_ROOTS", ("pkg",))
    jit._DEP_CACHE.clear()
    # Trace ISOLEE : sans cela les tests ecriraient dans la trace REELLE du
    # depot et fausseraient le taux qui decidera du passage au refus.
    monkeypatch.setattr(intro, "TRACE", tmp_path / "trace.json")
    import forge_panorama_builder as _P
    monkeypatch.setattr(_P, "scan_forge_modules", lambda *a, **k: {})
    return tmp_path


def _oplog(chemin: Path, entrees: list) -> Path:
    chemin.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entrees),
                      encoding="utf-8")
    return chemin


def _intro(banc, question=_QUESTION, **kw):
    kw.setdefault("index_enquetes", banc / "absent.json")
    kw.setdefault("oplog", banc / "oplog.jsonl")
    return intro.introspect(question, jit=jit, **kw)


# ── niveau 2 : la PERTINENCE, et ce que le budget a le droit d'y toucher ─────
def test_une_procedure_historique_propose_son_fichier(banc):
    _oplog(banc / "oplog.jsonl", [_ENTREE])
    r = _intro(banc)
    assert r["procedures_connues"], "la procedure historique n'est pas remontee"
    assert r["procedures_connues"][0]["fichiers"] == ["tools/forge_exemple.py"]
    assert r["fichiers_procedures"] == ["tools/forge_exemple.py"]


def test_budget_serre_efface_l_AFFICHAGE_mais_pas_le_PERIMETRE(banc):
    """Le defaut mesure : le rogneur videra la liste, jamais le perimetre."""
    _oplog(banc / "oplog.jsonl", [_ENTREE])
    r = _intro(banc, budget_tokens=1)
    assert r["procedures_connues"] == []
    assert r["budget"]["tronque"] is True
    assert r["budget"]["retire"].get("procedures_connues") == 1
    assert r["fichiers_procedures"] == ["tools/forge_exemple.py"]


def test_le_rogneur_NOMME_la_section_qu_il_a_videe(banc):
    """`[]` par manque de place et `[]` faute de resultat sont deux etats."""
    _oplog(banc / "oplog.jsonl", [_ENTREE])
    plein = _intro(banc, budget_tokens=4000)
    assert plein["budget"]["tronque"] is False
    assert plein["budget"]["retire"] == {}


def test_journal_absent_n_est_ni_vide_ni_rogne(banc):
    """Troisieme etat : on n'a pas pu regarder. Le dire, sinon « aucune
    procedure connue » se lit comme « aucune solution n'existe »."""
    r = _intro(banc, oplog=banc / "journal_qui_n_existe_pas.jsonl")
    assert r["procedures_connues"] == []
    assert r["fichiers_procedures"] == []
    assert r["budget"]["retire"] == {}
    raisons = " ".join(x["raison"] for x in r["non_consulte"])
    assert "journal absent" in raisons


def test_les_enquetes_tombent_AVANT_les_procedures(banc, monkeypatch):
    """LA cause racine : une section INTRONQUABLE affamait les procedures.

    Sans cet ordre, `enquetes_anterieures` gonfle librement et la procedure —
    la seule REPONSE de la reponse — saute la premiere. Mesure du 2026-08-31 :
    5 procedures rendues a un appel et 0 a un autre, meme question, meme budget.

    La section est INJECTEE : ce test porte sur l'ordre de sacrifice, pas sur le
    lecteur d'index. Fabriquer un index conforme a `forge_symptom_index` ferait
    dependre ce verrou du format d'un autre organe — et un index mal forme
    rendrait une liste vide, donc un test qui passe sans rien mesurer.
    """
    _oplog(banc / "oplog.jsonl", [_ENTREE])
    gros = [{"terme": "muet", "session": "aaaa1111", "date": "2026-08-01",
             "pieges": [{"ligne": n, "extrait": "x" * 200, "jetons": []}
                        for n in range(6)]} for _ in range(3)]
    monkeypatch.setattr(intro, "_enquetes", lambda q, nc, p: list(gros))
    r = _intro(banc, budget_tokens=300)
    assert r["budget"]["tronque"] is True, "le banc ne declenche aucun rognage"
    # Les enquetes ont ete sacrifiees ; la procedure a survecu.
    assert r["budget"]["retire"].get("enquetes_anterieures") == 3
    assert "procedures_connues" not in r["budget"]["retire"]
    assert r["procedures_connues"], "la procedure a saute avant les enquetes"


# ── niveau 3 : la REUTILISATION, avec son denominateur honnete ───────────────
def test_ecrire_dans_le_fichier_propose_rend_l_edition_JUGEABLE(banc):
    _oplog(banc / "oplog.jsonl", [_ENTREE])
    r = _intro(banc)
    intro.noter_consultation("TEST", _QUESTION, r)
    intro.noter_edition("TEST", True, "tools/forge_exemple.py")
    t = intro.taux_consultation()
    assert t["editions_jugeables"] == 1
    assert t["reutilisations"] == 1
    assert t["divergences"] == 0
    assert t["taux_reutilisation_pct"] == 100.0


def test_ecrire_AILLEURS_est_une_divergence(banc):
    _oplog(banc / "oplog.jsonl", [_ENTREE])
    r = _intro(banc)
    intro.noter_consultation("TEST", _QUESTION, r)
    intro.noter_edition("TEST", True, "app/forge_autre_chose.py")
    t = intro.taux_consultation()
    assert t["editions_jugeables"] == 1
    assert t["divergences"] == 1
    assert t["reutilisations"] == 0


def test_consultation_SANS_proposition_reste_NON_JUGEABLE(banc):
    """Le cas a ne JAMAIS transformer en divergence : sans piste proposee,
    l'edition suivante ne peut etre ni un suivi ni un ecart."""
    r = _intro(banc, oplog=banc / "journal_qui_n_existe_pas.jsonl")
    intro.noter_consultation("TEST", _QUESTION, r)
    intro.noter_edition("TEST", True, "app/n_importe_quoi.py")
    t = intro.taux_consultation()
    assert t["editions"] == 1
    assert t["avec_consultation"] == 1
    assert t["editions_jugeables"] == 0
    assert t["divergences"] == 0
    assert t["reutilisations"] == 0
    # Le taux n'est PAS 0 % : il n'existe pas.
    assert t["taux_reutilisation_pct"] is None


def test_un_budget_serre_ne_fabrique_PAS_de_fausse_divergence(banc):
    """LA regression a interdire.

    L'agent ecrit dans le fichier que la procedure designait ; seul le budget
    l'empechait de le VOIR. Compter une divergence ici accuserait l'agent d'un
    ecart cause par le rogneur — et un indicateur qui accuse a faux se fait
    desarmer.
    """
    _oplog(banc / "oplog.jsonl", [_ENTREE])
    r = _intro(banc, budget_tokens=1)
    assert r["procedures_connues"] == []      # invisible a l'affichage
    intro.noter_consultation("TEST", _QUESTION, r)
    intro.noter_edition("TEST", True, "tools/forge_exemple.py")
    t = intro.taux_consultation()
    assert t["reutilisations"] == 1
    assert t["divergences"] == 0


def test_le_chemin_absolu_de_l_agent_matche_le_fichier_relatif_propose(banc):
    """Le hub passe un chemin ABSOLU ; le journal porte des chemins relatifs.
    Sans rapprochement, toute edition reelle serait comptee divergente."""
    _oplog(banc / "oplog.jsonl", [_ENTREE])
    r = _intro(banc)
    intro.noter_consultation("TEST", _QUESTION, r)
    intro.noter_edition("TEST", True,
                        r"C:\Users\x\Script python IA\Nokido\tools\forge_exemple.py")
    t = intro.taux_consultation()
    assert t["reutilisations"] == 1, "chemin absolu non rapproche du relatif"


# ── honnetete du voisinage : un vide sans motif se lit « rien de proche » ────
def test_voisinage_sans_graine_DIT_pourquoi(banc):
    r = _intro(banc, question="probleme de latence chez le voisin")
    assert r["voisinage_structurel"] == {}
    raisons = " ".join(x["raison"] for x in r["non_consulte"])
    assert "pas de graine de depart" in raisons
