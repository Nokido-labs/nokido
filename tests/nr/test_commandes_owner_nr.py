"""NR -- commandes a taper par l'owner : deposees par un agent AUTHENTIFIE via la porte generique du hub
(`hub action=demander_ordre ordre=commande-deposer`), listees et copiees par le tray, marquees faites par lui.

Demande owner 2026-10-16 : « on a systematiquement besoin d'un suivi parallele pour des commandes a taper, ne pourrait-on
pas les stocker dans un presse-papier accessible via la tray tant qu'elles ne sont pas traitees ? » -- option (a) :
depot authentifie par le hub (pas un fichier de sandbox/ que tout processus local forgerait). Le tray COPIE, il
n'execute jamais une commande deposee.

Ecrit en TDD (owner 16/10, trois lois) : chaque test est vu ROUGE avant le code qui le satisfait.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def ob(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app import forge_ordres_bureau as m
    monkeypatch.setattr(m, "JOURNAL", tmp_path / "ordres.jsonl")
    monkeypatch.setattr(m, "COMMANDES", tmp_path / "commandes_owner.jsonl", raising=False)
    return m


def test_une_commande_deposee_par_un_agent_est_acceptee(ob):
    r = asyncio.run(ob.demander_ordre("CLAUDE", "commande-deposer", "armer le mode DEV pour retirer un clair",
                                      texte='& "python.exe" "tools\\forge_dev_mode.py" arm'))
    assert r["etat"] == ob.DEPOSE, r


def test_la_commande_deposee_attend_l_owner_avec_son_auteur(ob):
    asyncio.run(ob.demander_ordre("CLAUDE", "commande-deposer", "armer le mode DEV", texte="cmd x"))
    r = asyncio.run(ob.demander_ordre("TRAY", "commandes-en-attente"))
    assert [(c["demandeur"], c["texte"], c["raison"]) for c in r["commandes"]] == [("CLAUDE", "cmd x",
                                                                                    "armer le mode DEV")], r


def test_une_commande_qui_porte_un_secret_est_refusee_et_rien_n_est_stocke(ob):
    """Une commande transite par le tray et le presse-papier : un jeton y serait expose. Refus au DEPOT."""
    jeton = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    r = asyncio.run(ob.demander_ordre("CLAUDE", "commande-deposer", "connexion", texte="gh auth login --with-token " + jeton))
    assert r["etat"] == ob.REFUSE and ob.commandes_en_attente() == [], r


def test_seul_le_tray_marque_une_commande_faite(ob):
    """Le tray (session owner) marque une commande traitee ; un agent ne peut pas la faire disparaitre a sa place."""
    cid = asyncio.run(ob.demander_ordre("CLAUDE", "commande-deposer", "x", texte="cmd y"))["commande"]
    refus = asyncio.run(ob.demander_ordre("CLAUDE", "commande-faite", cible=cid))
    fait = asyncio.run(ob.demander_ordre("TRAY", "commande-faite", cible=cid))
    assert (refus["etat"], fait["etat"], ob.commandes_en_attente()) == (ob.REFUSE, "FAITE", []), (refus, fait)


TRAY = ROOT / "tools" / "nokido_tray.py"


def test_le_tray_releve_et_affiche_les_commandes_a_taper():
    """Le tray (pystray, coffre) n'est pas importe en test -- convention des NR du tray : on teste l'organe (ci-dessus)
    et la SOURCE. Il releve la liste par la porte generique et la montre dans un sous-menu."""
    src = TRAY.read_text(encoding="utf-8")
    assert '"ordre": "commandes-en-attente"' in src and "Commandes à taper" in src


def test_le_tray_copie_et_marque_sans_jamais_executer_une_commande_deposee():
    """Un clic COPIE le texte dans le presse-papier, un autre marque la commande faite (commande-faite). Le texte depose
    n'atteint jamais subprocess : c'est l'owner qui choisit de le coller (AST : le code, pas les commentaires)."""
    import ast

    arbre = ast.parse(TRAY.read_text(encoding="utf-8"))
    fonctions = {n.name: n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef)}
    for nom in ("_copier_commande", "_presse_papier", "_marquer_commande"):
        assert nom in fonctions, nom
    for nom in ("_copier_commande", "_presse_papier"):
        appels = {ast.unparse(n.func) for n in ast.walk(fonctions[nom]) if isinstance(n, ast.Call)}
        assert not any(a.startswith("subprocess") for a in appels), (nom, appels)
    assert "commande-faite" in ast.unparse(fonctions["_marquer_commande"])
