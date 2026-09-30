"""NR : le webhub doit PHOTOGRAPHIER son quatrieme mode de mort (vivant mais gele).

Contexte mesure (2026-09-17) : le webhub est tombe deux fois apres une page LLM
avec la signature port LISTENING + process vivant + `/health` muet 20 s. Aucun
des trois filets existants ne voit ca passer : `except Exception` n'attrape rien
(rien ne remonte), `faulthandler.enable` ne tire que sur une mort DURE, et un
kill externe n'ecrit rien par construction. Trois sessions d'enquete sont donc
reparties d'une hypothese au lieu d'un fait.

Ce NR verrouille QUATRE invariants du veilleur, et chacun a coute ailleurs :

  1. le veilleur est CABLE dans `main()` -- une fonction ecrite mais jamais
     appelee est une dette de cablage, pas une securite ;
  2. il NE TUE RIEN -- un garde a seuil arme sans la distribution du signal a
     tue le hub 16 fois en deux jours (2026-09-05) ;
  3. il declare un gel apres AU MOINS deux echecs -- un garde qui crie a faux
     se fait desarmer ;
  4. son fil est `daemon` -- sinon il retient l'arret du service.

Lecture par AST : importer `tools.nokido_web_hub` executerait le chargement
d'environnement et monterait l'application, ce qui n'a pas sa place dans la
suite pure. Meme parade que `test_webhub_auth_asgi_pur_nr`.

CONTROLE NEGATIF inclus : chaque verificateur est aussi passe sur une source
FABRIQUEE qui viole l'invariant, et doit la refuser. Un test qui ne sait pas
echouer ne prouve rien quand il passe.
"""
from __future__ import annotations

import ast
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "tools" / "nokido_web_hub.py"

NOM = "_veilleur_de_gel"
TUEURS = ("kill", "terminate", "_exit", "killpg", "abort")


def _arbre(texte: str) -> ast.Module:
    return ast.parse(texte)


def _fonction(arbre: ast.Module, nom: str):
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
            return noeud
    return None


def _appelle(arbre: ast.Module, appelant: str, appele: str) -> bool:
    """`appelant` contient-il un appel a `appele` ?"""
    fn = _fonction(arbre, appelant)
    if fn is None:
        return False
    for noeud in ast.walk(fn):
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name):
            if noeud.func.id == appele:
                return True
    return False


def _noms_appeles(fn: ast.AST) -> set[str]:
    noms = set()
    for noeud in ast.walk(fn):
        if isinstance(noeud, ast.Call):
            cible = noeud.func
            if isinstance(cible, ast.Name):
                noms.add(cible.id)
            elif isinstance(cible, ast.Attribute):
                noms.add(cible.attr)
    return noms


def _thread_daemon(fn: ast.AST) -> bool:
    for noeud in ast.walk(fn):
        if isinstance(noeud, ast.Call):
            cible = noeud.func
            nom = cible.attr if isinstance(cible, ast.Attribute) else getattr(cible, "id", "")
            if nom != "Thread":
                continue
            for mc in noeud.keywords:
                if mc.arg == "daemon" and isinstance(mc.value, ast.Constant):
                    return bool(mc.value.value)
            return False
    return False


def _seuil_au_moins(fn: ast.AST, variable: str) -> int | None:
    for noeud in ast.walk(fn):
        if isinstance(noeud, ast.Assign) and len(noeud.targets) == 1:
            cible = noeud.targets[0]
            if isinstance(cible, ast.Name) and cible.id == variable:
                if isinstance(noeud.value, ast.Constant):
                    return noeud.value.value
    return None


# --------------------------------------------------------------- invariants


def test_le_veilleur_existe_et_est_cable_dans_main():
    arbre = _arbre(SOURCE.read_text(encoding="utf-8"))
    assert _fonction(arbre, NOM) is not None, f"{NOM} absent de {SOURCE.name}"
    assert _appelle(arbre, "main", NOM), (
        f"{NOM} est ecrit mais main() ne l'appelle pas : un mecanisme non cable "
        "est une dette, jamais une securite"
    )


def test_le_veilleur_ne_tue_rien():
    arbre = _arbre(SOURCE.read_text(encoding="utf-8"))
    fn = _fonction(arbre, NOM)
    interdits = sorted(_noms_appeles(fn) & set(TUEURS))
    assert not interdits, (
        f"{NOM} appelle {interdits} : ce veilleur OBSERVE, il ne tue pas. "
        "Un seuil de mort ne s'arme qu'apres avoir l'histogramme du signal"
    )


def test_le_gel_demande_au_moins_deux_echecs():
    arbre = _arbre(SOURCE.read_text(encoding="utf-8"))
    fn = _fonction(arbre, NOM)
    seuil = _seuil_au_moins(fn, "echecs_pour_gel")
    assert seuil is not None, "le seuil d'echecs n'est plus une constante lisible"
    assert seuil >= 2, (
        f"seuil={seuil} : un gel declare sur UNE sonde ratee fait crier le garde "
        "a faux, et un garde qui crie a faux se fait desarmer"
    )


def test_le_fil_du_veilleur_est_daemon():
    arbre = _arbre(SOURCE.read_text(encoding="utf-8"))
    fn = _fonction(arbre, NOM)
    assert _thread_daemon(fn), (
        "le fil du veilleur doit etre daemon, sinon il retient l'arret du service"
    )


# ---------------------------------------------------- controles NEGATIFS
# Un test qui ne sait pas echouer ne prouve rien quand il passe.


def test_le_controle_du_cablage_sait_refuser():
    faux = "def _veilleur_de_gel(h, p):\n    pass\n\ndef main():\n    return 0\n"
    arbre = _arbre(faux)
    assert _fonction(arbre, NOM) is not None
    assert not _appelle(arbre, "main", NOM), (
        "le verificateur de cablage accepte une source ou main() n'appelle "
        "PAS le veilleur : il ne discrimine rien"
    )


def test_le_controle_des_tueurs_sait_refuser():
    faux = "def _veilleur_de_gel(h, p):\n    proc.kill()\n"
    fn = _fonction(_arbre(faux), NOM)
    assert _noms_appeles(fn) & set(TUEURS), (
        "le verificateur de tueurs laisse passer un appel a kill()"
    )


def test_le_controle_du_seuil_sait_refuser():
    faux = "def _veilleur_de_gel(h, p):\n    echecs_pour_gel = 1\n"
    fn = _fonction(_arbre(faux), NOM)
    assert _seuil_au_moins(fn, "echecs_pour_gel") == 1, (
        "le verificateur de seuil ne lit pas la valeur reelle"
    )


def test_le_controle_du_daemon_sait_refuser():
    faux = ("import threading\n"
            "def _veilleur_de_gel(h, p):\n"
            "    threading.Thread(target=None, daemon=False).start()\n")
    fn = _fonction(_arbre(faux), NOM)
    assert not _thread_daemon(fn), (
        "le verificateur de daemon accepte un fil non-daemon"
    )
