"""Le miroir public fabrique ce qui sera EXPOSE : ses garde-fous priment.

Trois proprietes de surete, chacune adossee a une mesure du 2026-08-29 :
  - il ne POUSSE jamais (publier reste un geste owner explicite) ;
  - il n'ecrit ni sur `alpha` ni sur `beta` (une branche dediee, sinon on
    ecraserait l'atelier avec un arbre ampute) ;
  - il refuse de produire un snapshot dont l'audit n'est pas VERT -- c'est tout
    l'objet de l'outil, un secret vivant dans l'histoire des branches publiables.
"""

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.53)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import forge_public_mirror as fpm  # noqa: E402


def test_exclut_ce_qui_porte_le_secret_et_les_dumps():
    """`sandbox/` porte le blob compromettant ; `RAG_plain_bak/` des dumps de
    bench (>100 Mo, donnees tierces possibles)."""
    assert "sandbox" in fpm.EXCLUSIONS
    assert "RAG_plain_bak" in fpm.EXCLUSIONS
    assert ".claude" in fpm.EXCLUSIONS


def test_la_strategie_commerciale_ne_part_pas_au_public():
    """Decision owner du 2026-08-30, rendue EXECUTABLE.

    `docs/roadmap_product_4phases.md` porte une grille de prix, des cibles
    d'acquisition nommees et des criteres de valorisation. Ce n'est pas un secret
    technique, donc aucun scanner de secrets ne l'arretera : seule cette exclusion
    le retient. Une decision qui ne tient qu'a une phrase dans un commentaire finit
    par sauter au refactor suivant — d'ou ce garde.
    """
    assert "docs/roadmap_product_4phases.md" in fpm.EXCLUSIONS, (
        "la roadmap produit repartirait au miroir public : exclusion retiree ?"
    )
    # Elle doit aussi disparaitre de l'HISTOIRE en mode --historique, sans quoi elle
    # reste lisible dans les commits anterieurs du miroir.
    assert "docs/roadmap_product_4phases.md" in fpm.PURGE_HISTORIQUE


def test_la_ref_cible_n_ecrase_ni_alpha_ni_beta():
    """Un snapshot est ampute : l'ecrire sur une branche de travail detruirait
    l'atelier."""
    assert fpm.REF_SNAPSHOT.endswith("/public-snapshot")
    assert "alpha" not in fpm.REF_SNAPSHOT and "beta" not in fpm.REF_SNAPSHOT


def test_source_inexistante_refuse_proprement():
    r = fpm.construire("branche-qui-n-existe-pas", apply=False)
    assert r["ok"] is False and "introuvable" in r["raison"]


def test_le_module_ne_pousse_jamais():
    """Aucun appel `push` dans le code : publier est un geste OWNER. Un outil qui
    peut publier tout seul finit par publier tout seul."""
    src = (ROOT / "tools" / "forge_public_mirror.py").read_text(encoding="utf-8")
    lignes_actives = [l for l in src.splitlines()
                      if not l.strip().startswith("#") and '"""' not in l]
    assert not any('"push"' in l or "'push'" in l for l in lignes_actives)


def test_dry_run_est_le_defaut():
    """`--apply` doit etre demande : rien ne se cree par simple consultation."""
    import inspect
    sig = inspect.signature(fpm.construire)
    assert sig.parameters["apply"].default is False
