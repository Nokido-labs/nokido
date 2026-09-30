"""NR — catalogue canonique de skills : la table de resolution des identites.

Mesure du 2026-09-12 qui motive ce NR (aucun point n'est hypothetique) :

  * ~/.claude/skills porte 28 dossiers ; NEUF declarent un `name:` different
    de leur dossier (`forge-hub/` declare `laforge-hub`, etc.).
  * Les compteurs d'usage sont donc SCINDES : `forge-hub`=2 ET `laforge-hub`=4
    pour un seul et meme skill ; `laforge`=9 pointe un skill qui n'existe sous
    ce nom dans AUCUNE surface (ancien nom de `nokido`).
  * Neuf espaces de noms disjoints coexistent (profil, depot, plugins, bundled,
    skilltree, manifestes de juin, RAG perime, cles d'usage) et aucun ne fait
    autorite.

Le catalogue n'est donc pas « un registre de plus » : c'est la table qui
resout ces identites vers un `skill_id` STABLE. Ce NR verrouille le contrat.

Invariants constitutionnels appliques ici :
  ILLISIBLE != ABSENT  — une surface qu'on n'a pas pu lire interdit le total.
  Un identifiant ne se derive pas du CHEMIN : un deplacement de fichier
  recreerait exactement le probleme qu'on est en train de corriger.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Import DIRECT, jamais `importorskip` : ce module est le LIVRABLE, pas une
# dependance optionnelle. Un `importorskip` rendrait SKIP (donc CI verte) tant
# que rien n'est livre — exactement le faux vert que la methode interdit.
import forge_skill_catalogue as cat  # noqa: E402


def _skill(dossier: pathlib.Path, nom_dossier: str, name_declare: str | None,
           description: str = "un skill de test") -> pathlib.Path:
    """Fabrique une surface au format REEL : <dir>/SKILL.md + frontmatter."""
    d = dossier / nom_dossier
    d.mkdir(parents=True, exist_ok=True)
    if name_declare is None:
        corps = "---\ndescription: %s\n---\n\n# %s\n" % (description, nom_dossier)
    else:
        corps = "---\nname: %s\ndescription: %s\n---\n\n# %s\n" % (
            name_declare, description, nom_dossier)
    (d / "SKILL.md").write_text(corps, encoding="utf-8")
    return d


def test_deux_identites_du_meme_skill_resolvent_au_meme_id(tmp_path):
    """`forge-hub` et `laforge-hub` sont UN skill, pas deux.

    C'est le defaut mesure : le disque dit `forge-hub`, la frontmatter dit
    `laforge-hub`, et les compteurs d'usage comptent les deux separement.
    """
    profil = tmp_path / "profil"
    _skill(profil, "forge-hub", "laforge-hub")

    releve = cat.scanner([cat.Surface("profil", profil, "claude")])

    id_par_dossier = cat.resoudre(releve, "forge-hub")
    id_par_declare = cat.resoudre(releve, "laforge-hub")

    assert id_par_dossier is not None, "le nom de dossier doit resoudre"
    assert id_par_declare is not None, "le nom declare doit resoudre"
    assert id_par_dossier == id_par_declare, (
        "forge-hub et laforge-hub designent le MEME skill : deux ids = "
        "le retriever indexerait l'un pendant que le client invoque l'autre")

    record = releve.records[id_par_dossier]
    assert "forge-hub" in record.aliases and "laforge-hub" in record.aliases, (
        "les deux identites doivent rester JOIGNABLES : on ne renomme rien, "
        "on ajoute un alias (un renommage detruirait l'historique d'usage)")


def test_skill_id_ne_depend_pas_du_chemin(tmp_path):
    """Un deplacement de fichier ne doit PAS creer un nouveau skill."""
    a = tmp_path / "emplacement_a"
    b = tmp_path / "emplacement_b"
    _skill(a, "forge-anatomy", "forge-anatomy")
    _skill(b, "forge-anatomy", "forge-anatomy")

    id_a = cat.resoudre(cat.scanner([cat.Surface("s", a, "claude")]), "forge-anatomy")
    id_b = cat.resoudre(cat.scanner([cat.Surface("s", b, "claude")]), "forge-anatomy")

    assert id_a == id_b, (
        "un skill_id derive du chemin recree le probleme des neuf espaces "
        "de noms des qu'un fichier bouge")


def test_surface_illisible_interdit_le_total(tmp_path):
    """ILLISIBLE != ABSENT : un total sur denominateur ampute est refuse.

    Meme patron que forge_context_budget : trois compteurs, et le total vaut
    None tant qu'une surface n'a pas pu etre lue.
    """
    bonne = tmp_path / "bonne"
    _skill(bonne, "forge-tdd", "forge-tdd")
    fantome = tmp_path / "surface_qui_n_existe_pas"

    releve = cat.scanner([
        cat.Surface("bonne", bonne, "claude"),
        cat.Surface("fantome", fantome, "claude"),
    ])
    c = cat.compteurs(releve)

    assert c["SKILLS_TOTAL"] is None, (
        "une surface illisible doit rendre le total INDETERMINE, jamais un "
        "chiffre rassurant calcule sur ce qu'on a pu voir")
    assert c["SKILLS_LUS"] == 1, "ce qui EST lu reste compte, nommement"
    assert c["SURFACES_ILLISIBLES"] == 1
    assert "fantome" in c["SURFACES_NON_LUES"], (
        "toute affirmation d'absence NOMME ce qu'on n'a pas pu voir")


def test_frontmatter_sans_name_est_nommee_pas_avalee(tmp_path):
    """Un SKILL.md sans `name:` est un ETAT, pas un silence.

    Une frontmatter cassee fait tomber TOUS les champs cote client : le
    catalogue doit le dire, pas ecarter l'entree sans trace.
    """
    profil = tmp_path / "profil"
    _skill(profil, "skill-casse", None)

    releve = cat.scanner([cat.Surface("profil", profil, "claude")])
    sid = cat.resoudre(releve, "skill-casse")

    assert sid is not None, "un skill sans `name:` reste JOIGNABLE par son dossier"
    record = releve.records[sid]
    assert record.name_declare is None
    assert record.etat == "SANS_NAME_DECLARE", (
        "l'etat doit etre nomme pour qu'un rattrapage reste possible")


def test_usage_historique_est_reconcilie_par_alias(tmp_path):
    """Les 2 usages de forge-hub + les 4 de laforge-hub font 6, pas deux lignes.

    Ces compteurs sont aujourd'hui le SEUL signal empirique de pertinence
    dont le systeme dispose : les perdre, c'est perdre la baseline.
    """
    profil = tmp_path / "profil"
    _skill(profil, "forge-hub", "laforge-hub")

    releve = cat.scanner([cat.Surface("profil", profil, "claude")])
    cat.appliquer_usages(releve, {"forge-hub": 2, "laforge-hub": 4, "inconnu-x": 99})

    sid = cat.resoudre(releve, "forge-hub")
    assert releve.records[sid].usage_total == 6, (
        "un skill a deux identites cumule ses usages, sinon toute mesure de "
        "pertinence est fausse de moitie")

    assert "inconnu-x" in releve.usages_orphelins, (
        "un usage qui ne resout vers aucun skill est SIGNALE (cf. `laforge`=9, "
        "ancien nom de `nokido`), jamais jete en silence")


def test_alias_declare_survit_a_l_absence_de_surface():
    """La table d'alias explicite ne se DEVINE pas.

    `laforge` -> `nokido` est un renommage constate, pas une regle derivable :
    il est declare a la main et le NR verrouille sa presence.
    """
    assert cat.ALIAS_DECLARES.get("laforge") == "nokido", (
        "le renommage laforge->nokido porte 9 usages historiques ; s'il "
        "disparait de la table, ces usages redeviennent orphelins")
