"""NR — l'inventaire des cles REELLEMENT demandees au coffre.

PHASE 1 (suite) du mandat « organe de secretion securisee ».

POURQUOI CE SECOND CLIQUET
==========================
Le registre d'observation ajoute a `forge_secrets` ne voit que SON process. Le
hub, les daemons, les jobs et la CI sont d'autres process : une vue runtime ne
peut donc pas rendre l'inventaire GLOBAL. Le scan statique, lui, ne depend
d'aucun process.

SEARCH BEFORE BUILD, fait avant d'ecrire : `forge_secret_source_audit` porte
deja le parcours du depot (2426 fichiers lus, 199 exempts, 0 illisible mesure le
2026-09-20), ses exemptions et son comptage d'illisibles. Il repond a « QUI lit
un secret SANS passer par le coffre ». Il lui manque la question symetrique :
« que le coffre doit-il CONTENIR ? ». On etend la brique qui porte deja la
moitie du contrat ; on n'en ajoute pas une seconde a cote.

CE QUE CE NR VERROUILLE
=======================
1. Les ALIAS comptent. Le depot ecrit `get_secret as _gs`, `_gs_gh`, `_gs_w`,
   `_lire_secret`. Un inventaire qui ne cherche que `get_secret(` sous-compte en
   silence -- exactement le defaut qu'il est cense mesurer.
2. L'instrument DIT ce qu'il n'a pas lu (`illisibles`, `exempts`). Un filtre qui
   ecarte des donnees sans le dire surestime la couverture.
3. Il est EPROUVABLE sur une racine jetable : un garde qu'on ne peut pas faire
   virer au rouge dans un test est une dette de cablage.
4. Il ne lit AUCUNE valeur -- il lit du texte source et n'ouvre aucun coffre.
"""
import pytest

MOD = "nokido_agent.tools.forge_secret_source_audit"


@pytest.fixture()
def audit():
    import importlib

    return importlib.import_module(MOD)


@pytest.fixture()
def depot_jetable(tmp_path):
    """Un mini-depot dont on connait la reponse exacte."""
    app = tmp_path / "app"
    app.mkdir()
    (app / "droit.py").write_text(
        "from nokido_agent.app.forge_secrets import get_secret\n"
        "K = get_secret('ALPHA_API_KEY')\n",
        encoding="utf-8",
    )
    (app / "avec_alias.py").write_text(
        "from nokido_agent.app.forge_secrets import get_secret as _gs\n"
        "def f():\n"
        "    return _gs('BETA_TOKEN')\n",
        encoding="utf-8",
    )
    (app / "avec_require.py").write_text(
        "from nokido_agent.app.forge_secrets import require\n"
        "require('GAMMA_SECRET', 'DELTA_API_KEY')\n",
        encoding="utf-8",
    )
    return tmp_path


def test_l_inventaire_existe_et_rend_des_stats(audit, depot_jetable):
    cles, stats = audit.cles_demandees(racine=depot_jetable, bases=("app",))
    assert isinstance(cles, dict)
    for champ in ("fichiers_lus", "illisibles", "exempts"):
        assert champ in stats, (
            "un instrument qui ecarte des fichiers sans le dire surestime sa "
            "couverture : %r manque" % champ
        )
    assert stats["fichiers_lus"] == 3


def test_les_alias_de_get_secret_sont_comptes(audit, depot_jetable):
    """Le defaut que l'inventaire est cense mesurer ne doit pas l'atteindre."""
    cles, _ = audit.cles_demandees(racine=depot_jetable, bases=("app",))
    assert "ALPHA_API_KEY" in cles, "l'appel direct doit etre vu"
    assert "BETA_TOKEN" in cles, (
        "`get_secret as _gs` est la forme reelle dans forge_llm_router, "
        "forge_mcp_registry et forge_embed_router : la rater, c'est sous-compter "
        "sans que rien ne le signale"
    )


