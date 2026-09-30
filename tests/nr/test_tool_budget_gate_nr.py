"""NR -- gouverneur de budget d'outils : empecher la boucle, pas commenter.

ORDRE OWNER 2026-09-11 : reduire les tokens brules par la repetition, le retry
aveugle, la relecture et l'exploration large, SANS ralentir les appels normaux.
Cible :   mesure ciblee -> decision -> action
et non : exploration large -> lecture massive -> relecture -> retry -> ...

DEUX CONTRAINTES DE FORME, aussi importantes que les regles elles-memes :

  1. UN APPEL NORMAL NE PRODUIT RIEN. exit 0, aucun JSON, aucun message. Un
     hook qui commente chaque appel ajoute au contexte precisement ce qu'il
     pretend economiser. << Les hooks doivent bloquer les mauvais appels ; ils
     ne doivent pas envoyer un rappel de 500 mots a chaque appel. >>
  2. L'ETAT VIT HORS CONTEXTE (fichier), jamais dans le prompt.

CE QUE CE NR FIGE, et pourquoi chaque point est un piege deja paye ailleurs :

  * `explanation` est VOLATIL. Deux appels rigoureusement identiques portent des
    explications differentes ; les inclure dans l'empreinte rendrait le garde
    inerte sans que rien ne le dise -- la forme exacte du garde branche sur un
    signal que personne n'emet.
  * UNE MUTATION REARME. Write/Edit, une navigation, un nouveau processus
    peuvent produire une information neuve : re-mesurer apres n'est pas une
    repetition, c'est une verification. Un garde qui l'interdit empeche une
    verification REELLEMENT nouvelle, ce que la regle de securite du brief
    interdit explicitement.
  * FAIL-OPEN, sans exception. Ce garde est BLOQUANT et GLOBAL : s'il casse, il
    paralyse la session entiere. Un etat illisible, corrompu ou un bug interne
    doivent laisser passer. Le cout des deux erreurs n'est pas symetrique --
    rater une boucle coute des tokens, bloquer a tort coute le travail.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "hook_tool_budget_gate.py"


def _charger(dossier_etat):
    """Charge le module avec son etat redirige vers tmp_path.

    Hermetique : aucun fichier du profil, aucune dependance a l'historique de
    la machine. La question a se poser reste << sur un clone tout neuf, ce test
    rend-il le meme verdict ? >>
    """
    if not SRC.exists():
        pytest.fail("%s absent -- le garde n'existe pas encore" % SRC.name)
    spec = importlib.util.spec_from_file_location("hook_tool_budget_gate", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DOSSIER_ETAT = Path(dossier_etat)
    return mod


APPEL = ("Bash", {"command": "Get-Process deno"})


# --------------------------------------------------------------------------
# 1. EMPREINTE : ce qui fait que deux appels sont << le meme >>
# --------------------------------------------------------------------------

def test_l_explanation_ne_change_pas_l_empreinte(tmp_path):
    """Champ volatil. L'inclure rendrait le garde inerte EN SILENCE."""
    G = _charger(tmp_path)
    a = G.empreinte("Bash", {"command": "ls", "explanation": "je regarde"})
    b = G.empreinte("Bash", {"command": "ls", "explanation": "je verifie encore"})
    assert a == b, (
        "l'empreinte varie avec `explanation` : aucun appel ne serait jamais "
        "vu comme repete, et le garde n'aurait jamais mordu -- sans le dire")


def test_deux_appels_differents_ont_des_empreintes_differentes(tmp_path):
    G = _charger(tmp_path)
    assert G.empreinte("Bash", {"command": "ls"}) != G.empreinte("Bash", {"command": "pwd"})
    assert G.empreinte("Bash", {"command": "ls"}) != G.empreinte("Read", {"command": "ls"})


# --------------------------------------------------------------------------
# 2. ANTI-REPEAT : 2 passent, le 3e sans etat neuf est refuse
# --------------------------------------------------------------------------

def test_les_deux_premiers_appels_identiques_passent(tmp_path):
    G = _charger(tmp_path)
    for rang in (1, 2):
        bloque, _ = G.verdict_pre(*APPEL)
        assert not bloque, "appel %d refuse : le contrat en autorise DEUX" % rang


def test_le_troisieme_appel_identique_est_refuse(tmp_path):
    G = _charger(tmp_path)
    G.verdict_pre(*APPEL)
    G.verdict_pre(*APPEL)
    bloque, raison = G.verdict_pre(*APPEL)
    assert bloque, "3e appel identique sans etat neuf : doit etre refuse"
    assert "REPEAT_TOOL_CALL" in raison


