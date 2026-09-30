"""NR M0.1 — le modèle de confiance ne doit pas pouvoir se blanchir lui-même.

⚠️ AVERTISSEMENT QUI FAIT PARTIE DU CONTRAT
    Le vert de ce NR ne vaut PAS « le système est sûr ». Il vaut seulement :
    « le modèle rapporte encore honnêtement ce qui a été mesuré ». La sécurité
    réelle du poste n'est jamais SEPARATION_PROUVEE tant que M0.1 n'est pas
    résolu — elle vaut NON_CERTIFIANT (travail inachevé) ou
    BLOCKED_BY_ENVIRONMENT (mené jusqu'à la frontière d'autorité du client).
    L'assertion porte sur cet INVARIANT, pas sur le libellé : un test qui fige
    un mot casse au premier renommage sans que rien de ce qu'il garde n'ait
    bougé, et apprend à le contourner.

CE QUE CE FICHIER EMPÊCHE
    Un modèle de confiance est un endroit idéal pour se mentir : il suffit de
    retirer une ligne du rapport pour que le verdict s'éclaircisse. Ce NR échoue
    donc si, sans justification mesurée :

      - `TD_ROOT` apparaît comme identifié alors qu'aucun nœud ne l'habite ;
      - une autorité partagée disparaît du rapport ;
      - un `UNKNOWN` (non mesuré) est converti en valeur sûre ;
      - un composant modifiable par le client devient implicitement de confiance ;
      - une preuve auto-certifiée devient acceptable ;
      - un cycle de confiance cesse d'être signalé ;
      - un verdict qui dépend du dépôt est présenté comme indépendant.

FAITS MESURÉS LE 2026-09-12 QUE CE NR VERROUILLE
    - le hub `NokidoMCP` tourne sous `NT AUTHORITY\\Systeme` (GetOwner, pid 12940) ;
    - `governed_edit` s'exécute in-process du hub : décideur et exécuteur confondus ;
    - `TD_CLIENT`, `TD_ENFORCEMENT` et `TD_EVIDENCE` partagent compte et dépôt ;
    - aucun nœud n'habite `TD_ROOT` ;
    - 7 chemins auto-modifiants, dont les tests eux-mêmes et le module M0.

    Les compteurs sont figés par un PLANCHER, pas par une égalité : un chiffre
    exact rendrait le NR faux au premier nœud ajouté, et on l'assouplirait — ce
    qui est exactement la dérive qu'on veut empêcher.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_trust_domains as TD  # noqa: E402


# ------------------------------------------------- le constat reste dit

def test_le_perimetre_reste_honnete():
    """On ne prétend pas l'inviolabilité absolue : l'administrateur de la
    machine sort du périmètre, et le dire fait partie du contrat."""
    r = TD.verdict_m01()
    assert "PROTECTED_AGAINST_CLIENT" in r["perimetre"]
    assert "ABSOLUMENT_INVIOLABLE" not in r["perimetre"].upper().replace(" ", "_") or \
        "pas ABSOLUMENT" in r["perimetre"]


def test_bloque_par_l_environnement_n_est_pas_une_sortie_commode():
    """Anti-triche symetrique : « bloqué » doit se PROUVER comme le reste.

    `BLOCKED_BY_ENVIRONMENT` est une conclusion confortable — elle clôt le
    chantier sans rien livrer. Elle n'est donc admise que si CHAQUE motif porte
    une mesure, l'état de cette mesure, et ce qu'il faudrait pour la lever. Un
    motif sans ces trois champs est une opinion sur la difficulté, pas une
    frontière.
    """
    r = TD.verdict_m01()
    if r["verdict"] != "BLOCKED_BY_ENVIRONMENT":
        return

    blocages = r.get("blocages_environnement") or []
    assert blocages, (
        "verdict BLOCKED_BY_ENVIRONMENT sans aucun motif : le chantier se "
        "declare bloque sans dire par quoi")

    ETATS_ADMIS = ("PROUVE", "NON_PROUVE", "UNKNOWN", "ILLISIBLE")
    for b in blocages:
        for champ in ("motif", "mesure", "etat", "ce_qu_il_faudrait"):
            assert (b.get(champ) or "").strip(), (
                "motif de blocage sans %r : %r" % (champ, b.get("motif")))
        assert any(b["etat"].upper().startswith(e) or e in b["etat"].upper()
                   for e in ETATS_ADMIS), (
            "l'etat du motif %r ne dit pas ce qui est prouve : %r"
            % (b["motif"], b["etat"]))
        assert len(b["mesure"]) > 80, (
            "la mesure du motif %r tient en une ligne — une frontiere se "
            "decrit, sinon elle ne se verifie pas" % (b["motif"],))


def test_une_racine_declaree_non_independante_est_visiblement_marquee():
    """Anti-triche : nommer une racine ne la crée pas.

    CORRIGÉ le 2026-09-12. La version précédente exigeait « si ROOT_IDENTIFIED
    alors ROOT_INDEPENDENCE_PROVEN ». Elle est devenue rouge le jour où la
    mesure a IDENTIFIÉ la vraie racine — l'off-switch humain — et prouvé qu'elle
    n'est PAS indépendante (son état est une ligne de `opsec_state` dans
    `RAG/embeddings.db`, base où le compte client obtient le verrou d'écriture).
    Le test poussait donc à l'une des deux fautes qu'il prétendait empêcher :
    CACHER la racine pour rester vert, ou TRUQUER la preuve. Un garde qui rend
    la mesure honnête impossible se fait désarmer.

    La forme juste ne porte pas sur le DROIT de déclarer, mais sur l'obligation
    de ne pas pouvoir lire le modèle comme « nous avons une racine » : une
    racine déclarée sans preuve d'indépendance doit rester visible comme telle.
    """
    r = TD.verdict_m01()
    v = r["verdicts"]
    if not v["ROOT_IDENTIFIED"]:
        assert not v["ROOT_INDEPENDENCE_PROVEN"], (
            "independance prouvee sans racine identifiee : incoherent")
        return

    if v["ROOT_INDEPENDENCE_PROVEN"]:
        return  # racine identifiee ET prouvee : plus rien a garder ici

    racines = [n for n in TD.graphe_mesure() if n.domaine == TD.TD_ROOT]
    assert racines, (
        "ROOT_IDENTIFIED est vrai sans aucun noeud TD_ROOT au graphe : le "
        "verdict s'auto-declare au lieu de se mesurer")

    marques = {c["noeud"] for c in r["chemins_auto_modifiants"]}
    for n in racines:
        assert n.nom in marques, (
            "la racine %r est declaree, non prouvee independante, et n'apparait "
            "NULLE PART dans chemins_auto_modifiants : le modele se lit alors "
            "comme s'il avait une racine de confiance" % (n.nom,))
        assert (n.mesure or "").strip(), (
            "la racine %r ne porte aucune mesure : une racine sans mesure est "
            "une declaration" % (n.nom,))


def test_le_verdict_global_reste_non_certifiant_tant_que_m01_est_ouvert():
    r = TD.verdict_m01()
    if r["verdicts_manquants"]:
        assert r["verdict"] != "SEPARATION_PROUVEE", (
            "verdict %r alors que M0.1 n'est pas resolu" % (r["verdict"],))


def test_les_autorites_partagees_ne_disparaissent_pas():
    """Le point le plus facile à faire disparaître : il suffit de retirer un
    champ `autorites` pour que la séparation paraisse acquise."""
    r = TD.verdict_m01()
    partagees = r["autorites_partagees"]
    assert len(partagees) >= 10, (
        "le rapport ne liste plus que %d autorite(s) partagee(s) — une "
        "separation ne se gagne pas en cessant de regarder" % len(partagees))
    formes = {p["forme"] for p in partagees}
    assert {"processus", "compte", "fichier"} <= formes, (
        "formes manquantes: %s" % (formes,))


def test_runtime_et_enforcement_partagent_encore_le_processus():
    """Décideur et exécuteur dans le même processus : mesuré, et central."""
    r = TD.verdict_m01()
    memes = [p for p in r["autorites_partagees"]
             if p["forme"] == "processus"
             and set(p["domaines"]) == {TD.TD_RUNTIME, TD.TD_ENFORCEMENT}]
    assert memes, "la confusion runtime/enforcement a disparu du rapport sans mesure"


def test_le_compte_du_hub_reste_declare():
    """SYSTEM n'est pas une racine de confiance : c'est un PRIVILÈGE. Le
    confondre avec une indépendance serait l'erreur suivante."""
    noeuds = TD.graphe_mesure()
    hub = [n for n in noeuds if n.nom == "hub Nokido"]
    assert hub, "le noeud hub a disparu du graphe"
    assert "Systeme" in (hub[0].autorites.get("compte") or ""), (
        "le compte SYSTEM du hub n'est plus declare")


