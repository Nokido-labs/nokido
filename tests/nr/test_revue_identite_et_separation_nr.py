# -*- coding: utf-8 -*-
"""NR — la revue porte une identite, et le garde de separation REFUSE vraiment.

Audit securite du 2026-09-18, finding #9. L'enonce disait « une branche de revue
qu'aucun chemin n'invoque ». La mesure a dit mieux, et autrement :

`enforce_separation` sait juger `task.review`. Cette branche n'avait AUCUN
appelant -- et pas par oubli : `forge_review` ne portait AUCUNE identite. Le
garde exige un `actor_agent` ; l'information n'existait pas au point d'appel,
donc l'appel etait IMPOSSIBLE, pas omis.

S'y ajoutait que les six appelants passaient tous `approved` en litteral : le
juge n'avait jamais refuse quoi que ce soit.

DEUX PIEGES PAYES EN ECRIVANT LE CORRECTIF, chacun teste ici :

1. `enforce_separation` RETOURNE `(bool, motif)`, elle ne LEVE PAS. Un premier
   jet l'appelait sous `except PermissionError` : le refus aurait ete ignore en
   silence. Le garde se serait relu comme actif en ne gardant rien -- exactement
   le defaut qu'on ferme.

2. Le garde resout l'executant dans `sandbox/tasks.db`, table `tasks`. Or
   `forge_review` travaille sur `agent_tasks`, dans une base DIFFERENTE : lui
   passer l'identifiant nu n'aurait trouve aucune ligne, donc AUCUN controle --
   un appel qui rend « autorise » parce qu'il n'a rien pu lire.

MORSURE : un acteur DIFFERENT de l'executant doit passer. Sans ce controle, un
garde qui refuse tout passerait les tests de refus en cassant l'usage normal.
"""

from __future__ import annotations

__FORGE_COLOR__ = "immunitaire/separation : le juge n'est pas le producteur"

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app.forge_separation import enforce_separation  # noqa: E402

SRC = RACINE / "app" / "forge_task_bus.py"


def test_le_garde_REFUSE_l_auto_validation():
    """Le comportement, pas la presence : un agent ne valide pas son travail."""
    ok, motif = enforce_separation(actor_agent="CLAUDE", action="task.review",
                                   target={"to_agent": "CLAUDE"})
    assert ok is False, "un agent peut valider son propre travail"
    assert "own task" in motif or "separation" in motif.lower()


def test_MORSURE_un_juge_DISTINCT_passe():
    """CONTROLE NEGATIF — sans lui, un garde qui refuse tout semblerait correct."""
    ok, motif = enforce_separation(actor_agent="GEMINI", action="task.review",
                                   target={"to_agent": "WORKER_CODE"})
    assert ok is True, f"un juge distinct est refuse a tort : {motif}"


def test_le_garde_refuse_la_collusion_par_lignage():
    """Deux noms differents, meme lignage : c'est encore soi-meme.

    Temoin MESURE (`_lineage`) : GEMINI et AGY rendent tous deux `google`.
    Un premier jet utilisait CLAUDE/cli_claude en SUPPOSANT la correspondance --
    elle n'existe pas, voir le test suivant. Un temoin se verifie.
    """
    ok, motif = enforce_separation(actor_agent="GEMINI", action="task.review",
                                   target={"to_agent": "agy"})
    assert ok is False, "la collusion par lignage n'est pas vue"
    assert "lineage" in motif.lower() or "collusion" in motif.lower()


def test_TROU_NOMME_la_surface_CLI_CLAUDE_n_a_aucun_lignage():
    """Trouve en choisissant mal un temoin, le 2026-09-18.

    `CLAUDE` rend le lignage `anthropic` ; `cli_claude` rend **None**. Or les
    regles du depot nomment explicitement cette surface `CLAUDE`/cli_claude :
    c'est le MEME modele derriere un autre point d'entree. La collusion par
    lignage ne se declencherait donc pas entre ces deux-la.

    Ce test ECHOUERA le jour ou la carte sera completee -- et c'est voulu : il
    tient la mesure, pas le souhait. Le corriger alors, en connaissance de cause.
    """
    from app.forge_separation import _lineage, normalize_agent

    assert _lineage(normalize_agent("CLAUDE")) == "anthropic"
    assert _lineage(normalize_agent("cli_claude")) is None, (
        "la carte de lignage a ete completee : retirer ce test et verifier que la "
        "collusion CLAUDE/cli_claude est desormais refusee"
    )