def test_une_mutation_rearme_le_compteur(tmp_path):
    """Re-mesurer APRES une modification n'est pas une repetition.

    C'est la contre-epreuve du garde : sans elle, il interdirait la
    verification qui suit un correctif -- exactement le geste qu'on veut."""
    G = _charger(tmp_path)
    G.verdict_pre(*APPEL)
    G.verdict_pre(*APPEL)
    G.noter_mutation("Edit", {"file_path": "x.py"})
    bloque, raison = G.verdict_pre(*APPEL)
    assert not bloque, (
        "appel refuse APRES une mutation : le garde empeche une verification "
        "reellement nouvelle, ce que la regle de securite interdit (%s)" % raison)


def test_un_appel_different_intercale_ne_rearme_PAS(tmp_path):
    """Lire un autre fichier ne rend pas neuf l'etat qu'on re-interroge.

    Sinon `Read A / Grep B / Read A / Grep B / Read A` -- la boucle exacte que
    le brief nomme -- ne serait jamais vue."""
    G = _charger(tmp_path)
    G.verdict_pre(*APPEL)
    G.verdict_pre("Bash", {"command": "echo autre"})
    G.verdict_pre(*APPEL)
    bloque, _ = G.verdict_pre(*APPEL)
    assert bloque, (
        "un simple appel intercale a rearme le compteur : la boucle "
        "A/B/A/B/A/B resterait invisible")


# --------------------------------------------------------------------------
# 3. ANTI-RETRY : meme echec deux fois, le 3e est refuse
# --------------------------------------------------------------------------

def test_le_troisieme_retry_apres_deux_memes_echecs_est_refuse(tmp_path):
    G = _charger(tmp_path)
    cmd = ("Bash", {"command": "pytest tests/x.py"})
    for _ in range(2):
        G.verdict_pre(*cmd)
        G.noter_echec(*cmd, erreur="exit code 1: 3 failed")
    bloque, raison = G.verdict_pre(*cmd)
    assert bloque, "meme commande, meme echec, 3e tentative : doit etre refusee"
    assert "RETRY_LOOP" in raison


def test_un_echec_different_ne_compte_pas_comme_le_meme(tmp_path):
    """Un echec qui CHANGE est une information : la boucle avance."""
    G = _charger(tmp_path)
    cmd = ("Bash", {"command": "pytest tests/x.py"})
    G.verdict_pre(*cmd)
    G.noter_echec(*cmd, erreur="exit code 1: 3 failed")
    G.verdict_pre(*cmd)
    G.noter_echec(*cmd, erreur="exit code 1: 1 failed")
    bloque, _ = G.verdict_pre(*cmd)
    assert not bloque, (
        "le diagnostic a change entre les deux tentatives : refuser ici "
        "arreterait un travail qui progresse")


def test_une_mutation_rearme_aussi_le_retry(tmp_path):
    G = _charger(tmp_path)
    cmd = ("Bash", {"command": "pytest tests/x.py"})
    for _ in range(2):
        G.verdict_pre(*cmd)
        G.noter_echec(*cmd, erreur="exit code 1: 3 failed")
    G.noter_mutation("Edit", {"file_path": "app/x.py"})
    bloque, _ = G.verdict_pre(*cmd)
    assert not bloque, (
        "on vient de corriger le code : relancer le test est le geste JUSTE")


# --------------------------------------------------------------------------
# 4. FORME DE SORTIE : silencieux par defaut, deny quand ca mord
# --------------------------------------------------------------------------

