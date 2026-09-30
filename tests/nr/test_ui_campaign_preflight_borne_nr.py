"""NR — le pré-contrôle du harnais UI ne peut pas attendre indéfiniment.

## Ce qui a été mesuré le 2026-09-19

La campagne `ui-acceptance` a tourné **1 662 s avec 0 s de CPU**, tenant la CI
de référence en otage, alors qu'elle déclare un budget de 480 s.

Cause : `_BUDGET_S` garde la **boucle des routes**. Il est évalué à chaque tour,
donc seulement une fois le navigateur obtenu. Un blocage **avant** la boucle —
au lancement du harnais — ne le rencontre jamais.

```
    lancement du harnais   <-- blocage ici
            |
            v
    boucle des routes      <-- _BUDGET_S evalue SEULEMENT ici
```

Et le blocage est attendu par construction : Playwright est **inopérant sous le
compte de service** et n'y lève aucune erreur — il attend, en silence.

## Ce que ce test verrouille

Que le pré-contrôle soit enveloppé d'une borne, et que son dépassement produise
`INDISPONIBLE` — le troisième état que ce module utilise déjà — et non un
verdict « contrat violé », qui serait faux : on n'a rien jugé, faute d'outil.

⚠️ Ce test lit la STRUCTURE, pas le comportement : démarrer une vraie campagne
demanderait un navigateur, c'est-à-dire précisément ce qui manque. Il mord donc
sur la régression qui compte — le retrait de la borne — et il le dit.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

SOURCE = RACINE / "tools" / "forge_ui_campaign.py"


def _arbre() -> ast.Module:
    assert SOURCE.exists(), "la campagne UI a disparu : %s" % SOURCE
    return ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))


def test_le_preflight_est_enveloppe_d_une_borne():
    """`_harnais_absent()` doit être appelé SOUS `asyncio.wait_for`."""
    arbre = _arbre()
    nus, bornes = [], []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Await):
            continue
        v = n.value
        if not isinstance(v, ast.Call):
            continue
        fn = v.func
        nom = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
        if nom == "_harnais_absent":
            nus.append(n.lineno)
        elif nom == "wait_for":
            for s in ast.walk(v):
                if isinstance(s, ast.Call):
                    f2 = s.func
                    n2 = f2.attr if isinstance(f2, ast.Attribute) else (
                        f2.id if isinstance(f2, ast.Name) else "")
                    if n2 == "_harnais_absent":
                        bornes.append(n.lineno)
    assert bornes, (
        "le pre-controle du harnais n'est pas borne : un blocage au lancement du "
        "navigateur echappe a _BUDGET_S, qui ne garde que la boucle des routes. "
        "Mesure du 2026-09-19 : 1 662 s a 0 %% de CPU, CI de reference bloquee.")
    assert not nus, (
        "un appel NU a _harnais_absent subsiste (l.%s) : il peut attendre sans "
        "fin sous un compte sans navigateur" % nus)


def test_la_borne_du_preflight_est_reglable_et_RAISONNABLE():
    """Une borne doit exister, être configurable, et rester bien sous le budget global."""
    import os

    src = SOURCE.read_text(encoding="utf-8", errors="replace")
    assert "_BUDGET_PREFLIGHT_S" in src, "la borne du pre-controle n'est pas nommee"
    assert "LAFORGE_UI_PREFLIGHT_S" in src, (
        "la borne doit etre reglable par l'environnement, comme _BUDGET_S")

    # On lit la valeur par defaut sans importer le module (il tire playwright).
    arbre = _arbre()
    defaut = None
    for n in ast.walk(arbre):
        if isinstance(n, ast.Assign):
            for c in n.targets:
                if isinstance(c, ast.Name) and c.id == "_BUDGET_PREFLIGHT_S":
                    for s in ast.walk(n.value):
                        if isinstance(s, ast.Constant) and isinstance(s.value, str):
                            try:
                                defaut = float(s.value)
                            except ValueError:
                                pass
    assert defaut is not None, "valeur par defaut de la borne introuvable"
    assert 5 <= defaut <= 180, (
        "borne de %s s : trop courte elle refuserait un demarrage lent, trop "
        "longue elle laisserait la CI bloquee" % defaut)


def test_le_depassement_rend_INDISPONIBLE_et_pas_un_verdict_de_violation():
    """On n'a rien jugé : dire « contrat violé » serait une accusation fausse."""
    # ⚠️ Ancrer sur le BON site. Chercher « TimeoutError » tombait sur
    # `_est_nav_timeout`, defini plus haut et sans rapport : le test analysait
    # une fenetre qui n'etait pas son sujet. On vise la clause qui garde le
    # pre-controle, reconnaissable a `asyncio.TimeoutError`.
    src = SOURCE.read_text(encoding="utf-8", errors="replace")
    i = src.find("except asyncio.TimeoutError")
    assert i > 0, (
        "aucune clause `except asyncio.TimeoutError` : le depassement du "
        "pre-controle n'est pas traite")
    fenetre = src[i:i + 900]
    assert "INDISPONIBLE" in fenetre or "_absent" in fenetre, (
        "le depassement doit alimenter le chemin INDISPONIBLE, pas un echec de contrat")
    assert "LAFORGE_UI_AUTO" in fenetre, (
        "le message doit dire quoi FAIRE : relancer sous un compte avec navigateur, "
        "ou desarmer l'auto-detection")


def test_le_budget_de_boucle_existe_toujours():
    """Contrôle négatif : on AJOUTE une borne, on n'en remplace aucune."""
    src = SOURCE.read_text(encoding="utf-8", errors="replace")
    assert "_BUDGET_S" in src and "LAFORGE_UI_BUDGET_S" in src, (
        "le budget de la boucle des routes a disparu : les deux bornes sont "
        "complementaires, elles gardent des phases differentes")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
