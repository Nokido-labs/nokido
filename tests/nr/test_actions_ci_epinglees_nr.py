"""NR — aucune action GitHub ne peut revenir a une reference mobile.

Revue defensive SUPPLY-CHAIN du 2026-09-19, point 4. Les workflows
referencaient leurs actions par tag (`@v7`, `@v4`) ou par BRANCHE
(`@release/v1`). Un tag git SE REDEPLACE : celui qui controle le depot d'une
action peut faire pointer `v7` ailleurs, et la CI executera ce code au prochain
declenchement — sans qu'aucun diff du depot ne bouge. C'est une modification de
ce que la machine execute, invisible a la relecture du depot.

DEUX FAITS RENDENT CE POINT CONCRET ICI :
  - la CI est SELF-HOSTED : ces actions tournent sur la machine de l'owner, pas
    sur un runner jetable qu'on jette apres ;
  - `pypa/gh-action-pypi-publish` etait reference par une BRANCHE, et c'est
    l'action qui PUBLIE sur PyPI.

Ce test ne verifie pas QUELLE version est epinglee — ca, c'est le diff de la
table dans `tools/forge_ci_pin_actions.py`, et c'est un geste humain delibere.
Il verifie la seule propriete qui ne doit jamais se perdre : que la reference
soit IMMUABLE.
"""

import re
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
WORKFLOWS = RACINE / ".github" / "workflows"

# Un sha git complet. Volontairement strict : un sha court se prefixe, donc il
# n'identifie pas un commit de facon stable dans le temps.
_SHA = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")

# Une action LOCALE (`./chemin`) ou un workflow reutilisable du depot lui-meme
# n'a pas de sha a porter : son contenu vient du commit en cours.
_LOCALE = ("./", ".github/")


def _references() -> list[tuple[str, int, str]]:
    trouvees = []
    for f in sorted(list(WORKFLOWS.glob("*.yml")) + list(WORKFLOWS.glob("*.yaml"))):
        for i, ligne in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = ligne.strip()
            if not s.startswith(("- uses:", "uses:")):
                continue
            ref = s.split("uses:", 1)[1].strip().split("#")[0].strip().strip("'\"")
            if ref and not ref.startswith(_LOCALE):
                trouvees.append((f.name, i, ref))
    return trouvees


@pytest.fixture(scope="module")
def refs():
    assert WORKFLOWS.is_dir(), f"{WORKFLOWS} introuvable"
    r = _references()
    # Sans cette borne, un dossier vide ou un parseur casse rendrait le test
    # VERT en n'ayant rien regarde — « je n'ai rien vu » n'est pas « il n'y a
    # rien ».
    assert len(r) >= 20, f"trop peu de references trouvees ({len(r)}) : le test ne regarde plus rien"
    return r


def test_toute_action_externe_est_epinglee_sur_un_sha(refs):
    mobiles = [f"{f}:{i} {ref}" for f, i, ref in refs if not _SHA.match(ref)]
    assert not mobiles, (
        "des actions sont referencees par une ref MOBILE (tag ou branche) — un "
        "tag se redeplace, et la CI est self-hosted :\n  " + "\n  ".join(mobiles)
    )


def test_aucune_reference_par_branche(refs):
    """MORSURE PARTICULIERE — `@release/v1`, la forme qui portait la publication
    PyPI. Une branche bouge a chaque commit de son auteur, c'est la reference la
    moins stable qui existe."""
    branches = [f"{f}:{i} {ref}" for f, i, ref in refs if "/" in ref.split("@", 1)[-1]]
    assert not branches, (
        "des actions sont referencees par une BRANCHE :\n  " + "\n  ".join(branches)
    )


def test_le_tag_lisible_est_conserve_en_commentaire():
    """Un sha nu est illisible : sans le tag en commentaire, personne ne sait
    quelle version tourne, et la table d'epinglage devient impossible a relire.
    C'est la forme recommandee par GitHub."""
    sans_tag = []
    for f in sorted(WORKFLOWS.glob("*.yml")):
        for i, ligne in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = ligne.strip()
            if s.startswith(("- uses:", "uses:")) and "@" in s:
                ref = s.split("uses:", 1)[1].strip()
                if ref.startswith(_LOCALE):
                    continue
                if "#" not in ref:
                    sans_tag.append(f"{f.name}:{i} {ref}")
    assert not sans_tag, (
        "sha epingle SANS le tag en commentaire :\n  " + "\n  ".join(sans_tag)
    )


def test_les_workflows_restent_du_yaml_valide():
    """Un epinglage qui casse la syntaxe supprime la CI au lieu de la proteger."""
    yaml = pytest.importorskip("yaml")
    casses = []
    for f in sorted(list(WORKFLOWS.glob("*.yml")) + list(WORKFLOWS.glob("*.yaml"))):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
            if not isinstance(d, dict) or "jobs" not in d:
                casses.append(f"{f.name}: pas de section jobs")
        except Exception as e:  # noqa: BLE001
            casses.append(f"{f.name}: {type(e).__name__}")
    assert not casses, "workflows invalides :\n  " + "\n  ".join(casses)


def test_la_table_d_epinglage_couvre_ce_qui_est_utilise():
    """L'outil et les workflows ne doivent pas diverger : une action utilisee mais
    absente de la table redeviendrait mobile au prochain passage de l'outil."""
    import ast

    src = (RACINE / "tools" / "forge_ci_pin_actions.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    table = next(
        (n for n in ast.walk(arbre)
         if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "EPINGLES"),
        None,
    )
    assert table is not None, "la table d'epinglage a disparu de l'outil"
    shas = {
        v.elts[0].value
        for v in ast.walk(table)
        if isinstance(v, ast.Tuple) and v.elts and isinstance(v.elts[0], ast.Constant)
    }
    utilises = {ref.split("@", 1)[1] for _, _, ref in _references() if "@" in ref}
    orphelins = sorted(utilises - shas)
    assert not orphelins, (
        "des sha presents dans les workflows ne viennent pas de la table de "
        f"l'outil : {orphelins[:4]} — l'outil les remettrait en tag au prochain "
        "passage, ou bien ils ont ete poses a la main"
    )