def test_un_appel_normal_ne_produit_AUCUNE_sortie(tmp_path, capsys):
    """Contrainte globale du brief. Un hook bavard coute ce qu'il pretend
    economiser -- et il le coute a CHAQUE tour, puisque le contexte est
    re-facture."""
    G = _charger(tmp_path)
    rc = G.traiter({"hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "echo ok"}})
    sortie = capsys.readouterr()
    assert rc == 0
    assert sortie.out == "", "un appel normal a ecrit sur stdout : %r" % sortie.out
    assert sortie.err == "", "un appel normal a ecrit sur stderr : %r" % sortie.err


def test_le_refus_a_la_forme_attendue_par_le_runtime(tmp_path, capsys):
    """`hookSpecificOutput.permissionDecision` -- les champs top-level
    decision/reason sont deprecies pour PreToolUse."""
    G = _charger(tmp_path)
    G.MODE = "enforce"
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
          "tool_input": {"command": "Get-Process deno"}}
    G.traiter(ev)
    G.traiter(ev)
    capsys.readouterr()
    G.traiter(ev)
    paye = json.loads(capsys.readouterr().out)
    hso = paye["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    assert hso["permissionDecisionReason"].strip()
    assert len(hso["permissionDecisionReason"]) < 400, (
        "raison trop longue : un refus est une raison COURTE, pas un cours")


# --------------------------------------------------------------------------
# 5. FAIL-OPEN -- le point le plus important du fichier
# --------------------------------------------------------------------------

def test_un_etat_illisible_ne_bloque_JAMAIS(tmp_path):
    """Ce garde est bloquant et global : casse, il paralyse la session.

    Le cout des deux erreurs n'est pas symetrique -- rater une boucle coute des
    tokens, bloquer a tort coute le travail."""
    G = _charger(tmp_path)
    (tmp_path / "etat.json").write_text("{ ceci n'est pas du json", encoding="utf-8")
    bloque, _ = G.verdict_pre(*APPEL)
    assert not bloque, "un etat corrompu fait refuser des appels legitimes"


def test_un_etat_inecrivable_ne_bloque_jamais(tmp_path, monkeypatch):
    """Ne pas pouvoir MEMORISER n'autorise pas a refuser.

    Premiere version de ce test : pointer le garde sur un dossier profond
    inexistant. Elle ne prouvait RIEN -- `mkdir(parents=True)` le creait, donc
    l'etat s'ecrivait parfaitement et les 5 appels identiques bloquaient au 3e,
    ce qui est le comportement JUSTE. Un test qui croit mesurer l'echec d'une
    ecriture alors qu'il mesure une reussite est un faux temoin : on injecte
    l'echec au lieu d'esperer qu'il survienne.
    """
    G = _charger(tmp_path)

    def _refuse(_etat):
        raise OSError("disque plein")

    monkeypatch.setattr(G, "_ecrire", _refuse)
    for rang in range(5):
        bloque, raison = G.verdict_pre(*APPEL)
        assert not bloque, (
            "appel %d refuse alors que l'etat ne peut pas s'ecrire : le garde "
            "devient amnesique, il ne doit pas devenir hostile (%s)"
            % (rang + 1, raison))


def test_le_mode_par_defaut_OBSERVE_et_ne_refuse_rien(tmp_path, capsys):
    """Observer avant d'enforcer.

    Un gate neuf est non bloquant le temps de MESURER son bruit -- pas par
    prudence, mais parce qu'un garde qui crie a faux se fait desarmer, et
    qu'on perd alors un garde juste. Le mode par defaut doit donc etre
    `observe`, sans quoi ce garde global partirait bloquant le jour de sa
    naissance.
    """
    G = _charger(tmp_path)
    assert G.MODE == "observe", (
        "mode par defaut = %r : un garde BLOQUANT et GLOBAL ne se promeut que "
        "sur mesure de son bruit" % G.MODE)
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
          "tool_input": {"command": "Get-Process deno"}}
    for _ in range(4):
        assert G.traiter(ev) == 0
    sortie = capsys.readouterr()
    assert sortie.out == "", "le mode observe a REFUSE un appel : %r" % sortie.out
    assert sortie.err == ""


def test_le_mode_observe_COMPTE_ce_qu_il_aurait_bloque(tmp_path):
    """Sans ce compteur, on ne saura jamais s'il faut le promouvoir.

    C'est la mesure que le brief reclame : blocked_calls et
    false_positive_blocks. Un garde qu'on ne peut pas evaluer ne se promeut pas
    -- il se desarme ou il s'impose a l'aveugle, et les deux sont mauvais."""
    G = _charger(tmp_path)
    ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
          "tool_input": {"command": "Get-Process deno"}}
    for _ in range(4):
        G.traiter(ev)
    obs = G._lire().get("aurait_bloque", {})
    assert obs, "le mode observe n'a rien mesure : il est alors inutile"
    assert sum(obs.values()) >= 2, (
        "2 morsures attendues sur 4 appels identiques, vu %r" % obs)


def test_une_entree_malformee_sort_en_zero(tmp_path, capsys):
    G = _charger(tmp_path)
    for ev in ({}, {"hook_event_name": "PreToolUse"}, {"tool_input": None}):
        assert G.traiter(ev) == 0
    assert capsys.readouterr().out == ""
