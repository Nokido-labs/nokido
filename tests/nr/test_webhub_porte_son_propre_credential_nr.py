"""NR — l'interface web presente SON credential, plus le passe-partout du hub.

REVUE DE SECURITE 2026-09-18. `wired_routes._hub_token()` ne rendait que le
jeton MAITRE, pendant que les appels declarent `X-Agent-Name: WEBHUB`. Or le
porteur du maitre CONSERVE l'agent du header ET son ring (`via=master_token`) :
c'est un passe-partout d'identite. Mesure faite ce jour, avec le vrai resolveur :

    maitre + X-Agent-Name: WEBHUB  ->  agent=WEBHUB  ring=2  via=master_token
    maitre + X-Agent-Name: CLAUDE  ->  agent=CLAUDE  ring=1  via=master_token
                                       ^^^^^^^^^^^^^^^^^^^^ n'importe qui

Tout appel d'outil passe par l'interface web s'executait donc avec l'autorite du
ROUTEUR et non celle de l'utilisateur : le CONFUSED DEPUTY, ferme le 2026-09-02
pour OPENAI_PROXY et DENOHUBMCP, et dont l'interface web avait ete OUBLIEE.

Preuve de l'oubli, mesuree avant correction : `FORGE_TOKEN_DENOHUBMCP` et
`FORGE_TOKEN_OPENAI_PROXY` etaient PRESENTS au coffre, `FORGE_TOKEN_WEBHUB`
ABSENT — et ce n'etait pas le filtre de ring qui l'ecartait (`ring_max=3`,
WEBHUB est ring 2), seulement un semis jamais relance.

CE TEST NE LIT AUCUN SECRET, et il a fallu s'y reprendre a deux fois.

Premiere version : elle substituait `app.forge_secrets.get_secret` alors que la
fonction testee importe `nokido_agent.app.forge_secrets` — DEUX NOMS D'IMPORT,
DEUX INSTANCES (mesure du 2026-09-10). La substitution ne mordait donc pas, le
test a lu le VRAI coffre, et pytest a imprime la valeur dans son diff d'echec.
Un test de credential qui rate sa substitution ne rend pas un faux vert : il
EXFILTRE. Le jeton concerne a ete rotationne dans la foulee.

D'ou les deux regles suivies ici, et elles se tiennent ensemble :
  - substituer par `sys.modules`, sur le nom REELLEMENT importe, et VERIFIER que
    la substitution a mordu avant de conclure quoi que ce soit ;
  - n'affirmer que sur des marqueurs fabriques et des empreintes, jamais sur une
    valeur — pour qu'un echec futur reste lisible sans rien reveler.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (RACINE, RACINE / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

WR = pytest.importorskip("app.web_hub.wired_routes", reason="webhub non importable")


# Marqueurs FABRIQUES : aucune valeur reelle ne traverse ce fichier, donc aucun
# echec futur ne peut en reveler une.
_PROPRE = "marqueur-jeton-propre-de-test"
_MAITRE = "marqueur-jeton-maitre-de-test"


@pytest.fixture()
def coffre(monkeypatch):
    """Substitue le coffre SUR LE NOM REELLEMENT IMPORTE et note l'ordre des clefs."""
    demandes = []

    def _faire(presentes):
        def _gs(cle, *a, **k):
            demandes.append(cle)
            return presentes.get(cle)

        # La fonction testee fait `from nokido_agent.app.forge_secrets import
        # get_secret` DANS son corps : c'est ce module-la qu'il faut substituer.
        #
        # Et il faut l'IMPORTER d'abord : `sys.modules.get(nom)` rendait None au
        # premier appel — le module n'y etait pas encore — donc le patch sautait
        # et la fonction lisait le VRAI coffre. Mesure du 2026-09-18 : le garde
        # ci-dessous l'a attrape, les tests suivants passaient parce que le
        # premier appel avait fini par peupler `sys.modules`. Une substitution
        # qui depend de l'ordre des tests n'est pas une substitution.
        import importlib

        for nom in ("nokido_agent.app.forge_secrets", "app.forge_secrets"):
            try:
                mod = sys.modules.get(nom) or importlib.import_module(nom)
            except Exception:  # noqa: BLE001 — un nom absent n'invalide pas l'autre
                continue
            monkeypatch.setattr(mod, "get_secret", _gs, raising=False)
        monkeypatch.setitem(WR._TOKEN_CACHE, "t", None)
        return demandes

    return _faire


