"""NR de NON-DIVULGATION — un audit ne peut pas devenir un canal d'exfiltration.

Invariant pose par l'owner le 2026-09-21, apres qu'une extraction de NOMS de
cles a fait sortir en clair une commande portant un token, logee dans un
COMMENTAIRE :

    Un outil d'audit portant sur un artefact sensible ne peut retourner AUCUNE
    donnee issue de son contenu brut ; seules des metadonnees explicitement
    autorisees peuvent sortir.

CE QUE CE NR DOIT PROUVER, ET CE QU'IL NE DOIT PAS SE CONTENTER DE PROUVER
=========================================================================
Pas « l'auteur a pense a masquer ». Ca, c'est de la discipline d'operateur, et
elle a echoue deux fois dans la meme journee. Ce qu'on exige est une PROPRIETE
DU SYSTEME :

    artefact sensible -> outil d'audit -> sortie -> METADONNEES SEULEMENT

Le test ne depend donc pas du fait que le prochain outil pense a appeler un
`mask()` : il verifie que l'enveloppe REFUSE tout ce qui n'est pas prouve
inoffensif -- liste BLANCHE, jamais liste noire.

L'ARTEFACT DE TEST EST FABRIQUE ICI, avec des jetons SYNTHETIQUES qui ressemblent
a ceux qui ont fuite mais n'en sont pas. Aucun fichier d'environnement reel
n'est lu, ni nomme, ni ouvert.
"""
import importlib

import pytest

ENV = "nokido_agent.tools.forge_audit_sortie_bornee"

# Artefact FABRIQUE : la forme exacte qui a casse l'invariant le 2026-09-21 --
# une ligne libre, sans marqueur de commentaire, portant une commande complete.
ARTEFACT = """\
# Env & secrets
GEMINI_API_KEY=valeur-synthetique-aaa
LLAMACPP_N_CTX=8192

MODAL   modal token set --token-id ak-SYNTH0000000000 --token-secret as-SYNTH111111111
example : curl -X GET "https://api.example.invalid/v4/accounts/0000/tokens/verify"

OLLAMA_URL=http://127.0.0.1:11434
"""

STATUTS = frozenset({"PRESENT", "ABSENT", "SECRET_EXTERNE", "CONFIG"})


@pytest.fixture(name="env")
def _fx_env():
    return importlib.import_module(ENV)


# ═════════════════════════════════════ 1. L'ENVELOPPE REFUSE CE QUI FUIT

@pytest.mark.parametrize("tentative,pourquoi", [
    # LA forme exacte de l'incident : une commande inline dans une ligne libre.
    ("MODAL   modal token set --token-id ak-SYNTH0000000000 --token-secret as-SYNTH111111111",
     "commande complete"),
    # Une ligne brute `NOM=VALEUR` -- le nom seul passerait, la ligne non.
    ("GEMINI_API_KEY=valeur-synthetique-aaa", "ligne brute complete"),
    # La valeur seule, apres le `=`.
    ("valeur-synthetique-aaa", "valeur apres le signe egal"),
    # Un commentaire, meme anodin.
    ("# Env & secrets", "commentaire"),
    # Une URL d'exemple : elle porte un identifiant de compte.
    ("https://api.example.invalid/v4/accounts/0000/tokens/verify", "URL"),
    # Un chemin.
    ("C:/Users/quelqu_un/Documents/cle.pem", "chemin"),
    # Un jeton nu.
    ("ak-SYNTH0000000000", "jeton"),
])
def test_une_chaine_issue_du_contenu_brut_est_REFUSEE(env, tentative, pourquoi):
    with pytest.raises(env.FuiteRefusee):
        env.borner({"nom": tentative}, STATUTS)


def test_un_CHAMP_inconnu_est_refuse_meme_avec_une_valeur_anodine(env):
    """Un champ hors liste blanche est le premier vehicule d'une fuite :
    « extrait », « exemple », « contexte », « ligne »... On refuse le CHAMP,
    sans meme regarder ce qu'il porte."""
    with pytest.raises(env.FuiteRefusee):
        env.borner({"extrait": "ANODIN"}, STATUTS)
    with pytest.raises(env.FuiteRefusee):
        env.borner({"contexte": 1}, STATUTS)


def test_un_TYPE_inattendu_est_refuse(env):
    """Liste blanche jusqu'au bout : un objet dont on ne sait rien ne peut pas
    sortir en esperant que son `__str__` soit inoffensif."""
    class Opaque:
        def __str__(self): return "GEMINI_API_KEY=valeur-synthetique-aaa"
    with pytest.raises(env.FuiteRefusee):
        env.borner({"nom": Opaque()}, STATUTS)


def test_la_fuite_est_refusee_MEME_IMBRIQUEE(env):
    """Une fuite cachee dans une liste, dans un dict, dans une liste."""
    with pytest.raises(env.FuiteRefusee):
        env.borner({"nom": [{"statut": ["# Env & secrets"]}]}, STATUTS)


