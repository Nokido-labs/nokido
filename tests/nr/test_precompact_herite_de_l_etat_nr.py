"""NR — une compaction HÉRITE de l'état précédent, elle ne repart pas des derniers tours.

## Le défaut, mesuré le 2026-09-19

`forge_session_provenance` attache `compaction_seq` et `parent_summary_id` à
chaque résumé : la **filiation** était enregistrée. Mais `claude_precompact`
n'avait **aucune occurrence** de ces deux clefs — `_build_prompt(payload,
session_id)` ne recevait que les derniers tours.

```
avant :  resume N = f(derniers tours)
apres :  resume N = f(resume N-1, delta)
```

La chaîne existait ; la continuité sémantique, non. Conséquence concrète : une
décision prise tôt et **non re-mentionnée** disparaissait dès la deuxième
compaction, alors qu'elle restait vraie. C'est la forme la plus coûteuse de
perte, parce qu'elle est **silencieuse** : un résumé reparti de zéro se lit
exactement comme un résumé normal.

## Ce qui est verrouillé ici

Que le parent soit RELU, que le prompt demande une mise à jour d'état (et non un
résumé), et que l'absence de parent retombe proprement sur le comportement
d'origine — une première compaction n'a rien à hériter.
"""
from __future__ import annotations

import ast
import importlib.util as _u
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

SOURCE = RACINE / "tools" / "claude_precompact.py"


def _module():
    """Chargé par chemin : ce fichier est un HOOK, pas un module importable."""
    spec = _u.spec_from_file_location("cpc_nr", SOURCE)
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_sans_parent_le_comportement_d_origine_est_intact():
    """Contrôle négatif : une première compaction n'hérite de rien."""
    m = _module()
    p = m._build_prompt("HISTORIQUE_TEMOIN", "sid-test", None)
    assert "HISTORIQUE_TEMOIN" in p
    assert "ÉTAT PRÉCÉDENT" not in p, (
        "sans parent, le prompt ne doit pas parler d'un etat qui n'existe pas")
    assert "session_id" in p, "le contrat de sortie JSON a disparu"


def test_avec_parent_le_prompt_demande_une_MISE_A_JOUR():
    m = _module()
    parent = {"compaction_seq": 7, "decisions": ["DECISION_TEMOIN"],
              "open_bugs": ["BUG_TEMOIN"], "key_context": "ETAT_TEMOIN"}
    p = m._build_prompt("NOUVEAUX_TOURS_TEMOIN", "sid-test", parent)

    assert "ÉTAT PRÉCÉDENT" in p
    assert "DECISION_TEMOIN" in p, "l'etat herite n'est pas transmis au modele"
    assert "ETAT_TEMOIN" in p
    assert "NOUVEAUX_TOURS_TEMOIN" in p, "le delta doit rester present"
    # L'instruction qui fait TOUT le travail : ne pas répéter n'est pas annuler.
    assert "CONSERVE" in p
    assert "n'est pas" in p or "pas l'annuler" in p, (
        "le prompt doit dire explicitement qu'un element non re-mentionne reste vrai")


def test_le_parent_ne_transmet_PAS_les_champs_inutiles():
    """`tools_used` et la provenance gonfleraient le prompt sans rien porter."""
    m = _module()
    parent = {"compaction_seq": 2, "decisions": ["D"], "tools_used": ["OUTIL_TEMOIN"],
              "parent_summary_id": "PARENT_ID_TEMOIN", "_source": "SOURCE_TEMOIN"}
    p = m._build_prompt("T", "sid", parent)
    assert "OUTIL_TEMOIN" not in p, "tools_used n'a pas a etre reinjecte"
    assert "PARENT_ID_TEMOIN" not in p
    assert "SOURCE_TEMOIN" not in p


def test_le_chemin_REEL_relit_le_parent_avant_de_construire_le_prompt():
    """AST : sans cet appel, la fonction d'heritage existerait sans etre utilisee.

    C'est la dette de cablage que ce depot paye ailleurs — un mecanisme present
    et non appele n'est pas une capacite.
    """
    arbre = ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))
    appelle_parent, passe_au_prompt = False, False
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            nom = n.func.id if isinstance(n.func, ast.Name) else (
                n.func.attr if isinstance(n.func, ast.Attribute) else "")
            if nom == "_dernier_resume":
                appelle_parent = True
            if nom == "_build_prompt" and len(n.args) >= 3:
                passe_au_prompt = True
    assert appelle_parent, "_dernier_resume n'est appele nulle part"
    assert passe_au_prompt, (
        "_build_prompt est appele sans le parent : l'heritage est ecrit mais pas cable")


def test_un_parent_illisible_ne_casse_PAS_la_compaction(monkeypatch):
    """Fail-soft assume : perdre l'heritage est regrettable, perdre le resume serait pire."""
    m = _module()
    monkeypatch.setattr(m, "DB", Path("/chemin/qui/n/existe/pas/x.db"))
    assert m._dernier_resume("sid-test") is None
    # et la construction du prompt reste possible
    p = m._build_prompt("T", "sid-test", None)
    assert "T" in p


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
