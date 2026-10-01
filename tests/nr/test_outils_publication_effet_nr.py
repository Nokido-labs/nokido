"""NR — trois outils de publication font ce qu'ils annoncent, mesuré par leur EFFET.

Le cliquet `test_nr_coverage_ratchet_nr` les a signalés le 2026-09-19 : ajoutés
au dépôt sans aucun test NR. Il avait raison — un outil qui déplace des
artefacts vers le public, redéploie un binaire de service ou généralise des
chemins machine mérite mieux qu'une vérification d'import.

Chaque test ci-dessous exerce un **effet**, jamais la simple importabilité.

| module | effet vérifié |
|---|---|
| `forge_dist_install_probe` | compte les imports plats par AST, pas par texte |
| `forge_enquetes_publier` | la généralisation retire les chemins machine |
| `forge_go_service_deploy` | refuse de déployer tant qu'un port écoute |
"""
from __future__ import annotations

import importlib.util as _u
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))


def _charger(nom: str):
    """Chargé par chemin : ces modules sont des OUTILS, pas des bibliothèques."""
    src = RACINE / "tools" / (nom + ".py")
    assert src.exists(), "outil disparu : %s" % src
    spec = _u.spec_from_file_location(nom + "_nr", src)
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# --------------------------------------------------------------- dist probe
def test_le_probe_compte_les_imports_plats_par_AST_et_non_par_texte(tmp_path):
    """La mesure qui a corrigé le README reposait sur cette distinction.

    Un comptage textuel donnait 4 449 là où l'AST en trouve 36 : il comptait les
    MENTIONS (commentaires, docstrings, chaînes). Si ce module se remettait à
    compter du texte, la conclusion publiée redeviendrait fausse.
    """
    m = _charger("forge_dist_install_probe")
    faux = tmp_path / "app"
    faux.mkdir()
    (faux / "piege.py").write_text(
        '"""Docstring qui parle de: import forge_secrets."""\n'
        "# commentaire : from forge_db_path import x\n"
        'CHAINE = "import forge_rag_engine"\n'
        "import os  # seul import REEL, et il n'est pas plat\n",
        encoding="utf-8")
    m.ROOT = tmp_path
    plats = m.imports_plats_du_depot()
    assert plats == {}, (
        "des MENTIONS ont ete comptees comme des imports : %r — c'est l'erreur "
        "qui avait produit le chiffre de 4 449" % plats)

    (faux / "vrai.py").write_text("from forge_secrets import get_secret\n", encoding="utf-8")
    plats = m.imports_plats_du_depot()
    assert any("vrai.py" in k for k in plats), (
        "un import plat REEL n'est pas detecte : la sonde ne mord plus")


def test_le_probe_rend_un_code_non_nul_si_une_ETAPE_echoue():
    """Défaut mesuré sur cet outil même : `rc=0` alors que le build avait échoué.

    La liste des modules restait vide, donc « aucun échec ». Une sonde qui rend
    vert quand elle n'a RIEN pu mesurer est pire qu'absente.
    """
    m = _charger("forge_dist_install_probe")
    rapport = {"etapes": [{"etape": "build", "etat": "ECHEC", "detail": "x"}],
               "modules": [], "entrypoints": [], "imports_plats": {}, "avec_deps": False}
    m.sonder = lambda **kw: rapport
    assert m.main([]) == 1, "un echec d'etape doit rendre un code non nul"


# ---------------------------------------------------------- enquetes publier
def test_la_generalisation_retire_les_chemins_machine():
    m = _charger("forge_enquetes_publier")
    gen = m._generiseur()
    temoin = r"le fichier C:\Users\CompteFabrique\Script python IA\Nokido\app\x.py"
    sortie = m._generiser(temoin) if hasattr(m, "_generiser") else gen(temoin)
    assert "CompteFabrique" not in sortie, (
        "un chemin de profil machine survit a la generalisation : il partirait "
        "dans l'artefact publie")


def test_le_controle_de_RESIDU_est_distinct_de_la_generalisation():
    """Deux étapes séparées : généraliser, puis VÉRIFIER qu'il ne reste rien.

    Les confondre ferait juger le filtre par lui-même — il conclurait toujours
    qu'il a bien travaillé.
    """
    m = _charger("forge_enquetes_publier")
    assert hasattr(m, "_residus"), "le controle de residu a disparu"
    restants = m._residus(r"chemin C:\Users\Quelquun\ailleurs")
    assert restants, "le controle de residu ne detecte plus un chemin machine"
    assert not m._residus("texte parfaitement anodin"), "faux positif sur du texte sain"


# --------------------------------------------------------- go service deploy
def test_le_garde_de_PORT_precede_toute_copie_de_binaire():
    """Écraser un binaire pendant qu'il tourne est le défaut que cet outil
    existe pour empêcher — le contrôle doit donc venir AVANT la copie.

    ⚠️ Vérifié par LECTURE de l'ordre, pas par exécution : une première version
    de ce test appelait `deployer()`, qui sortait bien avant le garde faute de
    `main.go` dans l'arbre courant. La sonde n'atteignait pas son sujet et
    aurait pu être « corrigée » en relâchant l'assertion. On mesure donc la
    propriété qui compte — l'ORDRE — là où elle est décidable.
    """
    import ast

    src = (RACINE / "tools" / "forge_go_service_deploy.py").read_text(
        encoding="utf-8", errors="replace")
    arbre = ast.parse(src)
    fn = next((n for n in ast.walk(arbre)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "deployer"), None)
    assert fn is not None, "la fonction `deployer` a disparu"

    l_port, l_copie = None, None
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            nom = n.func.attr if isinstance(n.func, ast.Attribute) else (
                n.func.id if isinstance(n.func, ast.Name) else "")
            if nom == "_port_occupe" and l_port is None:
                l_port = n.lineno
            if nom in ("copy2", "copy", "move", "replace") and l_copie is None:
                l_copie = n.lineno
    assert l_port is not None, (
        "aucun controle de port dans `deployer` : le binaire peut etre ecrase "
        "pendant qu'il tourne")
    if l_copie is not None:
        assert l_port < l_copie, (
            "le controle de port (l.%d) vient APRES la copie (l.%d) : il ne "
            "protege rien" % (l_port, l_copie))


