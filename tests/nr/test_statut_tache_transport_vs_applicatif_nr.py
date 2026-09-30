"""NR — le statut d'une tache ne se deduit pas du retour d'une reponse.

DEFAUT MESURE le 2026-09-08 dans sandbox/tasks.db :

    status         done      35
    status         failed     1

...alors que QUATRE des « done » portent un resultat
`{"intent": "ERR_INTERNAL", "status_code": "FAILURE"}`. Le compte par statut range
donc quatre echecs du cote sain, et un tableau de bord qui lit ce champ annonce
35 reussites pour 31.

CAUSE. `app/forge_mcp_registry` ecrit `UPDATE tasks SET status='done'` des qu'une
reponse revient, SANS jamais regarder son contenu. C'est la confusion
`TRANSPORT != APPLICATIF` de la constitution semantique : « le message est
revenu » n'est pas « le travail a reussi ». Meme famille que les trois
`ERR_TEST_FAIL` du 2026-09-07 ou l'etiquette decrivait le transport, et que
`REQUESTED != ACCEPTED != ACHIEVED`.

Noter que la table voisine `agent_tasks` fait DEJA correctement la distinction :
ses lecteurs croisent `forge_verdict='approved' AND status='done'`. C'est `tasks`
qui n'a que le statut de transport.

CE QUE CE NR EXIGE — et surtout ce qu'il n'exige PAS. Le classement se fait par
liste BLANCHE : n'est ECHEC que ce qui est PROUVE en echec. Un resultat en texte
libre (le cas majoritaire : les reponses d'un fournisseur cloud) reste INCONNU et
ne doit jamais devenir un echec. Poser l'inverse fabriquerait des pannes fictives,
exactement le defaut symetrique consigne le 2026-07-30 (24 pouls sans pid lus
comme 24 pannes).

La liste des intents d'echec vient du CATALOGUE `config/m2m_intents.json`, source
unique, et jamais d'une liste ecrite en dur ici : un intent d'erreur ajoute au
catalogue doit etre reconnu sans toucher a ce fichier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
CATALOGUE = RACINE / "config" / "m2m_intents.json"


def _module():
    import sys

    for chemin in (RACINE, RACINE / "app"):
        if str(chemin) not in sys.path:
            sys.path.insert(0, str(chemin))
    return pytest.importorskip("app.forge_m2m_protocol")


def _intents_erreur() -> set[str]:
    """Les codes de la categorie `error`, lus dans le catalogue lui-meme."""
    brut = json.loads(CATALOGUE.read_text(encoding="utf-8"))["intents"]
    codes: set[str] = set()
    for cle, valeur in brut.items():
        if isinstance(valeur, dict) and "error" in (cle, str(valeur.get("category"))):
            codes.update(valeur.keys() if cle == "error" else {cle})
        elif isinstance(valeur, dict) and str(valeur.get("category")) == "error":
            codes.add(cle)
    return {c for c in codes if isinstance(c, str) and c.startswith("ERR_")}


def test_le_catalogue_porte_bien_des_intents_d_erreur():
    """Sans cette source, le contrat suivant ne prouverait rien."""
    codes = _intents_erreur()
    assert codes, "aucun intent d'erreur lu dans le catalogue -- source introuvable"
    assert "ERR_INTERNAL" in codes, f"ERR_INTERNAL absent du catalogue : {sorted(codes)}"


def test_un_intent_d_erreur_donne_echec():
    """Le cas exact mesure dans tasks.db."""
    m = _module()
    for code in sorted(_intents_erreur()):
        charge = json.dumps({"intent": code, "status_code": "FAILURE"})
        assert m.statut_depuis_resultat(charge) == "echec", (
            f"{code} doit donner un echec, pas un statut de transport"
        )


def test_un_status_code_d_echec_suffit_sans_intent_connu():
    """Le code applicatif fait foi meme si l'intent n'est pas au catalogue."""
    m = _module()
    charge = json.dumps({"intent": "INTENT_INCONNU_DU_CATALOGUE", "status_code": "FAILURE"})
    assert m.statut_depuis_resultat(charge) == "echec"


def test_un_succes_reste_un_succes():
    m = _module()
    charge = json.dumps({"intent": "OK_DONE", "status_code": "SUCCESS"})
    assert m.statut_depuis_resultat(charge) == "succes"


def test_un_texte_libre_est_INCONNU_jamais_un_echec():
    """Liste BLANCHE. Le cas majoritaire ne doit pas devenir une panne fictive."""
    m = _module()
    for brut in (
        "[cohere] Voici le code genere pour le MVP du TUI multi-CLI : ...",
        "",
        "   ",
        "{ceci n'est pas du json",
        "[groq] [FIREWALL] envoi cloud bloque : reformuler ou router en local.",
    ):
        assert m.statut_depuis_resultat(brut) == "inconnu", (
            f"un resultat non decidable doit rester INCONNU, recu : {brut[:40]!r}"
        )


def test_un_json_sans_marqueur_est_INCONNU():
    m = _module()
    charge = json.dumps({"note": "travail fait", "duree_s": 12})
    assert m.statut_depuis_resultat(charge) == "inconnu"


def test_aucun_autre_verdict_que_les_trois_etats():
    """Trois etats, jamais deux -- et jamais quatre non plus."""
    m = _module()
    vus = {
        m.statut_depuis_resultat(json.dumps({"intent": "ERR_TIMEOUT", "status_code": "FAILURE"})),
        m.statut_depuis_resultat(json.dumps({"intent": "OK_DONE", "status_code": "SUCCESS"})),
        m.statut_depuis_resultat("texte libre"),
        m.statut_depuis_resultat(None),
    }
    assert vus <= {"echec", "succes", "inconnu"}, f"verdicts hors contrat : {vus}"


def test_la_liste_n_est_pas_ecrite_en_dur_dans_le_module():
    """Un intent d'erreur ajoute au catalogue doit etre reconnu sans toucher au code.

    On regarde le CODE, pas la prose. Premiere version de ce test : elle cherchait
    le code dans la SOURCE BRUTE et accusait `ERR_INTERNAL` cite dans un
    commentaire de documentation -- une MENTION prise pour un USAGE, exactement le
    defaut paye trois fois le 2026-09-08 (les « 165 fichiers au vieux chemin » qui
    etaient des docstrings, `__file__` compte comme nom libre, un instrument
    lisant son propre vocabulaire). Le contrat vise les chaines litterales
    EVALUEES : l'AST les distingue des commentaires, et les docstrings sont
    retirees explicitement.
    """
    import ast

    m = _module()
    arbre = ast.parse(
        (RACINE / "app" / "forge_m2m_protocol.py").read_text(
            encoding="utf-8", errors="replace"
        )
    )
    docstrings = set()
    for noeud in ast.walk(arbre):
        if isinstance(
            noeud, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            doc = ast.get_docstring(noeud)
            if doc:
                docstrings.add(doc)

    litteraux = {
        n.value
        for n in ast.walk(arbre)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value not in docstrings
    }
    codes = set(_intents_erreur())
    en_dur = sorted(codes & litteraux)
    assert not en_dur, (
        "codes d'erreur ecrits en dur dans le CODE du module au lieu d'etre lus "
        f"au catalogue : {en_dur}"
    )
    assert m is not None
