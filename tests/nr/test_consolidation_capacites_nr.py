# -*- coding: utf-8 -*-
"""Non-regression — la consolidation retrospective propose ce qui compte, une fois.

`forge_capability_consolidation` est le CONSOMMATEUR qui manquait a huit phases
d'archeologie : sans lui, `forgotten_capabilities.md` restait un fichier que
personne n'ouvrait (mesure 2026-08-28 : 1017 vestiges annonces, rapport vieux de
12,7 jours, aucun appelant hors du chainage interne des phases).

CE QUI EST GARDE — chacun est un defaut MESURE au premier essai reel du module :

1. DEDUPLICATION. Le meme fichier apparait sous plusieurs depots (`nokido:` et
   `nokido-redteam:` portent le meme `forge_ctf_runner`). Sans dedup, une seule
   capacite consommait deux places du plafond.
2. LE VOLUME N'EST PAS LA VALEUR. Le premier tri, par LOC, remontait un runner CTF
   de 708 lignes devant `forge_cerberus_x` (221 lignes) — qui porte pourtant
   snapshot / apply / validate / ROLLBACK, la capacite de rollback de mutation qui
   manque au corps.
3. TROIS ETATS pour l'absence : un module DEPLACE dans app/ ou tools/ est VIVANT.
   Le declarer perdu ferait crier le rapport a faux, et un rapport qui crie a faux
   se fait ignorer — exactement le sort du fichier qu'on essaie de ressusciter.
4. UNE SUPPRESSION QUI NOMME SA CIBLE EST UNE DECISION. La reprendre serait
   desobeir. Seul le dommage COLLATERAL se remonte.
5. DRY-RUN PAR DEFAUT : ce module inscrit des obligations qui pesent sur tous les
   tours suivants. Il ne doit rien ecrire tant qu'on n'a pas regarde.

6. LE LECTEUR DU REGISTRE NE DOIT PAS ETRE MUET (2026-08-29). La priorite donnee a
   ce qu'un TEST prouvait (`HISTORICALLY_PROVEN`) a d'abord ete branchee sur les
   cles `constituants` / `entrees` — alors que le registre expose `fiches`. Elle
   rendait ZERO nom : un cablage MORT, dans le module meme qui existe pour empecher
   les artefacts sans consommateur. Un lecteur qui rend toujours l'ensemble vide est
   indiscernable d'une absence de registre.

Hermetique : vestiges synthetiques, aucune lecture du vrai rapport, aucune dette.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

conso = pytest.importorskip("forge_capability_consolidation")


def _vestige(chemin, loc=100, commit="chore: cleanup", date="2026-04-16", score=1.0):
    return {"cible": "nokido:" + chemin, "chemin": chemin, "loc": loc, "score": score,
            "date": date, "commit": commit, "intention": "", "symboles": ""}


# ───────────────────────────────────────────── absence : trois etats

def test_un_module_deplace_n_est_pas_perdu():
    """`forge_generation.py` vit dans app/ : cite sous un autre chemin, il est VIVANT."""
    assert conso.encore_absent(_vestige("vieux/dossier/forge_generation.py")) is False


def test_un_module_reellement_absent_est_vu():
    assert conso.encore_absent(_vestige("app/forge_qui_n_a_jamais_existe_xyz.py")) is True


# ────────────────────────────────── decision vs dommage collateral

def test_un_commit_qui_nomme_sa_cible_est_une_decision():
    v = _vestige("app/forge_truc.py", commit="refactor: supprime forge_truc, remplace par X")
    assert conso.collateral(v) is False, "une suppression deliberee ne doit pas etre remontee"


def test_un_cleanup_qui_parle_d_autre_chose_est_collateral():
    v = _vestige("app/forge_truc.py", commit="chore: clean hackathon branch — remove 651 files")
    assert conso.collateral(v) is True


def test_un_commit_neutre_n_est_pas_collateral():
    """Contre-epreuve : sans motif de menage, on ne presume rien."""
    v = _vestige("app/forge_truc.py", commit="feat: nouvelle API de routage")
    assert conso.collateral(v) is False


# ─────────────────────────────────────── classement et unicite

def test_le_meme_fichier_n_est_propose_qu_une_fois():
    a = _vestige("tools/ctf/forge_ctf_runner.py", loc=708)
    b = dict(a, cible="nokido-redteam:tools/ctf/forge_ctf_runner.py")
    cles = [conso._cle_dette(c) for c in conso.candidats([a, b])]
    assert len(cles) == len(set(cles)), "doublon : deux depots, une seule capacite"


def test_le_coeur_passe_devant_un_silo_plus_gros():
    """LE defaut corrige : un runner CTF de 708 lignes ne prime pas sur un moteur
    de rollback de 221 lignes."""
    silo = _vestige("tools/ctf/forge_ctf_runner.py", loc=708)
    coeur = _vestige("forge_cerberus_x.py", loc=221)
    ordre = [c["chemin"] for c in conso.candidats([silo, coeur])]
    assert ordre[0] == "forge_cerberus_x.py", ordre


def test_le_collateral_passe_devant_la_decision():
    decide = _vestige("app/forge_aaa_decide.py", loc=900,
                      commit="refactor: supprime forge_aaa_decide")
    subi = _vestige("app/forge_zzz_subi.py", loc=10, commit="chore: reorg cleanup")
    ordre = [c["chemin"] for c in conso.candidats([decide, subi])]
    assert ordre[0] == "app/forge_zzz_subi.py", ordre


# ─────────────────── JAMAIS rapatrier l'offensif deporte (decision owner)

def test_ctf_recon_exegol_jamais_proposes():
    """Decision owner : le coeur est DEFENSIF, l'offensif vit en depot prive. Ces
    capacites ne sont pas perdues, elles sont DEPORTEES -- les proposer serait
    re-flaguer le coeur et defaire l'isolement. Mesure 2026-08-28 : le premier
    classement les remontait, parce que 'refactor(ctf): isolate CTF organ' n'etait
    pas lu comme une decision de domaine."""
    offensifs = [
        _vestige("tools/ctf/forge_ctf_runner.py", loc=708,
                 commit="refactor(ctf): isolate CTF organ"),
        _vestige("recon_silo/recon_master.py", loc=441,
                 commit="refactor(ctf): isolate CTF organ"),
        _vestige("forge_exegol_bridge.py", loc=445, commit="refacto(reorg): cleanup"),
        _vestige("app/forge_pwn_solver.py", loc=300, commit="chore: cleanup"),
        _vestige("app/forge_exploit_gen.py", loc=300, commit="chore: cleanup"),
    ]
    retenus = [c["chemin"] for c in conso.candidats(offensifs)]
    assert retenus == [], "un domaine offensif a ete propose a la reintegration : %s" % retenus


def test_est_offensif_reconnait_les_domaines():
    for p in ("tools/ctf/x.py", "recon_silo/y.py", "forge_exegol_bridge.py",
              "app/forge_pwn_z.py", "app/forge_exploit_a.py"):
        assert conso.est_offensif(p) is True, p


def test_est_offensif_ne_mord_pas_le_defensif():
    """Contre-epreuve : un garde qui jette le legitime avec l'offensif est inutile.
    forge_cerberus_x (rollback) et forge_firewall ne sont PAS offensifs."""
    for p in ("forge_cerberus_x.py", "app/forge_semantic_firewall.py",
              "app/forge_generation.py", "app/forge_rag_engine.py"):
        assert conso.est_offensif(p) is False, p


def test_cerberus_le_rollback_reste_recuperable():
    """Le moteur de rollback defensif ne doit PAS etre ecarte par le filtre
    offensif : son nom evoque l'offensif, sa fonction est la sauvegarde."""
    v = _vestige("forge_cerberus_x.py", loc=221, commit="refacto(reorg): cleanup")
    assert v["chemin"] in [c["chemin"] for c in conso.candidats([v])]


