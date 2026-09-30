# -*- coding: utf-8 -*-
"""NR — le workflow de publication PyPI garde ses quatre proprietes de surete.

CE FICHIER EXISTE A CAUSE D'UNE ERREUR, ET C'EST ELLE QU'IL EMPECHE DE REFAIRE.

Le 2026-09-09, cherchant << qui cree une release >>, j'ai balaye
`.github/workflows/*.yml` avec quatre motifs : `git tag`, `gh release`,
`action-gh-release`, `/releases`. Seul `gitleaks.yml` a matche -- dans une URL de
telechargement. J'en ai conclu << AUCUN workflow ne tague ni ne publie >>, puis
j'ai ECRIT un `release.yml`... par-dessus celui qui existait deja.

Le workflow ecrase publie l'open core sur PyPI en Trusted Publishing OIDC. Il
n'emploie aucun des quatre motifs : il passe par `pypa/gh-action-pypi-publish`.
Mon instrument ne pouvait pas le voir, et son silence s'est lu << absence >>.
Pousse, le remplacement aurait supprime la publication PyPI en silence : le
prochain tag `v*` n'aurait plus rien publie, et rien n'aurait echoue.

Deux lecons, toutes deux deja dans le corps et toutes deux payees ici :
  - une absence conclue d'un instrument NOMME ce que l'instrument ne peut pas
    voir (`ABSENT` vs `ILLISIBLE`) -- quatre motifs ne couvrent pas un domaine ;
  - avant d'ECRASER une cible, on la REGARDE. `governed_edit content=` remplace
    un fichier entier sans rien demander ; c'est `git status` qui a dit ` M` la
    ou j'attendais `??`, apres l'ecriture.

Les proprietes verrouillees ci-dessous sont celles dont la perte ne casserait
RIEN de visible -- le workflow continuerait de tourner, en publiant mal.
"""

from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent.parent
WORKFLOW = RACINE / ".github" / "workflows" / "release.yml"


def _charge():
    yaml = pytest.importorskip("yaml")
    texte = WORKFLOW.read_text(encoding="utf-8")
    return texte, yaml.safe_load(texte)


# ------------------------------------------- GITHUB RELEASE (owner 2026-09-10)
#
# Mesure : le depot porte un tag `v17.0.0` et l'API GitHub rend `[]` — AUCUNE
# Release. Le workflow build, verifie, publie sur TestPyPI ou PyPI, et s'arrete
# la. C'est ce que j'avais mal cherche le 2026-09-09 : ne trouvant ni
# `gh release create` ni `action-gh-release`, j'en avais conclu qu'aucun workflow
# de release n'existait — et j'avais ECRASE celui qui publiait sur PyPI.


def _job(nom):
    # `_charge()` rend un TUPLE `(texte, yaml)` — pas un dict. Le supposer m'a
    # coute 5 tests en TypeError : j'ai ecrit le helper sans lire la fonction
    # qu'il appelle.
    _texte, conf = _charge()
    return (conf.get("jobs") or {}).get(nom)


# --------------------------- GATE TESTPYPI DANS LE GRAPHE (owner 2026-09-10)
#
# « Une procedure ecrite dans les commentaires n'est pas une garantie ; le graphe
#   executable doit porter la contrainte. »
#
# Avant : `publish` ne dependait que de `build`. Un `git push --tags` atteignait
# donc PyPI sans qu'aucun artefact soit passe par TestPyPI. La regle « TestPyPI
# obligatoire » n'existait que dans l'en-tete du fichier — c'est-a-dire nulle part.


def test_pypi_est_INATTEIGNABLE_sans_passer_par_testpypi():
    """LE gate. `publish` doit dependre de la VERIFICATION TestPyPI, pas seulement
    du build. Sans cette arete, la regle n'est qu'une intention."""
    besoins = _job("publish").get("needs") or []
    besoins = [besoins] if isinstance(besoins, str) else besoins
    assert any("testpypi" in b for b in besoins), (
        f"publish atteignable sans preuve TestPyPI : needs={besoins}"
    )


