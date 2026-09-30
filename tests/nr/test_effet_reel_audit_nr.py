#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""NR — les quatre familles de « mecanisme present, effet nul » qui RECIDIVENT.

Mandat owner du 2026-09-16 : « verifier que chaque mecanisme qui existe, se relit
comme actif, et a un effet reel ». L'audit de phase 1 a montre que SIX familles
sont deja instrumentees (reachability_ledger, capability_contracts,
capability_execution_trace, body_regulation_audit, regulation_efficacy,
vitalite_gardes) et que QUATRE ne le sont pas -- precisement celles qui ont ete
payees plusieurs fois :

  A. GARDE SANS EMETTEUR      un signal LU que personne n'ECRIT.
                              Paye : `INSULIN_VECTORIZATION` lu a 0.0 en
                              permanence, frein jamais declenche ; `llama.wanted`
                              pose par 1 reveilleur sur 6 -> 73 arrets, 312,94 Go
                              recharges en 7,6 jours.
  B. INTERRUPTEUR OUBLIE      `disabled = true` dont la raison n'est ecrite nulle
                              part. Paye le 2026-09-16 : le commit 43b769366
                              « pilier local reouvert » a borne les args, traite
                              la cause de l'ecartement, et n'a JAMAIS leve
                              l'interrupteur. Dix jours d'embedding local mort.
  C. ARTEFACT DEVANT PREEXISTER, non versionne. Paye 2x : le gate `anatomie`
                              vert 3x en local et rouge au premier passage sur le
                              runner (lisait `module_cards.json`, non versionne) ;
                              et `pip_audit_*.json` ecrit dans `sandbox/`, que
                              `.gitignore` ecarte, donc invisible du worktree
                              detache qui doit le juger.
  D. POLITIQUE A N CHEMINS    une politique lue par UN SEUL des N chemins qui la
                              doivent. Paye 2x : `embed()` respectait
                              `pillar_policy.json` quand `embed_batch_fast`, le
                              chemin REEL, ne la lisait pas ; et
                              `.git-publish-rules.json` lu par le seul push
                              gouverne quand trois outils de publication
                              l'ignoraient.

CE QUE CES TESTS EXIGENT, et c'est le point : chaque detecteur est une fonction
PURE, qui recoit des donnees et rend un verdict. La collecte (lire le disque, git,
le TOML) est separee. Un detecteur qui ne serait testable qu'en lisant le vrai
depot ne serait pas gardable -- c'est le defaut meme qu'on traque.

ETAT ATTENDU : rouge tant que `tools/forge_effet_reel_audit.py` n'existe pas.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _audit():
    try:
        import forge_effet_reel_audit as m
    except Exception as e:  # noqa: BLE001
        pytest.fail("tools/forge_effet_reel_audit.py introuvable ou non importable "
                    "(%s: %s)" % (type(e).__name__, e))
    return m


# ---------------------------------------------------------------------------
# A. GARDE SANS EMETTEUR
# ---------------------------------------------------------------------------

def test_un_signal_lu_sans_aucun_ecrivain_est_signale():
    m = _audit()
    res = m.signaux_sans_emetteur(
        lectures={"INSULIN_VECTORIZATION": ["forge_rag_warmup.py"]},
        ecritures={})
    assert [r["signal"] for r in res] == ["INSULIN_VECTORIZATION"], res
    assert res[0]["lecteurs"] == ["forge_rag_warmup.py"]


def test_un_signal_ecrit_par_quelqu_un_n_est_PAS_signale():
    """Symetrie obligatoire : un garde arme n'est pas un defaut."""
    m = _audit()
    assert m.signaux_sans_emetteur(
        lectures={"docker.wanted": ["reclaimer.py"]},
        ecritures={"docker.wanted": ["forge_docker_agent.py"]}) == []


def test_l_asymetrie_des_emetteurs_est_rendue_pas_seulement_l_absence():
    """`llama.wanted` avait UN emetteur sur SIX chemins producteurs : la panne
    n'etait pas une absence, c'etait une MINORITE. Un detecteur binaire
    present/absent l'aurait ratee."""
    m = _audit()
    res = m.signaux_sans_emetteur(
        lectures={"llama.wanted": ["a.py", "b.py", "c.py", "d.py"]},
        ecritures={"llama.wanted": ["un_seul.py"]},
        ratio_alerte=0.5)
    assert [r["signal"] for r in res] == ["llama.wanted"], res
    assert res[0]["motif"] == "MINORITAIRE", res[0]