# ───────────────────────────────────── le module n'ecrit pas tout seul

def test_dry_run_par_defaut_n_ouvre_aucune_dette(monkeypatch, tmp_path):
    vide = tmp_path / "absent.md"
    monkeypatch.setattr(conso, "VESTIGES_MD", vide)
    r = conso.consolider()
    assert r["dry_run"] is True
    assert r.get("ouvertes", []) == []


def test_sans_rapport_il_le_dit_au_lieu_d_inventer(monkeypatch, tmp_path):
    monkeypatch.setattr(conso, "VESTIGES_MD", tmp_path / "absent.md")
    r = conso.consolider()
    assert "erreur" in r and "forge_archaeology" in r["erreur"], r


def test_un_rapport_perime_est_signale(monkeypatch, tmp_path):
    """Agir sur une carte de 12 jours, c'est risquer de ressusciter du deja repris."""
    p = tmp_path / "vestiges.md"
    p.write_text("_3 vestiges enrichis._\n", encoding="utf-8")
    import os
    vieux = __import__("time").time() - 30 * 86400
    os.utime(p, (vieux, vieux))
    monkeypatch.setattr(conso, "VESTIGES_MD", p)
    r = conso.consolider()
    assert r["perime"] is True and "avertissement" in r


def test_le_plafond_borne_les_obligations(monkeypatch, tmp_path):
    """Ouvrir 1017 dettes noierait les dettes vivantes : le remede serait pire."""
    p = tmp_path / "vestiges.md"
    p.write_text("_1017 vestiges enrichis._\n", encoding="utf-8")
    monkeypatch.setattr(conso, "VESTIGES_MD", p)
    faux = [_vestige("app/forge_absent_%d.py" % i, loc=i) for i in range(50)]
    monkeypatch.setattr(conso, "lire_vestiges", lambda *a, **k: faux)
    r = conso.consolider(plafond=3)
    assert len(r["proposees"]) <= 3


