# -*- coding: utf-8 -*-
"""NR — le GRAPHE de release porte la contrainte, pas ses commentaires.

__FORGE_COLOR__ = "qualite/build : non-regression du graphe de publication"

Regle owner (2026-09-10) : « une procedure ecrite dans les commentaires n'est
pas une garantie ; le graphe executable doit porter la contrainte ».

La propriete visee — GitHub Release, PyPI et le tag Git sont TROIS
REPRESENTATIONS DU MEME RELEASE, pas trois publications independantes :

    SHA certifie -> tag v* -> artefacts -> TestPyPI -> preuve fresh-venv
                                                    -> PyPI -> GitHub Release

Chaque fleche est un `needs:`. Ce test verifie qu'aucune ne peut etre coupee
sans qu'un rouge apparaisse ici.

DEUX DEFAUTS MESURES le 2026-09-10, tous deux invisibles a la relecture :

1. `skip-existing: true` sur TestPyPI est necessaire (un re-upload y est
   refuse) mais il laissait la preuve porter sur la wheel d'un ESSAI A BLANC
   anterieur, donc sur des octets que PyPI ne servirait jamais.
2. L'environnement GitHub `testpypi` n'admettait que la branche `alpha`. Depuis
   que TestPyPI est un passage OBLIGE, un push de tag y echouait AVANT l'OIDC :
   `tag -> PyPI -> Release` etait mort par construction. Cette moitie-la vit
   dans la configuration GitHub et ne peut pas etre testee ici — le test le DIT
   plutot que de laisser croire a une couverture complete.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


def _graphe() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert doc, "release.yml illisible ou vide — INDETERMINE, pas conforme"
    jobs = doc.get("jobs")
    assert jobs, "aucun job dans release.yml : denominateur vide"
    return jobs


def _besoins(job: dict) -> set[str]:
    n = job.get("needs", [])
    return {n} if isinstance(n, str) else set(n)


def test_les_cinq_etapes_existent():
    """Denominateur : sans elles, tous les tests suivants passeraient a vide."""
    jobs = _graphe()
    attendus = {"build", "publish-testpypi", "verify-testpypi", "publish", "create-release"}
    manquants = attendus - set(jobs)
    assert not manquants, f"etapes absentes du pipeline : {sorted(manquants)}"


def test_PyPI_est_inatteignable_sans_la_preuve_TestPyPI():
    """Le coeur du mandat : publier n'est pas fonctionner.

    `publish` ne doit dependre que de la PREUVE, jamais du seul upload TestPyPI :
    un `needs: publish-testpypi` suffirait a rendre la chaine verte sans qu'aucune
    installation reelle n'ait eu lieu.
    """
    jobs = _graphe()
    besoins = _besoins(jobs["publish"])
    assert "verify-testpypi" in besoins, (
        f"PyPI atteignable sans preuve d'installation : needs={sorted(besoins)}")
    assert "verify-testpypi" in _besoins(jobs["publish"]) and \
        "publish-testpypi" in _besoins(jobs["verify-testpypi"]), \
        "la chaine TestPyPI -> preuve -> PyPI est rompue"


def test_la_GitHub_Release_vient_APRES_PyPI():
    """Une Release creee avant (ou en parallele de) la publication annoncerait
    une version que PyPI ne sert pas encore — ou pas du tout si elle echoue."""
    jobs = _graphe()
    besoins = _besoins(jobs["create-release"])
    assert "publish" in besoins, (
        f"Release creable sans publication PyPI reussie : needs={sorted(besoins)}")


def test_la_Release_ne_RECONSTRUIT_aucun_artefact():
    """Reconstruire donnerait les MEMES versions avec d'AUTRES octets : la
    Release et PyPI cesseraient de decrire le meme objet."""
    jobs = _graphe()
    corps = yaml.safe_dump(jobs["create-release"], allow_unicode=True)
    assert "uv build" not in corps, "la Release rebuild : sa tracabilite serait fausse"
    assert "download-artifact" in corps, "la Release doit REPRENDRE l'artefact publie"
    assert "sha256sum" in corps, "sans empreintes, rien ne relie la Release a PyPI"


def test_la_Release_refuse_un_tag_inexistant():
    corps = yaml.safe_dump(_graphe()["create-release"], allow_unicode=True)
    assert "--verify-tag" in corps, "une faute de frappe produirait une Release orpheline"


def test_la_preuve_MESURE_l_identite_des_octets_servis():
    """`skip-existing` est un garde utile dont le DOMAINE devait etre corrige.

    Sans cette mesure, un essai a blanc publie avant le tag fait servir a
    TestPyPI la wheel de l'essai : la preuve reussit sur des octets que PyPI ne
    servira jamais. Presence != validite != preuve d'execution.
    """
    corps = yaml.safe_dump(_graphe()["verify-testpypi"], allow_unicode=True)
    # `download` n'est pas ambigu ICI : `test_le_depot_n_est_JAMAIS_une_source_
    # Python_dans_la_preuve` interdit `download-artifact` dans ce job, donc le
    # seul telechargement possible est celui de pip depuis l'index.
    assert "download" in corps, (
        "l'artefact servi par TestPyPI n'est jamais recupere : son identite n'est pas mesuree")
    assert "hashlib.sha256" in corps, "aucune empreinte calculee sur l'artefact servi"
    assert "WHEEL_SHA256" in corps, (
        "l'empreinte de reference doit venir du job `build`, pas etre recalculee ici")
    assert "sert un autre artefact" in corps.lower() or "AUTRE artefact" in corps, (
        "une divergence d'octets doit produire un refus NOMME, pas un vert")


def test_la_preuve_installe_depuis_l_INDEX_et_execute_du_code():
    """Ni `--no-index` ni `--find-links` : ils feraient reussir l'installation en
    la nourrissant de ce qu'on veut precisement exclure. Et `--help` ne prouve
    rien — il faut executer une capacite du corps."""
    corps = yaml.safe_dump(_graphe()["verify-testpypi"], allow_unicode=True)
    assert "--no-index" not in corps, "installation nourrie hors index : preuve nulle"
    assert "--find-links" not in corps, "installation nourrie hors index : preuve nulle"
    assert "https://test.pypi.org/simple/" in corps, "l'index TestPyPI n'est pas la source"
    assert "--no-cache-dir" in corps, (
        "un cache pip peut servir une wheel deja vue et masquer ce que l'index sert")
    assert "forge_secrets" in corps, "aucune capacite reelle executee"
    assert "forge_ports" in corps, "une seule capacite ne fait pas un smoke test"
    assert "sys.path" in corps, "l'independance au checkout n'est pas verifiee"
    assert "pip_check" in corps.replace(" ", "_") or '"check"' in corps, (
        "la coherence des dependances installees n'est pas verifiee")


# ------------------------------- CAMPAGNE MULTI-OS (mandat owner 2026-09-10)


def test_la_preuve_tourne_sur_les_TROIS_plateformes():
    """« ONE BUILD -> ONE WHEEL -> ONE TESTPYPI VERSION -> THREE CLEAN RUNNERS ».

    Un paquet `py3-none-any` n'est pas pour autant portable : ce qu'on mesure
    ici est l'installation et le RUNTIME sur trois OS, pas la roue elle-meme.
    """
    v = _graphe()["verify-testpypi"]
    strategie = v.get("strategy") or {}
    inclus = (strategie.get("matrix") or {}).get("include") or []
    noms = {e.get("name") for e in inclus}
    assert {"linux-x64", "windows-x64", "macos-arm64"} <= noms, (
        f"plateformes manquantes : {sorted(noms)}")
    assert strategie.get("fail-fast") is False, (
        "sans `fail-fast: false`, un echec sur un OS ANNULE les preuves des "
        "autres — on perdrait justement l'information qui distingue « le paquet "
        "est casse » de « cet OS-la est casse »")


def test_le_depot_n_est_JAMAIS_une_source_Python_dans_la_preuve():
    """Pas de `checkout`, et pas d'artefact telecharge non plus.

    Le second point est structurel : si l'artefact etait present dans le runner,
    un `pip install` pourrait le prendre pour source et la preuve porterait sur
    des octets qui n'ont jamais transite par l'index. On ne fait pas voyager la
    wheel, seulement son EMPREINTE.
    """
    v = _graphe()["verify-testpypi"]
    utilises = [str(s.get("uses", "")) for s in v.get("steps", [])]
    assert not any("checkout" in u for u in utilises), (
        "un checkout rend le depot importable : la preuve pourrait reussir en "
        "lisant l'arbre au lieu du paquet installe")
    assert not any("download-artifact" in u for u in utilises), (
        "l'artefact ne doit pas entrer dans le runner de preuve : il servirait "
        "d'installation possible. Seul son sha256 voyage, par output de `build`")


def test_la_version_prouvee_vient_de_l_ARTEFACT_pas_du_SOURCE():
    """Relire `pyproject.toml` validerait l'arbre source ; ici on valide ce qui a
    ete CONSTRUIT. La version est derivee du nom de la wheel dans `build`."""
    jobs = _graphe()
    sorties = jobs["build"].get("outputs") or {}
    assert {"version", "wheel_sha256"} <= set(sorties), (
        f"le job build n'exporte pas ce qu'il a produit : {sorted(sorties)}")
    corps_build = yaml.safe_dump(jobs["build"], allow_unicode=True)
    assert "cut -d- -f2" in corps_build, (
        "la version doit etre derivee du NOM DE LA WHEEL construite")
    corps_verify = yaml.safe_dump(jobs["verify-testpypi"], allow_unicode=True)
    assert "needs.build.outputs.version" in corps_verify, (
        "la preuve relit la version ailleurs que dans l'artefact du build")
    assert "pyproject.toml" not in corps_verify, (
        "la preuve relit le SOURCE : elle validerait l'arbre, pas le paquet")


def test_l_attente_de_propagation_est_BORNEE_et_son_echec_est_un_ECHEC():
    """Un index met parfois quelques secondes a servir une version fraiche.
    L'epuisement de l'attente doit rester un FAIL — jamais un PASS par defaut."""
    corps = yaml.safe_dump(_graphe()["verify-testpypi"], allow_unicode=True)
    assert "range(1, 7)" in corps, "la boucle d'attente n'est pas bornee a 6 essais"
    assert "time.sleep(20)" in corps, "pas d'intervalle entre les essais"
    assert "introuvable apres 6 essais" in corps, (
        "l'epuisement de l'attente doit produire un echec NOMME")


def test_PyPI_n_est_atteint_que_par_un_TAG():
    """`workflow_dispatch` doit rester un essai a blanc : il publie sur TestPyPI
    et JAMAIS sur PyPI."""
    jobs = _graphe()
    for etape in ("publish", "create-release"):
        garde = str(jobs[etape].get("if", ""))
        assert "push" in garde, (
            f"{etape} tourne sur declenchement manuel : PyPI atteignable a blanc")


def test_le_tag_doit_EGALER_la_version_du_paquet():
    """Sans cette garde, `v0.19.0` pourrait publier 0.18.0 : le tag cesserait
    d'etre la colonne vertebrale."""
    corps = yaml.safe_dump(_graphe()["build"], allow_unicode=True)
    assert "pyproject.toml" in corps and "GITHUB_REF_NAME" in corps, (
        "aucune garde tag == pyproject.version")


