# -*- coding: utf-8 -*-
"""NR -- alerte locale owner : une PR Dependabot PRETE remonte au demarrage de session.

Mesure (roadmap dependabot, 2026-10-17) : les PR Dependabot ont un verdict automatique
pose en commentaire (decision owner du 2026-10-14 -- « garder la fusion humaine »), mais
RIEN ne les signalait la ou l'owner ouvre session : la CI de quarantaine etait verte et la
revue attendait. `gh` n'est authentifie que sous le compte owner, et le demarrage de
session EST ce compte : c'est le seul point d'entree ou cette alerte a un sens.

Contrats gardes ici :
  1. `prs_dependabot_pretes(executer)` rend les PR MERGEABLE ; une PR CONFLICTING ou
     UNKNOWN ne l'est PAS rendue, sans que l'etat en devienne ILLISIBLE (la lecture, elle,
     a reussi) ;
  2. une sortie illisible ou gh absent rend l'etat ILLISIBLE, DIT -- jamais « aucune » :
     UNKNOWN n'est pas NO, une lecture qui echoue ne prouve pas qu'aucune PR n'est prete ;
  3. la ligne de session « [dependabot] N PR prete(s) : #.. » ne sort QUE s'il y a quelque
     chose a dire : rien si 0, ILLISIBLE si gh ne repond pas ;
  4. le hook ne casse JAMAIS la session : un outil de verdict absent ou casse se lit
     ILLISIBLE, pas en traceback ;
  5. la commande reelle est `gh pr list --author app/dependabot --json
     number,title,mergeable`, bordee au boot, et le chemin reel (executer=None) reprend
     exactement les memes etats que la doublure.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_dependabot_verdict as D  # noqa: E402

HOOK = ROOT / "tools" / "claude_session_start.py"

# Sortie JSON de `gh pr list --author app/dependabot --json number,title,mergeable`
# (mesure du 14/10 : #19, #24, #27 -- la fusion reste humaine, l'ALERTE, non).
_SORTIE = json.dumps([
    {"number": 19, "title": "bump setup-uv from 7.6.0 to 10.2.0", "mergeable": "MERGEABLE"},
    {"number": 24, "title": "bump pyo3 from 0.29.2 to 0.29.3", "mergeable": "CONFLICTING"},
    {"number": 27, "title": "bump requests from 2.33.1 to 2.33.2", "mergeable": "MERGEABLE"},
    {"number": 28, "title": "bump numpy from 1.26.4 to 2.5.3", "mergeable": "UNKNOWN"},
])


def _hook():
    spec = importlib.util.spec_from_file_location("claude_session_start_alerte_nr", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. seules les MERGEABLE sont rendues ──────────────────────────────────────────────────────────

def test_seules_les_pr_mergeable_sont_rendues():
    etat, prs = D.prs_dependabot_pretes(lambda: _SORTIE)
    assert etat == "OK"
    assert [p["number"] for p in prs] == [19, 27], (
        "CONFLICTING (#24) et UNKNOWN (#28) ne sont pas pretes ; la lecture, elle, a reussi")


def test_une_liste_vide_est_une_reponse_lisible_et_ne_produit_aucune_alerte():
    etat, prs = D.prs_dependabot_pretes(lambda: "[]")
    assert (etat, prs) == ("OK", [])
    assert _hook().alerte_prs_dependabot(lambda: "[]") is None, "0 PR : rien n'est dit"


# ── 2. illisible = DIT, jamais « aucune » ──────────────────────────────────────────────────────────

def test_une_sortie_illisible_est_dite_ILLISIBLE_et_jamais_aucune():
    illisibles = ("", "   ", "pas du json", '{"message": "Bad credentials"}',
                  "null", '"[]"', "[1, 2]", json.dumps([{"number": 1}]) + " coupee")
    for brut in illisibles:
        etat, prs = D.prs_dependabot_pretes(lambda b=brut: b)
        assert (etat, prs) == ("ILLISIBLE", []), "sortie %r lue comme un etat propre" % brut


def test_gh_absent_est_ILLISIBLE_pas_aucune():
    def _sans_gh():
        raise FileNotFoundError(2, "No such file or directory: 'gh'")

    assert D.prs_dependabot_pretes(_sans_gh) == ("ILLISIBLE", [])
    ligne = _hook().alerte_prs_dependabot(_sans_gh)
    assert ligne and "ILLISIBLE" in ligne and "PR prete(s)" in ligne, ligne
    assert "0 PR" not in ligne and "aucune" not in ligne.lower(), (
        "une lecture qui echoue ne dit pas qu'aucune PR n'est prete : %r" % ligne)


def test_une_pr_mergeable_ne_rend_pas_l_etat_illisible():
    """Contre-epreuve : c'est le JSON qui est illisible, pas le nombre de PR mergeables."""
    etat, prs = D.prs_dependabot_pretes(lambda: json.dumps(
        [{"number": 27, "title": "bump requests", "mergeable": "MERGEABLE"}]))
    assert (etat, [p["number"] for p in prs]) == ("OK", [27])