# -------------------------------------------------------- audit perimetre
def test_materialiser_en_DRY_RUN_n_ecrit_rien(tmp_path, monkeypatch):
    """Un outil qui matérialise un périmètre doit pouvoir être essayé à blanc.

    Sans cette garantie, la seule façon de savoir ce qu'il ferait est de le
    laisser le faire — et le dépôt a déjà payé un `working tree != HEAD` qui
    écrase (récupération par `forge_restore_from_head`).
    """
    m = _charger("forge_audit_perimetre")
    # On coupe git : ce test mesure l'ECRITURE, pas la resolution du sha.
    # ⚠️ `_git` rend un TRIPLET (rc, sortie, erreur) et ses flux sont en OCTETS
    # (l'appelant fait `.decode`). Une substitution approximative fait echouer
    # le test sur SA propre erreur et non sur le defaut vise — il a fallu deux
    # essais pour trouver ce contrat, ce qui est exactement le symptome qu'un
    # module sans aucun test ne documente pas ses interfaces.
    monkeypatch.setattr(m, "_git", lambda args: (0, b"app/x.py\ntools/y.py\n", b""))
    monkeypatch.setattr(m, "fichiers_du_sha", lambda sha, prefixe: ["app/x.py"])

    cible = tmp_path / "perimetre"
    m.materialiser("abc1234", ["app/"], cible, appliquer=False)
    ecrits = list(cible.rglob("*")) if cible.exists() else []
    assert not ecrits, (
        "le mode dry-run a ecrit %d entree(s) sous %s : un essai a blanc qui "
        "modifie le disque n'est pas un essai a blanc" % (len(ecrits), cible))


# ---------------------------------------------------------------------------
# Le tag pose doit == la version EMPAQUETEE (mesure 2026-09-19)
# ---------------------------------------------------------------------------

def test_le_garde_couvre_AUSSI_la_version_du_module(monkeypatch):
    """TROISIEME porte : `nokido_agent.__version__`, celle que la preuve IMPRIME.

    Mesure 2026-09-19 : apres avoir ferme tag<->pyproject, j'avais ouvert
    pyproject<->__version__ -- attrapee par `test_version_unique_nr`, pas par moi.
    Ici le pyproject CONCORDE et seul le module diverge : si le garde ne tenait
    que la premiere porte, ce cas passerait.
    """
    m = _charger("forge_dist_publish")
    monkeypatch.setattr(m, "_version_du_paquet", lambda s=None: "2.0.0")
    monkeypatch.setattr(m, "_version_du_module", lambda s=None: "1.9.9")

    with pytest.raises(SystemExit) as capture:
        m._verifier_version_du_paquet("2.0.0")
    motif = str(capture.value)
    assert "__init__.py" in motif and "1.9.9" in motif, (
        "le refus doit nommer la SOURCE divergente, pas seulement la divergence : %s" % motif)


def test_le_garde_de_version_refuse_un_tag_qui_ment(monkeypatch):
    """`forge_dist_publish` taguait `v0.20.2` sur un paquet reste en `0.20.1`.

    Consequence : PyPI REFUSE de republier une version existante, donc la chaine
    aurait servi l'ANCIEN artefact sous le nouveau numero. Le workflow
    `release.yml` portait deja ce garde ; il manquait du cote qui FABRIQUE le
    snapshot -- un contrat tenu d'un seul cote n'est pas un contrat.
    """
    m = _charger("forge_dist_publish")
    # TOUTES les sources sont substituees : n'en couvrir qu'une laisserait la
    # vraie valeur entrer par la porte oubliee -- et le test mesurerait le depot
    # au lieu du garde.
    monkeypatch.setattr(m, "_version_du_paquet", lambda s=None: "0.20.1")
    monkeypatch.setattr(m, "_version_du_module", lambda s=None: "0.20.1")

    with pytest.raises(SystemExit) as capture:
        m._verifier_version_du_paquet("0.99.0")
    motif = str(capture.value)
    assert "INCOHERENT" in motif, motif
    assert "0.99.0" in motif and "0.20.1" in motif, (
        "le refus doit NOMMER les deux versions, sinon il n'est pas diagnostiquable : %s" % motif)


def test_le_garde_de_version_laisse_passer_ce_qui_concorde(monkeypatch):
    """CONTRE-EPREUVE : sans elle, un garde qui refuse TOUT passerait le test
    precedent sans rien prouver."""
    m = _charger("forge_dist_publish")
    monkeypatch.setattr(m, "_version_du_paquet", lambda s=None: "1.2.3")
    monkeypatch.setattr(m, "_version_du_module", lambda s=None: "1.2.3")
    m._verifier_version_du_paquet("1.2.3")  # ne doit pas lever


def test_un_pyproject_illisible_ne_se_lit_pas_comme_coherent(monkeypatch):
    """Trois etats : concordant / divergent / NON VERIFIABLE.

    Un fichier illisible ne prouve AUCUNE coherence -- mais il ne doit pas non
    plus bloquer une publication en inventant une divergence. On laisse passer,
    et on le DIT.
    """
    m = _charger("forge_dist_publish")
    monkeypatch.setattr(m, "_version_du_paquet", lambda s=None: None)
    monkeypatch.setattr(m, "_version_du_module", lambda s=None: None)
    m._verifier_version_du_paquet("0.0.1")  # ne doit pas lever


def test_le_manifeste_vient_APRES_le_commit_ET_apres_les_artefacts():
    """Defaut de SEQUENCE — invisible a tout test unitaire, et paye le 2026-09-20.

    Ma premiere version ecrivait le manifeste AVANT `build_assets` : `artifacts`
    y aurait toujours ete ABSENT, et le champ aurait impute cette absence a
    « --with-assets non demande » alors que le lot allait etre construit trois
    lignes plus bas. Un manifeste se compose de valeurs OBSERVEES : il vient
    APRES D et APRES les empreintes, jamais avant l'un des deux.

    On compare des APPELS (ast.Call), pas des occurrences textuelles : la
    definition d'une fonction porte son nom elle aussi.
    """
    import ast
    m = _charger("forge_dist_publish")
    arbre = ast.parse(open(m.__file__, encoding="utf-8").read())
    appels = {}
    for n in ast.walk(arbre):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in ("build_assets", "write_dist_manifest",
                                  "commit_version")):
            appels.setdefault(n.func.id, []).append(n.lineno)
    manifeste = min(appels["write_dist_manifest"])
    assert min(appels["commit_version"]) < manifeste, \
        "le manifeste porte dist_commit : il ne peut pas preceder le commit"
    assert min(appels["build_assets"]) < manifeste, \
        "le manifeste porte les empreintes d'artefacts : il ne peut pas les " \
        "preceder, sinon il declare ABSENT ce qui va exister"


