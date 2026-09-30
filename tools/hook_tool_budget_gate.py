"""Gouverneur silencieux du budget d'outils -- empeche la boucle, ne commente pas.

__FORGE_COLOR__ = "immunitaire/guard : budget d'appels d'outils, anti-boucle"

ORDRE OWNER 2026-09-11. Cible :

    mesure ciblee -> decision -> action

et non :

    exploration large -> lecture massive -> relecture -> retry -> re-exploration

DEUX CONTRAINTES DE FORME, aussi structurantes que les regles :

  1. UN APPEL NORMAL NE PRODUIT RIEN : exit 0, aucun JSON, aucun message. Un
     hook qui commente chaque appel ajoute au contexte ce qu'il pretend
     economiser -- et il le rajoute a CHAQUE tour, puisque le contexte est
     re-facture. Les regles persistantes vivent dans CLAUDE.md ; un hook sert a
     empecher une depense AU MOMENT ou elle arrive.
  2. L'ETAT VIT HORS CONTEXTE, dans un fichier. Jamais dans le prompt.

FAIL-OPEN, SANS EXCEPTION. Ce garde est bloquant et global : casse, il
paralyse la session entiere. Etat illisible, dossier inecrivable, entree
malformee, bug interne -> on laisse passer. Le cout des deux erreurs n'est pas
symetrique : rater une boucle coute des tokens, bloquer a tort coute le
travail. C'est aussi la regle de securite du brief -- un garde anti-token ne
doit jamais empecher une verification reellement nouvelle.

Contrat, tel que fige par tests/nr/test_tool_budget_gate_nr.py :

    2 appels identiques           -> autorises
    3e identique, etat inchange   -> REPEAT_TOOL_CALL
    2 fois le MEME echec          -> la 3e tentative est REFUSEE (RETRY_LOOP)
    mutation / echec DIFFERENT    -> rearme (information nouvelle)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

# Redirigeable : les NR le pointent sur tmp_path, ce qui les rend hermetiques.
DOSSIER_ETAT = Path(
    os.environ.get("LAFORGE_BUDGET_DIR")
    or (Path.home() / ".claude" / "runtime" / "tool_budget"))

APPELS_IDENTIQUES_TOLERES = 2
MEMES_ECHECS_TOLERES = 2

# OBSERVER AVANT D'ENFORCER. Un gate neuf est non bloquant le temps de mesurer
# son bruit ; on le promeut sur MESURE, jamais d'emblee. La raison n'est pas la
# prudence : un garde qui crie a faux se fait desarmer, et on perd alors un
# garde JUSTE. En mode `observe` le verdict est calcule et COMPTE dans l'etat
# (`aurait_bloque`), mais rien n'est refuse et rien n'est dit -- de quoi
# repondre plus tard a la seule question qui compte : combien de fois
# aurait-il mordu, et sur quoi ?
MODE = os.environ.get("LAFORGE_BUDGET_MODE", "observe")

# Champs qui varient d'un appel a l'autre sans rien changer a ce qui est
# EXECUTE. Les inclure rendrait le garde inerte sans que rien ne le dise :
# deux appels rigoureusement identiques portent des explications differentes.
_CHAMPS_VOLATILS = ("explanation", "description")

# Outils dont la reussite peut produire une information NOUVELLE, donc rearment.
# Un shell n'y figure pas : relire la meme sortie n'apprend rien, et c'est la
# boucle `Read A / Grep B / Read A / Grep B` que le brief nomme.
_MUTANTS = frozenset((
    "Write", "Edit", "MultiEdit", "NotebookEdit", "governed_edit",
    "browser_navigate", "browser_click", "browser_type", "browser_fill_form",
    "browser_press_key", "browser_select_option", "browser_navigate_back",
    "browser_drag", "browser_drop", "browser_file_upload",
))


def _court(tool_name):
    return str(tool_name or "").rsplit("__", 1)[-1]


def empreinte(tool_name, tool_input):
    """Ce qui fait que deux appels sont << le meme >>."""
    utile = {k: v for k, v in (tool_input or {}).items()
             if k not in _CHAMPS_VOLATILS}
    try:
        corps = json.dumps(utile, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001 - muet-ok
        # muet-ok : une entree non serialisable n'est pas une faute de l'agent.
        # On degrade vers une empreinte grossiere plutot que de refuser.
        corps = repr(sorted(utile.items()))
    brut = "%s\x00%s" % (_court(tool_name), corps)
    return hashlib.sha1(brut.encode("utf-8", "replace")).hexdigest()[:16]


def _vide():
    return {"generation": 0, "appels": {}, "echecs": {}}


def _fichier():
    return DOSSIER_ETAT / "etat.json"


def _lire():
    try:
        return json.loads(_fichier().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - muet-ok
        # muet-ok : absent OU corrompu OU illisible -> on repart d'un etat
        # vide. Un etat qu'on ne peut pas lire ne justifie AUCUN refus ; il
        # justifie seulement de ne rien savoir encore.
        return _vide()


def _ecrire(etat):
    try:
        DOSSIER_ETAT.mkdir(parents=True, exist_ok=True)
        # Borne de croissance : ce fichier est un tampon de session, pas un
        # journal. Sans elle il grossit jusqu'a devenir lui-meme un cout.
        for cle in ("appels", "echecs"):
            if len(etat.get(cle, {})) > 400:
                gen = etat["generation"]
                etat[cle] = {k: v for k, v in etat[cle].items()
                             if v.get("gen") == gen}
        tmp = _fichier().with_suffix(".tmp")
        tmp.write_text(json.dumps(etat), encoding="utf-8")
        tmp.replace(_fichier())
    except Exception:  # noqa: BLE001 - muet-ok
        # muet-ok : ne pas pouvoir MEMORISER n'autorise pas a refuser. Le garde
        # devient amnesique, il ne devient pas hostile.
        pass


def verdict_pre(tool_name, tool_input):
    """(bloque, raison). Enregistre l'appel au passage. Ne leve JAMAIS."""
    try:
        emp = empreinte(tool_name, tool_input)
        etat = _lire()
        gen = etat.get("generation", 0)

        # RETRY d'abord : il porte plus d'information que la simple repetition.
        ech = etat.get("echecs", {}).get(emp)
        if ech and ech.get("gen") == gen and ech.get("n", 0) >= MEMES_ECHECS_TOLERES:
            return True, (
                "RETRY_LOOP: meme commande, meme echec %d fois. Modifier le "
                "diagnostic ou la commande avant de retenter."
                % ech.get("n", 0))

        vu = etat.setdefault("appels", {}).get(emp)
        n = vu.get("n", 0) if (vu and vu.get("gen") == gen) else 0
        if n >= APPELS_IDENTIQUES_TOLERES:
            return True, (
                "REPEAT_TOOL_CALL: %de appel identique sans etat nouveau. "
                "Exploiter le resultat deja obtenu, ou changer d'hypothese."
                % (n + 1))
        etat["appels"][emp] = {"n": n + 1, "gen": gen}
        _ecrire(etat)
        return False, ""
    except Exception:  # noqa: BLE001 - muet-ok
        # muet-ok : FAIL-OPEN. Un bug de ce garde ne doit jamais couter le
        # travail de la session.
        return False, ""


