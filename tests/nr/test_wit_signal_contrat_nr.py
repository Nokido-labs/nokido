# -*- coding: utf-8 -*-
"""NR — le contrat WIT du classifieur de signal, et les propriétés qu'il gèle.

__FORGE_COLOR__ = "immunitaire/guard : non-regression du contrat du premier composant wasm"

CE QUE CE CONTRAT FERME (2026-09-07). Trois remontées `ERR_TEST_FAIL` en un jour, trois
causes différentes, zéro test en échec — et un exécuteur rendant `FAILURE / timeout` sur
deux travaux réellement accomplis. Le contrat traduit en TYPES les quatre propriétés
qu'on en a tirées :

  1. `unknown` est un RÉSULTAT valide, jamais une erreur d'exécution ;
  2. `classification-error` dit « je n'ai pas pu m'exécuter », pas « c'est faux » ;
  3. le mot `verdict` est RÉSERVÉ au vérificateur — un premier jet nommait le type de
     retour `verdict-partiel`, refusé en revue : un nom suffit à recréer l'ambiguïté
     que le type venait de fermer ;
  4. `observation` ne porte PAS l'`intent`, donc le défaut mesuré
     `"ERR_TEST_FAIL" -> test-failure` est **structurellement inexprimable**.

Ce NR lit le fichier `.wit` comme un texte. Il ne compile rien : il empêche qu'une
révision ultérieure défasse en silence l'une de ces quatre propriétés.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIT = ROOT / "components" / "wit" / "nokido-signal.wit"


def _source() -> str:
    assert WIT.is_file(), "le contrat du classifieur a disparu : %s" % WIT
    return WIT.read_text(encoding="utf-8", errors="replace")


def _hors_commentaires() -> str:
    """Le contrat SANS ses commentaires.

    Indispensable : la docstring du .wit parle abondamment de `verdict` pour expliquer
    pourquoi ce mot est banni des types. Un test qui lirait tout se prononcerait sur
    la prose au lieu du contrat — piège déjà payé le 2026-09-07 sur `ci_local`."""
    return "\n".join(l for l in _source().splitlines()
                     if not l.lstrip().startswith("//"))


def test_le_monde_n_importe_rien() -> None:
    """Zéro capacité hôte : pas d'horloge donc pas de non-déterminisme, rien à exfiltrer.

    C'est ce qui rend le même binaire rejouable à l'identique d'un noeud à l'autre."""
    code = _hors_commentaires()
    i = code.find("world signal-classifier")
    assert i > 0, "le monde du composant a disparu"
    corps = code[i:]
    assert "export classify" in corps
    assert not re.search(r"^\s*import\s", corps, re.M), (
        "le classifieur ne doit recevoir AUCUNE capacite hote : un import ouvrirait "
        "une porte que le contrat promet fermee")


def test_unknown_est_un_resultat_pas_une_erreur() -> None:
    """« je ne peux pas conclure » n'est pas « je n'ai pas pu m'executer »."""
    code = _hors_commentaires()
    i, j = code.find("enum classification"), code.find("variant classification-error")
    assert i > 0 and j > 0, "les deux types du contrat doivent exister"
    enum_corps = code[i:code.find("}", i)]
    err_corps = code[j:code.find("}", j)]
    assert "unknown" in enum_corps, (
        "unknown doit etre une CLASSE valide : c'est la doctrine ILLISIBLE en type")
    assert "unknown" not in err_corps, (
        "unknown dans les erreurs ferait lire une abstention comme une panne")


def test_le_retour_est_un_result_typé() -> None:
    """Sans `result<>`, un repli interne redevient invisible a l'appelant."""
    code = _hors_commentaires()
    assert re.search(
        r"classify:\s*func\(.*?\)\s*->\s*result<\s*classification-result\s*,"
        r"\s*classification-error\s*>", code, re.S), (
        "la signature doit forcer l'appelant a traiter separement resultat et echec")


def test_le_mot_verdict_est_reserve_au_verificateur() -> None:
    """Gel LEXICAL : `verdict` ne nomme aucun type ni champ de ce contrat.

    `verdict-partiel` a ete refuse en revue — quelqu'un aurait ecrit
    `classify() -> TEST_FAILURE -> verdict = TEST_FAILURE`, et le contrat cense
    empecher la confusion l'aurait autorisee par son vocabulaire."""
    code = _hors_commentaires()
    assert "verdict" not in code, (
        "le mot verdict appartient a la sortie du verificateur, pas a la "
        "classification : trouve dans le contrat hors commentaires")
    assert "classification-result" in code, "le type de retour doit porter son vrai nom"


def test_l_observation_ne_porte_pas_l_etiquette() -> None:
    """La propriete la plus forte du contrat est une ABSENCE.

    Le classifieur ne recoit jamais l'`intent` du message, donc le defaut mesure
    `"ERR_TEST_FAIL" -> test-failure` ne peut pas se produire : il est
    inexprimable, pas seulement interdit."""
    code = _hors_commentaires()
    i = code.find("record observation")
    assert i > 0, "le type d'entree a disparu"
    corps = code[i:code.find("}", i)]
    for interdit in ("intent", "label", "etiquette", "claim"):
        assert interdit not in corps, (
            "`%s` dans l'observation redonnerait au classifieur de quoi conclure "
            "depuis une etiquette" % interdit)
    assert "option<string>" in corps, (
        "none (rien observe) et some(vide) sont DEUX etats : la provenance doit "
        "survivre au passage par M2M puis A2A")


def test_la_raison_est_obligatoire() -> None:
    """Un echec qui ne dit pas son motif se re-instruit a chaque fois."""
    code = _hors_commentaires()
    i = code.find("record classification-result")
    corps = code[i:code.find("}", i)]
    assert "raison: string" in corps, (
        "raison doit etre un string NON optionnel : sur unknown, il nomme ce qu'on "
        "n'a pas pu voir")


def test_les_classes_restent_bornees() -> None:
    """Pas de taxonomie « au cas ou » : chaque classe vient d'une observation reelle."""
    code = _hors_commentaires()
    i = code.find("enum classification")
    corps = code[i:code.find("}", i)]
    classes = {c.strip().rstrip(",") for c in corps.splitlines()[1:] if c.strip()}
    classes = {c for c in classes if c and not c.startswith("//")}
    assert classes == {"transport-timeout", "ci-failure-claim", "test-failure",
                       "interrupted", "not-run", "unknown"}, (
        "toute classe ajoutee doit correspondre a une observation datee : %s" % classes)
