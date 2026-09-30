"""NR — un fait établi tôt survit à N compactions successives.

## L'invariant

    Si une information est portée par HEAD_N,
    et qu'aucun evenement ulterieur ne l'invalide,
    alors elle doit rester recuperable dans HEAD_N+k.

## Pourquoi ce test n'existait pas, et pourquoi il manquait

Le dépôt distingue déjà `EXISTE` / `CAPTURABLE` / `RESTAURABLE`. Il manquait le
dernier cran, qui est le seul à décrire ce qui compte vraiment ici :

    EXISTE  !=  CAPTURABLE  !=  RESTAURABLE  !=  RECUPERABLE APRES N COMPACTIONS

Avant le 2026-09-19, un résumé était `f(derniers tours)`. Un fait établi tôt et
**jamais re-mentionné** disparaissait donc dès la deuxième compaction — en
silence, puisqu'un résumé reparti de zéro se lit comme un résumé normal.

## Le cas choisi est le pire, volontairement

Le fait témoin apparaît **une seule fois**, en C0, et n'est **jamais répété**.
C'est exactement la configuration qui cassait l'ancien système : tout test où
l'information est re-mentionnée passerait aussi sur du code défaillant.

## Ce que ce test prouve, et ce qu'il ne prouve pas

Il exerce le chemin **extractif**, qui est déterministe. Il prouve donc que la
MÉCANIQUE d'héritage tient sur N compactions réelles, écriture en base comprise.

Il ne prouve PAS qu'un LLM obéira à l'instruction de conservation : ça ne se
teste pas ici. Ce qui est vérifié pour le chemin LLM, c'est que l'état hérité
lui est bien PRÉSENTÉ — cf. `test_precompact_herite_de_l_etat_nr`.
"""
from __future__ import annotations

import importlib.util as _u
import json
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

SOURCE = RACINE / "tools" / "claude_precompact.py"

FAIT_TEMOIN = "DECISION_C0_JAMAIS_REPETEE : le videur resout le ring par requete"
N_COMPACTIONS = 4


def _module():
    spec = _u.spec_from_file_location("cpc_cont_nr", SOURCE)
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _base_jetable(tmp_path: Path) -> Path:
    db = tmp_path / "rag.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, source TEXT, "
                 "text TEXT, domain TEXT, ingested_at TEXT)")
    conn.commit()
    conn.close()
    return db


def _bruit(n: int) -> list[dict]:
    """Des tours qui ne mentionnent JAMAIS le fait témoin."""
    return [
        {"role": "user", "content": "question sans rapport numero %d" % n},
        {"role": "assistant",
         "content": "corrige un detail dans app/forge_bruit_%d.py sans lien" % n},
    ]


def test_le_fait_survit_a_N_compactions_successives(tmp_path, monkeypatch):
    m = _module()
    db = _base_jetable(tmp_path)
    monkeypatch.setattr(m, "DB", db)
    monkeypatch.setattr(m, "SUMMARY", tmp_path / "CONTEXT_SUMMARY.md")
    sid = "sid-continuite"

    # --- C0 : le fait est etabli UNE fois -------------------------------
    head = m._extractive_fallback(_bruit(0), sid, None)
    head["decisions"] = [FAIT_TEMOIN]
    m._store_summary(head, sid)

    # Garde de morsure : sans lui, une base muette ferait passer la suite.
    relu = m._dernier_resume(sid)
    assert relu is not None, "la base jetable n'a rien enregistre : le test ne mesure rien"
    assert FAIT_TEMOIN in (relu.get("decisions") or [])

    # --- C1..CN : QUE du bruit, le fait n'est jamais re-mentionne -------
    for i in range(1, N_COMPACTIONS + 1):
        parent = m._dernier_resume(sid)
        assert parent is not None, "chaine rompue a la compaction %d" % i
        suivant = m._extractive_fallback(_bruit(i), sid, parent)
        m._store_summary(suivant, sid)

    final = m._dernier_resume(sid)
    assert final is not None
    decisions = final.get("decisions") or []
    assert FAIT_TEMOIN in decisions, (
        "le fait etabli en C0 a DISPARU apres %d compactions. C'est la perte "
        "silencieuse que ce NR existe pour empecher : rien dans le resume final "
        "n'indiquerait qu'une information a ete perdue. decisions=%r"
        % (N_COMPACTIONS, decisions))


def test_le_nouveau_est_AUSSI_present(tmp_path, monkeypatch):
    """Contrôle négatif : un accumulateur qui ne ferait que recopier le parent
    passerait le test precedent sans rien valoir."""
    m = _module()
    db = _base_jetable(tmp_path)
    monkeypatch.setattr(m, "DB", db)
    monkeypatch.setattr(m, "SUMMARY", tmp_path / "CONTEXT_SUMMARY.md")
    sid = "sid-nouveau"

    head = m._extractive_fallback(_bruit(0), sid, None)
    head["decisions"] = [FAIT_TEMOIN]
    m._store_summary(head, sid)

    parent = m._dernier_resume(sid)
    suivant = m._extractive_fallback(_bruit(7), sid, parent)

    fichiers = suivant.get("files_modified") or []
    assert any("forge_bruit_7" in f for f in fichiers), (
        "le delta n'est pas integre : l'heritage ne doit pas etre une simple copie")
    assert FAIT_TEMOIN in (suivant.get("decisions") or []), "et l'herite doit rester"