def test_les_artefacts_sont_construits_DANS_le_lot_qu_on_lit():
    """Un chemin par defaut divergent ne casse rien bruyamment : il ment.

    `forge_release_assets` ecrit par defaut dans C:/tmp/laforge-release/... et
    le promoteur lit C:/tmp/nokido-release/... : les artefacts partaient
    AILLEURS que la ou on les cherche. Le promoteur doit donc passer `--out`.
    """
    import ast
    m = _charger("forge_dist_publish")
    arbre = ast.parse(open(m.__file__, encoding="utf-8").read())
    corps = next(n for n in ast.walk(arbre)
                 if isinstance(n, ast.FunctionDef) and n.name == "build_assets")
    texte = ast.unparse(corps)
    assert "'--out'" in texte or '"--out"' in texte, \
        "sans --out, le lot construit n'est pas celui que le manifeste lit"
    assert "out_dir" in [a.arg for a in corps.args.args], corps.args.args


def test_le_jeton_ne_touche_JAMAIS_l_URL_ni_la_ligne_de_commande(monkeypatch):
    """Invariants de secret (owner 2026-09-20), verifies et non relus.

    Le PAT ne doit apparaitre ni dans l'URL, ni dans `git remote`, ni dans
    `.git/config`, ni dans argv, ni dans les journaux. Il ne transite que par
    l'ENVIRONNEMENT du sous-processus git. Un secret dans argv se lit ; un
    secret dans `.git/config` SURVIT au processus.

    Note sur l'histoire de ce test : j'avais d'abord ecrit l'inverse — sonde
    ANONYME, en affirmant que le depot etait public. Il est PRIVE, et ma
    « lecture sans authentification » passait par un gestionnaire en cache.
    """
    m = _charger("forge_dist_publish")
    TEMOIN = "SECRET_TRES_RECONNAISSABLE_0123456789"
    monkeypatch.setattr(m, "_jeton_github", lambda: TEMOIN)
    vus = {}

    def faux_run(cmd, **kw):
        vus["cmd"] = list(cmd)
        vus["env"] = kw.get("env") or {}
        return type("R", (), {"returncode": 0, "stderr": "",
                              "stdout": "abc\trefs/heads/main\n"})()

    monkeypatch.setattr(m, "run", faux_run)
    assert m._etat_distant("https://exemple.invalid/x.git")[0] == "PORTE"
    joint = " ".join(vus["cmd"])
    assert TEMOIN not in joint, "le jeton est passe dans argv : %s" % joint
    assert "$GH_TOKEN" in joint, \
        "le helper doit LIRE la variable, pas recevoir sa valeur"
    assert vus["env"]["GH_TOKEN"] == TEMOIN
    assert vus["env"]["GIT_TERMINAL_PROMPT"] == "0"
    # La liste heritee est REINITIALISEE avant d'ajouter la notre : sans ce
    # premier `-c` vide, le gestionnaire du compte reste dans la chaine et
    # retente un prompt qu'aucun job detache ne peut satisfaire.
    assert vus["cmd"][1:3] == ["-c", "credential.helper="], vus["cmd"][:5]


def test_une_construction_de_release_ne_MUTE_pas_sa_source(tmp_path, monkeypatch):
    """`build = snapshot(S)` perd son sens si le build reecrit l'arbre source.

    Mesure du 2026-09-20 : `write_vendor_lock()` ecrivait a la racine du depot
    au milieu d'une promotion. PermissionError sous le compte d'un job detache
    -- mais le probleme de fond n'est pas le droit : un build qui REECRIT SON
    ENTREE n'est pas reproductible, et il aurait « marche » sous un compte
    proprietaire, en salissant l'arbre sans que personne ne le voie.
    """
    ra = _charger("forge_release_assets")
    racine = tmp_path / "depot"
    racine.mkdir()
    monkeypatch.setattr(ra, "ROOT", racine)
    monkeypatch.setattr(ra, "VENDORED", {})       # aucun bundle a hacher
    lot = tmp_path / "lot"
    dest = ra.write_vendor_lock(lot / "vendor.lock")
    assert dest == lot / "vendor.lock" and dest.is_file()
    assert not (racine / "vendor.lock").exists(), \
        "la construction a ecrit dans le depot source"
    # CONTRE-EPREUVE : le chemin de MAINTENANCE ecrit bien a la racine, sinon
    # on aurait casse `--vendor-lock-only` en croyant proteger la source.
    assert ra.write_vendor_lock() == racine / "vendor.lock"
    assert (racine / "vendor.lock").is_file()


def test_tout_git_du_promoteur_porte_safe_directory():
    """Un contrat tenu d'un seul cote n'est pas un contrat.

    `sync_snapshot` portait `-c safe.directory=*` avec un commentaire expliquant
    que sans lui la commande meurt en « detected dubious ownership » sous tout
    compte non proprietaire — donc dans TOUT job detache. `build_code_tarball`
    ne l'avait pas : mesure du 2026-09-20, exit 128 au milieu d'une promotion,
    APRES que le commit dist et le tag avaient deja ete poses.

    CORRECTION du 2026-09-20, meme journee : j'avais ecrit ici que « celles qui
    operent dans le clone dist n'en ont pas besoin, il appartient au compte qui
    l'a clone ». FAUX des que la chaine traverse DEUX comptes — et c'est ce que
    la porte de publication impose : le clone est fait par le compte d'un job
    deporte (SID …-1008), la publication par un autre (…-1009), parce qu'un
    `run_job` ne transmet pas les variables d'environnement que la porte exige.
    git refuse alors en « detected dubious ownership ». Une justification qui ne
    tenait que par coincidence se lisait comme une regle.
    """
    import ast
    dp = _charger("forge_dist_publish")
    assert dp._GIT_DIST[:3] == ["git", "-c", "safe.directory=*"], dp._GIT_DIST
    # La regle juste distingue OPERER SUR UN DEPOT LOCAL de PARLER A UNE URL :
    # `ls-remote <url>` n'ouvre aucun depot, `safe.directory` n'y a aucun sens.
    # Ma premiere version l'exigeait partout et se faisait refuser par son
    # propre sujet -- un garde trop large se fait desarmer.
    nus = []
    for n in ast.walk(ast.parse(open(dp.__file__, encoding="utf-8").read())):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "run" and n.args):
            continue
        if not any(k.arg == "cwd" for k in n.keywords):
            continue          # pas de depot local ouvert : rien a exiger
        if "_GIT_DIST" not in ast.unparse(n.args[0]):
            nus.append((n.lineno, ast.unparse(n.args[0])[:70]))
    assert not nus, ("commande(s) git ouvrant un depot LOCAL sans "
                     "safe.directory : elles ne cassent que lorsque deux "
                     "comptes interviennent, donc pas la ou on les teste : %s"
                     % nus)
    ra = _charger("forge_release_assets")
    arbre = ast.parse(open(ra.__file__, encoding="utf-8").read())
    fn = next(n for n in ast.walk(arbre)
              if isinstance(n, ast.FunctionDef) and n.name == "build_code_tarball")
    texte = ast.unparse(fn)
    assert "safe.directory=*" in texte, \
        "git archive sur le depot source sans safe.directory : meurt en job detache"
    assert "check=True" not in texte, \
        "check=True seul perd le message de git : l'echec doit DIRE pourquoi"


