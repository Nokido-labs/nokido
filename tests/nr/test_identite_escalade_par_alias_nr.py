"""NR adversarial — fournir l'identifiant d'un autre ne doit donner ni son ring ni sa cle.

CAP V9, P2 : identite. Ce NR n'est PAS un census -- `test_registre_identite_unicite_nr`
couvre deja la STRUCTURE (aucun alias ne designe l'identite d'un autre acteur,
aucun alias revendique par deux acteurs). Celui-ci attaque la RESOLUTION :

    « Puis-je fournir un identifiant ou un alias appartenant a A et obtenir les
      privileges, l'identite ou la cle de B ? »

POURQUOI CETTE ATTAQUE EXACTEMENT
=================================
Elle a deja reussi une fois. Mesure du 2026-09-20 : `LAFORGE_CLI` (ring 1)
revendiquait l'alias `nokido_cli`, qui appartient a `NOKIDO_CLI` (ring 4).
Fournir cet alias faisait donc resoudre vers une identite de ring 1 -- une
elevation de privilege silencieuse, residu du cutover
(`forge_identity_registry_upgrade.py:91`). Corrige par `61bf46e71`, avec une
resolution en DEUX PASSES : canoniques d'abord, alias ensuite.

Le registre a ete mesure a 146 identites pour 77 acteurs, et le champ `actor`
est universel (146/146) la ou `canonical` ne couvrait que 4 entrees -- c'est
`actor` qui porte la propriete, pas `canonical`.

CE QUI EST ATTAQUE ICI, et chaque cas est une tentative, pas un inventaire :
  1. resolution d'un alias vers l'identite d'un AUTRE acteur ;
  2. obtention de la CLE TPM d'un autre par son identifiant ;
  3. ELEVATION DE RING par un identifiant qu'on ne possede pas ;
  4. confusion par NORMALISATION (casse, espaces, prefixe parasite) ;
  5. identifiant inconnu -> refus explicite, jamais un defaut permissif.

Le cas 4 vise `agt_agt_gemini`, mesure le 2026-09-20 avec 25 messages accumules :
un prefixe double ne doit pas resoudre vers GEMINI par accident.

AUCUNE CLE N'EST CREEE : `nom_cle_agent` calcule un NOM, il ne touche pas le TPM.
"""
import importlib
import json
import pathlib

import pytest

# Un NR d'attaque lit ce que le corps ne publie pas : `_resoudre_agent`,
# `_ring_resolu`, `_REG_CACHE`. C'est son objet, pas une negligence — le nommer
# ici plutot que de laisser 5 avertissements sans reponse.
# pylint: disable=protected-access

M2M = "nokido_agent.app.forge_m2m_protocol"
TPM = "nokido_agent.app.forge_persona_tpm"
POSTAL = "nokido_agent.app.forge_postal"
REGISTRE = pathlib.Path(__file__).resolve().parents[2] / "config" / "agent_identities.json"


# `name=` : sans lui, pylint compte un `redefined-outer-name` par test qui
# consomme la fixture -- 20 signalements pour un motif pytest parfaitement
# normal. Le NR voisin (`test_registre_identite_unicite_nr`) note 9,81/10 sans
# fixtures ; la difference venait de la forme, pas du fond.
@pytest.fixture(name="resoudre")
def _fx_resoudre():
    return importlib.import_module(M2M)._resoudre_agent


@pytest.fixture(name="agents")
def _fx_agents():
    d = json.loads(REGISTRE.read_text(encoding="utf-8", errors="replace"))
    src = d.get("agents") or {}
    assert len(src) > 50, "registre trop maigre : le test ne prouverait rien"
    return src


def _acteur(agents, canon):
    return (agents.get(canon) or {}).get("actor")


def _ring(agents, canon):
    return (agents.get(canon) or {}).get("ring")


# ------------------------------------------------ detecteurs, isoles pour etre
#                                                    eux-memes mis a l'epreuve