def test_le_rapport_distingue_detaille_et_annonce(monkeypatch, tmp_path):
    """Un top-20 ne doit pas se lire comme un inventaire complet."""
    p = tmp_path / "vestiges.md"
    p.write_text("_1017 vestiges enrichis._\n", encoding="utf-8")
    monkeypatch.setattr(conso, "VESTIGES_MD", p)
    monkeypatch.setattr(conso, "lire_vestiges", lambda *a, **k: [])
    r = conso.consolider()
    assert r["vestiges_annonces_par_l_entete"] == 1017
    assert r["vestiges_detailles_dans_le_rapport"] == 0


def _ecrire_registre(tmp_path, fiches):
    """Registre synthetique : le test ne lit jamais le vrai rapport."""
    import json as _j
    p = tmp_path / "reachability.json"
    p.write_text(_j.dumps({"fiches": fiches}), encoding="utf-8")
    return p


def test_le_lecteur_du_registre_n_est_pas_muet(tmp_path):
    """Regression 2026-08-29 : branche sur `constituants`/`entrees` alors que le
    registre expose `fiches`, le lecteur rendait ZERO nom -- cablage MORT dans le
    module meme qui existe pour empecher les artefacts sans consommateur."""
    p = _ecrire_registre(tmp_path, [
        {"nom": "forge_arbitrator", "etat": "HISTORICALLY_PROVEN"},
        {"nom": "processed_at", "etat": "UNPROVEN"},
        {"nom": "forge_litellm", "etat": "ORPHELIN"},
    ])
    assert conso._noms_historiquement_prouves(p) == {"forge_arbitrator"}


def test_registre_absent_ne_bloque_pas_mais_ne_ment_pas(tmp_path):
    """Pas de registre -> repli sur l'ordre precedent. On ne bloque pas la
    consolidation, on ne pretend pas non plus avoir mesure."""
    assert conso._noms_historiquement_prouves(tmp_path / "absent.json") == set()


def test_format_inattendu_ne_passe_pas_pour_un_registre_vide(tmp_path):
    import json as _j
    p = tmp_path / "r.json"
    p.write_text(_j.dumps({"autre_cle": [1, 2]}), encoding="utf-8")
    assert conso._noms_historiquement_prouves(p) == set()


def test_la_preuve_fait_remonter_un_candidat(tmp_path, monkeypatch):
    """Entre deux vestiges, celui dont un TEST demontrait l'usage passe devant."""
    monkeypatch.setattr(conso, "_PROUVES_CACHE", {"forge_arbitrator"})
    v = [
        {"chemin": "app/forge_zzz.py", "loc": 900, "intention": "", "depot": "nokido"},
        {"chemin": "app/forge_arbitrator.py", "loc": 10, "intention": "", "depot": "nokido"},
    ]
    monkeypatch.setattr(conso, "encore_absent", lambda x: True)
    monkeypatch.setattr(conso, "collateral", lambda x: False)
    monkeypatch.setattr(conso, "_est_coeur", lambda x: False)
    ordre = [c["chemin"] for c in conso.candidats(v)]
    assert ordre[0] == "app/forge_arbitrator.py", (
        "le vestige PROUVE doit primer sur le plus volumineux")