def test_un_credential_dans_l_URL_est_REFUSE():
    """La voie « PAT dans l'URL » est SUPPRIMEE, pas rendue non-defaut.

    La laisser possible, c'est accepter qu'un appel futur la reprenne par
    accident — et un PAT place la finit dans .git/config, qu'on ne revoque pas.
    """
    m = _charger("forge_dist_publish")
    with pytest.raises(SystemExit) as e:
        m._refuser_credential_dans_url("github", "https://u:tok@github.com/o/r.git")
    assert "SUPPRIMEE" in str(e.value)
    # CONTRE-EPREUVE : une URL propre doit passer, sinon le garde bloque tout.
    m._refuser_credential_dans_url("github", "https://github.com/o/r.git")


def test_sans_jeton_on_REFUSE_au_lieu_de_repartir_de_zero(monkeypatch):
    """ABSENT et ILLISIBLE refusent tous deux, mais pas pour la meme raison.

    Sans credential, le remote est classe ILLISIBLE — et c'est exactement
    l'etat ou un `git init` fabriquerait un historique orphelin, impossible a
    publier sans --force. Le refus doit donc tomber AVANT, en nommant la cause,
    pas trois etapes plus loin sur un symptome.
    """
    import types
    m = _charger("forge_dist_publish")
    faux = types.ModuleType("forge_secrets")
    faux.get_secret = lambda _k: None
    monkeypatch.setitem(sys.modules, "forge_secrets", faux)
    with pytest.raises(SystemExit) as e:
        m._jeton_github()
    assert "aucun jeton" in str(e.value) and "orphelin" in str(e.value)

    def coffre_ferme(_k):
        raise RuntimeError("coffre ferme")

    faux.get_secret = coffre_ferme
    with pytest.raises(SystemExit) as e2:
        m._jeton_github()
    assert "ILLISIBLE" in str(e2.value), str(e2.value)


def test_l_identite_de_publication_est_PSEUDONYME():
    """Mesure du 2026-09-20 : 4 commits dist publies sur 5 portaient l'identite
    CIVILE de l'owner, et une adresse personnelle. L'outil l'avait en dur, donc
    chaque promotion outillee REGRESSAIT — le seul commit correct (2026-07-09)
    avait visiblement ete fait a la main. Une convention qui ne tient que lorsque
    l'humain court-circuite l'outil n'est pas une convention.

    Ce test lit la valeur IMPORTEE, jamais le texte source. Raison mesuree le
    meme jour : ma premiere correction a ajoute la bonne adresse AVANT l'ancienne
    sans retirer celle-ci. Python gardait la DERNIERE, donc le correctif ne
    changeait RIEN tout en se relisant comme correct. Un test sur le texte
    l'aurait validee ; seul un test sur la VALEUR la refuse.
    """
    m = _charger("forge_dist_publish")
    assert m.AUTHOR_NAME == "user", m.AUTHOR_NAME
    assert m.AUTHOR_EMAIL.lower().startswith("user@")
    assert m.AUTHOR_EMAIL.lower().endswith("users.noreply.github.com")
    # Le COMMIT et le TAG annote portent tous deux cette identite : corriger un
    # seul des deux sites laisserait l'identite civile dans l'objet-tag.
    src = open(m.__file__, encoding="utf-8").read()
    assert src.count("GIT_AUTHOR_NAME") == 2, \
        "commit et tag doivent tous deux porter l'identite pseudonyme"


def test_le_NOM_DE_MACHINE_est_generise():
    """Trouve dans l'arbre PUBLIE, par la verification J' du 2026-09-20.

    Quatre fichiers du dist portaient le hostname reel, alors que d'autres
    portaient deja `DESKTOP-…` ou `DESKTOP-XXXX`. La regle existait donc dans
    les tetes et avait ete appliquee A LA MAIN par endroits, jamais outillee —
    la forme la plus trompeuse d'une convention : elle a l'air tenue partout ou
    l'on regarde, et ne l'est nulle part ou l'on ne regarde pas.

    Motif GENERIQUE et non litteral : inscrire le hostname dans la table le
    ferait entrer dans la source publiee, et ne couvrirait que cette machine.
    """
    m = _charger("forge_dist_publish")
    out, n = m.generiser_texte('ObjectName "DESKTOP-XXXX\\user"')
    assert "DESKTOP-XXXX" not in out, out
    assert "DESKTOP-XXXX" in out and n >= 1
    # IDEMPOTENT : une seconde passe ne doit rien abimer.
    assert m.generiser_texte(out)[0] == out
    # Une AUTRE machine est couverte aussi — c'est l'interet du motif.
    assert "DESKTOP-XXXX" not in m.generiser_texte("hote DESKTOP-XXXX")[0]
    # CONTRE-EPREUVE : un texte sans marqueur n'est pas touche, sinon le garde
    # reecrirait du contenu legitime en croyant proteger.
    neutre = "un texte ordinaire, sans aucun marqueur machine"
    assert m.generiser_texte(neutre) == (neutre, 0)


def test_la_cible_par_defaut_est_GitHub_Nokido_labs():
    """Owner 2026-09-20 : la cible VERIFIEE est GitHub Nokido-labs/nokido-dist.

    Codeberg etait declare « primary (sovereign) » alors qu'il n'est pas
    lisible depuis ce poste — `git ls-remote` y demande une authentification,
    donc son etat est INDETERMINE : ni vide, ni porteur. Or `ensure_dist_repo`
    clone le PREMIER remote qui PORTE un historique : laisser une autorite
    qu'on ne sait pas lire en tete, c'est accepter qu'elle gagne le jour ou elle
    repond. Codeberg n'est pas supprime — il est retire de l'AUTORITE.
    """
    m = _charger("forge_dist_publish")
    assert list(m.DEFAULT_REMOTES) == ["github"], m.DEFAULT_REMOTES
    # 2026-09-30 : nokido-dist renomme Nokido-labs/nokido (la VITRINE). Le promoteur
    # ecrit l'identite CANONIQUE de la vitrine, jamais l'ancien nom ni l'atelier prive.
    assert m.DEFAULT_REMOTES["github"].endswith("Nokido-labs/nokido.git")
    assert m.DIST_REPO_GITHUB == "Nokido-labs/nokido"
    # L'identite canonique est ECRITE, pas obtenue par une redirection
    # historique : une redirection peut cesser, un nom canonique non.
    assert "nokido-dist" not in m.DEFAULT_REMOTES["github"]
    assert "nokido-private" not in m.DEFAULT_REMOTES["github"], "la vitrine ne vise jamais l'atelier prive"
    # Codeberg reste disponible, en miroir opt-in.
    assert "codeberg.org" in m.CODEBERG_URL