def test_les_chemins_auto_modifiants_restent_signales():
    r = TD.verdict_m01()
    noms = {c["noeud"] for c in r["chemins_auto_modifiants"]}
    for attendu in ("tests de non-regression", "module M0",
                    "selection des tests executes", "gate d'ecriture client"):
        assert attendu in noms, (
            "%r n'est plus signale comme modifiable par l'acteur qu'il "
            "certifie" % attendu)


def test_m0_lui_meme_n_echappe_pas_au_modele():
    """M0 ne se déclare pas spécial : son code, ses tests et la sélection des
    tests exécutés influencent le verdict, donc ce sont des méta-effets."""
    r = TD.verdict_m01()
    noms = {c["noeud"] for c in r["chemins_auto_modifiants"]}
    assert "module M0" in noms


def test_les_non_mesures_restent_listes():
    """Un champ non mesuré doit rester visible. Le convertir en valeur sûre est
    exactement le fail-open qu'on traque depuis le début."""
    r = TD.verdict_m01()
    assert isinstance(r["non_mesures"], list)
    for n in TD.graphe_mesure():
        for champ in (n.qui_peut_modifier, n.qui_peut_appeler,
                      n.qui_peut_observer, n.qui_peut_certifier):
            assert champ is None or isinstance(champ, str), (
                "un booleen a remplace un acteur : UNKNOWN ne doit pas devenir safe")