def _ecarts_alias_croise(agents, resoudre):
    """Tout alias qui resout vers l'identite d'un AUTRE acteur que celui qui le
    declare."""
    fautes = []
    for canon, fiche in agents.items():
        proprietaire = fiche.get("actor")
        for alias in (fiche.get("aliases") or []):
            obtenu, _surface = resoudre(alias)
            if not obtenu:
                continue
            if _acteur(agents, obtenu) != proprietaire:
                fautes.append(
                    "%s declare l'alias %r, mais il resout vers %s (acteur %s "
                    "au lieu de %s)" % (canon, alias, obtenu,
                                        _acteur(agents, obtenu), proprietaire))
    return fautes


def _ecarts_ring(agents, resoudre):
    """Tout alias par lequel on atteint un ring PLUS PRIVILEGIE (plus bas) que
    celui de l'identite qui le declare."""
    fautes = []
    for canon, fiche in agents.items():
        mien = fiche.get("ring")
        if mien is None:
            continue
        for alias in (fiche.get("aliases") or []):
            obtenu, _s = resoudre(alias)
            if not obtenu or obtenu == canon:
                continue
            son_ring = _ring(agents, obtenu)
            if son_ring is not None and son_ring < mien:
                fautes.append(
                    "l'alias %r de %s (ring %s) resout vers %s (ring %s) : "
                    "ELEVATION" % (alias, canon, mien, obtenu, son_ring))
    return fautes


# ---------- LES DETECTEURS MORDENT-ILS ? (contre-epreuve, registre SYNTHETIQUE)
#
# Les deux tests qui suivent sont passes VERTS du premier coup sur le registre
# reel. Un vert de premier coup ne dit pas « le corps est sain » : il dit
# « le detecteur n'a rien trouve », ce qui inclut « le detecteur est aveugle ».
# On lui donne donc un registre FAUTIF fabrique, ou la faute est connue par
# construction, et on exige qu'il la voie.
#
# PORTEE, dite explicitement : ceci prouve que le DETECTEUR n'est pas aveugle.
# Cela ne prouve rien sur `_resoudre_agent`, qui lit le registre du disque et
# ne peut pas recevoir un registre injecte.

_REG_ALIAS_CROISE = {
    "LAFORGE_CLI": {"actor": "LAFORGE", "ring": 1, "aliases": ["nokido_cli"]},
    "NOKIDO_CLI": {"actor": "NOKIDO", "ring": 4, "aliases": []},
}
_REG_ELEVATION = {
    "OUTIL_FAIBLE": {"actor": "OUTIL", "ring": 4, "aliases": ["admin_hub"]},
    "ADMIN_HUB": {"actor": "ADMIN", "ring": 0, "aliases": []},
}


def test_le_detecteur_d_alias_croise_VOIT_le_cas_historique():
    """Le cas corrige par `61bf46e71`, rejoue en laboratoire."""
    faux = lambda x: ({"nokido_cli": "NOKIDO_CLI"}.get(x), None)  # noqa: E731
    vus = _ecarts_alias_croise(_REG_ALIAS_CROISE, faux)
    assert vus, "le detecteur d'alias croise est AVEUGLE : il laisse passer le cas connu"
    assert "NOKIDO_CLI" in vus[0]


def test_le_detecteur_d_elevation_VOIT_un_ring_gagne():
    """Un outil de ring 4 qui atteint le ring 0 par un alias."""
    faux = lambda x: ({"admin_hub": "ADMIN_HUB"}.get(x), None)  # noqa: E731
    vus = _ecarts_ring(_REG_ELEVATION, faux)
    assert vus, "le detecteur d'elevation est AVEUGLE : ring 4 -> ring 0 non vu"
    assert "ELEVATION" in vus[0]


# ------------------------------------------------ 1. resolution croisee, REELLE

def test_aucun_alias_ne_resout_vers_l_identite_d_un_AUTRE_acteur(resoudre, agents):
    """L'attaque historique, rejouee sur TOUS les alias reellement declares."""
    fautes = _ecarts_alias_croise(agents, resoudre)
    assert not fautes, "ELEVATION PAR ALIAS :\n  " + "\n  ".join(fautes[:10])