def _fausse_certification(tmp_path, sha, suites=("ruff critique",)):
    """Un dossier d'artefacts de CI minimal, mais de la MEME FORME que le vrai."""
    import json
    (tmp_path / "generations").mkdir(parents=True, exist_ok=True)
    (tmp_path / "generations" / "GEN-00042.json").write_text(json.dumps({
        "generation": "GEN-00042", "statut": "STABLE",
        "depot": {"sha": sha}, "tests": {s: "PASS" for s in suites},
    }), encoding="utf-8")
    for nom, t, sk, f, e in (("a_junit.xml", 100, 3, 0, 0),
                             ("b_junit.xml", 7, 0, 0, 0)):
        (tmp_path / nom).write_text(
            '<?xml version="1.0"?><testsuites><testsuite name="x" tests="%d" '
            'skipped="%d" failures="%d" errors="%d"></testsuite></testsuites>'
            % (t, sk, f, e), encoding="utf-8")
    return tmp_path


def test_la_certification_dit_QUELLE_preuve_etablit_QUOI(tmp_path):
    """H' — les preuves sont rendues PAR PORTEE, jamais fondues en un champ.

    Mesure du 2026-09-20 : le registre de generation de l'ancre annonce
    « toutes les suites FOURNIES sont vertes » et n'en contient QU'UNE. Les
    10 909 tests vivent dans les JUnit. Un `ci_proof_hash` unique aurait donc
    herite d'un libelle qui promet bien plus que sa charge.
    """
    m = _charger("forge_dist_publish")
    sha = "a" * 40
    c = m._lire_certification(_fausse_certification(tmp_path, sha), sha)
    assert c["etat"] == "LUE"
    assert c["generation_proof"]["suites_declarees"] == ["ruff critique"]
    assert "PORTEE" in c["generation_proof"] and "PORTEE" in c["junit_proof"]
    j = c["junit_proof"]
    # 107 collectes - 3 skipped = 104 executes : deux denominateurs, un fait.
    assert (j["collectes"], j["executes"], j["skipped"]) == (107, 104, 3)
    assert (j["failures"], j["errors"], j["illisibles"]) == (0, 0, [])
    assert c["NON_COUVERT"], "une preuve muette sur ses angles morts se lit exhaustive"


def test_un_chemin_de_certification_RELATIF_se_resout_contre_la_racine(monkeypatch,
                                                                       tmp_path):
    """Le meme argument marchait a la main et echouait en job detache.

    Mesure du 2026-09-20, premiere promotion : `--certification sandbox/...`
    resolvait contre le repertoire COURANT, qui n'est pas la racine dans un job
    detache. Le promoteur traite deja pyproject.toml et .git-publish-rules.json
    comme relatifs a la racine : un troisieme chemin ne peut pas avoir une autre
    convention.
    """
    m = _charger("forge_dist_publish")
    sha = "a" * 40
    _fausse_certification(tmp_path / "sous" / "dossier", sha)
    monkeypatch.setattr(m, "ROOT", tmp_path)
    c = m._lire_certification("sous/dossier", sha)
    assert c["etat"] == "LUE" and c["generation_proof"]["fichier"] == "GEN-00042.json"


def test_un_dossier_de_certification_absent_NOMME_ou_il_a_cherche(monkeypatch,
                                                                  tmp_path):
    """« Non trouve » sans dire OU l'on a cherche n'est pas un diagnostic."""
    m = _charger("forge_dist_publish")
    monkeypatch.setattr(m, "ROOT", tmp_path)
    with pytest.raises(SystemExit) as e:
        m._lire_certification("nulle/part", "a" * 40)
    msg = str(e.value)
    assert "demande" in msg and "resolu" in msg and "nulle/part" in msg


def test_une_preuve_qui_porte_sur_un_AUTRE_sha_est_REFUSEE(tmp_path):
    """Sinon on adosse une promotion a la preuve de quelqu'un d'autre."""
    m = _charger("forge_dist_publish")
    d = _fausse_certification(tmp_path, "a" * 40)
    with pytest.raises(SystemExit) as e:
        m._lire_certification(d, "b" * 40)
    assert "AUCUN ne porte sur" in str(e.value)


def test_un_registre_CORROMPU_est_NOMME_pas_avale(tmp_path):
    """Le commentaire disait « compte plus bas » et rien ne le comptait.

    Un registre illisible n'est pas un registre absent : le refus doit le
    NOMMER, sinon on cherche pourquoi la preuve ne porte pas sur S alors que le
    fichier est simplement corrompu.
    """
    m = _charger("forge_dist_publish")
    sha = "a" * 40
    d = _fausse_certification(tmp_path, sha)
    (d / "generations" / "GEN-00043.json").write_text("{ pas du json",
                                                      encoding="utf-8")
    # Le bon registre est toujours la : la lecture aboutit ET nomme l'abime.
    c = m._lire_certification(d, sha)
    assert c["etat"] == "LUE"
    # Le balayage est COMPLET : il ne s'arrete pas au premier registre qui
    # correspond, sinon la liste des illisibles serait un denominateur partiel
    # qui se lit comme complet (defaut trouve par ce test meme).
    assert c["registres_lus"] == 2 and c["registres_correspondants"] == ["GEN-00042.json"]
    assert any("GEN-00043" in x for x in c["registres_illisibles"]), c
    # Et quand plus AUCUN registre ne porte sur S, le refus cite l'illisible.
    with pytest.raises(SystemExit) as e:
        m._lire_certification(d, "b" * 40)
    assert "ILLISIBLES" in str(e.value) and "GEN-00043" in str(e.value)


def test_sans_certification_le_manifeste_le_DIT(tmp_path):
    """ABSENTE est un etat DECLARE, pas un champ qu'on omet en silence."""
    m = _charger("forge_dist_publish")
    c = m._lire_certification(None, "a" * 40)
    assert c["etat"] == "ABSENTE" and c["motif"]
    assert c["generation_proof"] is None and c["junit_proof"] is None


