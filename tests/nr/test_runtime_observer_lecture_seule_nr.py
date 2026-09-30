# -*- coding: utf-8 -*-
"""NR — l'organe sensoriel est en lecture seule, et c'est PROUVE, pas declare.

Un module qui annonce « READ_ONLY » dans un dictionnaire ne prouve rien : c'est
une dette de cablage, pas une securite -- exactement ce que ce depot traque
ailleurs (« ne jamais confondre l'existence d'un mecanisme avec son effet »).

Ces tests relisent la SOURCE par AST et EXECUTENT l'organe. Ils refusent :
  - subprocess, os.system, os.popen, eval, exec, compile
  - toute ouverture de fichier en ecriture
  - tout SQL mutant
  - la lecture de la VALEUR d'une variable d'environnement (seule sa presence)
  - tout chemin de profil utilisateur en sortie

Et, cote sortie : le contrat OBSERVATION / FAITS / DECLARE / INCONNU / LIMITES
doit etre COMPLET. `DECLARE != OBSERVE` est une erreur payee le 2026-09-18, deux
fois dans la meme heure : un rapport a pris le defaut de sa propre sonde pour un
reglage de la base, puis l'absence d'une variable dans SON bac pour une
contention du systeme.
"""

from __future__ import annotations

__FORGE_COLOR__ = "sensoriel/observabilite : l'organe ne peut rien modifier"

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

SRC = RACINE / "app" / "forge_runtime_observer.py"
ARBRE = ast.parse(SRC.read_text(encoding="utf-8"))

APPELS_INTERDITS = {"system", "popen", "eval", "exec", "compile", "run", "Popen",
                    "spawn", "spawnl", "execv", "remove", "unlink", "rmdir"}
MODULES_INTERDITS = {"subprocess", "shutil", "socket", "requests", "urllib"}


def _appels(nom_attendu):
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.Call):
            f = n.func
            nom = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            if nom == nom_attendu:
                yield n


def test_aucun_module_d_execution_importe():
    importes = set()
    for n in ast.walk(ARBRE):
        if isinstance(n, ast.Import):
            importes.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            importes.add(n.module.split(".")[0])
    intrus = sorted(importes & MODULES_INTERDITS)
    assert not intrus, f"modules d'execution ou de reseau importes : {intrus}"


def test_aucun_appel_d_execution():
    trouves = sorted({
        (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")) + ":" + str(n.lineno)
        for n in ast.walk(ARBRE) if isinstance(n, ast.Call)
        for f in [n.func]
        if (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)) in APPELS_INTERDITS
    })
    assert not trouves, f"appels d'execution ou de suppression : {trouves}"


def test_aucune_ouverture_en_ecriture():
    fautifs = []
    for n in _appels("open"):
        for a in list(n.args[1:]) + [k.value for k in n.keywords if k.arg == "mode"]:
            if isinstance(a, ast.Constant) and any(c in str(a.value) for c in "wax+"):
                fautifs.append(n.lineno)
    for n in _appels("write_text"):
        fautifs.append(n.lineno)
    for n in _appels("write_bytes"):
        fautifs.append(n.lineno)
    assert not fautifs, f"ecritures de fichier aux lignes {sorted(set(fautifs))}"


def _docstrings() -> set:
    """Les noeuds de docstring, a EXCLURE du scan.

    L'AST protege des COMMENTAIRES (il ne les porte pas) -- mais PAS des
    docstrings : elles sont des `ast.Constant` comme les autres. J'avais ecrit
    l'inverse dans ce fichier, et le test m'a repris : il accusait la docstring
    du module observe, qui ENUMERE justement les mots interdits.

    Septieme fois que ce motif mord dans ce depot le meme jour. « Un instrument
    ne lit jamais son propre vocabulaire » ne se satisfait pas de passer a l'AST :
    il faut exclure ce qui DECRIT, pas seulement ce qui commente.
    """
    ids = set()
    for n in ast.walk(ARBRE):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            corps = getattr(n, "body", None) or []
            if (corps and isinstance(corps[0], ast.Expr)
                    and isinstance(corps[0].value, ast.Constant)
                    and isinstance(corps[0].value.value, str)):
                ids.add(id(corps[0].value))
    return ids


DOCSTRINGS = _docstrings()