def test_require_compte_toutes_ses_cles(audit, depot_jetable):
    cles, _ = audit.cles_demandees(racine=depot_jetable, bases=("app",))
    assert "GAMMA_SECRET" in cles
    assert "DELTA_API_KEY" in cles, "require() prend N cles, pas une"


def test_chaque_cle_nomme_ses_sites(audit, depot_jetable):
    """Sans le site, un inventaire ne permet ni de segmenter par organe ni de
    designer un proprietaire : c'est la matiere des phases 3 et 4."""
    cles, _ = audit.cles_demandees(racine=depot_jetable, bases=("app",))
    fiche = cles["ALPHA_API_KEY"]
    assert fiche["occurrences"] >= 1
    assert any("droit.py" in s for s in fiche["sites"])


def test_un_fichier_illisible_est_compte_jamais_ignore(audit, depot_jetable, monkeypatch):
    """ILLISIBLE n'est pas ABSENT, y compris pour un fichier source."""
    from pathlib import Path

    vrai = Path.read_text

    def lecture_qui_echoue(self, *a, **k):
        if self.name == "avec_alias.py":
            raise OSError("refus simule")
        return vrai(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", lecture_qui_echoue)
    cles, stats = audit.cles_demandees(racine=depot_jetable, bases=("app",))
    assert stats["illisibles"] == 1, (
        "un fichier qu'on n'a PAS PU lire doit etre compte : sinon l'inventaire "
        "se croit complet alors qu'il a un trou"
    )
    assert "BETA_TOKEN" not in cles      # non vu, et l'instrument le DIT


def test_l_inventaire_n_ouvre_aucun_coffre(audit, depot_jetable, monkeypatch):
    """L'inventaire lit du TEXTE SOURCE. Il ne doit toucher aucune source de
    secrets -- sinon un audit deviendrait lui-meme un consommateur."""
    import importlib

    secrets = importlib.import_module("nokido_agent.app.forge_secrets")
    touche = []
    for nom in ("_machine_vault", "_wcm", "_dotenv"):
        monkeypatch.setattr(
            secrets, nom,
            lambda k, _n=nom: touche.append(_n),
        )
    audit.cles_demandees(racine=depot_jetable, bases=("app",))
    assert touche == [], "l'inventaire a interroge %s" % touche


# ---------------------------------------- PHASE 2 : SECRET n'est pas CONFIG

NATURES = {"SECRET_EXTERNE", "CREDENTIAL_INTERNE", "CONFIG", "INDETERMINE"}


def test_la_nature_est_un_ensemble_ferme(audit):
    assert hasattr(audit, "nature"), "le classificateur doit etre EXPOSE, pas recopie"
    for cle in ("OPENAI_API_KEY", "FORGE_TOKEN_CLAUDE", "LAFORGE_KEY_SECRET_TTL", "CLE"):
        assert audit.nature(cle)["nature"] in NATURES


def test_un_reglage_qui_porte_le_mot_cle_nest_pas_un_secret(audit):
    """Le module le dit deja dans ses propres commentaires : « UN NOM N'EST PAS
    UNE PREUVE (...) un secret est une VALEUR D'AUTHENTIFICATION, pas un
    parametre de comportement ». La nature REUTILISE NON_SECRET au lieu d'une
    seconde heuristique -- deux heuristiques divergent toujours en silence.
    """
    for reglage in ("LAFORGE_KEY_SECRET_TTL", "ONNXGENAI_MAX_TOKENS",
                    "LAFORGE_ALLOW_SECRETS_READ", "LMSTUDIO_MODEL",
                    "TOKENIZERS_PARALLELISM"):
        assert audit.nature(reglage)["nature"] == "CONFIG", (
            "%s est un reglage : le classer SECRET ferait crier l'instrument a "
            "faux, et un garde qui crie a faux finit desarme" % reglage
        )


def test_un_jeton_emis_par_le_corps_nest_pas_une_cle_de_tiers(audit):
    """Distinction qui commande la PHASE 9 : les deux familles n'ont pas la
    meme procedure de rotation.

    CREDENTIAL_INTERNE -> emis par Nokido, rotable par un geste LOCAL
                          (forge_vault_seed_agent_tokens), revocable par nous.
    SECRET_EXTERNE     -> emis par un tiers ; « rotation » veut dire aller sur
                          le site du fournisseur. Nous ne pouvons pas le
                          revoquer, seulement cesser de l'utiliser.
    Les confondre, c'est promettre une rotation qu'on ne peut pas tenir.
    """
    for interne in ("FORGE_TOKEN_CLAUDE", "FORGE_TOKEN_BRIDGE",
                    "LAFORGE_ADMIN_TOKEN", "LAFORGE_SUPERVISOR_TOKEN"):
        assert audit.nature(interne)["nature"] == "CREDENTIAL_INTERNE", interne
    for externe in ("OPENAI_API_KEY", "GEMINI_API_KEY", "HUGGINGFACE_TOKEN",
                    "R2_SECRET_KEY"):
        assert audit.nature(externe)["nature"] == "SECRET_EXTERNE", externe


def test_indetermine_dit_pourquoi_et_ce_qui_trancherait(audit):
    """PHASE 3 : « INDETERMINE est valide, mais il doit dire pourquoi, quel
    instrument manque, et qui peut trancher. »

    `CLE`, `NOM_CLE` et `NOKIDO_CLE_QUI_N_EXISTE_PAS_` sont des litteraux de
    test ou de migration passes par la voie de production : un nom trop court
    ou trop generique ne PEUT pas etre classe par son nom.
    """
    for flou in ("CLE", "NOM_CLE"):
        fiche = audit.nature(flou)
        assert fiche["nature"] == "INDETERMINE"
        assert fiche["pourquoi"], "%s ne dit pas pourquoi il est indetermine" % flou
        assert fiche["trancher"], "%s ne dit pas ce qui permettrait de trancher" % flou


def test_l_inventaire_porte_la_nature_de_chaque_cle(audit, depot_jetable):
    """Le raccord : la nature doit voyager avec l'inventaire, sinon il faudrait
    la recalculer ailleurs -- et c'est ainsi qu'on obtient deux classements."""
    cles, _ = audit.cles_demandees(racine=depot_jetable, bases=("app",))
    assert cles["ALPHA_API_KEY"]["nature"] == "SECRET_EXTERNE"
    assert cles["BETA_TOKEN"]["nature"] in NATURES


# ------------------------------------------------ raccord avec le diagnostic

def test_le_diagnostic_sait_consommer_cet_inventaire():
    """Le raccord, pas seulement la piece.

    `diagnostic(scan=True)` doit faire apparaitre les cles du scan avec leur
    origine. Sans ce raccord, l'inventaire serait juste et inutile -- un module
    present mais non cable n'est pas une securite.
    """
    import importlib

    secrets = importlib.import_module("nokido_agent.app.forge_secrets")
    d = secrets.diagnostic(scan=True)
    assert "scan" in d, "le diagnostic doit dire si le scan a eu lieu ET son etat"
    assert d["scan"]["etat"] in {"FAIT", "ILLISIBLE", "NON_DEMANDE"}
    if d["scan"]["etat"] == "FAIT":
        origines = {f["origine"] for f in d["cles"].values()}
        assert "scan" in origines, (
            "les cles vues par le scan doivent entrer dans l'inventaire, sinon "
            "l'audit reste borne a sa liste codee en dur"
        )
        assert d["total"] > d["total_known"], (
            "le scan du depot reel doit voir plus que les 26 cles declarees "
            "(74 mesurees le 2026-09-20)"
        )


def test_le_scan_nest_pas_fait_sans_quon_le_demande():
    """Un audit qui scanne 2400 fichiers a chaque appel serait abandonne.
    Le cout doit etre explicite."""
    import importlib

    secrets = importlib.import_module("nokido_agent.app.forge_secrets")
    d = secrets.diagnostic()
    assert d["scan"]["etat"] == "NON_DEMANDE"