# ── 3. le chemin REEL, pas seulement la doublure ───────────────────────────────────────────────────

def test_la_commande_reelle_porte_les_pr_dependabot_mergeables_et_est_bornee(monkeypatch):
    appels = []

    def _gh(*args, **kwargs):
        appels.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, _SORTIE, "")

    monkeypatch.setattr(D, "_gh", _gh)
    etat, prs = D.prs_dependabot_pretes()
    assert etat == "OK" and [p["number"] for p in prs] == [19, 27]
    assert list(appels[0][0]) == ["pr", "list", "--author", "app/dependabot",
                                  "--json", "number,title,mergeable"]
    assert appels[0][1].get("timeout", 120) <= 30, (
        "un hook qui attend 120 s retarde le demarrage de session")


def test_le_chemin_reel_sans_gh_dit_ILLISIBLE(monkeypatch):
    def _sabsent(*args, **kwargs):
        raise FileNotFoundError(2, "gh absent de PATH")

    monkeypatch.setattr(D, "_gh", _sabsent)
    assert D.prs_dependabot_pretes() == ("ILLISIBLE", [])


def test_le_chemin_reel_qui_refuse_dit_ILLISIBLE(monkeypatch):
    def _refus(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "gh: authentification expiree")

    monkeypatch.setattr(D, "_gh", _refus)
    assert D.prs_dependabot_pretes() == ("ILLISIBLE", [])


# ── 4. la ligne au demarrage de session ────────────────────────────────────────────────────────────

def test_la_ligne_de_session_nomme_les_pr_pretes():
    ligne = _hook().alerte_prs_dependabot(lambda: _SORTIE)
    assert ligne == "[dependabot] 2 PR prete(s) : #19, #27", ligne


def test_le_hook_l_affiche_dans_main():
    """Un calcul jamais imprime n'est pas une alerte : le wiring se lit dans `main`."""
    src = HOOK.read_text(encoding="utf-8")
    main = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    appeles = {c.func.id for c in ast.walk(main)
               if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "alerte_prs_dependabot" in appeles, "aucun appel dans main : jamais vue"
    segment = ast.get_source_segment(src, main) or ""
    i = segment.index("alerte_prs_dependabot")
    assert "print" in segment[i:], "la ligne doit etre IMPRIMEE, pas calculee puis jetee"


def test_un_outil_casse_ne_casse_jamais_la_session(monkeypatch):
    """Le hook ne doit pas mourir parce qu'un outil voisin a change de signature."""
    faux = types.ModuleType("forge_dependabot_verdict")

    def _casse(*_args, **_kwargs):
        raise RuntimeError("module de verdict casse")

    faux.prs_dependabot_pretes = _casse
    monkeypatch.setitem(sys.modules, "forge_dependabot_verdict", faux)
    texte = _hook().alerte_prs_dependabot(lambda: _SORTIE)
    assert texte and "ILLISIBLE" in texte, texte
    assert "0 PR" not in texte and "aucune" not in texte.lower()