def _manifeste(m, monkeypatch, tmp_path, assets, version="1.2.3"):
    import json
    monkeypatch.setattr(m, "_nom_du_paquet", lambda s=None: "nokido-agent")
    monkeypatch.setattr(m, "_version_du_paquet", lambda s=None: version)
    monkeypatch.setattr(m, "_revision_du_promoteur", lambda: "abc1234")
    rm = tmp_path / "RELEASE_MANIFEST.json"
    if assets is not None:
        rm.write_text(json.dumps({"assets": [
            {"name": n, "sha256": "f" * 64} for n in assets]}), encoding="utf-8")
    dest = tmp_path / "dist-manifest.json"
    m.write_dist_manifest(dest, depot_source="O/r", source_sha="a" * 40,
                          version=version, dist_commit="d" * 40,
                          certification={"etat": "ABSENTE"},
                          assets_manifest=rm, profil="public")
    return json.loads(dest.read_text(encoding="utf-8"))


def test_le_manifeste_relie_S_les_preuves_D_et_les_artefacts(monkeypatch, tmp_path):
    """Un artefact sans ce lien ne se rattache a rien : c'est le trou que H'
    ferme. `dist_commit` ne peut etre connu qu'APRES le commit — le manifeste
    est donc un ASSET, pas un fichier du commit qu'il decrit."""
    m = _charger("forge_dist_publish")
    o = _manifeste(m, monkeypatch, tmp_path, ["nokido-1.2.3.tar.gz"])
    assert o["source"]["sha"] == "a" * 40 and o["dist"]["commit"] == "d" * 40
    assert o["package"]["name"] == "nokido-agent" and o["package"]["version"] == "1.2.3"
    assert o["package"]["lues_depuis"] == "source.sha"
    assert o["artifacts"]["sha256"]["nokido-1.2.3.tar.gz"] == "f" * 64
    assert o["promotion"]["promoter_revision"] == "abc1234"
    assert "NOTE" in o["promotion"], \
        "le promoteur n'est pas le sujet promu : il faut le DIRE dans l'artefact"


def test_un_artefact_qui_porte_une_AUTRE_version_est_REFUSE(monkeypatch, tmp_path):
    """Derniere defense : un build CORRECT mais issu du MAUVAIS paquet."""
    m = _charger("forge_dist_publish")
    with pytest.raises(SystemExit) as e:
        _manifeste(m, monkeypatch, tmp_path, ["nokido-9.9.9.tar.gz"])
    assert "AUTRE version" in str(e.value)


def test_un_nom_sans_version_est_DECLARE_pas_refuse(monkeypatch, tmp_path):
    """Contre-epreuve du garde precedent : une ABSENCE de version dans le nom
    n'est pas une incoherence. Refuser la-dessus inventerait une regle."""
    m = _charger("forge_dist_publish")
    o = _manifeste(m, monkeypatch, tmp_path, ["knowledge-pack-int8.bin"])
    assert o["artifacts"]["sans_version_dans_le_nom"] == ["knowledge-pack-int8.bin"]


def test_artefacts_ABSENTS_ne_se_lisent_pas_ILLISIBLES(monkeypatch, tmp_path):
    """Sans --with-assets rien n'est construit : c'est une etape NON DEMANDEE,
    pas une panne. Les confondre ferait chercher un defaut inexistant."""
    m = _charger("forge_dist_publish")
    o = _manifeste(m, monkeypatch, tmp_path, None)
    assert o["artifacts"]["etat"].startswith("ABSENT")
    assert "ILLISIBLE" not in o["artifacts"]["etat"]


