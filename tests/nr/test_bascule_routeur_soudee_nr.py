"""Non-regression : le POINT DE BASCULE du routeur est SOUDE dans le chemin reel.

DEFAUT MESURE le 2026-09-08, en travaillant l'entree B1 de la roadmap de veille.
Deux affirmations du depot ne peuvent pas etre vraies en meme temps :

  - `forge_retrieval_router.fusionner` se declare "LE POINT DE BASCULE, et le seul",
    et promet que "passer de l'un a l'autre ne demande aucun autre changement
    architectural -- c'est la condition posee par l'owner" ;
  - `forge_rag_engine` ecrit, a son site d'observation : "aucune ligne en aval ne
    consomme `_rt_dec`", et n'importe que `decider` et `observer`.

Mesure : `fusionner` n'a AUCUN appelant hors tests. Poser
`LAFORGE_ROUTER_MODE=active` aujourd'hui ne changerait donc STRICTEMENT RIEN au
ranking. C'est le motif deja paye deux fois -- un mecanisme present mais non cable
est une dette de cablage, jamais une capacite -- et il est ici invisible en lecture
de code, parce que les deux moities sont justes chacune de son cote.

CE QUE CE FICHIER PROUVE, ET CE QU'IL NE PROUVE PAS.
  - niveau CABLAGE (tests 1, 2, 4) : lecture AST de `app/forge_rag_engine.py`. Le
    cablage EST une propriete de la source ; un test qui monterait un moteur complet
    mesurerait autre chose et demanderait la base de 24,9 Go. La limite est assumee
    et dite : ces trois tests prouvent que l'appel EXISTE, est ALIMENTE et se trouve
    AVANT la consommation -- pas que la fusion soit bonne.
  - niveau MECANIQUE (test 3) : fixture a la forme REELLE (rangs construits comme le
    moteur les construit, par `enumerate` de deux classements) prouvant qu'en ACTIVE
    l'ordre CHANGE. Sans lui, souder l'appel sur un mecanisme mort passerait tous les
    tests de cablage.

Aucune fixture ici ne vaut mesure de QUALITE : la baseline (`is_technical`, booleen
qui multiplie le rang lexical par 1,2) reste a battre, et se bat avec un banc, pas
avec un test d'inertie.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "app",):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_retrieval_router as rr  # noqa: E402

MOTEUR = RACINE / "app" / "forge_rag_engine.py"
ROUTEUR_MOD = "forge_retrieval_router"
BASCULE = "fusionner"


def _arbre():
    """Source du moteur, en AST. Un fichier illisible est DIT, jamais avale : sans
    cette distinction, un test vert ne se distinguerait pas d'un test aveugle."""
    if not MOTEUR.exists():
        pytest.fail(f"ILLISIBLE : {MOTEUR} absent -- ce test n'a rien pu regarder")
    try:
        src = MOTEUR.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - chemin d'illisibilite
        pytest.fail(f"ILLISIBLE : {MOTEUR} ({exc!r}) -- ce test n'a rien pu regarder")
    return ast.parse(src)


def _nom_appele(call: ast.Call) -> str:
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _noms_locaux_de_bascule(arbre) -> set:
    """Les noms LOCAUX sous lesquels `fusionner` est appelable dans ce fichier.

    PIEGE DEJA PAYE (2026-09-08, `forge_mcp_registry`) : chercher le nom BRUT rate
    tout import aliase. Le moteur importe `fusionner as _rt_fusionner` -- un
    detecteur litteral aurait declare le cablage absent alors qu'il etait la, et on
    aurait "corrige" du code sain. On resout l'alias, on ne devine pas.
    """
    noms = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(ROUTEUR_MOD):
            for a in n.names:
                if a.name == BASCULE:
                    noms.add(a.asname or a.name)
    return noms


def _affectations_de_bascule(arbre) -> list[ast.Assign]:
    """Les `combined = fusionner(...)`. On exige la REAFFECTATION : un appel dont le
    resultat est jete serait un appel decoratif, vert au grep et sans effet."""
    locaux = _noms_locaux_de_bascule(arbre)
    trouves = []
    for n in ast.walk(arbre):
        if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Call):
            continue
        if _nom_appele(n.value) not in locaux:
            continue
        cibles = [t.id for t in n.targets if isinstance(t, ast.Name)]
        if "combined" in cibles:
            trouves.append(n)
    return trouves


def _lignes_de_consommation(arbre) -> list[int]:
    """Ou `combined` est LU pour produire le classement (`combined.items()`)."""
    lignes = []
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Attribute) and n.attr == "items"
                and isinstance(n.value, ast.Name) and n.value.id == "combined"):
            lignes.append(n.lineno)
    return lignes


