"""NR — le chemin TEMP du sandbox a UN point unique, et il est purge.

CONTEXTE, owner 2026-09-08 : « on avait interdit les ecritures tmp sur C: et
elles sont normalement sur D:\\Temp ». La mesure a montre que ce n'etait PAS le
cas pour les executions du hub : `TEMP` et `TMP` du compte sandbox pointent vers
`<depot>/sandbox/workspace/tmp`, sur C: et DANS le depot -- 4112 fichiers,
0,55 Go accumules.

DEUX DEFAUTS, un de forme et un de fond.

1. FORME — le chemin etait calcule EN DUR sur DEUX sites du module de lancement
   (lignes 488 et 667, `_tmp = str(WORKSPACE / "tmp")`). C'est precisement ce que
   la regle du corps interdit : un etat partage bascule par un INTERRUPTEUR lu a
   chaque appel, jamais site par site, sinon un site bascule seul. Patron etabli :
   `forge_db_path.m2m_path()` + `sandbox/m2m.switch` (2026-09-06).

2. FOND — rien ne purgeait cette zone. `cleanup_workdir` audite des dossiers
   PARENTS (node_modules, venv), pas ce tmp ; `forge_log_retention` est le
   purgeur du corps et n'en savait rien.

CE QUE CE NR N'EXIGE PAS, et pourquoi. Il n'impose AUCUN deplacement vers D:.
Mesure du jour : D: a 64,0 Go libres contre 140,6 Go pour C:, donc deplacer
chargerait le disque le moins libre ; et surtout `forge_workspace_guard` compare
des chemins RELATIFS A ROOT, si bien qu'un tmp hors du depot serait REFUSE
(« ecriture hors zone agent ») -- le code porte deja la cicatrice de ce piege :
« C:/tmp bloque par WORKSPACE_GUARD process-wide ». Le contrat est donc : UN
point de decision, un defaut INCHANGE, et une purge bornee. Deplacer devient
possible en changeant un seul endroit, le jour ou c'est decide.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SRC_LANCEUR = RACINE / "app" / "forge_sandbox_exec.py"
SRC_RETENTION = RACINE / "tools" / "forge_log_retention.py"


def _lanceur():
    import sys

    for chemin in (RACINE, RACINE / "app"):
        if str(chemin) not in sys.path:
            sys.path.insert(0, str(chemin))
    return pytest.importorskip("app.forge_sandbox_exec")


def test_le_chemin_tmp_a_une_fonction_dediee():
    """Un point de decision, nomme, appelable -- pas deux expressions jumelles."""
    m = _lanceur()
    assert hasattr(m, "chemin_tmp_sandbox"), (
        "le module de lancement doit exposer chemin_tmp_sandbox() : sans point "
        "unique, un site peut basculer seul"
    )
    valeur = m.chemin_tmp_sandbox()
    assert isinstance(valeur, str) and valeur, "le chemin tmp doit etre une chaine non vide"


def test_aucun_site_ne_recalcule_le_chemin_en_dur():
    """Le contrat qui empeche la derive de revenir.

    On cherche l'expression `WORKSPACE / "tmp"` dans l'AST : c'est elle qui etait
    dupliquee. La fonction dediee a le droit de la contenir UNE fois.
    """
    arbre = ast.parse(SRC_LANCEUR.read_text(encoding="utf-8", errors="replace"))

    def est_workspace_tmp(noeud) -> bool:
        return (
            isinstance(noeud, ast.BinOp)
            and isinstance(noeud.op, ast.Div)
            and isinstance(noeud.left, ast.Name)
            and noeud.left.id == "WORKSPACE"
            and isinstance(noeud.right, ast.Constant)
            and noeud.right.value == "tmp"
        )

    dans_la_fonction = set()
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                noeud.name == "chemin_tmp_sandbox":
            for sous in ast.walk(noeud):
                dans_la_fonction.add(id(sous))

    dehors = [
        n for n in ast.walk(arbre)
        if est_workspace_tmp(n) and id(n) not in dans_la_fonction
    ]
    assert not dehors, (
        f"{len(dehors)} site(s) recalculent WORKSPACE / 'tmp' hors de "
        "chemin_tmp_sandbox() -- un site peut alors basculer seul"
    )


def test_les_poseurs_de_TEMP_passent_par_la_fonction():
    """TEMP et TMP doivent venir du point unique, pas d'une variable ad hoc."""
    source = SRC_LANCEUR.read_text(encoding="utf-8", errors="replace")
    poses = source.count('env["TEMP"]')
    appels = source.count("chemin_tmp_sandbox(")
    assert poses >= 2, f"attendu au moins 2 sites posant TEMP, vus {poses}"
    assert appels >= poses, (
        f"{poses} sites posent TEMP mais seulement {appels - 1} appel(s) au point "
        "unique : au moins un site calcule encore son chemin"
    )


def test_un_override_d_environnement_est_honore(monkeypatch, tmp_path):
    """Deplacer doit devenir une DECISION, prise a un seul endroit."""
    m = _lanceur()
    monkeypatch.setenv("LAFORGE_SANDBOX_TMP", str(tmp_path))
    assert m.chemin_tmp_sandbox() == str(tmp_path)


def test_le_defaut_reste_INCHANGE(monkeypatch):
    """Sans override, le comportement d'avant, au caractere pres.

    Un correctif de FORME ne change pas le comportement : c'est ce qui permet de
    le livrer sans fenetre de risque.
    """
    m = _lanceur()
    monkeypatch.delenv("LAFORGE_SANDBOX_TMP", raising=False)
    attendu = str(m.WORKSPACE / "tmp")
    assert m.chemin_tmp_sandbox() == attendu


def test_la_retention_connait_la_zone_tmp():
    """Le purgeur du corps doit couvrir cette zone -- pas un treizieme outil.

    `forge_log_retention` porte deja le patron (dry-run, tiers, bornes) ; on
    l'etend au lieu d'ecrire un purgeur de plus.
    """
    assert SRC_RETENTION.is_file(), "forge_log_retention.py introuvable"
    arbre = ast.parse(SRC_RETENTION.read_text(encoding="utf-8", errors="replace"))
    noms = {
        n.name for n in ast.walk(arbre)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_purge_workspace_tmp" in noms, (
        "la zone tmp du workspace n'est purgee par personne : 4112 fichiers "
        "mesures le 2026-09-08"
    )


def test_la_purge_lit_le_MEME_chemin_que_le_poseur():
    """Deux notions du chemin tmp = une purge qui rate sa cible.

    C'est le meme defaut que le poseur a deux sites, vu depuis l'autre bout.
    """
    source = SRC_RETENTION.read_text(encoding="utf-8", errors="replace")
    assert "chemin_tmp_sandbox" in source, (
        "la purge doit demander le chemin au point unique du module de lancement, "
        "jamais le reconstruire"
    )
