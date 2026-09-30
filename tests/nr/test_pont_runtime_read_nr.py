"""NR — la seconde portee du pont n'atteint pas les outils de la premiere.

Ouverture du 2026-09-19 : la passerelle exposee a un assistant externe rendait le
code COMMITE (GitHub) mais rien du RUNTIME — ni le processus qui tourne, ni la
base ouverte, ni les files qui attendent. `runtime:read` ouvre cela en LECTURE.

L'ORDRE A ETE TENU, et c'est le sujet de ce test. Le 2026-09-18, la portee etait
verifiee UNE FOIS a la porte (`scope not in portees`) : sain tant qu'il n'y en
avait qu'une, puisque la porte ET la capacite coincidaient. Un fil de detente
(`test_pont_portee_par_outil_nr`) exigeait qu'une seconde portee arrive AVEC sa
table `outil -> portee`. La table a donc ete posee AVANT, puis la portee.

Sans elle, l'elargissement de la porte — qui accepte desormais deux portees et
deux ressources — aurait donne a un jeton d'OBSERVATION l'acces aux operations
GitHub, et a un jeton GitHub l'acces au runtime. Ce test mesure les quatre cases
de la matrice, pas seulement les deux qui marchent.

LA RESSOURCE SE VERIFIE SELON LA PORTEE. Une habilitation GitHub est liee a UN
depot que l'appelant doit redire : c'est ce qui empeche un jeton d'un depot d'en
lire un autre. Une habilitation runtime porte l'instance, qu'aucun argument
client ne designe. Exiger un `repo` la rendrait inutilisable ; accepter n'importe
quoi retirerait la liaison a la ressource pour tout le monde.
"""

import sys
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

P = pytest.importorskip("tools.forge_github_bridge")


@pytest.fixture()
def sans_reseau(monkeypatch):
    """Aucune operation GitHub ne doit partir : un refus qui a deja appele le
    reseau n'est pas un refus. On compte les appels."""
    partis = []
    table = dict(P._TABLE)
    for k in table:
        if k != "runtime_observe":
            table[k] = lambda a, _k=k: (partis.append(_k), (True, {"op": _k}))[1]
    monkeypatch.setattr(P, "_TABLE", table)
    return partis


def _cap(scope, ressource):
    return P.forger_capacite({
        "aud": P.AUDIENCE, "scope": scope, "resource": ressource,
        "exp": time.time() + 60, "jti": "nr" + str(time.time_ns()),
        "sub": "nr", "replay": "multi",
    })


def _depot():
    return sorted(P.DEPOTS_AUTORISES)[0]


def test_la_portee_runtime_n_atteint_pas_les_operations_github(sans_reseau):
    """LA MORSURE — la case de la matrice qui justifie toute la table."""
    ok, motif = P.traiter("branch_head", {"repo": _depot()},
                          _cap(P.SCOPE_RUNTIME, P.RESSOURCE_RUNTIME))
    assert not ok, "un jeton d'observation atteint les operations GitHub"
    assert "portee" in str(motif).lower(), f"le refus ne nomme pas la portee : {motif}"
    assert not sans_reseau, "un appel GitHub est parti malgre le refus"


def test_la_portee_github_n_atteint_pas_le_runtime(sans_reseau):
    """MORSURE SYMETRIQUE — l'autre sens compte autant."""
    ok, motif = P.traiter("runtime_observe", {"portee": "identite"},
                          _cap(P.SCOPE, _depot()))
    assert not ok, "un jeton GitHub atteint l'observation du runtime"
    assert "portee" in str(motif).lower(), f"le refus ne nomme pas la portee : {motif}"


def test_chaque_portee_atteint_LA_SIENNE(sans_reseau):
    """NON-REGRESSION — une frontiere qui bloque tout n'est pas une frontiere."""
    ok, _ = P.traiter("branch_head", {"repo": _depot()}, _cap(P.SCOPE, _depot()))
    assert ok, "la portee GitHub n'atteint plus ses propres operations"
    ok2, res = P.traiter("runtime_observe", {"portee": "identite"},
                         _cap(P.SCOPE_RUNTIME, P.RESSOURCE_RUNTIME))
    assert ok2, f"la portee runtime n'atteint pas l'observation : {res}"


def test_une_habilitation_runtime_liee_a_un_depot_est_refusee(sans_reseau):
    """La ressource reste liee, meme quand l'appelant ne la redit pas."""
    ok, motif = P.traiter("runtime_observe", {"portee": "identite"},
                          _cap(P.SCOPE_RUNTIME, _depot()))
    assert not ok and "ressource" in str(motif).lower(), motif


def test_toute_operation_exposee_est_classee():
    """Liste BLANCHE : une operation ajoutee sans portee serait REFUSEE, jamais
    autorisee par defaut. Le test le verifie sur la table REELLE."""
    non_classees = sorted(set(P._TABLE) - set(P.PORTEE_PAR_OUTIL))
    assert not non_classees, (
        f"operations exposees sans portee declaree : {non_classees} — elles "
        "seraient refusees, mais surtout personne n'a decide de leur frontiere"
    )


def test_l_observation_reste_en_lecture_seule():
    """Ce qu'on ouvre a un tiers ne doit pas pouvoir AGIR. Verifie par AST sur
    l'organe, pas sur sa docstring : un dictionnaire qui affiche READ_ONLY ne
    garantit rien."""
    import ast

    src = (RACINE / "app" / "forge_runtime_observer.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    interdits = {"system", "popen", "run", "call", "check_output", "eval", "exec",
                 "Popen", "spawn"}
    fautifs = [
        ast.unparse(n)[:70] for n in ast.walk(arbre)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr in interdits
        and getattr(getattr(n.func, "value", None), "id", "") in {"os", "subprocess", "sp"}
    ]
    assert not fautifs, f"l'organe d'observation peut AGIR : {fautifs}"


def test_une_portee_d_observation_inconnue_se_corrige_seule():
    """PAS un refus, et c'est voulu : l'organe nomme l'inconnu et ENUMERE les
    portees valides, pour qu'un appelant distant se corrige sans nous ecrire.
    Un refus sec l'enverrait chercher une panne qui n'existe pas."""
    ok, res = P.traiter("runtime_observe", {"portee": "portee_qui_n_existe_pas"},
                        _cap(P.SCOPE_RUNTIME, P.RESSOURCE_RUNTIME))
    assert ok, "une portee inconnue produit un refus au lieu d'un constat"
    assert "inconnu" in res, res
    assert any("portees disponibles" in str(l) for l in res.get("limites", [])), (
        "le constat ne dit pas quelles portees existent : l'appelant ne peut pas "
        "se corriger"
    )