def test_aucun_alias_ne_donne_acces_a_un_ring_PLUS_PRIVILEGIE(resoudre, agents):
    """Le coeur de l'attaque : le ring obtenu ne doit jamais etre MEILLEUR que
    celui de l'identite qui declare l'alias.

    Un ring plus BAS est plus privilegie (ring 1 > ring 4). Le cas
    LAFORGE_CLI(1)/NOKIDO_CLI(4) etait exactement cela.
    """
    fautes = _ecarts_ring(agents, resoudre)
    assert not fautes, "\n  ".join(fautes[:10])


# ------------------------------------------------ 2. la cle d'un autre

def test_un_identifiant_ne_donne_jamais_la_cle_d_un_AUTRE_acteur(agents):
    """`nom_cle_agent` derive le nom de cle TPM de l'identite CANONIQUE. Si deux
    acteurs distincts pouvaient obtenir le meme nom de cle, l'un signerait pour
    l'autre.

    Ne cree aucune cle : on calcule des NOMS.
    """
    nom_cle_agent = importlib.import_module(TPM).nom_cle_agent
    par_nom = {}
    for canon, fiche in agents.items():
        try:
            nom = nom_cle_agent(canon)
        except ValueError:
            continue                      # non declare : refus, c'est correct
        par_nom.setdefault(nom, set()).add(fiche.get("actor"))
    collisions = {n: a for n, a in par_nom.items() if len(a) > 1}
    assert not collisions, (
        "un meme nom de cle TPM est atteint par PLUSIEURS acteurs : %s" % collisions
    )


def test_un_agent_NON_DECLARE_ne_recoit_aucune_cle():
    """Donner du materiel cryptographique a une etiquette inconnue, ce serait
    authentifier un fantome. Le refus doit etre EXPLICITE."""
    nom_cle_agent = importlib.import_module(TPM).nom_cle_agent
    with pytest.raises(ValueError):
        nom_cle_agent("AGENT_QUI_N_EXISTE_PAS_2026_ESCALADE")


# ------------------------------------------------ 3. confusion par normalisation

@pytest.mark.parametrize("propre,deforme", [
    ("GEMINI", "agt_agt_gemini"),   # double prefixe, mesure le 2026-09-20 (25 msg)
    ("GEMINI", "  GEMINI  "),       # espaces
    ("GEMINI", "GeMiNi"),           # casse mixte
    ("GEMINI", "GEMINI\n"),         # retour a la ligne
    ("CLAUDE_CLI", "claude_cli"),   # une seconde famille, pour ne pas prouver
    ("CLAUDE_CLI", " CLAUDE_CLI"),  # une propriete du seul cas GEMINI
])
def test_une_forme_DEFORMEE_ne_resout_pas_vers_une_AUTRE_identite(resoudre, propre,
                                                                  deforme):
    """Une entree deformee doit rendre soit la MEME identite que la forme propre,
    soit RIEN.

    Ce qu'on refuse, c'est qu'elle rende une identite DIFFERENTE : c'est ainsi
    qu'on obtient les privileges d'autrui par une faute de frappe choisie.

    La reference est ce que rend la forme PROPRE, jamais un acteur ecrit en dur :
    premiere version de ce test, l'acteur attendu etait ecrit en clair et le test
    criait au defaut sur une resolution JUSTE -- le registre declare
    `GEMINI.actor = ANTIGRAVITY`, un acteur portant plusieurs identites de
    surface. Un test qui recopie le registre au lieu de le lire mesure sa
    propre copie.
    """
    attendu, _sr = resoudre(propre)
    assert attendu, "la forme propre %r ne resout vers rien : test sans reference" % propre
    obtenu, _s = resoudre(deforme)
    if obtenu is None:
        return                              # refus : reponse sure
    assert obtenu == attendu, (
        "la forme %r resout vers %s alors que %r resout vers %s : une deformation "
        "donne acces a une AUTRE identite" % (deforme, obtenu, propre, attendu)
    )


