"""NR — RETRIEVAL de skills : quels skills sont pertinents pour un objectif.

Couche 2 sur 3. Le CATALOGUE (forge_skill_catalogue) dit quels skills
existent ; le PLANNING (forge_goap_hub_bridge) dit dans quel ordre les
utiliser. Ici, et seulement ici : lesquels sont pertinents.

Cette separation n'est pas cosmetique. `forge_skill_rag_bridge` a melange les
roles et fini par scorer des DOMAINES (`devops`, `reseau_dns`) en croyant
scorer des skills — 639 lignes, zero importeur, et un `rag_score(skill_id)`
qui mesure la couverture documentaire au lieu de la pertinence d'une tache.

Contraintes REELLES du jour (mesurees, pas supposees) :
  * aucun backend d'embedding ne repond (`:8099`, `:8091`, `:1234` fermes,
    `:11434` expire) => le score SEMANTIQUE est indisponible. La baseline est
    donc lexicale + metadonnees, ce qui est de toute facon l'ordre impose :
    baseline deterministe AVANT tout scoring cognitif.
  * les compteurs d'usage sont la SEULE preuve empirique de pertinence dont
    le systeme dispose ; le catalogue les reconcilie desormais par alias.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_skill_catalogue as cat  # noqa: E402
import forge_skill_retrieval as ret  # noqa: E402


def _skill(base: pathlib.Path, dossier: str, name: str, description: str) -> None:
    d = base / dossier
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        '---\nname: %s\ndescription: "%s"\n---\n\n# %s\n' % (name, description, name),
        encoding="utf-8")


def _catalogue(tmp_path: pathlib.Path) -> cat.Releve:
    base = tmp_path / "skills"
    _skill(base, "forge-anatomy", "forge-anatomy",
           "diagnostic anatomique des organes Nokido, pathologie par symptome")
    _skill(base, "netcfg-agent", "netcfg-agent",
           "configuration reseau multi-vendor, switches, VLAN, deploiement SSH")
    _skill(base, "forge-tdd", "forge-tdd",
           "methode de test, NR rouge avant correctif, cliquet de couverture")
    return cat.scanner([cat.Surface("t", base, "claude")])


def test_un_objectif_explicite_remonte_le_bon_skill(tmp_path):
    """Le cas nominal : l'objectif nomme le domaine, le skill sort en tete."""
    releve = _catalogue(tmp_path)
    res = ret.chercher(releve, "configurer les VLAN sur les switches du reseau")

    assert res.candidats, "un objectif clair ne doit pas rendre une liste vide"
    premier = res.candidats[0]
    assert releve.records[premier.skill_id].name_declare == "netcfg-agent", (
        "l'objectif parle de VLAN, switches et reseau : netcfg-agent doit "
        "primer sur forge-anatomy et forge-tdd")
    assert res.verdict == "TROUVE"


def test_le_score_n_est_jamais_opaque(tmp_path):
    """Ne jamais cacher POURQUOI un skill a ete propose."""
    releve = _catalogue(tmp_path)
    res = ret.chercher(releve, "diagnostic des organes et pathologie")
    c = res.candidats[0]

    assert c.score_components, "les composantes du score doivent etre exposees"
    assert set(c.score_components) >= {"lexical", "usage"}, (
        "au minimum : ce qui vient du texte et ce qui vient de l'historique")
    assert c.reason, "une raison lisible accompagne chaque candidat"
    assert abs(sum(c.score_components.values()) - c.score) < 1e-6, (
        "le score total doit etre la somme de ses composantes, sinon les "
        "composantes sont decoratives et le score reste opaque")


def test_aucun_candidat_pertinent_rend_SEARCH_MORE_pas_NO_SKILL(tmp_path):
    """Un catalogue muet n'autorise pas a conclure « pas de skill ».

    C'est la meme distinction que ILLISIBLE != ABSENT : « je n'ai rien trouve
    dans MON catalogue » n'est pas « il n'existe rien ». Le verdict doit
    orienter vers une recherche elargie, jamais fermer la question.
    """
    releve = _catalogue(tmp_path)
    res = ret.chercher(releve, "composer une symphonie pour hautbois et theremine")

    assert res.verdict == "SEARCH_MORE", (
        "sous le seuil de pertinence, le verdict est SEARCH_MORE : "
        "NO_SKILL fermerait la question au lieu d'elargir la recherche")
    assert res.seuil is not None, "le seuil applique doit etre dit"


