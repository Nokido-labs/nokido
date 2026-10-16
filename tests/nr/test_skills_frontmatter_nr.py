"""NR — les frontmatters des skills restent chargeables par TOUTES les surfaces (15/10).

Mesures payees le 14/10 :
  - 8 skills portaient `name: laforge-*` dans un dossier `forge-*` : certaines surfaces
    voyaient deux skills, d'autres aucune ;
  - des blocs fusionnes laissaient un `name:` en debut de ligne dans le CORPS : les
    chargeurs qui cherchent `---` + `name:` creaient des commandes fantomes en double
    (`/forge-models` et `/laforge-models` sur AGY) ;
  - une cle `targets:` privait des surfaces d'une skill universelle ;
  - des descriptions de 400 a 900 caracteres noyaient l'intention et pesaient sur le
    budget de contexte de chaque tour.

Forme retenue apres le debat (swarm, Gemini web, AGY) : intention + situations + apport,
350 caracteres au plus. Le cliquet lit docs/skills, la source ; les copies deployees
(.agents/skills, profils des CLI) sont produites par forge_skill_sync.
"""
import re
from pathlib import Path

import pytest
import yaml

RACINE = Path(__file__).resolve().parents[2] / "docs" / "skills"
PLAFOND_DESCRIPTION = 350
SKILLS = sorted(RACINE.glob("*/SKILL.md"))


def _lire(chemin: Path):
    texte = chemin.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert texte.startswith("---\n"), "%s : pas de frontmatter en tete" % chemin.parent.name
    _, entete, corps = texte.split("---", 2)
    return yaml.safe_load(entete) or {}, corps


def test_les_skills_sont_trouvees():
    # Un glob vide rendrait tous les tests ci-dessous verts sans rien verifier.
    assert len(SKILLS) >= 20, "docs/skills : %d SKILL.md trouves sous %s" % (len(SKILLS), RACINE)


@pytest.mark.parametrize("chemin", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_le_nom_est_celui_du_dossier(chemin):
    entete, _ = _lire(chemin)
    assert entete.get("name") == chemin.parent.name


@pytest.mark.parametrize("chemin", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_aucun_name_parasite_dans_le_corps(chemin):
    _, corps = _lire(chemin)
    lignes = [l for l in corps.splitlines() if re.match(r"^name:", l)]
    assert not lignes, "%s : `name:` en debut de ligne dans le corps -> %r" % (chemin.parent.name, lignes)


@pytest.mark.parametrize("chemin", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_aucune_restriction_de_surface(chemin):
    entete, _ = _lire(chemin)
    assert "targets" not in entete, "%s : cle `targets` dans le frontmatter" % chemin.parent.name


def test_chaque_skill_est_classee_une_fois_dans_les_familles():
    # Index des familles dans forge-capability : une skill hors index n'est trouvee par
    # personne qui cherche par besoin ; une skill classee deux fois brouille la carte.
    texte = (RACINE / "forge-capability" / "SKILL.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "## Familles de skills" in texte, "forge-capability : section « Familles de skills » absente"
    section = texte.split("## Familles de skills", 1)[1].split("\n## ", 1)[0]
    lignes = [l for l in section.splitlines() if l.startswith("| ") and not l.startswith("| famille")]
    classees = [nom for l in lignes for nom in re.findall(r"`([a-z0-9-]+)`", l.split("|")[2])]
    noms = {p.parent.name for p in SKILLS}
    doublons = sorted({n for n in classees if classees.count(n) > 1})
    assert not doublons, "classees plusieurs fois : %s" % doublons
    assert not sorted(noms - set(classees)), "skills hors des familles : %s" % sorted(noms - set(classees))
    assert not sorted(set(classees) - noms), "familles citant une skill absente : %s" % sorted(set(classees) - noms)


@pytest.mark.parametrize("chemin", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_la_description_est_bornee(chemin):
    entete, _ = _lire(chemin)
    description = " ".join(str(entete.get("description") or "").split())
    assert description, "%s : description vide" % chemin.parent.name
    assert len(description) <= PLAFOND_DESCRIPTION, "%s : description de %d caracteres (plafond %d)" % (
        chemin.parent.name, len(description), PLAFOND_DESCRIPTION)