def test_un_signal_ni_lu_ni_ecrit_n_est_pas_invente():
    m = _audit()
    assert m.signaux_sans_emetteur(lectures={}, ecritures={}) == []


# ---------------------------------------------------------------------------
# B. INTERRUPTEUR OUBLIE
# ---------------------------------------------------------------------------

_TOML = """
[[service]]
name = "AvecMotif"
# 2026-09-06 : coupe faute de RAM, a re-mesurer apres bornage.
disabled = true

[[service]]
name = "SansMotif"
disabled = true

[[service]]
name = "CommenteSansDate"
# coupe parce que ca ne marchait pas
disabled = true

[[service]]
name = "Actif"
port = 1234
"""


def test_un_interrupteur_sans_motif_date_est_signale():
    m = _audit()
    res = m.interrupteurs_sans_motif(_TOML)
    noms = sorted(r["service"] for r in res)
    assert noms == ["CommenteSansDate", "SansMotif"], res


def test_un_interrupteur_AVEC_motif_date_ne_l_est_pas():
    m = _audit()
    assert "AvecMotif" not in [r["service"] for r in m.interrupteurs_sans_motif(_TOML)]


def test_un_service_actif_n_est_jamais_signale():
    m = _audit()
    assert "Actif" not in [r["service"] for r in m.interrupteurs_sans_motif(_TOML)]


def test_le_detecteur_rend_le_DENOMINATEUR():
    """Une liste sans son total se lit comme une catastrophe ou comme rien. Le
    dossier du 2026-09-16 disait 25 sur 35 disabled sur 91 services -- les trois
    nombres ensemble, jamais le premier seul."""
    m = _audit()
    tot = m.compter_services(_TOML)
    assert tot == {"services": 4, "actifs": 1, "disabled": 3}, tot


# ---------------------------------------------------------------------------
# C. ARTEFACT DEVANT PREEXISTER
# ---------------------------------------------------------------------------

def test_un_artefact_LU_sans_etre_ecrit_et_ignore_est_signale():
    m = _audit()
    res = m.artefacts_a_preexister(
        sites=[{"artefact": "sandbox/module_cards.json", "module": "census.py",
                "ecrit_ici": False}],
        est_ignore=lambda p: True)
    assert [r["artefact"] for r in res] == ["sandbox/module_cards.json"], res


def test_un_artefact_que_le_module_ECRIT_n_est_pas_signale():
    """Une SORTIE a le droit d'etre ignoree : elle est produite par le run. C'est
    le cas de 5 des 6 artefacts examines le 2026-09-16 -- les compter aurait
    fabrique cinq faux positifs."""
    m = _audit()
    assert m.artefacts_a_preexister(
        sites=[{"artefact": "sandbox/engrid_audit.json", "module": "forge_engrid_audit.py",
                "ecrit_ici": True}],
        est_ignore=lambda p: True) == []


def test_un_artefact_VERSIONNE_n_est_pas_signale():
    m = _audit()
    assert m.artefacts_a_preexister(
        sites=[{"artefact": "sandbox/workspace/organ_map_full.json",
                "module": "census.py", "ecrit_ici": False}],
        est_ignore=lambda p: False) == []


def test_un_artefact_lu_par_DEUX_modules_dont_un_l_ecrit_n_est_pas_signale():
    """Producteur et consommateur distincts : le fichier EXISTE au moment de la
    lecture. Ne pas confondre avec un artefact que personne ne produit."""
    m = _audit()
    sites = [
        {"artefact": "sandbox/x.json", "module": "producteur.py", "ecrit_ici": True},
        {"artefact": "sandbox/x.json", "module": "lecteur.py", "ecrit_ici": False},
    ]
    assert m.artefacts_a_preexister(sites=sites, est_ignore=lambda p: True) == []


# ---------------------------------------------------------------------------
# D. POLITIQUE A N CHEMINS
# ---------------------------------------------------------------------------