def test_la_substitution_du_coffre_mord_vraiment(coffre):
    """GARDE DU TEST LUI-MEME — sans lui, les autres cas liraient le vrai coffre
    et un echec imprimerait un secret. C'est arrive le 2026-09-18."""
    demandes = coffre({"FORGE_TOKEN_WEBHUB": _PROPRE})
    rendu = WR._hub_token()
    assert demandes, "le coffre substitue n'a JAMAIS ete appele — mauvais module"
    assert rendu == _PROPRE, (
        "la valeur rendue ne vient pas du coffre substitue : la substitution ne "
        "mord pas, ce test lirait le VRAI coffre"
    )


def test_le_jeton_propre_est_prefere_au_maitre(coffre):
    demandes = coffre({"FORGE_TOKEN_WEBHUB": _PROPRE, "FORGE_MCP_TOKEN": _MAITRE})
    rendu = WR._hub_token()
    assert rendu == _PROPRE, (
        "l'interface presente encore le jeton MAITRE alors qu'elle a le sien : "
        "c'est le passe-partout d'identite du confused deputy"
    )
    assert demandes and demandes[0] == "FORGE_TOKEN_WEBHUB", (
        f"le maitre est demande en premier : {demandes}"
    )


def test_le_repli_sur_le_maitre_existe_et_ne_casse_rien(coffre):
    """MORSURE SYMETRIQUE — sur une machine dont le coffre n'a pas ce jeton, on
    garde le comportement d'avant plutot que de rendre l'interface muette."""
    coffre({"FORGE_MCP_TOKEN": _MAITRE})
    assert WR._hub_token() == _MAITRE, (
        "sans jeton propre, l'interface ne peut plus joindre le hub du tout — "
        "le durcissement a casse la capacite au lieu de la gouverner"
    )


def test_le_repli_est_journalise_pas_silencieux(coffre, caplog):
    """Un repli silencieux se lit comme un succes. Il doit se voir, et le message
    doit porter le GESTE qui le corrige, pas seulement le constat."""
    import logging

    coffre({"FORGE_MCP_TOKEN": "maitre"})
    with caplog.at_level(logging.WARNING, logger="forge.webhub"):
        WR._hub_token()
    texte = " ".join(r.getMessage() for r in caplog.records)
    assert "FORGE_TOKEN_WEBHUB" in texte, f"le repli n'est pas signale : {texte!r}"
    assert "forge_vault_seed_agent_tokens" in texte, (
        "le message ne dit pas comment corriger — un avertissement sans geste se "
        "relit sans rien changer"
    )


def test_aucun_credential_quand_le_coffre_est_vide(coffre):
    """Ni jeton propre ni maitre : on rend une chaine vide, jamais une valeur
    inventee. L'echec doit etre franc."""
    coffre({})
    assert WR._hub_token() == ""


def test_la_copie_de_secours_de_mcp_lab_suit_le_meme_ordre():
    """`mcp_lab` importe cette fonction, mais garde une copie pour le cas ou
    l'import echoue. La laisser sur le maitre reintroduirait le defaut par le
    chemin de secours — c'est-a-dire la ou personne ne regarde."""
    import ast

    src = (RACINE / "app" / "web_hub" / "mcp_lab.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    fn = next(
        (n for n in ast.walk(arbre)
         if isinstance(n, ast.FunctionDef) and n.name == "_mcplab_hub_token"),
        None,
    )
    assert fn is not None, "la copie de secours a disparu ou a ete renommee"
    cles = [
        n.value for n in ast.walk(fn)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
        and n.value.startswith("FORGE_")
    ]
    assert cles, "la copie de secours ne demande plus aucune clef"
    assert cles[0] == "FORGE_TOKEN_WEBHUB", (
        f"la copie de secours demande {cles[0]!r} en premier : le chemin de "
        "secours rouvrirait le confused deputy"
    )


def test_le_registre_declare_la_delegation_de_l_interface():
    """Le jeton propre ne suffit pas : sans regle de delegation, l'interface ne
    peut pas declarer l'identite de son utilisateur. Le mecanisme et sa
    declaration vont ensemble — un mecanisme non declare est une dette."""
    import app.forge_videur as V

    regle = V._delegation_de("WEBHUB")
    assert regle, "WEBHUB n'a aucune regle de delegation au registre"
    plancher = int(regle.get("ring_min_delegue", 0))
    assert plancher >= 1, (
        f"plancher de delegation trop bas ({plancher}) : meme compromise, "
        "l'interface ne doit JAMAIS atteindre le ring 0"
    )


