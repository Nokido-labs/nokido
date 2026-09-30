r"""NR — P1-F : la matrice SOURCE x CREDENTIAL x DECISION, mesuree sans effet de bord.

MESURE DU 2026-09-21.

LE PROBLEME DE METHODE, D'ABORD
===============================
`swarm_run`, `recon_run` et `ctf_run` portent la meme condition de refus. La
sonder en runtime declencherait un fan-out LLM REEL sur quatre providers : le
handler pose une `task` par defaut quand le corps est vide, donc meme une
requete « neutre » a un effet. Le classement honnete de cette voie est

    NON_MESURABLE_SANS_EFFET_DE_BORD

et surtout pas `SAFE`, ni `VULNERABLE`.

LA VOIE RETENUE : mesurer LE GARDE, pas la route. La condition est EXTRAITE du
source du hub par AST, puis evaluee sur les sept combinaisons. Rien n'est
reecrit a la main :

    ce NR ne teste pas MA copie de la condition, il teste CELLE DU HUB.

C'est ce qui separe une mesure d'une paraphrase. Si quelqu'un modifie la
condition dans `nokido_hub.py`, cette table change ici -- sans edition.

CE QUE CELA NE PROUVE PAS, et qui doit rester lisible :
  * que le handler soit ATTEINT (middleware, ordre des routes, proxy amont) ;
  * que `valid` soit calcule correctement en amont de ce `if` ;
  * que l'effet suive la decision.
On mesure UN maillon : `REQUESTED -> ACCEPTED`. Pas `AUTHENTICATED`, pas
`AUTHORIZED`, pas `EFFECTED`.

LE FAIT MESURE
==============
    client not in ('127.0.0.1', '::1', 'localhost', '')

Tout appelant local passe sans porteur -- chaine vide comprise, celle que
`request.client` rend quand il est absent. `LOCAL_ONLY != TRUSTED` : le compte
sandbox du hub atteint le loopback, et cela n'authentifie personne (directive
owner du 2026-09-18).

Ce NR ne ferme rien. Il rend la table VRAIE et opposable.

NOTE POUR LE CORRECTIF FUTUR, pas pour ce NR : la bibliotheque standard offre
`ipaddress.ip_address(x).is_loopback`, qui couvre `127.0.0.0/8` entier et les
formes IPv6 mappees. La liste en dur ne reconnait que trois ecritures ; ce
n'est pas l'objet ici, et l'elargir serait durcir avant d'avoir mesure.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

#: Handlers dont on extrait la condition de refus.
CIBLES = ("swarm_run", "recon_run", "ctf_run")

#: Les sept situations. `valid` est le resultat AMONT de la verification du
#: porteur ; `client` est `request.client.host`, ou "" quand il est absent.
CAS = (
    ("REMOTE_EXTERNAL",        False, "203.0.113.7"),
    ("REMOTE_EXTERNAL_AUTH",   True,  "203.0.113.7"),
    ("REMOTE_LOOPBACK",        False, "127.0.0.1"),
    ("REMOTE_LOOPBACK_AUTH",   True,  "127.0.0.1"),
    ("LOCALHOST_NOM",          False, "localhost"),
    ("LOOPBACK_IPV6",          False, "::1"),
    ("CLIENT_VIDE",            False, ""),
)


def _racine() -> Path:
    for base in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[1]):
        if (base / "tools" / "nokido_hub.py").exists():
            return base
    raise AssertionError("racine du depot introuvable")


def _condition_de_refus(handler: str) -> str:
    """La condition du `if` qui rend 401, EXTRAITE du hub. Jamais recopiee."""
    src = (_racine() / "tools" / "nokido_hub.py").read_text(encoding="utf-8")
    for fn in ast.walk(ast.parse(src)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name != handler:
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.If) and "401" in ast.dump(n):
                return ast.unparse(n.test)
    raise AssertionError("condition de refus introuvable dans %s" % handler)


def _refuse(condition: str, valid: bool, client: str) -> bool:
    """Evalue la condition EXTRAITE, dans un espace de noms MINIMAL et FERME.

    Si la condition se met a dependre d'autre chose, on obtient une NameError
    -- un echec bruyant -- au lieu d'une mesure silencieusement fausse.
    """
    return bool(eval(condition, {"__builtins__": {}},  # noqa: S307 - expression du depot
                     {"valid": valid, "client": client}))


# ────────────────  L INSTRUMENT LIT BIEN LE HUB  ──────────────────────────

@pytest.mark.parametrize("handler", CIBLES)
def test_la_condition_est_extraite_et_non_recopiee(handler):
    """Si l'extraction echouait, tous les tests suivants mesureraient une
    condition inventee. C'est le controle qui evite la paraphrase."""
    cond = _condition_de_refus(handler)
    assert "valid" in cond and "client" in cond, (
        "la condition extraite de %s ne porte plus les deux variables "
        "attendues : re-mesurer avant de conclure (%r)" % (handler, cond))