# ------------------------------- CONTRAT OWNER DU 2026-09-10
#
# « GitHub Release, PyPI et le tag Git = TROIS REPRESENTATIONS DU MEME RELEASE. »
# Chaque clause enoncee devient un test ci-dessous. Une clause sans test est une
# intention ; on en a deja paye le prix avec la regle d'environnement `testpypi`,
# ecrite en commentaire et fausse pendant des semaines.


def test_INVARIANT_VERSION_les_ARTEFACTS_aussi_sont_gardes():
    """tag = pyproject = **wheel** = **sdist** = PyPI = Release.

    La garde `tag == pyproject.version` ne dit RIEN des octets produits : un
    build servant une autre version (cache, arbre sale, metadonnee dynamique)
    passerait. La chaine serait fausse des sa premiere maille.
    """
    corps = yaml.safe_dump(_graphe()["build"], allow_unicode=True)
    assert "dist/*.whl" in corps, "la version de la WHEEL produite n'est jamais verifiee"
    assert "dist/*.tar.gz" in corps, "la version de la SDIST produite n'est jamais verifiee"


def test_le_BUILD_est_REPRODUCTIBLE_pour_un_SHA_donne():
    """Sans cela, la garde d'identite des octets bloque le pipeline a juste titre.

    Mesure du 2026-09-10, deux builds du MEME commit :

        sans SOURCE_DATE_EPOCH, mtime modifie -> 940c30c6... puis 1bf2af77...
        avec SOURCE_DATE_EPOCH, mtime modifie -> dbed0370... deux fois

    setuptools tire les horodatages du zip du `mtime` des sources, qu'un
    checkout REECRIT a chaque run. L'essai a blanc publie la version sur
    TestPyPI ; le tag rejoue, `skip-existing` sert la wheel de l'essai, et les
    octets different alors que le code est identique. Trois hypotheses avaient
    ete nommees AVANT la mesure (A reproductible / B SOURCE_DATE_EPOCH /
    C bumper la version) : B confirmee, A et C refutees.
    """
    corps = yaml.safe_dump(_graphe()["build"], allow_unicode=True)
    assert "SOURCE_DATE_EPOCH" in corps, (
        "build non reproductible : deux runs du meme SHA produiront des octets "
        "differents, et la garde d'identite des octets rougira sans defaut reel")
    assert "pretty=%ct" in corps, (
        "l'horodatage doit venir d'une DATE DE COMMIT, pas d'une constante ni de "
        "l'heure du run — sinon il n'est pas reproductible d'un run a l'autre")
    # ⚠️ ET IL DOIT SUIVRE LE CONTENU EMPAQUETE, pas le dernier commit.
    #
    # Mesure du 2026-09-10 : avec `git log -1 --pretty=%ct` tout court, corriger
    # le WORKFLOW change l'horodatage, donc les octets de la wheel, alors que le
    # paquet est identique — deux builds mesures a b649fda3... et a926d07a... .
    # `skip-existing` sert alors la version deja publiee, la garde d'empreinte
    # rougit, et il faudrait BUMPER a chaque retouche de CI. Dater sur le dernier
    # commit ayant touche la distribution rend un correctif de CI bit-a-bit neutre.
    # ⚠️ Lecture du TEXTE BRUT, pas du dump : `yaml.safe_dump` re-enveloppe les
    # lignes longues a 80 colonnes et coupe les commandes shell au milieu. Un
    # oracle qui lit un dump ne lit pas le fichier — paye ici meme, 2026-09-10.
    brut = WORKFLOW.read_text(encoding="utf-8")
    assert "nokido_agent app tools pyproject.toml" in brut, (
        "l'horodatage suit le dernier commit tout court : toute retouche de CI "
        "changerait les octets de la wheel et brulerait la version publiee")
    assert "fetch-depth" in brut, (
        "sans historique complet, `git log -- <chemins>` ne peut pas remonter au "
        "dernier changement du contenu empaquete")