def test_un_job_verifie_l_installation_depuis_testpypi():
    """Publier sur TestPyPI ne prouve rien : `pip install` qui reussit n'est pas
    la preuve finale. Il faut un job qui INSTALLE depuis l'index et EXECUTE."""
    verif = _job("verify-testpypi")
    assert verif, "aucun job de verification apres TestPyPI"
    texte = " ".join(str(e) for e in verif.get("steps", []))
    assert "test.pypi.org" in texte, "la verification n'installe pas depuis TestPyPI"
    for interdit in ("--no-index", "--find-links"):
        assert interdit not in texte, (
            f"{interdit} ferait reussir l'installation sans l'index : preuve nulle")


def test_la_verification_execute_une_capacite_pas_seulement_help():
    """`--help` prouve qu'un script demarre, pas que le corps fonctionne."""
    texte = " ".join(str(e) for e in _job("verify-testpypi").get("steps", []))
    assert "import nokido_agent" in texte or "nokido_agent." in texte, (
        "la verification ne traverse aucun import du corps")


def test_un_job_cree_la_release_github():
    """Sans lui, chaque version publiee sur PyPI reste invisible cote GitHub."""
    assert _job("create-release"), "aucun job de creation de Release GitHub"


def test_la_release_n_est_creee_QU_APRES_la_publication_pypi():
    """L'ORDRE est la garantie. Une Release creee avant (ou en parallele de) la
    publication annoncerait une version que PyPI ne sert pas encore — ou pas du
    tout si la publication echoue."""
    besoins = _job("create-release").get("needs") or []
    besoins = [besoins] if isinstance(besoins, str) else besoins
    assert "publish" in besoins, f"create-release ne depend pas de publish : {besoins}"


def test_la_release_ne_se_declenche_QUE_sur_un_tag():
    """`workflow_dispatch` est l'essai a blanc vers TestPyPI : il ne doit jamais
    produire de Release publique."""
    condition = str(_job("create-release").get("if", ""))
    assert "push" in condition, f"condition trop large : {condition!r}"


def test_la_release_NE_RECONSTRUIT_PAS_les_artefacts():
    """Les fichiers publies sur PyPI et ceux attaches a la Release doivent etre
    les MEMES octets. Reconstruire produirait un artefact different — meme
    version, autre empreinte — et rendrait la tracabilite fausse."""
    etapes = _job("create-release").get("steps", [])
    texte = " ".join(str(e) for e in etapes)
    for interdit in ("uv build", "python -m build", "setup.py"):
        assert interdit not in texte, f"la Release reconstruit un artefact : {interdit}"
    assert "download-artifact" in texte, "la Release doit REPRENDRE l'artefact construit"


def test_la_release_a_le_droit_d_ecrire_et_rien_de_plus():
    """`contents: write` est necessaire pour creer une Release. `id-token` ne
    l'est PAS : ce job ne publie sur aucun index."""
    perms = _job("create-release").get("permissions", {})
    assert perms.get("contents") == "write"
    assert "id-token" not in perms, "ce job n'a pas a porter un jeton OIDC"


def test_le_workflow_de_publication_existe_et_parse():
    assert WORKFLOW.exists(), "Track A (publication PyPI) n'a plus de workflow"
    _charge()


def test_la_publication_REELLE_n_est_jamais_declenchable_a_la_main():
    """`workflow_dispatch` sert a l'essai a blanc ; il ne doit JAMAIS toucher PyPI.

    Une version publiee sur PyPI ne peut pas etre re-uploadee : un declenchement
    manuel qui atteindrait le vrai index brulerait le numero de version.
    """
    _, doc = _charge()
    publish = doc["jobs"]["publish"]
    condition = str(publish.get("if", ""))
    assert "push" in condition, (
        "le job `publish` doit etre borne au push d'un tag, vu : %r" % condition)
    assert "workflow_dispatch" not in condition, (
        "un declenchement manuel ne doit jamais atteindre PyPI")
    assert publish.get("environment") == "pypi", (
        "l'environnement GitHub est la barriere qui restreint l'OIDC aux tags v*")