def test_l_identite_est_lue_DEPUIS_LE_SHA_promu(monkeypatch):
    """H' — identity = S : le garde de version interroge la SOURCE PROMUE.

    Sans ce point, on pouvait tagger la version du depot de travail sur une
    archive faite depuis un AUTRE commit. Elargir la signature ne suffit pas :
    un parametre que personne ne renseigne est une dette de cablage, pas une
    correction. Ce test verifie donc que le sha TRAVERSE les trois portes.
    """
    m = _charger("forge_dist_publish")
    vus = []
    monkeypatch.setattr(m, "_version_du_paquet",
                        lambda s=None: (vus.append(("pyproject", s)), "1.0.0")[1])
    monkeypatch.setattr(m, "_version_du_module",
                        lambda s=None: (vus.append(("module", s)), "1.0.0")[1])
    m._verifier_version_du_paquet("1.0.0", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    assert vus == [("pyproject", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"),
                   ("module", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")], vus
    # CONTRE-EPREUVE : sans source, on ne fabrique pas un sha par defaut.
    vus.clear()
    m._verifier_version_du_paquet("1.0.0")
    assert vus == [("pyproject", None), ("module", None)], vus


def test_avec_un_sha_la_lecture_passe_par_GIT_et_pas_par_le_disque(monkeypatch):
    """Contre-epreuve de la DISCRIMINATION, et elle est necessaire.

    Sur ce depot, la version du worktree et celle de l'ancre coincident (0.20.2
    des deux cotes, mesure du 2026-09-20) : un test qui les compare ne prouverait
    RIEN -- il passerait meme si la lecture depuis le sha n'etait jamais prise.
    On fabrique donc une source git distincte du disque.
    """
    m = _charger("forge_dist_publish")
    MOTIF = r'^version\s*=\s*"([^"]+)"'
    ok = type("R", (), {"returncode": 0, "stdout": 'version = "9.9.9"\n', "stderr": ""})()
    monkeypatch.setattr(m, "run", lambda *a, **k: ok)
    assert m._version_declaree("pyproject.toml", MOTIF, "abc1234") == "9.9.9"
    # Sans sha, la lecture reste sur le DISQUE et ne voit pas la fabrication.
    assert m._version_declaree("pyproject.toml", MOTIF) != "9.9.9"
    # Un `git show` qui ECHOUE rend None : illisible n'est pas « incoherent ».
    ko = type("R", (), {"returncode": 128, "stdout": "", "stderr": "fatal"})()
    monkeypatch.setattr(m, "run", lambda *a, **k: ko)
    assert m._version_declaree("pyproject.toml", MOTIF, "abc1234") is None


def test_le_snapshot_dist_EMBARQUE_release_yml_du_sha_promu(monkeypatch, tmp_path):
    """Le dist est l'EDITEUR TestPyPI (owner 2026-09-30) : il doit porter le
    workflow de publication. `.gitattributes` exclut `.github/workflows/` de
    `git archive` ; le promoteur le rapporte donc lui-meme — depuis le SHA
    PROMU (jamais le worktree), et AVANT la politique publique, qui doit pouvoir
    le juger comme tout autre fichier. Seul `release.yml` part : la CI
    self-hosted reste hors du dist.

    Hermetique : `git archive` et `git show` sont simules, aucun reseau.
    """
    import io
    import tarfile

    m = _charger("forge_dist_publish")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "perime.txt").write_text("ancien", encoding="utf-8")
    appels = []

    def faux_run(cmd, cwd=None, check=True, capture=False, env=None):
        appels.append(list(cmd))
        if "archive" in cmd:
            sortie = cmd[cmd.index("-o") + 1]
            with tarfile.open(sortie, "w") as t:
                data = b"x = 1\n"
                info = tarfile.TarInfo("app/forge_x.py")
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if "show" in cmd:
            return type("R", (), {"returncode": 0, "stdout": "name: Release to PyPI\n",
                                  "stderr": ""})()
        raise AssertionError(f"commande inattendue : {cmd}")

    vu_par_la_politique = []
    monkeypatch.setattr(m, "run", faux_run)
    monkeypatch.setattr(m, "TMP", tmp_path)
    monkeypatch.setattr(m, "_appliquer_politique_publique", lambda d: vu_par_la_politique.append(
        (d / ".github" / "workflows" / "release.yml").is_file()))
    monkeypatch.setattr(m, "_generiser_chemins_owner", lambda d: None)
    monkeypatch.setattr(m, "_verifier_identite_civile", lambda d: None)
    monkeypatch.setattr(m, "_scanner_secrets", lambda d: None)

    m.sync_snapshot("abc1234", dist)

    wf = dist / ".github" / "workflows" / "release.yml"
    assert wf.read_text(encoding="utf-8") == "name: Release to PyPI\n"
    assert not (dist / ".github" / "workflows" / "ci-selfhosted.yml").exists()
    assert (dist / "app" / "forge_x.py").is_file() and not (dist / "perime.txt").exists()
    shows = [c for c in appels if "show" in c]
    assert shows and all(c[-1] == "abc1234:.github/workflows/release.yml" for c in shows), (
        f"le workflow doit venir du SHA promu : {shows}")
    assert vu_par_la_politique == [True], (
        "la politique publique doit juger le workflow embarque, donc passer APRES")


# L'ASSET SOURCE DE LA RELEASE SE TIRE DE D, PAS DE S. Mesure du 2026-09-30 :
# `nokido-<v>-src.tar.gz` sortait d'un `git archive` de la SOURCE -- donc sans
# la politique publique ni la generisation que porte le depot dist. Le tarball
# v0.20.2 publie contenait 186 chemins bloques (docs/ip/**, config/clients/**,
# .agents/**, calibration gelee) et 421 fichiers a marqueurs machine. Le depot
# dist etait propre ; l'artefact joint a cote le contournait.
def test_l_asset_source_est_tire_de_D_dans_le_depot_dist(monkeypatch, tmp_path):
    m = _charger("forge_dist_publish")
    vus = []
    monkeypatch.setattr(m, "run", lambda cmd, **k: vus.append(list(cmd)))
    d = "d" * 40
    m.build_assets("1.2.3", d, tmp_path / "lot", True, depot=tmp_path / "dist")
    cmd = vus[0]
    assert cmd[cmd.index("--branch") + 1] == d, cmd
    assert cmd[cmd.index("--repo") + 1] == str(tmp_path / "dist"), cmd


def test_le_promoteur_passe_D_et_le_depot_dist_aux_artefacts():
    """Le chemin REEL : `main()` doit appeler `build_assets` avec D et le clone
    dist. Un `build_assets` correct appele avec S ne changerait rien."""
    import inspect
    src = inspect.getsource(_charger("forge_dist_publish").main)
    assert "build_assets(args.version, dist_commit," in src and "depot=dist" in src, (
        "main() ne tire pas l'asset source de D")


def test_le_manifeste_public_ne_nomme_aucun_depot_comme_source():
    """2026-09-30 : `source.repository` part avec la vitrine publique. Par defaut il
    ne designe AUCUN depot : ni `Nokido-labs/nokido` (la vitrine, ou ce sha n'existe
    pas) ni l'atelier prive. Chemin reel : le defaut de `--source-repo` dans main()."""
    import inspect
    m = _charger("forge_dist_publish")
    assert "/" not in m.SOURCE_PUBLIEE and "nokido" not in m.SOURCE_PUBLIEE.lower()
    src = inspect.getsource(m.main)
    assert '"--source-repo", default=SOURCE_PUBLIEE' in src, (
        "le defaut de --source-repo ne passe plus par SOURCE_PUBLIEE")


def test_forge_release_assets_archive_le_depot_demande(monkeypatch, tmp_path):
    ra = _charger("forge_release_assets")
    vus = []

    def faux_run(cmd, **k):
        vus.append(list(cmd))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(ra.subprocess, "run", faux_run)
    ra.build_code_tarball(tmp_path, "1.2.3", "abc1234", repo=tmp_path / "dist")
    cmd = vus[0]
    assert cmd[cmd.index("-C") + 1] == str(tmp_path / "dist") and "abc1234" in cmd, cmd
    # CONTRE-EPREUVE : sans `repo`, le comportement historique (le depot source) reste.
    vus.clear()
    ra.build_code_tarball(tmp_path, "1.2.3", "abc1234")
    assert vus[0][vus[0].index("-C") + 1] == str(ra.ROOT), vus[0]


# IDENTITE CIVILE : pseudonyme partout, sauf dans les documents ou un titulaire
# identifiable est requis (decision owner 2026-09-30, avant le passage en public
# du dist). Mesure du jour : 28 fichiers du dist la portaient, dont du code
# (motifs de caviardage, identifiant Kaggle en dur). Les motifs vivent dans une
# liste PRIVEE, jamais dans le code publie ; le promoteur REFUSE de publier.
# Les NR n'emploient qu'une identite SYNTHETIQUE.
def _egress():
    import sys as _s
    for p in (str(RACINE), str(RACINE / "app")):
        if p not in _s.path:
            _s.path.insert(0, p)
    import forge_git_egress
    return forge_git_egress


def test_la_liste_privee_se_lit_commentaires_ignores(tmp_path):
    eg = _egress()
    f = tmp_path / "identites.txt"
    f.write_text("# commentaire\n\n\\bjean\\.synthetique\\b\nsynthetique\n", encoding="utf-8")
    motifs = eg.identites_privees(f)
    assert len(motifs) == 2 and motifs[0].search("Contact : JEAN.SYNTHETIQUE@x.test")
    assert eg.identites_privees(tmp_path / "absente.txt") == [], "absente = liste vide, jamais une erreur"


def test_la_liste_privee_ne_part_jamais_au_public():
    eg = _egress()
    motifs = eg.load_manifest()["profiles"]["public"]["blocked_paths"]
    assert eg._path_blocked("config/identites_privees.txt", motifs)
    manifest = (RACINE / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    assert "exclude config/identites_privees.txt" in manifest, "une wheel locale l'embarquerait"


def test_le_promoteur_refuse_l_identite_hors_documents_juridiques(tmp_path):
    import re as _re
    m = _charger("forge_dist_publish")
    dist = tmp_path / "dist"
    (dist / "docs").mkdir(parents=True)
    (dist / "NOTICE").write_text("Copyright Jean Synthetique\n", encoding="utf-8")
    (dist / "docs" / "CLA.md").write_text("Licensor: Jean Synthetique\n", encoding="utf-8")
    (dist / "README.md").write_text("Maintenu par Jean Synthetique\n", encoding="utf-8")
    motifs = [_re.compile("synthetique", _re.I)]
    with pytest.raises(RuntimeError, match="README.md"):
        m._verifier_identite_civile(dist, motifs)
    # CONTRE-EPREUVE : seuls les documents juridiques la portent -> publication permise.
    (dist / "README.md").write_text("Maintenu par user\n", encoding="utf-8")
    m._verifier_identite_civile(dist, motifs)


def test_le_promoteur_refuse_sans_liste_privee(tmp_path, monkeypatch):
    m = _charger("forge_dist_publish")
    eg = _egress()
    monkeypatch.setattr(eg, "identites_privees", lambda *a, **k: [])
    (tmp_path / "dist").mkdir()
    with pytest.raises(RuntimeError, match="liste privee"):
        m._verifier_identite_civile(tmp_path / "dist")


def test_le_garde_d_identite_est_cable_apres_la_generisation():
    import inspect
    src = inspect.getsource(_charger("forge_dist_publish").sync_snapshot)
    assert "_generiser_chemins_owner(dist)" in src and "_verifier_identite_civile(dist)" in src
    assert src.index("_verifier_identite_civile(dist)") > src.index("_generiser_chemins_owner(dist)")


# SCAN DE SECRETS AU PROMOTEUR (owner 2026-09-30 : dist « pas bride »). La
# politique publique ne bloque plus config/clients, cline_mcp_settings, jea...
# -- le filet devient un scan fail-closed de TOUT le dist, par le MEME juge que le
# gate egress (profil public + sa liste blanche). Jeton FACTICE construit a
# l'execution : ecrit en clair, il ferait rougir le scanner du pre-commit.
def test_le_promoteur_refuse_un_secret_dans_le_dist(tmp_path):
    m = _charger("forge_dist_publish")
    dist = tmp_path / "dist"
    (dist / "config" / "clients").mkdir(parents=True)
    faux = "gh" + "p_" + "A1b2C3d4" * 5
    (dist / "config" / "clients" / "x.jsonc").write_text('{"token": "%s"}\n' % faux, encoding="utf-8")
    (dist / "README.md").write_text("rien\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="config/clients/x.jsonc"):
        m._scanner_secrets(dist)


def test_le_scan_de_secrets_respecte_la_liste_blanche_du_profil_public(tmp_path):
    """Contre-epreuve : les fixtures de test epinglees (path + label) passent."""
    m = _charger("forge_dist_publish")
    dist = tmp_path / "dist"
    (dist / "tests").mkdir(parents=True)
    (dist / "tests" / "test_functions.py").write_text(
        'password = "%s"\n' % ("x" * 20), encoding="utf-8")
    m._scanner_secrets(dist)


def test_le_scan_de_secrets_est_cable_apres_le_garde_d_identite():
    import inspect
    src = inspect.getsource(_charger("forge_dist_publish").sync_snapshot)
    assert "_scanner_secrets(dist)" in src
    assert src.index("_scanner_secrets(dist)") > src.index("_verifier_identite_civile(dist)")


def test_le_commit_dist_n_ecarte_pas_les_fichiers_du_gitignore(tmp_path):
    """Mesure du 2026-09-30 : `git add -A` dans le clone dist ecartait EN SILENCE
    tout fichier que la source suit malgre son .gitignore (13 fichiers, dont le
    census sandbox/workspace/organ_map_full.json lu par le code) -- a CHAQUE
    promotion depuis toujours. Le snapshot est deja cure (politique, generisation,
    gardes) : tout ce qu'il contient doit partir. Vrai depot git, hermetique."""
    import subprocess as sp
    m = _charger("forge_dist_publish")
    dist = tmp_path / "dist"
    dist.mkdir()
    sp.run(["git", "init", "-q", str(dist)], check=True)
    (dist / ".gitignore").write_text("workspace/\n", encoding="utf-8")
    (dist / "workspace").mkdir()
    (dist / "workspace" / "carte.json").write_text("{}\n", encoding="utf-8")
    (dist / "code.py").write_text("x = 1\n", encoding="utf-8")
    # CONTRE-EPREUVE d'abord : le scenario est reel -- un `add -A` simple ecarte bien le fichier.
    temoin = tmp_path / "temoin"
    temoin.mkdir()
    sp.run(["git", "init", "-q", str(temoin)], check=True)
    (temoin / ".gitignore").write_text("workspace/\n", encoding="utf-8")
    (temoin / "workspace").mkdir()
    (temoin / "workspace" / "carte.json").write_text("{}\n", encoding="utf-8")
    sp.run(["git", "-c", "safe.directory=*", "-C", str(temoin), "add", "-A"], check=True)
    indexes = sp.run(["git", "-c", "safe.directory=*", "-C", str(temoin), "ls-files"],
                     capture_output=True, text=True, errors="replace", check=True).stdout.split()
    assert "workspace/carte.json" not in indexes, "scenario sans objet : le .gitignore n'ecarte rien"

    assert m.commit_version(dist, "9.9.9", "a" * 40)
    suivis = sp.run(["git", "-c", "safe.directory=*", "-C", str(dist), "ls-files"],
                    capture_output=True, text=True, errors="replace", check=True).stdout.split()
    assert "workspace/carte.json" in suivis and "code.py" in suivis, suivis


def test_aucun_identifiant_kaggle_en_dur():
    """L'identifiant Kaggle portait le nom civil : il se lit dans l'environnement."""
    for outil in ("kaggle_push", "kaggle_sync", "forge_kaggle_cfg_from_env"):
        src = (RACINE / "tools" / (outil + ".py")).read_text(encoding="utf-8")
        assert "KAGGLE_USERNAME" in src, f"{outil} ne lit pas KAGGLE_USERNAME"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