def test_INVARIANT_ARTEFACT_la_Release_CONSTATE_les_octets_de_PyPI():
    """« vrai par construction » n'est pas « constate ».

    Les octets joints viennent du meme artefact que ceux publies — mais c'est
    exactement le raisonnement qui a laisse `skip-existing` faire prouver la
    mauvaise wheel sur TestPyPI. La Release MESURE que PyPI sert ces octets-la.
    """
    corps = yaml.safe_dump(_graphe()["create-release"], allow_unicode=True)
    assert "pip download" in corps, "les octets servis par PyPI ne sont jamais recuperes"
    assert "servi par PyPI" in corps or "SERVI" in corps, "aucune comparaison d'empreinte"


def test_la_Release_REFERENCE_la_version_PyPI_et_le_SHA_certifie():
    """« Ne jamais creer une GitHub Release qui ne permet pas de remonter au SHA
    certifie. » Des notes auto-generees listent des PR — jamais la version
    publiee ni le commit juge."""
    corps = yaml.safe_dump(_graphe()["create-release"], allow_unicode=True)
    assert "pypi.org/project/nokido-agent" in corps, (
        "la Release ne reference pas explicitement la version PyPI")
    assert "GITHUB_SHA" in corps, "la Release ne porte pas le SHA certifie"
    assert "--notes-file" in corps, (
        "notes non maitrisees : `--generate-notes` et `--notes` ne se combinent pas "
        "de facon garantie, et un pipeline ne se pose pas sur un comportement suppose")