def test_une_chaine_vide_ou_absurde_ne_resout_vers_RIEN(resoudre):
    for entree in ("", "   ", "../../admin", "*", None):
        obtenu, _s = resoudre(entree) if entree is not None else (None, None)
        assert not obtenu, "%r resout vers %s" % (entree, obtenu)


# ------------------------------------------------ 4. la resolution est stable

def test_la_resolution_est_DETERMINISTE(resoudre, agents):
    """Deux appels identiques doivent rendre la meme identite. Une resolution
    qui depend de l'ordre d'iteration ferait dependre un privilege du hasard --
    et c'est precisement ce que la correction en DEUX PASSES a supprime."""
    echantillon = list(agents)[:40]
    for canon in echantillon:
        a, _ = resoudre(canon)
        b, _ = resoudre(canon)
        assert a == b, "%s resout differemment d'un appel a l'autre" % canon


# ------------------------------------------------ 5. le RING lu a l'execution
#
# Les tests ci-dessus portent sur `_resoudre_agent`. Mais le ring qui commande
# reellement le tri du postal est lu par `forge_postal._ring_of`, qui est une
# SECONDE resolution, independante -- elle indexe le registre par
# `agent.upper()` sans passer par les alias. Deux resolutions pour une meme
# question, c'est la ou les verdicts divergent.
#
# Mesure du 2026-09-21 sur `sandbox/m2m.db` (21 924 messages, 16 expediteurs
# distincts) : 252 messages (1,1 %) sont emis sous un alias -- `agt_claude`
# (161), `agt_gemini` (89), `agt_antigravity` (2) -- dont le canonique est de
# ring 1, et que `_ring_of` lit 3.
#
# PORTEE EXACTE, pour ne pas vendre une faille la ou la mesure montre autre
# chose : l'unique appelant de `_ring_of` est `forge_postal:471`,
# `ring_boost = 1.0 if _ring_of(...) <= 1 else 0.0`. Ce n'est donc PAS une
# autorisation, c'est une PRIORITE DE TRI. Au seuil `<= 1`, un alias lu 3 au
# lieu de 1 PERD son boost ; un alias de ring 4 lu 3 n'en gagne aucun. Le
# defaut qui mord aujourd'hui est la perte, pas le gain.
#
# Ce qui reste vrai independamment de l'appelant : `_ring_of` range UNKNOWN du
# cote d'une VALEUR. Un registre illisible et un agent inexistant rendent tous
# deux 3, qui est plus privilegie que 31 des 146 identites declarees. C'est une
# dette de cablage : le jour ou un second appelant s'en sert pour autoriser,
# elle devient une elevation.

def test_un_alias_ne_PERD_pas_le_ring_de_son_identite(agents):
    """`_ring_of` doit rendre le ring du CANONIQUE, alias compris.

    Sans cela, deux resolutions coexistent et se contredisent : `_resoudre_agent`
    sait que `agt_claude` est `CLAUDE`, `_ring_of` l'ignore.
    """
    _ring_of = importlib.import_module(POSTAL)._ring_of
    fautes = []
    for canon, fiche in agents.items():
        vrai = fiche.get("ring")
        if vrai is None:
            continue
        for alias in (fiche.get("aliases") or []):
            lu = _ring_of(alias)
            if lu != vrai:
                fautes.append("%s (ring %s) lu %s via son alias %r"
                              % (canon, vrai, lu, alias))
    assert not fautes, (
        "%d alias ne rendent pas le ring de leur identite :\n  %s"
        % (len(fautes), "\n  ".join(fautes[:8]))
    )


