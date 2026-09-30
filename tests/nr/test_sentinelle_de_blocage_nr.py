"""NR — une sentinelle de BLOCAGE doit refuser tout l'espace des rings.

INVARIANT VERROUILLE ICI : quand un garde exprime « bloque » par une VALEUR
rendue a un comparateur, cette valeur doit refuser CHAQUE ring legal. Ce n'est
pas une question de reglage : c'est le sens du signal.

DEFAUT MESURE LE 2026-09-12 qui motive ce NR.
`ToolRegistry._get_ring_needed` rendait `99` pour `is_active=0`, commente
« bloque ». Le site appelant compare `if ring > ring_needed: refuser`, et un
ring vaut 0..4. `99` ne refusait donc AUCUN ring : couper un outil le rendait
plus permissif que le laisser actif, et le commentaire disait le contraire de
ce que le code faisait.

La famille du defaut : une sentinelle choisie « grande pour etre sure » dans un
comparateur ou GRAND veut dire PERMISSIF. Le sens de la comparaison fait partie
du contrat de la sentinelle, et il ne se lit pas depuis la sentinelle seule.

CE QUE CE NR NE DEMONTRE PAS :
  - il ne dit rien du hub VIVANT (source et unitaire seulement) ;
  - il ne couvre pas les autres gardes a sentinelle du depot : il verrouille
    celui-ci, nomme. Etendre la liste quand un autre est mesure.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE.parent), str(RACINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REGISTRE = RACINE / "app" / "forge_mcp_registry.py"
REG = pytest.importorskip("nokido_agent.app.forge_mcp_registry")

#: tout l'espace des rings declares : MASTER=-1, SYSTEM=0, DEV=1, TRUSTED=2,
#: COLLAB=3, UNTRUSTED=4. Un blocage doit tenir sur TOUS, pas sur les usuels.
RINGS_LEGAUX = (-1, 0, 1, 2, 3, 4)


@pytest.fixture
def base_avec_outil_coupe(tmp_path):
    db = tmp_path / "bareme.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE forge_tools ("
                "tool_name TEXT PRIMARY KEY, min_ring INTEGER, is_active INTEGER)")
    con.executemany("INSERT INTO forge_tools VALUES (?,?,?)",
                    [("coupe", 2, 0), ("coupe_null", 2, None), ("actif", 2, 1)])
    con.commit()
    con.close()
    return db


@pytest.mark.parametrize("outil", ["coupe", "coupe_null"])
def test_un_outil_coupe_refuse_tout_l_espace_des_rings(
        monkeypatch, base_avec_outil_coupe, outil):
    reg = REG.get_registry()
    monkeypatch.setattr(reg, "db_path", base_avec_outil_coupe, raising=False)
    plafond = reg._get_ring_needed(outil, {})
    admis = [r for r in RINGS_LEGAUX if not (r > plafond)]
    assert not admis, (
        "outil coupe (%s) encore admis aux rings %s : la sentinelle vaut %r, "
        "or le comparateur est `ring > plafond` — une sentinelle GRANDE y "
        "signifie PERMISSIF, pas bloque." % (outil, admis, plafond))


def test_controle_positif_un_outil_actif_n_est_pas_bloque(
        monkeypatch, base_avec_outil_coupe):
    """Sans lui, un correctif qui bloquerait TOUT passerait le test precedent."""
    reg = REG.get_registry()
    monkeypatch.setattr(reg, "db_path", base_avec_outil_coupe, raising=False)
    plafond = reg._get_ring_needed("actif", {})
    admis = [r for r in RINGS_LEGAUX if not (r > plafond)]
    assert admis == [-1, 0, 1, 2], (
        "plafond d'un outil ACTIF altere : admis=%s, plafond=%r" % (admis, plafond))


def test_la_sentinelle_grande_ne_revient_pas_dans_ce_garde():
    """Garde de SOURCE contre la reintroduction de l'idiome.

    LIT L'AST, PAS LE TEXTE. Le premier jet cherchait `return 9\\d` par regex
    et matchait le `return 99` cite dans le COMMENTAIRE qui documente
    justement le defaut : un instrument qui lit son propre vocabulaire crie a
    faux, et un garde qui crie a faux se fait desarmer. L'AST ne voit pas les
    commentaires.
    """
    import ast

    if not REGISTRE.is_file():
        pytest.skip("registre absent: %s" % REGISTRE)
    arbre = ast.parse(REGISTRE.read_text(encoding="utf-8", errors="replace"))
    cible = next((n for n in ast.walk(arbre)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                  and n.name == "_get_ring_needed"), None)
    assert cible is not None, "_get_ring_needed a disparu"

    grands = [n.value.value for n in ast.walk(cible)
              if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)
              and isinstance(n.value.value, int)
              and n.value.value > max(RINGS_LEGAUX)]
    assert not grands, (
        "_get_ring_needed rend %s, au-dela du plus grand ring legal (%d) : "
        "dans un comparateur `ring > plafond`, une telle valeur n'exprime pas "
        "« bloque » mais « permis a tous »"
        % (grands, max(RINGS_LEGAUX)))

    # PAS d'assertion sur le LITTERAL de la sentinelle. Le premier jet exigeait
    # `return -1` : le NR aurait alors suivi chaque correction du code au lieu
    # de juger l'invariant — et il aurait entérine -1, qui laissait justement
    # passer MASTER. Un NR qui se cale sur la valeur trouvee ne garde rien ;
    # les tests de comportement ci-dessus sont la seule autorite sur la valeur.