def test_les_PERMISSIONS_sont_au_plus_juste():
    """Le defaut du depot est en lecture ; chaque job n'ouvre que ce qu'il lui
    faut. La Release ECRIT le depot mais ne publie RIEN : lui donner `id-token`
    lui donnerait le pouvoir de publier sur l'index."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert doc.get("permissions") == {"contents": "read"}, (
        f"defaut du workflow trop large : {doc.get('permissions')}")
    jobs = doc["jobs"]
    rel = jobs["create-release"].get("permissions") or {}
    assert rel.get("contents") == "write", "la Release ne peut pas etre creee"
    assert "id-token" not in rel, (
        "le job Release porte id-token : il pourrait publier sur l'index")
    for etape in ("publish", "publish-testpypi"):
        assert (jobs[etape].get("permissions") or {}).get("id-token") == "write", (
            f"{etape} sans OIDC : il faudrait un token stocke en secret")


def test_seul_PyPI_porte_l_environnement_protege_par_TAG():
    """`pypi` est l'environnement qui atteint l'index public : sa regle de
    deploiement doit rester Tag `v*` SEUL. `testpypi` admet en plus la branche,
    parce que l'essai a blanc tourne par workflow_dispatch.

    ⚠️ Cote DEPOT on ne peut verifier que la DECLARATION des environnements ;
    leurs regles vivent dans la configuration GitHub (cf. le test d'angle mort).
    """
    jobs = _graphe()
    assert jobs["publish"].get("environment") == "pypi"
    assert jobs["publish-testpypi"].get("environment") == "testpypi"
    assert jobs["create-release"].get("environment") is None, (
        "la Release ne doit dependre d'aucun environnement de publication")


def test_la_preuve_LANCE_un_entrypoint_installe():
    """Un `[project.scripts]` peut s'installer parfaitement et mourir au premier
    lancement — il suffit qu'il importe un module sous un nom que la wheel
    n'expose pas. Aucune verification d'import ne le voit, parce que personne ne
    LANCE la commande. Mesure du 2026-09-19 : `nokido-doctor` importait
    `app.forge_install_prerequis`, que le paquet publie nomme
    `nokido_agent.app.forge_install_prerequis`.
    """
    corps = yaml.safe_dump(_graphe()["verify-testpypi"], allow_unicode=True)
    assert "nokido-doctor" in corps, (
        "aucun entrypoint n'est LANCE : la preuve s'arrete a l'import")
    assert "entrypoint nokido-doctor" in corps, (
        "l'etape doit etre NOMMEE, sinon son absence ne se distingue pas d'un succes")
    # Le verdict ne doit pas se prendre sur le seul code de retour : cette
    # commande rend 1 quand un prerequis manque sur le runner, ce qui est
    # ATTENDU et n'est pas un echec du paquet.
    assert "returncode in (0, 1)" in corps, (
        "juger cet entrypoint sur rc==0 ferait echouer la release parce qu'un "
        "runner GitHub n'a ni deno ni ollama — un faux echec, pire qu'un trou")


def test_la_preuve_couvre_le_SDIST_et_pas_seulement_la_wheel():
    """Une wheel correcte n'implique pas un sdist correct.

    La wheel sort de l'arbre, le sdist de `MANIFEST.in` : un fichier de donnees
    oublie n'existe que dans le second cas, et seulement si on installe REELLEMENT
    depuis lui. `--no-binary` est ce qui force pip a le reconstruire au lieu de
    reprendre la wheel deja publiee.
    """
    corps = yaml.safe_dump(_graphe()["verify-testpypi"], allow_unicode=True)
    assert "sdist installable" in corps, "le sdist publie n'est jamais installe"
    assert "--no-binary" in corps, (
        "sans --no-binary, pip reprend la wheel : le sdist n'est pas teste")
    assert "venv-sdist" in corps, (
        "le sdist doit s'installer dans un venv PROPRE, sinon il herite de la wheel")
    # Le verdict se prend par comparaison, pas sur un nombre ecrit en dur : un
    # seuil code se perimerait au premier fichier de donnees ajoute.
    assert "MANIFEST" in corps, (
        "un sdist incomplet doit nommer sa cause, sinon le message n'aide personne")


# L'EDITEUR est le depot dist (owner 2026-09-30) : le paquet publie doit etre le
# contenu FILTRE et generise du dist, pas la source. Le meme `release.yml` vit
# dans les deux depots (le promoteur l'embarque), donc son graphe se juge PAR
# DEPOT, et par EVENEMENT : une garde relue a l'oeil ne dit pas ce qui tourne.
# L'editeur se designe par la variable de depot NOKIDO_EDITEUR == 'true', JAMAIS
# par un nom (owner 2026-09-30) : au renommage prevu (nokido -> nokido-private,
# nokido-dist -> nokido), le nom `nokido` change de proprietaire -- une garde
# `github.repository == 'Nokido-labs/nokido'` ferait publier la SOURCE pendant
# la fenetre. La variable suit le depot quand on le renomme.
DEPOT_SOURCE = ""        # variable absente sur la source
DEPOT_DIST = "true"      # posee sur l'editeur seulement


def _condition_vraie(expr, depot: str, evenement: str) -> bool:
    """Evalue une garde `if:` pour un couple (valeur de NOKIDO_EDITEUR, evenement).

    Seules `vars.NOKIDO_EDITEUR`, `github.event_name`, `==`, `!=`, `||`, `&&` sont
    traduites : tout autre symbole -- `github.repository` compris -- leve une
    erreur a l'evaluation, et le test echoue en le disant.
    """
    if expr in (None, ""):
        return True
    s = str(expr).strip()
    if s.startswith("${{") and s.endswith("}}"):
        s = s[3:-2]
    s = (s.replace("vars.NOKIDO_EDITEUR", repr(depot))
          .replace("github.event_name", repr(evenement))
          .replace("||", " or ").replace("&&", " and "))
    return bool(eval(s, {"__builtins__": {}}, {}))  # noqa: S307 - chaine du depot, symboles traduits


def _jobs_executes(depot: str, evenement: str) -> set[str]:
    """Jobs qui tournent : garde vraie ET tous les `needs` executes (un job
    saute fait sauter ses dependants, comme GitHub le fait par defaut)."""
    jobs = _graphe()
    tournent: set[str] = set()
    restants = dict(jobs)
    while True:
        prets = [n for n, j in restants.items() if _besoins(j) <= set(jobs) - set(restants)]
        if not prets:
            break
        for n in prets:
            j = restants.pop(n)
            if _besoins(j) <= tournent and _condition_vraie(j.get("if"), depot, evenement):
                tournent.add(n)
    assert not restants, f"cycle ou needs inconnus : {sorted(restants)}"
    return tournent


def test_l_EDITEUR_est_le_dist_la_source_ne_publie_RIEN():
    for evenement in ("push", "workflow_dispatch"):
        publies = _jobs_executes(DEPOT_SOURCE, evenement) & {
            "publish-testpypi", "publish", "create-release"}
        assert not publies, (
            f"la source publie encore ({evenement}) : {sorted(publies)} — deux "
            "editeurs pour une meme version, et TestPyPI n'accepte qu'un upload")
    assert "build" in _jobs_executes(DEPOT_SOURCE, "push"), (
        "la source doit continuer a CONSTRUIRE (verification du paquet)")


def test_sur_le_dist_TestPyPI_est_MANUEL_et_prouve_sur_les_trois_OS():
    tournent = _jobs_executes(DEPOT_DIST, "workflow_dispatch")
    attendus = {"build", "publish-testpypi", "verify-testpypi"}
    assert attendus <= tournent, f"manquent sur dispatch : {sorted(attendus - tournent)}"
    assert not tournent & {"publish", "create-release"}, (
        "un declenchement manuel sur le dist atteint PyPI ou cree une Release")


def test_sur_le_dist_le_tag_de_PROMOTION_ne_publie_RIEN():
    """Le promoteur pousse `v*` sur le dist : ce push ne doit rien publier
    (choix owner 2026-09-30 : TestPyPI se lance a la main). PyPI reel reste
    donc inatteignable partout tant que l'owner ne rouvre pas ce chemin."""
    tournent = _jobs_executes(DEPOT_DIST, "push")
    assert not tournent, f"le tag de promotion declenche : {sorted(tournent)}"


def test_l_evaluateur_de_gardes_MORD():
    """Contre-epreuve : sans elle, un evaluateur qui rendrait toujours faux
    ferait passer les trois tests ci-dessus pour de mauvaises raisons."""
    assert _condition_vraie("vars.NOKIDO_EDITEUR == 'true'", DEPOT_DIST, "push")
    assert not _condition_vraie("vars.NOKIDO_EDITEUR == 'true'", DEPOT_SOURCE, "push")
    assert _condition_vraie("github.event_name == 'push'", DEPOT_SOURCE, "push")
    assert _condition_vraie(None, DEPOT_SOURCE, "push")


def test_aucune_garde_ne_depend_du_NOM_du_depot():
    """Un nom de depot change de proprietaire au renommage : la garde doit tenir
    par la variable NOKIDO_EDITEUR, qui suit le depot."""
    for nom, job in _graphe().items():
        garde = str(job.get("if", ""))
        assert "github.repository" not in garde, f"{nom} : garde par nom de depot ({garde})"


def test_CE_QUE_CE_TEST_NE_COUVRE_PAS_est_ECRIT():
    """Trois etats, jamais deux. La moitie du pipeline vit dans la CONFIGURATION
    GitHub (regles de deploiement des environnements) et reste hors de portee
    d'un test de depot. Un NR qui n'annonce pas son angle mort laisse croire a
    une couverture qu'il n'a pas — c'est ainsi que le blocage `testpypi` a
    survecu a une relecture.
    """
    entete = WORKFLOW.read_text(encoding="utf-8")[:4000]
    assert "deployment-branch-policies" in entete, (
        "l'en-tete doit porter la commande qui MESURE les regles d'environnement, "
        "sinon l'angle mort de ce NR n'est documente nulle part")
