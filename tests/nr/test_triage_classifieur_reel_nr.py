"""Non-regression : le triage local/cloud appelle un symbole qui EXISTE.

DEFAUT MESURE le 2026-09-12 par execution reelle (`sandbox/mesure_am1_multi_intention.py`,
job `job_cb2dce8821fd`). `forge_hybrid_cortex._triage` contenait :

    try:
        from nokido_agent.app.forge_nlu import FastClassifier
        if FastClassifier().classify(prompt) == "chat":
            return False, "forge_nlu=chat (local)"
    except Exception:  # muet-ok : affinage best-effort, jamais bloquant
        pass
    return True, "raisonnement cloud (par defaut)"

`FastClassifier` **n'existe pas** dans `forge_nlu` — ni sous le nom plat, ni sous
le nom namespace. Le module s'importe (ce n'est donc pas une affaire de chemin),
mais le symbole n'y est cite que dans une DOCSTRING. `CLAUDE.md` l'annonce pourtant
comme le thalamus de tri de Nokido : un nom present partout sauf dans le code.

Consequence mesuree sur 8 prompts : **8/8 partis au cloud**, tous sous le meme
motif « raisonnement cloud (par defaut) », dont 5 purement conversationnels. Le
compteur `motif_forge_nlu_jamais_emis` vaut `true` : l'affinage souverain n'a
jamais tourne une seule fois depuis l'ecriture du module.

C'est la forme exacte du motif consigne dans `RULES_SHARED.md` — « un garde
branche sur un signal que PERSONNE n'emet » — aggrave par un `except: pass` qui
avale un `ImportError` PERMANENT. Le code se relit comme protege ; la mesure dit
que la branche locale est morte depuis toujours.

⚠️ PORTEE HONNETE : `forge_hybrid_cortex` a **zero importeur** hors de lui-meme
(`get_cortex()` n'est appele nulle part). Ce defaut n'a donc AUCUN cout de tokens
observable aujourd'hui — c'est une dette de cablage, pas une fuite en cours. Il est
corrige parce qu'un import mort dans un `except` muet est une bombe a retardement
le jour ou le module sera cable, pas parce qu'il couterait quelque chose ce matin.

Ce fichier est ecrit ROUGE avant le correctif.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app", RACINE / "tools"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

SOURCE = RACINE / "app" / "forge_hybrid_cortex.py"


def _arbre() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))


def _corps(nom: str) -> ast.FunctionDef:
    for n in ast.walk(_arbre()):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == nom:
            return n
    raise AssertionError(f"fonction {nom} introuvable dans {SOURCE.name}")


def _symboles_importes_de(fn: ast.AST, module_suffixe: str) -> set[str]:
    """Noms importes depuis un module dont le chemin finit par `module_suffixe`."""
    noms: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(module_suffixe):
            noms.update(a.name for a in n.names)
    return noms


def test_tout_symbole_importe_de_forge_nlu_par_le_triage_existe_vraiment():
    """Le coeur du defaut. On ne relit pas le code : on IMPORTE le module cible et
    on demande a Python si le symbole y est."""
    import importlib

    demandes = _symboles_importes_de(_corps("_triage"), "forge_nlu")
    assert demandes, (
        "_triage n'importe plus rien de forge_nlu : le triage souverain a disparu "
        "au lieu d'etre repare"
    )
    mod = importlib.import_module("forge_nlu")
    manquants = sorted(n for n in demandes if not hasattr(mod, n))
    assert not manquants, (
        f"_triage importe de forge_nlu des symboles ABSENTS : {manquants}. "
        f"forge_nlu exporte notamment : "
        f"{sorted(n for n in dir(mod) if not n.startswith('_'))[:12]}"
    )


def test_le_triage_ne_ravale_pas_l_echec_du_classifieur_en_silence():
    """Un `except: pass` transforme un classifieur MORT en verdict « cloud ».
    Le gestionnaire doit journaliser ou rendre un motif qui nomme l'etat."""
    fn = _corps("_triage")
    for n in ast.walk(fn):
        if not isinstance(n, ast.ExceptHandler):
            continue
        muet = all(isinstance(s, (ast.Pass, ast.Expr)) and
                   not isinstance(getattr(s, "value", None), ast.Call)
                   for s in n.body)
        assert not muet, (
            "chemin d'erreur MUET dans _triage : l'indisponibilite du classifieur "
            "est indiscernable d'un verdict « cloud » rendu par le classifieur"
        )


def test_les_trois_etats_du_classifieur_ont_des_motifs_DISTINCTS():
    """UNKNOWN n'est pas NO. « classifieur illisible », « classifieur non entraine »
    et « le classifieur a repondu » sont trois faits differents ; s'ils sortent sous
    le meme motif, aucun operateur ne peut distinguer une panne d'une decision."""
    fn = _corps("_triage")
    motifs = {
        n.value for n in ast.walk(fn)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) > 8
    }
    par_defaut = [m for m in motifs if "par defaut" in m]
    assert len(par_defaut) >= 2, (
        f"un seul motif de repli : {sorted(motifs)}. Les trois etats du classifieur "
        "doivent etre discernables dans la trace"
    )
    assert any("ILLISIBLE" in m or "illisible" in m for m in motifs), (
        f"aucun motif ne nomme l'etat ILLISIBLE : {sorted(motifs)}"
    )


def test_le_triage_appelle_reellement_le_classifieur_et_non_seulement_l_importe():
    """Un import ne prouve pas un appel. La branche locale doit consommer un VOTE."""
    fn = _corps("_triage")
    src = ast.unparse(fn)
    assert "predict(" in src, (
        "aucun appel a predict() : le classifieur est importe sans etre interroge"
    )
    assert "confident" in src, (
        "le vote est utilise sans consulter `confident` : une prediction peu sure "
        "serait traitee comme une certitude"
    )


# ---------------------------------------------- contre-epreuve du detecteur
def test_le_detecteur_de_symbole_absent_attrape_bien_un_absent():
    """Symetrie : verifier que le test du haut echouerait s'il y avait un absent.
    Sans cela, un detecteur casse rendrait un vert rassurant."""
    import importlib

    mod = importlib.import_module("forge_nlu")
    assert not hasattr(mod, "FastClassifier"), (
        "FastClassifier existe desormais dans forge_nlu — ce NR a ete ecrit sur "
        "la mesure inverse, le relire avant de le modifier"
    )
    faux = {"get_router_if_ready", "FastClassifier"}
    manquants = sorted(n for n in faux if not hasattr(mod, n))
    assert manquants == ["FastClassifier"], (
        f"le detecteur ne distingue pas present/absent : {manquants}"
    )
