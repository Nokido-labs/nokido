# -*- coding: utf-8 -*-
"""NR — un widget ne fait plus ATTENDRE le LLM avant de rendre.

CE QUI A ETE MESURE. Les trois widgets `/ui/auto/*` appelaient la cascade AVANT
de rendre quoi que ce soit, avec une borne de 25 s. L'utilisateur regardait une
page vide ; le gate UI, lui, voyait la route tantot dans son budget tantot hors
budget -- d'ou un verdict qui changeait d'une passe a l'autre sans qu'une ligne
de code ait bouge. Le registre des routes instables a accumule SIX routes, dont
ces trois-la.

⚠️ CE QU'IL NE FAUT PAS FAIRE, et que j'allais faire : reduire la borne. Elle a
ete portee de 8 a 25 s le 2026-08-30 SUR MESURE -- trois generations du meme
widget en 20,2 s, 18,6 s et 4,0 s, toutes avec un HTML valide. A 8 s, la borne
coupait une generation qui ABOUTISSAIT et la page servait un repli en le
presentant comme un echec. Le defaut n'a jamais ete la duree de la generation,
c'est qu'on la faisait attendre a l'utilisateur.

LE CONTRAT VERROUILLE ICI :
  1. `generer=0` (le defaut -- ce que voient l'utilisateur ET le gate) rend le
     repli SANS jamais appeler `generate_ui` ;
  2. le repli est enveloppe d'un `hx-get` qui rappelle la route en `generer=1` ;
  3. l'echec de generation rend **204**, pas un second repli : htmx ne remplace
     alors rien et l'information deja affichee reste. Une generation ratee
     n'efface jamais ce qui est servi.

Juge sur l'AST : charger FastAPI pour cela couterait des secondes a chaque run
de la suite pure, et le contrat est STRUCTUREL.
"""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

WIDGETS = ("ui_auto_critical_events", "ui_auto_services_status",
           "ui_auto_veille_summary")
SRC = ROOT / "app" / "web_hub" / "app.py"


def _handlers():
    arbre = ast.parse(SRC.read_text(encoding="utf-8", errors="replace"))
    trouves = {n.name: n for n in ast.walk(arbre)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name in WIDGETS}
    manquants = set(WIDGETS) - set(trouves)
    assert not manquants, "handler(s) introuvable(s) : %s" % sorted(manquants)
    return trouves


def test_chaque_widget_accepte_le_drapeau_generer():
    for nom, fn in _handlers().items():
        args = [a.arg for a in fn.args.args]
        assert "generer" in args, (
            "%s n'a pas de parametre `generer` : il ne peut pas court-circuiter "
            "la generation, donc il fait attendre" % nom)


def test_le_repli_part_AVANT_tout_appel_a_generate_ui():
    """Le coeur du contrat : sur le chemin par defaut, la cascade n'est JAMAIS
    atteinte. Un `return` place apres l'appel ne servirait a rien."""
    for nom, fn in _handlers().items():
        lignes_repli = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) == "enveloppe_progressive"
                 or getattr(n.func, "attr", None) == "enveloppe_progressive")]
        lignes_cascade = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) == "generate_ui"
                 or getattr(n.func, "attr", None) == "generate_ui")]
        assert lignes_repli, "%s ne sert pas de repli immediat" % nom
        assert lignes_cascade, "%s n'appelle plus la cascade du tout" % nom
        assert min(lignes_repli) < min(lignes_cascade), (
            "%s appelle generate_ui AVANT de servir le repli : il fait toujours "
            "attendre" % nom)


def test_un_echec_de_generation_rend_204_et_n_ecrase_rien():
    """204 = htmx ne touche pas au DOM. Rendre un second repli ECRASERAIT le
    tableau deja affiche par un contenu equivalent, pour rien."""
    for nom, fn in _handlers().items():
        codes = [kw.value.value for n in ast.walk(fn)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", None) == "Response"
                 for kw in n.keywords
                 if kw.arg == "status_code" and isinstance(kw.value, ast.Constant)]
        assert 204 in codes, (
            "%s ne rend pas 204 quand la generation echoue : le repli deja "
            "affiche serait remplace" % nom)


def test_l_enveloppe_porte_bien_le_rappel_htmx():
    from app.web_hub.ui_generate import enveloppe_progressive

    out = enveloppe_progressive("<table>x</table>", "/ui/auto/x?generer=1", "widget-x")
    assert "<table>x</table>" in out, "le repli n'est pas dans la reponse"
    assert 'hx-get="/ui/auto/x?generer=1"' in out
    assert 'hx-swap="outerHTML"' in out
    assert 'id="widget-x"' in out


def test_l_enveloppe_echappe_les_guillemets_de_l_appelant():
    """L'url et la cle finissent DANS des attributs HTML. Un guillemet non
    echappe y fermerait l'attribut, ce qui laisserait injecter le suivant. On
    verifie l'echappement sans ecrire de motif d'attaque."""
    from app.web_hub.ui_generate import enveloppe_progressive

    out = enveloppe_progressive("<p>ok</p>", '/x"suite', 'cle"suite')
    assert "&quot;" in out, "les guillemets ne sont pas echappes"
    assert '"/x"suite"' not in out, "l'attribut hx-get est ferme prematurement"
    assert '"cle"suite"' not in out, "l'attribut id est ferme prematurement"


def test_la_borne_de_generation_n_est_PAS_rabotee():
    """Regression interdite : 25 s est une MESURE (20,2 / 18,6 / 4,0 s), pas un
    reglage. La rabaisser couperait des generations qui aboutissent."""
    import inspect

    from app.web_hub.ui_generate import generate_ui

    defaut = inspect.signature(generate_ui).parameters["timeout_s"].default
    assert defaut >= 25.0, (
        "borne ramenee a %s s : elle couperait des generations mesurees a "
        "20,2 s et 18,6 s" % defaut)