def test_les_trois_routes_portent_la_meme_condition():
    """Trois copies d'une meme regle : corriger l'une laisserait les deux
    autres ouvertes. Le fait est enregistre pour que la divergence, si elle
    apparait un jour, soit VISIBLE au lieu d'etre rassurante."""
    conds = {h: _condition_de_refus(h) for h in CIBLES}
    assert len(set(conds.values())) == 1, (
        "les conditions ont DIVERGE entre les trois routes : %s" % conds)


# ──────────────────────  LA MATRICE MESUREE  ──────────────────────────────

def test_la_matrice_source_credential_decision():
    """LE COEUR. Table de verite de la condition REELLE, sur les sept cas."""
    cond = _condition_de_refus("swarm_run")
    obtenu = {nom: ("401" if _refuse(cond, v, c) else "PASSE") for nom, v, c in CAS}

    attendu = {
        "REMOTE_EXTERNAL":      "401",     # sans porteur, depuis l'exterieur
        "REMOTE_EXTERNAL_AUTH": "PASSE",   # porteur valide
        "REMOTE_LOOPBACK":      "PASSE",   # <- SANS PORTEUR, et ca passe
        "REMOTE_LOOPBACK_AUTH": "PASSE",
        "LOCALHOST_NOM":        "PASSE",   # <- SANS PORTEUR
        "LOOPBACK_IPV6":        "PASSE",   # <- SANS PORTEUR
        "CLIENT_VIDE":          "PASSE",   # <- SANS PORTEUR, client inconnu
    }
    assert obtenu == attendu, (
        "la table de verite du garde a CHANGE : %s. Si la garde a ete FERMEE, "
        "tant mieux -- mettre a jour cette table et le prouver en runtime. "
        "Sinon, une regression l'a ouverte davantage." % obtenu)


def test_quatre_situations_passent_sans_aucun_porteur():
    """Enonce le fait separement du tableau, pour qu'il ne se perde pas dans
    une comparaison de dictionnaires."""
    cond = _condition_de_refus("swarm_run")
    passent = [nom for nom, v, c in CAS if not v and not _refuse(cond, v, c)]
    assert set(passent) == {"REMOTE_LOOPBACK", "LOCALHOST_NOM",
                            "LOOPBACK_IPV6", "CLIENT_VIDE"}, (
        "l'ensemble des situations qui passent SANS porteur a change : %s" % passent)


def test_le_garde_refuse_bien_quelque_chose():
    """CONTRE-EPREUVE. Un garde qui laisserait TOUT passer rendrait les tests
    precedents verts sans rien prouver. Il doit exister au moins un refus."""
    cond = _condition_de_refus("swarm_run")
    refus = [nom for nom, v, c in CAS if _refuse(cond, v, c)]
    assert refus, (
        "la condition ne refuse AUCUN des sept cas : le garde est inoperant, "
        "ou l'extraction mesure autre chose que ce qu'on croit")


def test_l_instrument_distingue_deux_conditions_construites():
    """P1-I. Le detecteur doit separer un garde ouvert au local d'un garde
    ferme -- prouve sur deux expressions ecrites ICI, pas sur le depot, pour
    que la distinction ne dependent pas de l'etat du corps."""
    ouverte = "not valid and client not in ('127.0.0.1', '::1', 'localhost', '')"
    fermee = "not valid"
    assert _refuse(ouverte, False, "127.0.0.1") is False
    assert _refuse(fermee, False, "127.0.0.1") is True
    assert _refuse(ouverte, False, "203.0.113.7") is True
    assert _refuse(fermee, True, "203.0.113.7") is False


# ──────────  CE QUI N EST PAS MESURE, ET QUI LE RESTE  ───────────────────

def test_la_voie_runtime_est_declaree_non_mesurable():
    """Le docstring doit continuer de porter le classement honnete de la voie
    runtime : un lecteur qui ne verrait que la matrice pourrait croire que
    l'absence de sonde est un oubli, et la combler par une requete qui
    declenche un fan-out reel."""
    assert "NON_MESURABLE_SANS_EFFET_DE_BORD" in __doc__
    assert "fan-out" in __doc__