def noter_mutation(tool_name=None, tool_input=None):
    """Une modification a eu lieu : tout ce qui precede peut avoir change."""
    try:
        etat = _lire()
        etat["generation"] = etat.get("generation", 0) + 1
        _ecrire(etat)
    except Exception:  # noqa: BLE001 - muet-ok
        pass


def _normaliser_erreur(erreur):
    """Normalisation MINIMALE, et c'est un choix.

    Premiere version : retirer tous les chiffres, pour absorber pid, duree et
    numero de ligne. Elle rendait `exit code 1: 3 failed` et
    `exit code 1: 1 failed` IDENTIQUES -- c'est-a-dire qu'elle effacait
    exactement le signe du progres, et le garde arretait un travail qui
    avancait. Le NR l'a attrapee.

    Le biais se choisit dans le bon sens : un horodatage qui rend deux echecs
    << differents >> fait rater une boucle (cout : des tokens) ; une
    normalisation trop agressive bloque un travail qui progresse (cout : le
    travail). On garde donc le texte.
    """
    return " ".join(str(erreur or "").lower()[:400].split())


def noter_echec(tool_name, tool_input, erreur=""):
    """Un echec IDENTIQUE s'accumule ; un echec DIFFERENT est une information."""
    try:
        emp = empreinte(tool_name, tool_input)
        h = hashlib.sha1(_normaliser_erreur(erreur).encode("utf-8", "replace")
                         ).hexdigest()[:12]
        etat = _lire()
        gen = etat.get("generation", 0)
        prec = etat.setdefault("echecs", {}).get(emp)
        if prec and prec.get("gen") == gen and prec.get("err") == h:
            prec["n"] = prec.get("n", 0) + 1
        else:
            # Le diagnostic a CHANGE : la boucle avance, on rearme.
            gen += 1
            etat["generation"] = gen
            etat["echecs"][emp] = {"err": h, "n": 1, "gen": gen}
        _ecrire(etat)
    except Exception:  # noqa: BLE001 - muet-ok
        pass


def traiter(ev):
    """Aiguille l'evenement. Retourne le code de sortie. N'ecrit QUE sur refus."""
    try:
        evenement = str((ev or {}).get("hook_event_name") or "")
        nom = (ev or {}).get("tool_name") or ""
        entree = (ev or {}).get("tool_input") or {}
        if not isinstance(entree, dict):
            entree = {}

        if evenement == "PostToolUse":
            if _court(nom) in _MUTANTS:
                noter_mutation(nom, entree)
            return 0

        if evenement == "PostToolUseFailure":
            noter_echec(nom, entree, (ev or {}).get("error") or "")
            return 0

        if evenement != "PreToolUse" or not nom:
            return 0

        bloque, raison = verdict_pre(nom, entree)
        if not bloque:
            return 0  # RIEN. Pas un mot.
        if MODE != "enforce":
            _compter_observation(nom, raison)
            return 0  # observe : on mesure, on ne refuse pas, on se tait
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": raison,
            }
        }))
        return 0
    except Exception:  # noqa: BLE001 - muet-ok
        # muet-ok : FAIL-OPEN jusqu'au bout.
        return 0


def _compter_observation(nom, raison):
    """Mesure du garde en mode observe -- hors contexte, jamais dans le prompt."""
    try:
        etat = _lire()
        obs = etat.setdefault("aurait_bloque", {})
        cle = "%s|%s" % (_court(nom), raison.split(":", 1)[0])
        obs[cle] = obs.get(cle, 0) + 1
        _ecrire(etat)
    except Exception:  # noqa: BLE001 - muet-ok
        pass


def main():
    try:
        ev = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - muet-ok
        return 0
    return traiter(ev)


if __name__ == "__main__":
    sys.exit(main())