def test_une_politique_a_lecteur_UNIQUE_parmi_N_chemins_est_signalee():
    m = _audit()
    res = m.politiques_a_lecteur_unique(
        lecteurs={"config/pillar_policy.json": ["forge_embed_router.embed"]},
        chemins_du_domaine={"config/pillar_policy.json":
                            ["forge_embed_router.embed",
                             "forge_embed_router.embed_batch_fast"]})
    assert [r["politique"] for r in res] == ["config/pillar_policy.json"], res
    assert res[0]["chemins_sans_lecture"] == ["forge_embed_router.embed_batch_fast"]


def test_une_politique_lue_par_TOUS_ses_chemins_n_est_pas_signalee():
    m = _audit()
    assert m.politiques_a_lecteur_unique(
        lecteurs={"p.json": ["a", "b"]},
        chemins_du_domaine={"p.json": ["a", "b"]}) == []


def test_une_politique_sans_chemin_declare_reste_INDETERMINEE_pas_saine():
    """Ne pas savoir quels chemins DEVRAIENT la lire n'est pas une preuve que
    tous la lisent. UNKNOWN n'est ni NO ni YES."""
    m = _audit()
    res = m.politiques_a_lecteur_unique(
        lecteurs={"p.json": ["a"]}, chemins_du_domaine={})
    assert [r["motif"] for r in res] == ["INDETERMINE"], res


# ---------------------------------------------------------------------------
# CE QUE LA PREMIERE PASSE REELLE A CORRIGE -- et qui ne doit pas revenir
# ---------------------------------------------------------------------------

def test_la_famille_A_est_DELEGUEE_et_non_re_derivee():
    """J'ai declare cette famille « sans instrument » apres une recherche par NOM
    qui couvrait reachab/capability/regulation/vitalite et jamais signal ni
    intention. Elle EST instrumentee : forge_signal_coupling (avec une policy
    fail_closed/fail_open par signal), forge_endocrine.orphans(), et
    forge_audit_intention_effet."""
    m = _audit()
    a = m.famille_A_deleguee()
    assert a["motif"] == "DEJA_INSTRUMENTE", a
    assert any("signal_coupling" in x for x in a["delegue_a"]), a


def test_la_collecte_STATIQUE_des_signaux_a_ete_retiree():
    """Elle annoncait `docker.wanted : AUCUN_EMETTEUR` alors que
    `forge_docker_agent.ensure_daemon` le pose (WANT_FLAG l.47), et `snn.wanted`
    alors que le commit 2b4445855 l'emet. forge_signal_coupling l'avait ecrit
    avant moi : un grep sur llama.wanted rendait 14 lectures et 0 ecriture, et
    c'etait FAUX, l'ecriture passant par CIBLES[cible]['drapeau']. Un emetteur se
    CONSTATE a l'execution."""
    m = _audit()
    assert not hasattr(m, "collecte_signaux"), (
        "la collecte par regex est revenue : elle produit des faux orphelins, et "
        "neutraliser un faux orphelin SUPPRIME une protection"
    )


def test_les_etats_runtime_ne_sont_pas_des_artefacts_de_preuve():
    """Premiere passe : 28 artefacts annonces, dont a2a.log, git_proxy.log,
    *.heartbeat et llama.wanted -- tous crees par le service EN TOURNANT. Un
    artefact d'ETAT n'est pas un artefact de PREUVE."""
    m = _audit()
    for suffixe in (".log", ".heartbeat", ".wanted", ".pid"):
        assert suffixe in m._SUFFIXES_RUNTIME, suffixe