def test_un_agent_INCONNU_n_obtient_pas_un_ring_intermediaire(agents):
    """Un identifiant que le registre ne connait pas ne doit pas se voir
    attribuer un ring plus privilegie que la moins privilegiee des identites
    declarees. UNKNOWN n'est pas une valeur de ring."""
    _ring_of = importlib.import_module(POSTAL)._ring_of
    pire = max(f["ring"] for f in agents.values() if f.get("ring") is not None)
    for inconnu in ("AGENT_INEXISTANT_XYZ_2026", "", "../../admin", "*"):
        lu = _ring_of(inconnu)
        assert lu >= pire, (
            "%r obtient le ring %s, plus privilegie que le pire ring declare "
            "(%s) : un inconnu est mieux traite que 31 identites connues"
            % (inconnu, lu, pire)
        )


def test_un_registre_ILLISIBLE_ne_devient_pas_un_ring(monkeypatch, tmp_path, agents):
    """Un registre qu'on ne peut pas lire rend aujourd'hui 3, exactement comme
    un agent de ring 3. ILLISIBLE et 3 deviennent indistinguables.

    On rend le registre introuvable et on exige que le resultat ne soit pas une
    valeur privilegiee.
    """
    FP = importlib.import_module(POSTAL)
    pire = max(f["ring"] for f in agents.values() if f.get("ring") is not None)
    monkeypatch.setattr(FP, "ROOT", tmp_path, raising=True)
    # Le cache `_REG_CACHE` survit a un changement de ROOT : sans le vider, la
    # lecture reussit sur l'ancien contenu et ce test ne mesurerait RIEN. Meme
    # famille que « simuler un refus par une absence » -- une mise en scene qui
    # ne reproduit pas la panne qu'elle pretend reproduire.
    for cle, vide in (("mtime", 0.0), ("agents", {}), ("index", {})):
        monkeypatch.setitem(FP._REG_CACHE, cle, vide)
    lu, etat = FP._ring_resolu("CLAUDE")
    assert etat == "ILLISIBLE", "registre introuvable -> etat %r au lieu d'ILLISIBLE" % etat
    assert lu >= pire, (
        "registre illisible -> ring %s : une panne de lecture se fait passer "
        "pour une identite de ring %s" % (lu, lu)
    )


def test_l_etat_de_la_resolution_est_DISTINGUABLE(agents):
    """Trois etats et jamais deux : RESOLU / INCONNU / ILLISIBLE.

    `_ring_of` ne rend qu'un entier -- il ne PEUT pas dire lequel des trois.
    Le corps doit exposer la forme qui le dit, faute de quoi aucun appelant ne
    pourra jamais distinguer une panne d'un ring.
    """
    FP = importlib.import_module(POSTAL)
    assert hasattr(FP, "_ring_resolu"), (
        "aucune forme ne rend l'ETAT de la resolution : `_ring_of` seul ne peut "
        "pas distinguer un ring reel d'une panne de lecture"
    )
    _r, etat = FP._ring_resolu("AGENT_INEXISTANT_XYZ_2026")
    assert etat == "INCONNU", "agent inexistant -> etat %r" % etat
    for canon in list(agents)[:3]:
        _r2, etat2 = FP._ring_resolu(canon)
        assert etat2 == "RESOLU", "%s -> etat %r" % (canon, etat2)


def test_une_identite_CANONIQUE_prime_toujours_sur_un_alias(resoudre, agents):
    """La correction du 2026-09-20 : canoniques d'abord, alias ensuite. Si un
    nom est a la fois canonique pour X et alias de Y, il DOIT rendre X."""
    fautes = []
    alias_vers = {}
    for canon, fiche in agents.items():
        for alias in (fiche.get("aliases") or []):
            alias_vers.setdefault(alias.upper(), canon)
    for canon in agents:
        if canon.upper() in alias_vers and alias_vers[canon.upper()] != canon:
            obtenu, _s = resoudre(canon)
            if obtenu != canon:
                fautes.append(
                    "%s est canonique mais resout vers %s (alias de %s)"
                    % (canon, obtenu, alias_vers[canon.upper()]))
    assert not fautes, "\n  ".join(fautes[:10])