def test_la_revue_ACCEPTE_un_acteur():
    """Sans parametre d'acteur, l'appel au garde est IMPOSSIBLE, pas omis."""
    import inspect

    from app.forge_task_bus import forge_review

    params = inspect.signature(forge_review).parameters
    assert "acteur" in params, "la revue ne porte toujours aucune identite"
    assert params["acteur"].kind is inspect.Parameter.KEYWORD_ONLY, (
        "l'acteur doit etre keyword-only : les six appelants historiques passent "
        "leurs arguments positionnellement"
    )
    assert params["acteur"].default is None, (
        "un defaut non nul fabriquerait une identite — pire qu'aucune"
    )


def test_le_refus_du_garde_est_LU_pas_attendu_en_exception():
    """Piege n°1, rendu executable.

    On lit l'appel dans l'AST : sa valeur de retour doit etre DEPAQUETEE.
    Un appel dont le resultat est jete laisserait passer tout refus.
    """
    arbre = ast.parse(SRC.read_text(encoding="utf-8"))
    appels = [n for n in ast.walk(arbre)
              if isinstance(n, ast.Call)
              and getattr(n.func, "id", None) == "enforce_separation"]
    assert appels, "le garde n'est plus appele depuis la revue"
    # l'appel doit etre le membre droit d'une affectation a deux cibles
    affectations = [n for n in ast.walk(arbre)
                    if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                    and getattr(n.value.func, "id", None) == "enforce_separation"
                    and isinstance(n.targets[0], ast.Tuple)
                    and len(n.targets[0].elts) == 2]
    assert affectations, (
        "le retour de `enforce_separation` n'est pas depaquete en (ok, motif) : "
        "un refus serait ignore en silence"
    )


def test_aucun_except_PermissionError_autour_du_garde():
    """Piege n°1, second angle : la forme fautive ne doit pas revenir.

    Relu par AST. Une premiere version cherchait le TEXTE, et accusait le
    COMMENTAIRE qui decrit la forme interdite -- huitieme occurrence du meme
    motif dans la journee. L'AST ne porte pas les commentaires.
    """
    arbre = ast.parse(SRC.read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(arbre)
              if isinstance(n, ast.FunctionDef) and n.name == "forge_review")
    fautifs = [
        h.lineno for h in ast.walk(fn)
        if isinstance(h, ast.ExceptHandler)
        and h.type is not None
        and "PermissionError" in ast.dump(h.type)
    ]
    assert not fautifs, (
        f"la revue attend une exception que le garde ne leve jamais, lignes {fautifs}"
    )


def test_l_executant_est_lu_dans_la_BONNE_table():
    """Piege n°2, rendu executable.

    Le garde resout l'executant dans `tasks` ; la revue vit dans `agent_tasks`.
    Passer l'identifiant nu ne trouverait rien et rendrait « autorise ».
    """
    src = SRC.read_text(encoding="utf-8")
    bloc = src[src.index("def forge_review"):]
    assert "FROM agent_tasks WHERE id=?" in bloc, (
        "l'executant n'est pas lu dans agent_tasks"
    )
    assert '"to_agent"' in bloc or "'to_agent'" in bloc, (
        "le garde recoit un identifiant nu au lieu d'un dict portant l'executant : "
        "il ne trouverait aucune ligne et n'appliquerait aucun controle"
    )


def test_une_revue_ANONYME_est_journalisee_pas_silencieuse():
    """La dette subsiste pour les six appelants historiques — elle est DITE.

    Les casser d'un coup remplacerait un trou par une panne ; une revue anonyme
    qui ne se distingue pas d'une revue attribuee, en revanche, est un faux calme.
    """
    src = SRC.read_text(encoding="utf-8")
    bloc = src[src.index("def forge_review"):]
    # 2026-09-26 : la dette #9 est SOLDEE (1af81abd6, 24/09, AUTH-6) -- une revue anonyme n'est plus
    # seulement journalisee puis approuvee, elle est REFUSEE (fail-closed). Le test suit la decision :
    # le refus doit etre DIT, avec sa raison.
    assert "ANONYME" in bloc and "REFUSEE" in bloc and "AUTH-6" in bloc, (
        "l'absence d'acteur passe en silence"
    )