def test_l_herite_vient_EN_TETE_pour_survivre_aux_troncatures():
    """Les listes sont bornées en aval ; ce qui est ancien doit passer devant."""
    m = _module()
    parent = {"compaction_seq": 1, "decisions": ["ANCIEN_1", "ANCIEN_2"]}
    neuf = {"decisions": ["NOUVEAU_1"]}
    fusion = m._fusionner_etat(parent, dict(neuf))
    assert fusion["decisions"][:2] == ["ANCIEN_1", "ANCIEN_2"], (
        "l'herite doit preceder le neuf : une troncature ne doit pas manger "
        "ce qui a survecu a plusieurs compactions")
    assert "NOUVEAU_1" in fusion["decisions"]


def test_aucun_doublon_ne_s_accumule():
    """Sans dédoublonnage, N compactions feraient enfler la liste sans fin."""
    m = _module()
    parent = {"decisions": ["X"], "files_modified": ["a.py"]}
    fusion = m._fusionner_etat(parent, {"decisions": ["X"], "files_modified": ["a.py"]})
    assert fusion["decisions"] == ["X"]
    assert fusion["files_modified"] == ["a.py"]


def test_LA_MORSURE_est_prouvee_le_fait_disparait_sans_heritage(tmp_path, monkeypatch):
    """Sans cette preuve, le test principal pourrait être vert par construction.

    On rejoue exactement la meme chaine, mais en NE passant PAS le parent —
    c'est-a-dire le comportement d'AVANT le 2026-09-19. Le fait temoin doit
    alors disparaitre. S'il survivait quand meme, c'est que le test principal
    mesure autre chose que l'heritage.
    """
    m = _module()
    db = _base_jetable(tmp_path)
    monkeypatch.setattr(m, "DB", db)
    monkeypatch.setattr(m, "SUMMARY", tmp_path / "CONTEXT_SUMMARY.md")
    sid = "sid-morsure"

    head = m._extractive_fallback(_bruit(0), sid, None)
    head["decisions"] = [FAIT_TEMOIN]
    m._store_summary(head, sid)

    for i in range(1, N_COMPACTIONS + 1):
        # parent DELIBEREMENT ignore : l'ancien comportement
        suivant = m._extractive_fallback(_bruit(i), sid, None)
        m._store_summary(suivant, sid)

    final = m._dernier_resume(sid)
    assert final is not None
    assert FAIT_TEMOIN not in (final.get("decisions") or []), (
        "le fait survit MEME sans heritage : le test principal ne prouve donc "
        "pas ce qu'il annonce — il faut revoir le temoin ou la chaine")


def test_le_cout_se_STABILISE_et_ne_croit_pas_indefiniment(tmp_path, monkeypatch):
    """Dette MESURÉE le 2026-09-19, puis bornée.

    Avant la borne, `decisions` et `files_modified` croissaient linéairement
    (~+145 c d'état par compaction, sans plafond) là où `key_context` se
    stabilisait, parce que lui en avait une. Extrapolé, l'état dépassait
    `MAX_PAYLOAD_CHARS` vers la 80e compaction.

    On vérifie ici les DEUX propriétés à la fois, car l'une sans l'autre ne vaut
    rien : le coût plafonne, ET le fait le plus ancien survit quand même.
    """
    m = _module()
    db = _base_jetable(tmp_path)
    monkeypatch.setattr(m, "DB", db)
    monkeypatch.setattr(m, "SUMMARY", tmp_path / "S.md")
    sid = "sid-cout"

    head = m._extractive_fallback(_bruit(0), sid, None)
    head["decisions"] = [FAIT_TEMOIN]
    m._store_summary(head, sid)

    tailles = {}
    for i in range(1, 46):
        parent = m._dernier_resume(sid)
        s = m._extractive_fallback(_bruit(i), sid, parent)
        m._store_summary(s, sid)
        if i in (30, 45):
            etat = {k: s.get(k) for k in ("decisions", "open_bugs",
                                          "files_modified", "key_context") if s.get(k)}
            tailles[i] = len(json.dumps(etat, ensure_ascii=False))

    assert tailles[45] == tailles[30], (
        "l'etat croit encore entre la 30e et la 45e compaction (%d -> %d) : la "
        "borne ne stabilise pas" % (tailles[30], tailles[45]))
    assert tailles[45] < m.MAX_PAYLOAD_CHARS // 3, (
        "l'etat herite occupe %d c, soit plus du tiers du payload (%d) : la "
        "continuite couterait plus qu'elle ne rapporte"
        % (tailles[45], m.MAX_PAYLOAD_CHARS))

    final = m._dernier_resume(sid)
    assert FAIT_TEMOIN in (final.get("decisions") or []), (
        "la borne a mange le fait le plus ancien : elle doit garder les DEUX "
        "bouts, les plus etablis et les plus recents")


def test_la_troncature_DIT_ce_qu_elle_ecarte():
    """Une borne muette se lit comme une liste complète — défaut `text[:3000]`."""
    m = _module()
    parent = {"decisions": ["D%02d" % i for i in range(40)]}
    fusion = m._fusionner_etat(parent, {"decisions": ["NEUF"]})
    assert "_tronque" in fusion, (
        "la troncature ne dit pas combien elle ecarte : dans l'artefact, pas "
        "seulement dans un log qui disparait")
    assert fusion["_tronque"].get("decisions", 0) > 0
    # les deux bouts survivent
    assert "D00" in fusion["decisions"], "le plus ancien doit survivre"
    assert "NEUF" in fusion["decisions"], "le plus recent doit survivre"


def test_sans_parent_la_fusion_est_neutre():
    m = _module()
    neuf = {"decisions": ["SEUL"]}
    assert m._fusionner_etat(None, dict(neuf))["decisions"] == ["SEUL"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
