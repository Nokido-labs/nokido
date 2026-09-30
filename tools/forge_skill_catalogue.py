"""Catalogue CANONIQUE des skills — la table de resolution des identites.

Pourquoi ce module existe (mesure du 2026-09-12, aucun point hypothetique).
Neuf espaces de noms de skills coexistent et AUCUN ne fait autorite :

    1. ~/.claude/skills/<dir>/SKILL.md     28  dont 9 declarent `laforge-*`
    2. Nokido/docs/skills/<dir>/SKILL.md   19  `name:` == dossier partout
    3. Nokido/.claude/skills/               1  joignabilite douteuse
    4. plugins (cache recopie ~8x)        ~26  jamais figes
    5. skills fournis par le client       >=13 hors disque
    6. skilltree.SKILL_TREE                30  des DOMAINES, pas des skills
    7. skill_indexer_state.json             —  fichiers .md plats, juin 2026
    8. RAG domain='skill'                  30  chemins LaForge/ perimes
    9. cles skillUsage                     29  melange 1/2/4/5

Consequence CHIFFREE du desordre : `forge-hub`=2 et `laforge-hub`=4 comptent
separement UN SEUL skill, et `laforge`=9 pointe un skill qui n'existe sous ce
nom nulle part (ancien nom de `nokido`). Tout score de pertinence bati sur ces
compteurs serait faux de moitie.

Ce que ce module fait — et ce qu'il ne fait PAS.
  FAIT    : resoudre N identites vers un `skill_id` stable, conserver les
            alias, reconcilier les usages, compter en nommant ce qu'il n'a
            pas pu lire.
  NE FAIT PAS : choisir un skill pour une tache (c'est le RETRIEVAL, couche
            distincte), ni ordonner des skills (c'est le PLANNING, porte par
            forge_goap_hub_bridge dont Action(preconditions/effects/cost)
            convient deja). Melanger ces trois couches dans un seul objet est
            precisement ce qui a produit `forge_skill_rag_bridge`, qui score
            des DOMAINES en croyant scorer des skills.

Deux invariants constitutionnels, executes et non decoratifs :
  * ILLISIBLE != ABSENT. Sous un compte non privilegie, `exists()` rend False
    pour un dossier qui EXISTE. On ne tranche donc jamais entre « absent » et
    « acces refuse » : les deux donnent NON_LUE, et une surface non lue rend
    le TOTAL `None` au lieu d'un chiffre rassurant.
  * Un identifiant ne se derive JAMAIS du chemin. Un deplacement de fichier
    recreerait exactement le desordre qu'on corrige ici.

NR : tests/nr/test_skill_catalogue_canonique_nr.py
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import sys
from typing import Iterable

__FORGE_COLOR__ = "cognition/skill-catalogue : table de resolution des identites de skills"

ROOT = pathlib.Path(__file__).resolve().parent.parent

# --- Renommages CONSTATES -----------------------------------------------------
# Se declarent a la main, ne se devinent pas : `laforge` -> `nokido` est un
# renommage historique porteur de 9 usages. Aucune regle ne le derive, et une
# regle inventee se propagerait en RAG ou plus rien ne la distinguerait d'une
# mesure. N'ajouter ici que du MESURE.
ALIAS_DECLARES: dict[str, str] = {
    "laforge": "nokido",
}

# Profil owner en DUR : sous le compte de service, USERPROFILE vaut
# C:\Windows\system32\config\systemprofile — un scan derive de l'environnement
# y lit 0 skill et rend un rapport « rassurant et entierement faux » (paye le
# 2026-09-12). Surchargeable explicitement pour les tests et les autres postes.
PROFIL_OWNER = pathlib.Path(
    os.environ.get("LAFORGE_PROFIL_CLAUDE", r"%USERPROFILE%\.claude"))


@dataclasses.dataclass(frozen=True)
class Surface:
    """Un endroit ou des skills vivent, et le client qui peut les executer."""

    nom: str
    chemin: pathlib.Path
    client: str


@dataclasses.dataclass
class Record:
    """Un skill, vu par toutes ses identites a la fois."""

    skill_id: str
    canonique: str
    name_declare: str | None
    name_dossier: str
    description: str
    aliases: set[str] = dataclasses.field(default_factory=set)
    sources: set[str] = dataclasses.field(default_factory=set)
    clients: set[str] = dataclasses.field(default_factory=set)
    chemins: list[str] = dataclasses.field(default_factory=list)
    etat: str = "OK"
    usage_total: int = 0


@dataclasses.dataclass
class Releve:
    """Resultat d'un scan — porte AUSSI ce qui n'a pas pu etre lu."""

    records: dict[str, Record] = dataclasses.field(default_factory=dict)
    index: dict[str, str] = dataclasses.field(default_factory=dict)
    surfaces_lues: list[str] = dataclasses.field(default_factory=list)
    surfaces_non_lues: dict[str, str] = dataclasses.field(default_factory=dict)
    usages_orphelins: dict[str, int] = dataclasses.field(default_factory=dict)
    yaml_verifie: bool = False


def canoniser(nom: str | None) -> str:
    """Ramene une identite quelconque a son nom canonique.

    Deux regles seulement, toutes deux mesurees : la table de renommages
    declares, puis l'equivalence `laforge-X` == `forge-X` (9 occurrences au
    profil, zero au depot).
    """
    n = (nom or "").strip().lower()
    if not n:
        return ""
    n = ALIAS_DECLARES.get(n, n)
    if n.startswith("laforge-"):
        n = "forge-" + n[len("laforge-"):]
    return ALIAS_DECLARES.get(n, n)


def id_de(canonique: str) -> str:
    """skill_id stable, derive du NOM canonique et jamais du chemin."""
    empreinte = hashlib.sha256(canonique.encode("utf-8")).hexdigest()[:12]
    return "sk_" + empreinte


def _frontmatter(texte: str) -> tuple[str | None, str, str]:
    """Extrait (name, description, etat) du bloc entre les deux `---`.

    Un `: ` dans un scalaire non quote casse le YAML et fait tomber TOUS les
    champs cote client — le skill devient alors introuvable sans le moindre
    avertissement (paye sur forge-workflow-autopsy). On le DETECTE quand PyYAML
    est disponible, et on le DIT quand il ne l'est pas.
    """
    lignes = texte.splitlines()
    if not lignes or lignes[0].strip() != "---":
        return None, "", "SANS_FRONTMATTER"
    fin = None
    for i in range(1, len(lignes)):
        if lignes[i].strip() == "---":
            fin = i
            break
    if fin is None:
        return None, "", "FRONTMATTER_NON_FERMEE"
    bloc = "\n".join(lignes[1:fin])

    try:
        import yaml  # noqa: PLC0415
    except Exception:
        nom = None
        desc = ""
        for ligne in bloc.splitlines():
            if ligne.startswith("name:"):
                nom = ligne.split(":", 1)[1].strip()
            elif ligne.startswith("description:"):
                desc = ligne.split(":", 1)[1].strip()
        return nom, desc, "YAML_NON_VERIFIE"

    try:
        d = yaml.safe_load(bloc)
    except Exception:
        # Cote client, ce cas fait tomber name, description, allowed-tools et
        # disable-model-invocation d'un bloc : le skill est present sur disque
        # et absent du catalogue effectif.
        return None, "", "FRONTMATTER_INVALIDE"
    if not isinstance(d, dict):
        return None, "", "FRONTMATTER_NON_MAPPING"
    nom = d.get("name")
    return (str(nom) if nom else None), str(d.get("description") or ""), "OK"


def _enregistrer(releve: Releve, record: Record, identites: Iterable[str]) -> None:
    existant = releve.records.get(record.skill_id)
    if existant is None:
        releve.records[record.skill_id] = record
        cible = record
    else:
        cible = existant
        cible.aliases |= record.aliases
        cible.sources |= record.sources
        cible.clients |= record.clients
        cible.chemins.extend(record.chemins)
        if cible.name_declare is None and record.name_declare:
            cible.name_declare = record.name_declare
        if not cible.description:
            cible.description = record.description
    for ident in identites:
        i = (ident or "").strip().lower()
        if i:
            cible.aliases.add(i)
            releve.index[i] = cible.skill_id
            releve.index[canoniser(i)] = cible.skill_id


def scanner(surfaces: list[Surface]) -> Releve:
    """Scanne les surfaces ; ce qui n'est pas lu est NOMME, jamais avale."""
    releve = Releve()
    try:
        import yaml  # noqa: F401,PLC0415

        releve.yaml_verifie = True
    except Exception:
        releve.yaml_verifie = False

    for s in surfaces:
        # Pas de `exists()` prealable : il LEVE sous compte de service au lieu
        # de rendre False, et rend False sur un dossier existant sous sandbox.
        try:
            dossiers = sorted(p for p in s.chemin.iterdir() if p.is_dir())
        except Exception as exc:
            releve.surfaces_non_lues[s.nom] = type(exc).__name__
            continue
        releve.surfaces_lues.append(s.nom)

        for d in dossiers:
            fichier = d / "SKILL.md"
            try:
                texte = fichier.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                canon_d = canoniser(d.name)
                rec = Record(
                    skill_id=id_de(canon_d),
                    canonique=canon_d,
                    name_declare=None,
                    name_dossier=d.name,
                    description="",
                    aliases={d.name.lower()},
                    sources={s.nom},
                    clients={s.client},
                    chemins=[str(d)],
                    etat="SKILL_MD_" + type(exc).__name__.upper(),
                )
                _enregistrer(releve, rec, [d.name])
                continue

            declare, desc, etat_fm = _frontmatter(texte)
            canon = canoniser(declare or d.name)
            etat = "OK"
            if declare is None:
                etat = ("SANS_NAME_DECLARE" if etat_fm in ("OK", "YAML_NON_VERIFIE")
                        else etat_fm)
            rec = Record(
                skill_id=id_de(canon),
                canonique=canon,
                name_declare=declare,
                name_dossier=d.name,
                description=desc,
                aliases={d.name.lower()},
                sources={s.nom},
                clients={s.client},
                chemins=[str(d)],
                etat=etat,
            )
            _enregistrer(releve, rec, [d.name, declare or "", canon])

    return releve