def test_le_job_testpypi_ne_publie_JAMAIS_sur_le_vrai_index():
    """DOMAINE DE VALIDITE CORRIGE le 2026-09-10 — l'intention est INCHANGEE.

    Ce garde exigeait `if: workflow_dispatch` : TestPyPI etait alors un essai a
    blanc optionnel, et la contrainte « TestPyPI avant PyPI » n'existait que dans
    un commentaire. Elle est desormais portee par le GRAPHE : le job tourne sur
    les DEUX evenements, et `publish` en depend (`needs: verify-testpypi`).

    Verifier sa condition de declenchement reviendrait donc a interdire
    exactement ce qu'on vient de rendre obligatoire. Ce qui reste a garder, et qui
    n'a jamais change : ce job ne doit jamais atteindre le VRAI index.

    On ne supprime pas l'ancien garde ; on corrige son domaine de validite.
    """
    texte, doc = _charge()
    smoke = doc["jobs"]["publish-testpypi"]
    assert smoke.get("environment") == "testpypi", (
        "l'environnement GitHub est la barriere qui separe les deux index")
    etapes = " ".join(str(e) for e in smoke.get("steps", []))
    assert "test.pypi.org" in etapes, (
        "sans `repository-url` vers TestPyPI, ce job publierait sur le VRAI index")
    # `"pypi.org/legacy" not in etapes` echouait : c'est une SOUS-CHAINE de
    # `test.pypi.org/legacy/`. 7e occurrence du motif dans la journee — on teste
    # l'URL COMPLETE, pas un fragment.
    import re as _re
    urls = _re.findall(r"https?://[^\s'\"]+", etapes)
    vrais = [u for u in urls if "pypi.org" in u and not u.startswith(
        ("https://test.pypi.org", "http://test.pypi.org"))]
    assert not vrais, f"ce job vise le VRAI index : {vrais}"


def test_testpypi_tolere_une_version_deja_publiee():
    """TestPyPI refuse le re-upload. Sans `skip-existing`, rejouer la chaine apres
    un essai a blanc casserait la publication REELLE — pour une raison qui n'a
    rien a voir avec la qualite de l'artefact."""
    texte, _doc = _charge()
    assert "skip-existing: true" in texte


def test_aucun_token_PyPI_n_est_stocke():
    """Trusted Publishing (OIDC) : le secret qui n'existe pas ne fuit pas."""
    texte, doc = _charge()
    for job in ("publish", "publish-testpypi"):
        perms = doc["jobs"][job].get("permissions") or {}
        assert perms.get("id-token") == "write", (
            "%s doit s'authentifier par OIDC, pas par un token" % job)
    interdits = [m for m in ("secrets.PYPI", "TWINE_PASSWORD", "TWINE_USERNAME",
                             "password:")
                 if m in texte]
    assert not interdits, (
        "un identifiant PyPI stocke annule l'interet du Trusted Publishing : %r"
        % interdits
    )


def test_le_jeton_par_defaut_reste_en_LECTURE():
    _, doc = _charge()
    assert doc.get("permissions") == {"contents": "read"}, (
        "publier ne demande aucune ecriture sur le depot ; vu : %r"
        % (doc.get("permissions"),)
    )


def test_le_garde_anti_release_incoherente_est_toujours_la():
    """Un tag `v1.2.3` qui publierait un wheel 1.2.2 est irrattrapable."""
    texte, _ = _charge()
    assert "pyproject.toml" in texte and "GITHUB_REF_NAME" in texte, (
        "le workflow doit comparer le tag a la version de pyproject AVANT de build"
    )
