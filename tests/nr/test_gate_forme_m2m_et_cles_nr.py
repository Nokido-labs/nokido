"""NR — le capability-gate doit voir DEUX fautes qu'il ne voyait pas.

Mesure du 2026-09-17, en session. Deux formes fautives sont passées sans le
moindre rappel, alors que la doctrine les proscrit toutes les deux :

1. UN MESSAGE M2M ÉCRIT COMME UNE LETTRE. Cinq envois de 601, 860, 1388, 1456
   et 1544 caractères de substance INLINE, quand le contrat est
   `{intent, pointer_ref}` vers le SSoT. Le gate ne pouvait pas le voir : son
   `main()` sort immédiatement si `action` n'est pas l'une de
   ("shell", "python", "trusted_script", "run_job", ""). Or un message M2M a
   `action="notify"`. La classe d'appel entière était hors du champ du garde —
   même famille que la mesure du 2026-09-07 sur `run_job{script:...}`, où deux
   classes d'appel rendaient zéro caractère extrait.

2. UNE CLÉ DE PARAMÈTRE QUI N'EXISTE PAS. `run action=python command="..."` est
   accepté par le hub, qui IGNORE `command` et exécute du vide — sortie vide,
   aucune erreur, indistinguable d'un script sans sortie. Le gate lit pourtant
   `command` dans `_texte_commande` et scanne son CONTENU comme s'il allait être
   exécuté. Il valide le texte, jamais le NOM des clés. Même piège que `args=`
   au lieu de `script_args=` (mesuré le 2026-08-31) : là, une règle LEXICALE
   matche le mot « args » n'importe où — y compris dans un script qui parle
   d'args, ce qui en fait un garde qui crie à faux.

Ce NR verrouille le comportement, pas l'implémentation : il interroge la
fonction PURE, puis le chemin réel par `main()` sur stdin/stdout.
"""
from __future__ import annotations

import io
import json
import os
import sys

import pytest

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (RACINE, os.path.join(RACINE, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

gate = pytest.importorskip("hook_capability_gate")


# ── 1. le message M2M écrit comme une lettre ────────────────────────────────

def test_un_message_m2m_en_lettre_est_signale():
    """Un payload massif SANS pointer_ref est une lettre : le gate doit le dire."""
    lettre = json.dumps({"intent": "REVIEW_FINDING", "constat": "mot " * 300})
    touche, msg = gate.verdict_forme(
        "mcp__laforge-sovereign-hub__hub",
        {"action": "notify", "to": "gemini", "message": lettre})
    assert touche, (
        "un message M2M de %d caracteres sans pointer_ref n'a declenche AUCUN "
        "rappel — le contrat est {intent, pointer_ref} vers le SSoT" % len(lettre))
    assert "pointer_ref" in msg


def test_un_message_m2m_avec_pointeur_passe_en_silence():
    """Contrôle négatif : sans lui, un garde qui crie TOUJOURS passerait le test."""
    pointeur = json.dumps({"intent": "FACT_PROPOSED",
                           "pointer_ref": "bb:architecture_rules/accord_x",
                           "text": "Accord propose, valide ou amende."})
    touche, _ = gate.verdict_forme(
        "mcp__laforge-sovereign-hub__hub",
        {"action": "notify", "to": "gemini", "message": pointeur})
    assert not touche, "la forme CORRECTE ne doit produire aucun rappel"


def test_un_long_payload_qui_porte_un_pointeur_est_tolere():
    """La règle vise la LETTRE, pas le VOLUME : des données pointées passent."""
    gros = json.dumps({"intent": "REVIEW_FINDING", "pointer_ref": "bb:zone/cle",
                       "mesures": list(range(400))})
    touche, _ = gate.verdict_forme(
        "mcp__laforge-sovereign-hub__hub",
        {"action": "notify", "to": "gemini", "message": gros})
    assert not touche, (
        "un payload volumineux MAIS pointe ne doit pas etre signale — sinon le "
        "garde frappe les donnees et se fait desarmer")


# ── 2. la clé de paramètre qui n'existe pas ─────────────────────────────────

def test_une_cle_inexistante_est_signalee_et_nomme_la_bonne():
    """`command=` sur un `run` : ignoré en silence par le hub."""
    touche, msg = gate.verdict_forme("run", {"action": "python", "command": "print(1)"})
    assert touche, (
        "`command` n'est pas un parametre de `run` : il est IGNORE en silence et "
        "le script part vide — le gate doit le dire AVANT l'appel")
    assert "code" in msg, "le rappel doit NOMMER la cle acceptee, pas seulement refuser"


def test_la_forme_correcte_ne_declenche_rien():
    touche, _ = gate.verdict_forme("run", {"action": "python", "code": "print(1)"})
    assert not touche


def test_une_cle_inconnue_n_est_pas_confondue_avec_une_mention_dans_le_texte():
    """Le contrôle porte sur les CLÉS, jamais sur le texte — anti-faux-positif.

    Un script qui PARLE de `command` ou d'`args` ne fait rien de fautif. C'est
    précisément ce qui rend la règle lexicale actuelle peu fiable : elle a
    matché un script de test le 2026-09-17.
    """
    touche, _ = gate.verdict_forme(
        "run", {"action": "python", "code": "cfg = {'command': 'x', 'args': []}"})
    assert not touche, (
        "une MENTION de `command`/`args` dans le code n'est pas une cle fautive")


# ── 3. le chemin RÉEL : main() sur stdin/stdout ─────────────────────────────

def _passer_par_main(evenement: dict, capsys) -> str:
    """Emprunte le point d'entrée réel du hook, pas seulement la fonction."""
    stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(evenement))
    try:
        rc = gate.main()
    finally:
        sys.stdin = stdin
    assert rc == 0, "un hook de nudge ne doit JAMAIS sortir non nul"
    cap = capsys.readouterr()
    return cap.out + cap.err


def test_le_point_d_entree_remonte_le_rappel_m2m(capsys):
    lettre = json.dumps({"intent": "REVIEW_FINDING", "constat": "mot " * 300})
    sortie = _passer_par_main({
        "tool_name": "mcp__laforge-sovereign-hub__hub",
        "tool_input": {"action": "notify", "to": "gemini", "message": lettre}}, capsys)
    assert "pointer_ref" in sortie, (
        "le rappel n'atteint pas l'agent par le chemin reel — un nudge qui "
        "n'arrive pas n'existe pas")