def test_le_moteur_importe_le_point_de_bascule():
    """Importer `decider` et `observer` sans `fusionner`, c'est observer sans pouvoir
    agir : exactement l'etat mesure le 2026-09-08."""
    arbre = _arbre()
    importes = {
        a.name
        for n in ast.walk(arbre)
        if isinstance(n, ast.ImportFrom) and (n.module or "").endswith(ROUTEUR_MOD)
        for a in n.names
    }
    assert importes, (
        f"{MOTEUR.name} n'importe RIEN de {ROUTEUR_MOD} : le routeur n'est pas branche")
    assert BASCULE in importes, (
        f"{MOTEUR.name} importe {sorted(importes)} mais pas `{BASCULE}` -- le mode "
        "ACTIVE serait inerte, et le basculer ne changerait rien au ranking")


def test_la_bascule_est_soudee_et_realimente_le_classement():
    """L'appel doit REAFFECTER `combined`. Sinon la fusion est calculee puis jetee."""
    arbre = _arbre()
    aff = _affectations_de_bascule(arbre)
    assert aff, (
        f"aucun `combined = {BASCULE}(...)` dans {MOTEUR.name} : le point de bascule "
        "existe et n'a pas d'appelant dans le chemin reel")


def test_la_bascule_recoit_bien_des_RANGS():
    """`fusionner(combined, decision)` sans rangs rend `combined` QUOI QU'IL ARRIVE
    (garde interne `if not rangs`). Un cablage sans troisieme argument alimente serait
    donc soude ET inerte -- la pire des deux, parce qu'il se relit comme fait."""
    arbre = _arbre()
    aff = _affectations_de_bascule(arbre)
    if not aff:
        pytest.skip("cablage absent : deja dit par test_la_bascule_est_soudee")
    for a in aff:
        call = a.value
        args = list(call.args)
        kw = {k.arg: k.value for k in call.keywords}
        troisieme = args[2] if len(args) >= 3 else kw.get("rangs")
        assert troisieme is not None, (
            f"ligne {call.lineno} : {BASCULE}() appele sans `rangs` -- il rendra "
            "toujours l'entree, le mode ACTIVE resterait sans effet")
        assert not (isinstance(troisieme, ast.Constant) and troisieme.value in (None, {})), (
            f"ligne {call.lineno} : `rangs` est une constante vide -- cablage inerte")


def test_la_fusion_precede_la_consommation_du_classement():
    """Fusionner APRES avoir consomme `combined` serait un no-op silencieux."""
    arbre = _arbre()
    aff = _affectations_de_bascule(arbre)
    conso = _lignes_de_consommation(arbre)
    if not aff:
        pytest.skip("cablage absent : deja dit par test_la_bascule_est_soudee")
    assert conso, (
        "aucun `combined.items()` trouve : la forme du moteur a change, ce test ne "
        "mesure plus ce qu'il croit mesurer -- le relire avant de le croire")
    assert min(a.lineno for a in aff) < min(conso), (
        f"la fusion (l.{min(a.lineno for a in aff)}) arrive APRES la consommation "
        f"(l.{min(conso)}) : elle ne peut plus influencer le classement")


def test_la_mecanique_change_bien_l_ordre_en_ACTIVE(monkeypatch):
    """SIMULATION a la forme reelle. Le moteur construit ses rangs par `enumerate` de
    deux classements (`dr` dense, `sr` lexical) ; on reproduit cette forme, pas une
    forme commode. Garde anti-'souder sur un mecanisme mort'."""
    dense = [(7, 0.91), (3, 0.88), (1, 0.42)]      # -> dr
    lexical = [(1, 12.0), (7, 3.0), (3, 0.5)]      # -> sr

    rang_dense = {idx: r for r, (idx, _) in enumerate(dense)}
    rang_lex = {idx: r for r, (idx, _) in enumerate(lexical)}
    idxs = set(rang_dense) | set(rang_lex)
    rangs = {i: (rang_lex.get(i), rang_dense.get(i)) for i in idxs}

    combined = {}
    for r, (idx, _) in enumerate(dense):
        combined[idx] = combined.get(idx, 0.0) + 1.0 / (60 + r + 1)
    for r, (idx, _) in enumerate(lexical):
        combined[idx] = combined.get(idx, 0.0) + 1.0 / (60 + r + 1)

    monkeypatch.delenv("LAFORGE_ROUTER_MODE", raising=False)
    d_shadow = rr.decider("qu'est-ce que la couverture de Markov d'un organe",
                          {"vector": "AVAILABLE"})
    assert rr.fusionner(combined, d_shadow, rangs) is combined, "SHADOW a mute le classement"

    monkeypatch.setenv("LAFORGE_ROUTER_MODE", rr.ACTIVE)
    d_actif = rr.decider("qu'est-ce que la couverture de Markov d'un organe",
                         {"vector": "AVAILABLE"})
    sortie = rr.fusionner(combined, d_actif, rangs)
    assert sortie is not combined, "ACTIVE a rendu l'objet d'entree : mecanisme mort"
    assert sorted(sortie, key=sortie.get, reverse=True) != sorted(
        combined, key=combined.get, reverse=True), (
        "ACTIVE n'a pas change l'ordre sur une requete conceptuelle : le profil ne "
        "pese pas, souder le cablage sur ce mecanisme ne servirait a rien")