# ------------------------------------------------------- controle positif

def _graphe_separe():
    """Fixture TOTALEMENT independante : aucune autorite partagee, aucune
    auto-modification, une racine hors de portee du client.

    Sans elle, un modele qui refuserait TOUT passerait tous les tests ci-dessus
    — « sur » parce qu'inutile.
    """
    return [
        TD.Noeud("client", TD.TD_CLIENT, artefact="agent",
                 qui_peut_modifier=TD.TD_CLIENT, qui_peut_appeler=TD.TD_CLIENT,
                 qui_peut_observer=TD.TD_CLIENT, qui_peut_certifier=TD.TD_CLIENT,
                 autorites={"compte": "cpt_client", "processus": "p_client"}),
        TD.Noeud("mediateur", TD.TD_ENFORCEMENT, artefact="hors depot",
                 qui_peut_modifier=TD.TD_ROOT, qui_peut_appeler=TD.TD_CLIENT,
                 qui_peut_observer=TD.TD_EVIDENCE, qui_peut_certifier=TD.TD_EVIDENCE,
                 autorites={"compte": "cpt_enf", "processus": "p_enf"}),
        TD.Noeud("verificateur", TD.TD_EVIDENCE, artefact="hors depot",
                 qui_peut_modifier=TD.TD_ROOT, qui_peut_appeler=TD.TD_ROOT,
                 qui_peut_observer=TD.TD_EVIDENCE, qui_peut_certifier=TD.TD_EVIDENCE,
                 autorites={"compte": "cpt_evi", "processus": "p_evi"}),
        TD.Noeud("racine", TD.TD_ROOT, artefact="hors depot, hors portee client",
                 qui_peut_modifier=TD.TD_ROOT, qui_peut_appeler=TD.TD_ROOT,
                 qui_peut_observer=TD.TD_ROOT, qui_peut_certifier=TD.TD_ROOT,
                 autorites={"compte": "cpt_root", "processus": "p_root"}),
    ]


def test_une_separation_reelle_est_reconnue():
    """Contrôle positif : le modèle DOIT pouvoir rendre un verdict favorable."""
    r = TD.verdict_m01(_graphe_separe())
    assert r["verdict"] == "SEPARATION_PROUVEE", r["verdicts_manquants"]


def test_une_seule_autorite_partagee_suffit_a_refuser():
    """Contrôle négatif du contrôle positif : la fixture n'est pas verte « par
    construction », elle l'est parce qu'elle est séparée."""
    g = _graphe_separe()
    g[1].autorites["compte"] = g[0].autorites["compte"]  # enforcement == client
    r = TD.verdict_m01(g)
    assert r["verdict"] == "NON_CERTIFIANT"
    assert r["autorites_partagees"]


def test_une_racine_modifiable_par_le_client_n_est_pas_une_racine():
    g = _graphe_separe()
    g[3].qui_peut_modifier = TD.TD_CLIENT
    r = TD.verdict_m01(g)
    assert r["verdicts"]["ROOT_INDEPENDENCE_PROVEN"] is False
    assert r["verdict"] == "NON_CERTIFIANT"
