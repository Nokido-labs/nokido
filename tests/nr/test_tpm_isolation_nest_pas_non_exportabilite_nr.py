"""NR — la non-exportabilite d'une cle TPM n'est PAS une isolation entre appelants.

CAP V9, P4. Invariant pose par l'owner, et il est contre-intuitif : c'est
precisement pour cela qu'il doit etre EXECUTE et pas seulement ecrit.

    NON-EXPORTABILITE  la cle ne peut pas SORTIR du TPM
    ISOLATION          seul son proprietaire legitime peut s'en SERVIR

Le TPM garantit la premiere. Il ne garantit pas la seconde. Une cle
non-exportable protege contre l'EXFILTRATION, pas contre l'USURPATION : tout
code qui atteint le provider peut demander une signature, et la signature
produite sera indiscernable d'une signature legitime.

CE QUI A ETE MESURE LE 2026-09-21
=================================
`forge_persona_tpm.sign_as(agent_id, payload)` ne prend QU'UN NOM. Aucune
preuve, aucun jeton, aucun appel a `forge_mcp_rbac`. N'importe quelle ligne de
code du process peut donc ecrire `sign_as("HUB", ...)` et obtenir une signature
au nom du HUB.

Et la limite etait bien nommee -- mais dans le docstring d'un AUTRE fichier de
test (`test_tpm_cle_par_agent_nr`, L20-22). Un avertissement range dans un test
n'arrete personne : celui qui appellera `sign_as` lira `sign_as`. C'est pour ca
que ce NR exige l'avertissement A LA FONCTION, la ou il sera lu au moment de
s'en servir.

CE QUE CE NR NE FAIT PAS
========================
Il ne cree, n'ouvre et ne supprime AUCUNE cle TPM. Il lit des signatures de
fonctions et des textes. Il passe donc identiquement sur une machine sans TPM,
sur un compte sans droits, et sur un poste ou les cles n'existent pas encore --
ce qui est le cas mesure : les 7 cles d'agents sont `INDISPONIBLE` depuis les
deux comptes non-admin testes, et INDISPONIBLE n'est pas ABSENTE.
"""
import importlib
import inspect
import pathlib
import re

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : lecture de tous les app/*.py
#   et tools/*.py (l.85)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

TPM = "nokido_agent.app.forge_persona_tpm"
RACINE = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(name="tpm")
def _fx_tpm():
    return importlib.import_module(TPM)


# ------------------------------------------------ 1. la limite est DITE la ou on agit

def test_sign_as_AVERTIT_qu_il_n_authentifie_personne(tpm):
    """L'avertissement doit vivre dans la fonction, pas dans un test voisin."""
    doc = inspect.getdoc(tpm.sign_as) or ""
    bas = doc.lower()
    assert "usurp" in bas or "n'authentifie" in bas or "autorisation" in bas, (
        "`sign_as` ne dit pas qu'il n'authentifie PAS son appelant. Celui qui "
        "l'utilisera lira ce docstring, pas celui d'un fichier de test :\n%r"
        % doc[:200]
    )


def test_sign_as_ne_prend_AUCUNE_preuve_en_parametre(tpm):
    """Constat verrouille, et volontairement fige.

    Si un jour `sign_as` gagne un parametre de preuve (jeton, contexte
    d'autorisation), ce test rougira -- et c'est ce qu'on veut : il faudra
    alors relire l'invariant et mettre a jour le contrat, plutot que de laisser
    croire que l'ancienne limite tient encore.
    """
    params = list(inspect.signature(tpm.sign_as).parameters)
    assert params == ["agent_id", "payload"], (
        "la signature de `sign_as` a change (%s) : relire l'invariant "
        "non-exportabilite != isolation avant d'adapter ce test" % params
    )


# ------------------------------------------------ 2. sentinelle de CABLAGE

def _appelants_de(nom: str):
    """Sites appelant `nom` hors du module qui le definit et hors des tests."""
    out = []
    for sous in ("app", "tools"):
        for p in sorted((RACINE / sous).glob("*.py")):
            if p.name == "forge_persona_tpm.py":
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                # ILLISIBLE n'est pas ABSENT : on le dit au lieu de l'ignorer.
                out.append(("%s/%s" % (sous, p.name), -1, "ILLISIBLE"))
                continue
            for m in re.finditer(r"\b%s\s*\(" % re.escape(nom), txt):
                ln = txt[:m.start()].count("\n") + 1
                out.append(("%s/%s" % (sous, p.name), ln,
                            txt.splitlines()[ln - 1].strip()[:90]))
    return out


# Appelants de `sign_as` ADMIS, chacun avec le controle d'autorisation qui PRECEDE la
# signature. Ajoute le 2026-09-24 (chantier d'authentification, preuve TPM) apres
# relecture de l'invariant : `forge_dpop.CleTpm` ne se construit que pour le porteur du
# credential PROPRE de l'agent (`_porteur_autorise`, temps constant au coffre), et
# `sign` n'est atteignable que sur une instance construite. Le test ci-dessous VERIFIE
# ce controle dans le code : une entree ici n'est pas une exemption, c'est un contrat.
APPELANTS_AUTORISES = {"app/forge_dpop.py": "_porteur_autorise"}


def test_chaque_appelant_admis_autorise_AVANT_de_signer():
    import ast
    for fichier, controle in APPELANTS_AUTORISES.items():
        arbre = ast.parse((RACINE / fichier).read_text(encoding="utf-8"))
        classes = [c for c in ast.walk(arbre) if isinstance(c, ast.ClassDef)
                   and any(isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "sign_as"
                           for n in ast.walk(c))]
        assert classes, "%s : aucun porteur de sign_as trouve -- retirer l'entree" % fichier
        for c in classes:
            init = next((f for f in c.body if isinstance(f, ast.FunctionDef)
                         and f.name == "__init__"), None)
            assert init is not None, "%s.%s : pas de __init__ pour autoriser" % (fichier, c.name)
            appels = {getattr(n.func, "id", getattr(n.func, "attr", ""))
                      for n in ast.walk(init) if isinstance(n, ast.Call)}
            leve = any(isinstance(n, ast.Raise) for n in ast.walk(init))
            assert controle in appels and leve, (
                "%s.%s : la construction doit appeler %s ET lever si refus, AVANT toute "
                "signature" % (fichier, c.name, controle))


def test_sentinelle_le_jour_ou_quelqu_un_CABLE_sign_as():
    """Mesure du 2026-09-21 : `sign_as` n'a AUCUN appelant de production.

    Ses seuls sites sont la sonde d'etat de `forge_tpm_agent_keys`, qui signe
    une chaine temoin pour savoir si la cle repond. La racine de confiance
    materielle existe donc, et n'est CABLEE NULLE PART -- c'est une dette de
    cablage, pas une securite en place. Provisionner les 7 cles ne changerait
    rien tant qu'aucun chemin ne les utilise.

    Ce test n'interdit pas de cabler : il oblige a RELIRE l'invariant en le
    faisant. Le jour ou un appelant apparait, il rougit et demande qu'on
    verifie que ce site porte un controle d'autorisation AVANT de signer.
    """
    sites = _appelants_de("sign_as")
    illisibles = [s for s in sites if s[2] == "ILLISIBLE"]
    reels = [s for s in sites
             if s[2] != "ILLISIBLE" and "forge_tpm_agent_keys" not in s[0]
             and s[0] not in APPELANTS_AUTORISES]
    assert not illisibles, (
        "des fichiers n'ont pas pu etre lus, la couverture est INCOMPLETE et "
        "non vide : %s" % illisibles[:5]
    )
    assert not reels, (
        "un appelant de `sign_as` est apparu hors de la sonde d'etat :\n  %s\n"
        "AVANT d'adapter ce test : verifier que ce site autorise son appelant, "
        "car `sign_as` signe au nom de QUI ON LUI DIT, sans le verifier."
        % "\n  ".join("%s:%d  %s" % s for s in reels[:6])
    )


# ------------------------------------------------ 3. la creation reste un geste eleve

def test_la_creation_de_cle_reste_hors_de_portee_des_agents():
    """Mesure du 2026-09-21 sur DEUX comptes : `LaForgeSbxOffline` (hub) ET
    `LaForgeTrusted` (canal d'ecriture privilegie) rendent tous deux
    `admin : NON`. La creation d'une cle MACHINE exige l'elevation, donc aucun
    canal du hub ne peut la porter -- contrairement a l'ecriture du coffre, qui
    passe par `trusted_script`.

    On verifie que l'outil REFUSE au lieu de tenter, et qu'il nomme le geste.
    """
    outil = importlib.import_module("nokido_agent.tools.forge_tpm_agent_keys")
    src = inspect.getsource(outil.main)
    assert "REFUS" in src, "l'outil doit refuser explicitement sans elevation"
    assert "FORGE_TPM_MACHINE" in src, (
        "le magasin MACHINE doit etre force a la creation : sans ce drapeau les "
        "cles iraient dans le magasin UTILISATEUR de celui qui les cree, et le "
        "compte qui signe ne les verrait jamais"
    )


def test_ABSENTE_et_REFUSEE_appellent_des_gestes_OPPOSES():
    """Une cle qui EXISTE mais qu'on ne peut pas ouvrir rend NTE_PERM ; une cle
    qui n'existe pas rend NTE_BAD_KEYSET ou NTE_NOT_FOUND. Les confondre envoie
    provisionner une cle deja provisionnee, ou reparer des droits hors de cause.

    Ce test verifiait d'abord une PHRASE (« INDISPONIBLE ne veut pas dire
    ABSENTE »). Elle disait la bonne chose, mais l'outil ne POUVAIT pas faire
    mieux : `_open_key` jetait le code d'erreur. Depuis le 2026-09-21 la
    distinction est mesuree, donc le test porte sur elle et non sur sa
    formulation -- un test qui verrouille une phrase interdit de la corriger.
    """
    outil = importlib.import_module("nokido_agent.tools.forge_tpm_agent_keys")
    src = inspect.getsource(outil.main)
    for attendu in ("ABSENTE", "REFUSEE", "0x80090010", "provisionner"):
        assert attendu in src, (
            "le rapport ne nomme pas %r : l'operateur ne peut pas savoir s'il "
            "doit provisionner ou ouvrir un acces" % attendu
        )