def test_un_skill_a_l_etat_douteux_est_signale(tmp_path):
    """Une description non fiable ne doit pas se presenter comme fiable.

    Un SKILL.md dont la frontmatter ne parse pas perd TOUS ses champs cote
    client : sa description n'est plus celle de l'auteur. Le proposer sans le
    dire, c'est scorer sur un texte qu'on sait faux.
    """
    base = tmp_path / "skills"
    d = base / "forge-casse"
    d.mkdir(parents=True)
    # Un ` : ` non quote — exactement le defaut mesure sur deux skills reels.
    (d / "SKILL.md").write_text(
        "---\nname: forge-casse\ndescription: reseau VLAN switches : et voila\n---\n",
        encoding="utf-8")
    releve = cat.scanner([cat.Surface("t", base, "claude")])

    res = ret.chercher(releve, "reseau VLAN switches", seuil=0.0)
    assert res.candidats, "le skill reste proposable"
    assert res.candidats[0].fiabilite != "OK", (
        "sa fiabilite doit porter l'etat du catalogue, pas 'OK' par defaut")


def test_l_usage_historique_departage_a_egalite_lexicale(tmp_path):
    """A texte equivalent, ce qui a DEJA servi passe devant.

    Les compteurs d'usage sont la seule preuve empirique de pertinence
    disponible tant qu'aucun embedder ne repond.
    """
    base = tmp_path / "skills"
    _skill(base, "skill-a", "skill-a", "audit du reseau interne")
    _skill(base, "skill-b", "skill-b", "audit du reseau interne")
    releve = cat.scanner([cat.Surface("t", base, "claude")])
    cat.appliquer_usages(releve, {"skill-b": 40})

    res = ret.chercher(releve, "audit du reseau interne")
    gagnant = releve.records[res.candidats[0].skill_id]
    assert gagnant.name_declare == "skill-b", (
        "a lexical egal, 40 usages doivent primer sur 0")


def test_resultat_deterministe(tmp_path):
    """Deux appels identiques rendent le meme ordre.

    Un catalogue parcouru via un `set` donne un ordre qui change d'un
    processus a l'autre : la baseline de l'etape 10 serait inexploitable.
    """
    releve = _catalogue(tmp_path)
    a = [c.skill_id for c in ret.chercher(releve, "reseau switches VLAN").candidats]
    b = [c.skill_id for c in ret.chercher(releve, "reseau switches VLAN").candidats]
    assert a == b and a, "l'ordre doit etre stable entre deux appels"


def test_l_usage_ne_fabrique_pas_de_pertinence(tmp_path):
    """Un skill hors sujet reste hors sujet, meme tres utilise.

    Defaut MESURE le 2026-09-12 sur le catalogue reel : avec un prior d'usage
    ADDITIF, `laforge-ops` (21 usages, zero terme commun) sortait PREMIER sur
    « composer une symphonie pour hautbois et theremine ». L'historique doit
    departager a pertinence egale, jamais en creer : il est donc proportionne
    au lexical.
    """
    base = tmp_path / "skills"
    _skill(base, "tres-utilise", "tres-utilise", "gestion des sauvegardes disque")
    _skill(base, "pertinent-neuf", "pertinent-neuf", "audit reseau VLAN switches")
    releve = cat.scanner([cat.Surface("t", base, "claude")])
    cat.appliquer_usages(releve, {"tres-utilise": 500})

    res = ret.chercher(releve, "audit reseau VLAN switches", seuil=0.0)
    premier = releve.records[res.candidats[0].skill_id]
    assert premier.name_declare == "pertinent-neuf", (
        "500 usages ne doivent pas faire remonter un skill sans aucun terme "
        "commun devant celui qui repond a l'objectif")

    hors_sujet = [c for c in res.candidats
                  if releve.records[c.skill_id].name_declare == "tres-utilise"]
    assert hors_sujet and hors_sujet[0].score_components["usage"] == 0.0, (
        "lexical nul => composante d'usage nulle, sinon le score total nait "
        "d'un signal qui ne dit rien de la tache demandee")


def test_top_k_est_respecte(tmp_path):
    releve = _catalogue(tmp_path)
    res = ret.chercher(releve, "reseau diagnostic test", k=2, seuil=0.0)
    assert len(res.candidats) <= 2