def resoudre(releve: Releve, nom: str) -> str | None:
    """Rend le skill_id pour n'importe laquelle des identites connues."""
    n = (nom or "").strip().lower()
    if n in releve.index:
        return releve.index[n]
    return releve.index.get(canoniser(n))


def appliquer_usages(releve: Releve, usages: dict[str, int]) -> Releve:
    """Reconcilie l'historique d'usage — la seule baseline empirique existante.

    Un usage qui ne resout vers aucun skill est SIGNALE et conserve : c'est le
    cas de `laforge`=9 avant declaration de son alias. Le jeter en silence
    ferait disparaitre la preuve qu'un renommage a eu lieu.
    """
    for cle, n in (usages or {}).items():
        sid = resoudre(releve, cle)
        if sid is None:
            releve.usages_orphelins[cle] = int(n or 0)
            continue
        releve.records[sid].usage_total += int(n or 0)
    return releve


def _par_etat(releve: Releve) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in releve.records.values():
        out[r.etat] = out.get(r.etat, 0) + 1
    return out


def compteurs(releve: Releve) -> dict:
    """Compte en trois etats — jamais un total sur denominateur ampute."""
    lus = len(releve.records)
    illisibles = len(releve.surfaces_non_lues)
    return {
        "SKILLS_LUS": lus,
        "SKILLS_TOTAL": None if illisibles else lus,
        "SURFACES_LUES": list(releve.surfaces_lues),
        "SURFACES_ILLISIBLES": illisibles,
        "SURFACES_NON_LUES": dict(releve.surfaces_non_lues),
        "IDENTITES_MULTIPLES": sum(
            1 for r in releve.records.values()
            if r.name_declare and r.name_declare.lower() != r.name_dossier.lower()),
        "ETATS": _par_etat(releve),
        "YAML_VERIFIE": releve.yaml_verifie,
        "USAGES_ORPHELINS": dict(releve.usages_orphelins),
    }