def test_une_famille_partiellement_couverte_NOMME_ce_qu_elle_ne_voit_pas():
    """Premiere passe : la famille D affichait « 0 politique a lecture partielle »
    alors que sa collecte n'existait pas -- un zero obtenu sans avoir regarde, donc
    un VERT, le defaut meme que cet outil traque, reproduit sur lui-meme.

    Elle est desormais collectee, mais a la granularite FICHIER. Or le defaut de
    `pillar_policy.json` etait INTRA-module : `embed()` lisait la politique,
    `embed_batch_fast()` du meme fichier ne la lisait pas. Une collecte par fichier
    ne peut pas le voir -- et doit donc le DIRE, au lieu de rendre un vert sur une
    granularite qu'elle n'atteint pas."""
    m = _audit()
    assert hasattr(m, "CARTE_POLITIQUES"), "la carte n'est pas declaree"
    assert hasattr(m, "POLITIQUES_HORS_PORTEE"), (
        "rien ne nomme ce que la collecte ne couvre PAS : le silence y passera "
        "pour une absence de defaut"
    )
    assert "pillar_policy" in " ".join(m.POLITIQUES_HORS_PORTEE), (
        "le defaut intra-module qui a motive cette famille n'est pas declare "
        "hors portee"
    )
    src = (RACINE / "tools" / "forge_effet_reel_audit.py").read_text(encoding="utf-8")
    assert "politiques_a_lecteur_unique({}, {})" not in src, (
        "appel a vide restaure : il fabrique un vert sans mesure"
    )


def test_la_carte_des_politiques_nomme_TOUS_les_chemins_de_publication():
    """Le P0 du 2026-09-15 a aligne trois outils de publication sur le manifeste,
    apres qu'un seul le lisait. Le gate existe pour que cela ne se defasse pas."""
    m = _audit()
    attendus = m.CARTE_POLITIQUES.get(".git-publish-rules.json") or []
    for chemin in ("forge_git_egress.py", "forge_public_mirror.py",
                   "forge_dist_publish.py"):
        assert chemin in attendus, chemin


# ---------------------------------------------------------------------------
# L'AUDITEUR EST LUI-MEME SOUMIS A SA PROPRE REGLE
# ---------------------------------------------------------------------------

def test_l_auditeur_ne_lit_pas_son_propre_vocabulaire():
    """Un instrument qui se scanne lui-meme se signale lui-meme : paye 5 fois en
    trois jours dans ce depot. Sa source est exclue de la collecte."""
    m = _audit()
    assert hasattr(m, "FICHIERS_EXCLUS"), (
        "aucune exclusion declaree : l'auditeur va lire ses propres exemples"
    )
    assert any("forge_effet_reel_audit" in x for x in m.FICHIERS_EXCLUS)


def test_le_cliquet_de_capacites_est_CABLE_lui_aussi():
    """`forge_capability_ratchet` existait depuis le 2026-08-16, avec un socle
    VERSIONNE et un NR... et aucun gate ne le lancait. Le registre mesure 165 noms
    de surface MCP pour 58 prouves par usage, et l'instrument capable de surveiller
    la derive de ces contrats n'etait appele par personne.

    Un cliquet que rien ne declenche ne cliquette pas."""
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert "forge_capability_ratchet.py" in src, (
        "le cliquet de capacites n'est lance par aucun gate : outil present, "
        "effet nul"
    )


def test_le_cliquet_de_capacites_DIT_quand_sa_matrice_manque():
    """Il a fait rougir la CI DEUX FOIS de suite sur un arbre sain, parce que sa
    matrice vit dans `sandbox/*.json` -- gitignore, donc TOUJOURS absente du
    worktree detache de `--reference`. C'est la famille C de cet audit appliquee a
    lui-meme : un artefact devant PREEXISTER que le depot ne porte pas.

    Le remede n'est pas de le desarmer ni de lui inventer un suppleant non
    verifie : c'est de DIRE qu'on n'a pas mesure, et de nommer ce qui manque.
    Un `[skip]` muet serait un vert."""
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8")
    i = src.find("capacites-cliquet : matrice absente")
    assert i > 0, (
        "l'absence de matrice ne se dit pas : elle passera en echec critique, ou "
        "pire, en silence"
    )
    fenetre = src[i:i + 400]
    assert "NON MESURE" in fenetre, "le skip ne dit pas que ce n'est pas un succes"
    assert "forge_regression_matrix" in fenetre, (
        "le message ne dit pas COMMENT produire la mesure manquante"
    )


def test_l_auditeur_est_CABLE_a_la_ci():
    """Le premier resultat de l'audit du 2026-09-16 : les instruments qui mesurent
    l'effet reel n'ont eux-memes aucun appelant. Un auditeur non lance est
    exactement le defaut qu'il traque."""
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8")
    assert "forge_effet_reel_audit" in src, (
        "l'auditeur n'est lance par personne : mecanisme present, effet nul"
    )