@pytest.mark.parametrize("mot", ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER"])
def test_aucun_sql_mutant(mot):
    """Cherche le mot dans les chaines OPERATIONNELLES : ni commentaire (absent
    de l'AST) ni docstring (presente, et exclue ici)."""
    fautifs = [
        n.lineno for n in ast.walk(ARBRE)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and id(n) not in DOCSTRINGS
        and mot in n.value.upper() and "sqlite_master" not in n.value
    ]
    assert not fautifs, f"{mot} present dans une chaine operationnelle, lignes {fautifs}"


def test_morsure_le_scan_voit_un_vrai_SQL_hors_docstring(tmp_path):
    """CONTROLE NEGATIF — sans lui, exclure les docstrings pourrait tout exclure
    et le test passerait au vert en ne regardant plus rien."""
    f = tmp_path / "faux.py"
    f.write_text('"""docstring citant DELETE FROM t."""\n'
                 'def g(c):\n'
                 '    return c.execute("DELETE FROM t")\n', encoding="utf-8")
    arbre = ast.parse(f.read_text(encoding="utf-8"))
    docs = set()
    for n in ast.walk(arbre):
        if isinstance(n, (ast.Module, ast.FunctionDef)):
            b = getattr(n, "body", None) or []
            if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant):
                docs.add(id(b[0].value))
    vus = [n.lineno for n in ast.walk(arbre)
           if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and id(n) not in docs and "DELETE" in n.value.upper()]
    assert vus == [3], (
        f"le scan doit voir le DELETE de la ligne 3 et ignorer la docstring, il rend {vus}"
    )


def test_la_valeur_d_une_variable_d_environnement_n_est_jamais_RENDUE():
    """`os.environ.get(x)` est tolere pour tester la PRESENCE -- mais son
    resultat doit passer par `bool()`. Rendre la valeur pourrait publier un
    chemin de profil, voire un secret."""
    nus = []
    for n in ast.walk(ARBRE):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get"
                and isinstance(n.func.value, ast.Attribute)
                and n.func.value.attr == "environ"):
            continue
        parent_bool = any(
            isinstance(p, ast.Call) and getattr(p.func, "id", None) == "bool"
            and any(a is n for a in ast.walk(p))
            for p in ast.walk(ARBRE) if isinstance(p, ast.Call)
        )
        if not parent_bool:
            nus.append(n.lineno)
    assert not nus, (
        f"valeur d'environnement rendue telle quelle, lignes {nus} — "
        "n'en rendre que la PRESENCE"
    )


# ── EXECUTION : le contrat tient-il vraiment ? ───────────────────────────────

from app.forge_runtime_observer import PORTEES, observer, observer_tout  # noqa: E402

CASES = ("observation", "faits", "declare", "inconnu", "limites")


@pytest.mark.parametrize("portee", PORTEES)
def test_le_contrat_est_complet_pour_chaque_portee(portee):
    r = observer(portee)
    manquantes = [c for c in CASES if c not in r]
    assert not manquantes, f"cases absentes du contrat : {manquantes}"
    assert r["observation"]["compte"], "l'observateur ne se nomme pas"
    assert r["observation"]["portee"] == portee
    assert r["limites"], "aucune limite declaree : un observateur en a toujours"


@pytest.mark.parametrize("portee", PORTEES)
def test_aucun_chemin_de_profil_utilisateur_en_sortie(portee):
    import json

    texte = json.dumps(observer(portee), default=str)
    maison = str(Path.home())
    for forme in (maison, maison.replace("\\", "/"), maison.replace("\\", "\\\\")):
        assert forme not in texte, f"chemin de profil publie : {forme}"


def test_une_portee_inconnue_se_NOMME_au_lieu_de_se_taire():
    r = observer("portee_qui_n_existe_pas")
    assert r["inconnu"], "une portee inconnue passe en silence"
    assert any("portees disponibles" in l for l in r["limites"]), (
        "l'appelant distant ne peut pas se corriger seul"
    )


def test_morsure_une_portee_qui_leve_ne_casse_pas_l_appelant(monkeypatch):
    """CONTROLE NEGATIF — un observateur qui propage une exception fait tomber
    ce qu'il observe. Il doit rendre un INCONNU nomme."""
    import app.forge_runtime_observer as obs

    def _explose():
        raise RuntimeError("sonde cassee")

    monkeypatch.setitem(obs._PORTEES, "db", _explose)
    r = obs.observer("db")
    assert r["faits"] == {}
    assert "sonde cassee" in str(r["inconnu"]), (
        "l'echec de la sonde n'est pas rendu : il serait lu comme une absence"
    )


def test_les_capacites_declarees_correspondent_a_ce_qui_est_verifie():
    from app.forge_runtime_observer import CAPACITES

    assert CAPACITES["mode"] == "READ_ONLY"
    assert CAPACITES["effets_de_bord"] is False
    assert CAPACITES["execute_des_processus"] is False
    assert Path(RACINE / CAPACITES["invariant_verifie_par"]).exists(), (
        "les capacites citent un NR qui n'existe pas : une garantie sans garde"
    )


def test_observer_tout_couvre_les_portees_declarees():
    r = observer_tout()
    assert set(r) == set(PORTEES)