def surfaces_reelles() -> list[Surface]:
    """Les surfaces du poste. `Nokido/.claude/skills` n'est PAS incluse.

    Le cwd de session est la racine du projet, pas `Nokido/` : un skill pose
    la n'est pas charge par le client. L'inclure gonflerait le catalogue de
    skills injoignables — exactement le faux positif qu'on cherche a eviter.
    """
    return [
        Surface("profil", PROFIL_OWNER / "skills", "claude"),
        Surface("depot", ROOT / "docs" / "skills", "nokido"),
    ]


def usages_du_poste() -> dict[str, int]:
    """Lit UNIQUEMENT la cle skillUsage de ~/.claude.json.

    Lecture CIBLEE : ce fichier porte des secrets (env et headers des serveurs
    MCP). On n'en extrait que des noms et des compteurs, jamais le reste.
    """
    p = PROFIL_OWNER.parent / ".claude.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    su = d.get("skillUsage") or {}
    return {k: int((v or {}).get("usageCount") or 0)
            for k, v in su.items() if isinstance(v, dict)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Catalogue canonique des skills")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    ap.add_argument("--sans-usages", action="store_true",
                    help="ne pas lire les compteurs d'usage du poste")
    ap.add_argument("--anomalies", action="store_true",
                    help="NOMME les skills dont l'etat n'est pas OK")
    a = ap.parse_args(argv)

    releve = scanner(surfaces_reelles())
    if not a.sans_usages:
        appliquer_usages(releve, usages_du_poste())
    c = compteurs(releve)

    if a.json:
        print(json.dumps(c, indent=2, ensure_ascii=False))
        return 0

    if a.anomalies:
        # Un compteur qui dit « 1 frontmatter invalide » sans nommer le skill
        # ne permet aucun rattrapage : l'anomalie se lit, elle ne se corrige pas.
        casses = [r for r in releve.records.values() if r.etat != "OK"]
        print("ANOMALIES : %d sur %d skills lus" % (len(casses), c["SKILLS_LUS"]))
        for r in sorted(casses, key=lambda x: x.etat):
            print("  [%s] %s (declare=%s) %s"
                  % (r.etat, r.name_dossier, r.name_declare, "; ".join(r.chemins)))
        return 0

    total = c["SKILLS_TOTAL"]
    print("SKILLS_TOTAL       : %s" % ("INDETERMINE" if total is None else total))
    print("SKILLS_LUS         : %d" % c["SKILLS_LUS"])
    print("IDENTITES_MULTIPLES: %d" % c["IDENTITES_MULTIPLES"])
    print("SURFACES_LUES      : %s" % ", ".join(c["SURFACES_LUES"]))
    if c["SURFACES_ILLISIBLES"]:
        print("SURFACES_NON_LUES  : %s" % c["SURFACES_NON_LUES"])
    print("ETATS              : %s" % c["ETATS"])
    if c["USAGES_ORPHELINS"]:
        print("USAGES_ORPHELINS   : %s" % c["USAGES_ORPHELINS"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