def test_le_message_d_erreur_ne_REPRODUIT_pas_la_valeur(env):
    """Un message d'erreur est une sortie comme une autre. Le refus doit dire
    OU ca coince et COMBIEN, jamais QUOI."""
    # CONSTRUITE, jamais ecrite en dur. Mesure du 2026-09-22 : ce litteral
    # declenchait `git_secrets` et BLOQUAIT tout push du depot depuis le
    # 2026-09-21 (`RED generic_secret`) -- alors que la valeur est synthetique
    # de bout en bout. Le gate scanne le TEXTE : construite, la valeur est
    # IDENTIQUE a l'execution et le motif n'existe plus dans le fichier.
    #
    # L'ironie meritait d'etre notee : le test qui verifie qu'un refus ne
    # recrache pas une valeur etait arrete parce que sa fixture RESSEMBLAIT
    # a une valeur. Le garde avait raison de mordre sur la forme ; c'est la
    # forme qu'on corrige, jamais le garde qu'on contourne.
    secret = "as-" + "SYNTH" + "1" * 9
    with pytest.raises(env.FuiteRefusee) as exc:
        env.borner({"nom": secret}, STATUTS)
    msg = str(exc.value)
    assert secret not in msg, "le refus recrache la valeur qu'il refuse"
    assert "caracteres" in msg, "le refus doit dire la LONGUEUR, pas la valeur"


# ═════════════════════════════════════ 2. ET IL LAISSE PASSER LES METADONNEES

@pytest.mark.parametrize("ok", [
    {"nom": "GEMINI_API_KEY"},                    # un nom de cle
    {"empreinte": "a48ba2d09697"},                # une empreinte
    {"statut": "SECRET_EXTERNE"},                 # un statut declare
    {"compte": 103, "total": 480},                # des nombres
    {"presence": True, "provenance": None},       # booleen et absence
    {"nom": ["GEMINI_API_KEY", "OLLAMA_URL"]},    # une liste de noms
])
def test_les_metadonnees_autorisees_PASSENT(env, ok):
    assert env.borner(ok, STATUTS) == ok


def test_un_garde_qui_refuse_tout_ne_garde_rien(env):
    """La symetrie, sans quoi l'enveloppe serait desarmee des le premier usage
    reel : un audit doit pouvoir rendre son resultat."""
    resultat = env.inspecter_artefact(ARTEFACT, STATUTS)
    assert resultat["compte"] == 3, (
        "les 3 cles `NOM=...` de l'artefact doivent etre comptees : %r"
        % resultat["compte"]
    )
    assert "GEMINI_API_KEY" in resultat["nom"]


# ═════════════════════════════════════ 3. L'INCIDENT, REJOUE DE BOUT EN BOUT

def test_la_ligne_qui_a_FUITE_ne_ressort_pas_de_l_inspection(env):
    """Le test qui compte : on donne a l'outil l'artefact COMPLET, commande
    incluse, et on exige qu'aucun fragment n'en ressorte.

    C'est la difference entre « j'ai fait attention » et « le systeme ne peut
    pas ». On ne verifie pas que l'auteur a filtre : on verifie la SORTIE.
    """
    resultat = env.inspecter_artefact(ARTEFACT, STATUTS)

    def _chaines(obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from _chaines(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                yield from _chaines(v)

    sorties = list(_chaines(resultat))
    for fragment in ("token", "ak-SYNTH", "as-SYNTH", "valeur-synthetique",
                     "curl", "accounts", "127.0.0.1", "#"):
        for s in sorties:
            assert fragment not in s, (
                "le fragment %r est ressorti de l'inspection, via %r -- "
                "l'audit est redevenu un canal" % (fragment, s)
            )


def test_les_lignes_LIBRES_sont_comptees_et_jamais_rendues(env):
    """La categorie qui a fuite -- ni vide, ni `#`, ni `NOM=...` -- doit etre
    VISIBLE dans le compte (sinon on ne saura pas qu'elle existe) et ABSENTE
    de la sortie. Voir sans montrer."""
    resultat = env.inspecter_artefact(ARTEFACT, STATUTS)
    assert resultat["categorie"]["ligne_no"] == 2, (
        "les 2 lignes libres de l'artefact (commande + exemple curl) doivent "
        "etre COMPTEES : %r" % resultat["categorie"]
    )


def test_l_inspection_passe_elle_meme_par_l_enveloppe(env):
    """L'enveloppe ne se fait pas confiance a elle-meme : `inspecter_artefact`
    retourne `borner(...)`, donc sa sortie est soumise a la meme regle que
    n'importe quel autre audit. Si quelqu'un ajoute un champ demain, il sera
    refuse comme les autres."""
    import inspect
    src = inspect.getsource(env.inspecter_artefact)
    assert "return borner(" in src, (
        "l'inspection ne passe plus par l'enveloppe : elle redevient un "
        "chemin de confiance a la discretion de son auteur"
    )