# ══════════════════════════════════════════════════════════════════════════
#  UN REPLI NE DOIT JAMAIS DEVENIR PERMANENT PAR MISE EN CACHE
#  Mesure du 2026-09-22, sur trafic reel.
#
#  Le jeton propre a ete seme le 2026-09-18 -- le docstring de `_hub_token` le
#  dit lui-meme : « Le jeton a ete seme le jour meme ». Quatre jours plus tard,
#  la vue d'audit compte, sur une fenetre homogene :
#
#      WEBHUB   master_token 4 378   token 1 072
#
#  80 % du trafic de l'interface porte encore le PASSE-PARTOUT, alors que son
#  credential propre est PRESENT au coffre (verifie sans lire sa valeur).
#
#  LA CAUSE N'EST PAS UNE CLE MANQUANTE, C'EST UN CACHE SANS INVALIDATION :
#
#      if _TOKEN_CACHE["t"] is not None:
#          return _TOKEN_CACHE["t"]
#
#  Un process demarre AVANT le semis a fige le maitre, et ne relira jamais. Le
#  repli -- concu comme une tolerance temporaire, et correctement journalise --
#  est devenu l'etat permanent.
#
#      LE REPLI ETAIT JUSTE, SA MISE EN CACHE L'A RENDU DEFINITIF
#
#  Meme motif que la fuite du 2026-09-21 (cle revoquee -> repli -> cache jamais
#  purge). Deux caches differents, une seule faute : cacher un resultat DEGRADE
#  avec la meme duree qu'un resultat NOMINAL.
#
#  CE QUE CELA CHANGE POUR LE DURCISSEMENT EN ATTENTE : ces 4 378 appels sont
#  99,3 % des declassements qu'un plancher sur le maitre provoquerait. Les
#  ramener sur le jeton propre fait tomber le cout d'armer de 23,2 % a ~0,15 %.
#  On ne contourne donc RIEN : on retire la cause.
# ══════════════════════════════════════════════════════════════════════════

def test_le_repli_sur_le_maitre_n_est_pas_fige_en_cache(coffre):
    """LE COEUR. Le coffre change SANS que le cache soit vide -- exactement ce
    qui s'est passe le 2026-09-18 quand la cle a ete semee sur un service deja
    demarre.

    On mute le dictionnaire du coffre au lieu de rappeler la fixture : celle-ci
    remet `_TOKEN_CACHE` a None, ce qui ferait passer ce test A TORT.
    """
    presentes = {"FORGE_MCP_TOKEN": _MAITRE}
    coffre(presentes)
    assert WR._hub_token() == _MAITRE, "le repli ne s'est pas produit : re-mesurer"

    presentes["FORGE_TOKEN_WEBHUB"] = _PROPRE  # semis, cache NON touche
    assert WR._hub_token() == _PROPRE, (
        "le repli sur le maitre est FIGE : le jeton propre a beau exister, "
        "l'interface continue de porter le passe-partout jusqu'au prochain "
        "redemarrage du service"
    )


def test_le_jeton_propre_lui_reste_cache(coffre):
    """CONTRE-EPREUVE : ne pas supprimer le cache, seulement le refuser au
    resultat DEGRADE. Sans ce test, on paierait un acces coffre par appel."""
    presentes = {"FORGE_TOKEN_WEBHUB": _PROPRE}
    demandes = coffre(presentes)
    assert WR._hub_token() == _PROPRE
    avant = len(demandes)
    assert WR._hub_token() == _PROPRE
    assert len(demandes) == avant, (
        "le jeton PROPRE n'est plus cache : chaque appel repaie un acces au "
        "coffre alors que rien ne le justifie"
    )


def test_le_cache_existe_bien(coffre):
    """CONTROLE POSITIF. Si `_TOKEN_CACHE` disparaissait, le test precedent
    serait vert pour une raison sans rapport avec ce qu'il mesure."""
    assert hasattr(WR, "_TOKEN_CACHE"), (
        "plus de cache du tout : le test de non-fixation ne mesure plus rien")


def test_un_coffre_vide_ne_fige_pas_non_plus(coffre):
    """SYMETRIQUE. `""` n'est pas `None` : si l'absence totale etait mise en
    cache, semer la cle plus tard ne servirait a rien non plus.

        ABSENCE MOMENTANEE != ABSENCE DEFINITIVE
    """
    presentes = {}
    coffre(presentes)
    assert WR._hub_token() == ""
    presentes["FORGE_TOKEN_WEBHUB"] = _PROPRE
    assert WR._hub_token() == _PROPRE, (
        "un coffre vide a ete mis en cache : l'interface reste muette meme "
        "apres le semis")
