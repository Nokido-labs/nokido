"""Non-regression : la verite a UNE adresse -- tout nom du hub sait se router.

QUATRE registres de fournisseurs coexistent dans Nokido. Le 2026-09-02, cinq
passes d'arene ont ete perdues a interroger le mauvais : `forge_llm_router`
nomme par (fournisseur, modele) -- `gemini_flash`, `groq_fast` -- tandis que
`forge_agent_proxy.ask` nomme par famille -- `gemini`, `groq`. **3 noms communs
sur 39 et 33.** Ils ne divergeaient pas : ils etaient quasi disjoints.

Le cout n'etait pas l'echec, c'etait le MESSAGE : `Provider 'X' inconnu` se lit
comme « ce fournisseur est mort », alors qu'il dit « tu parles la mauvaise
langue ». J'ai enterre groq, mistral et together_ai sur ce malentendu.

Ce test ne fusionne rien -- il exige que le mapping reste COMPLET. Une entree
ajoutee d'un cote sans alias fait rougir la CI, au lieu de couter trois passes
a la prochaine session.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
for sous in ("app", "tools"):
    if str(ROOT / sous) not in sys.path:
        sys.path.insert(0, str(ROOT / sous))

import forge_provider_alias as fpa  # noqa: E402


@pytest.fixture(scope="module")
def diag():
    d = fpa.diagnostic()
    if d.get("etat") != "MESURE":
        pytest.skip("registres illisibles ici : %s -- l'essai n'est pas MENE, "
                    "ce qui n'est pas un succes" % d.get("raison"))
    return d


# --------------------------------------------------------------------------- #
# L'invariant : aucun nom orphelin, d'aucun cote
# --------------------------------------------------------------------------- #

def test_tout_nom_du_hub_sait_se_router(diag):
    """LE garde. Une entree du hub sans alias est un appel qui echouera loin de
    sa cause, avec un message qui accuse le fournisseur."""
    assert diag["non_mappes"] == [], (
        "ces entrees du registre hub ne savent pas se router vers ask() : %s. "
        "Ajouter leur alias dans forge_provider_alias.ALIAS." % diag["non_mappes"])


def test_aucun_alias_ne_pointe_vers_le_vide(diag):
    """Un alias vers un nom inexistant est pire qu'une absence d'alias : il
    donne l'illusion du cablage."""
    assert diag["alias_casses"] == [], diag["alias_casses"]


def test_aucun_alias_ne_survit_a_son_entree(diag):
    """Un alias orphelin signale une entree hub supprimee -- a nettoyer, sinon la
    table ment sur ce qui existe."""
    assert diag["alias_orphelins"] == [], diag["alias_orphelins"]


# --------------------------------------------------------------------------- #
# La resolution elle-meme
# --------------------------------------------------------------------------- #

def test_un_nom_deja_executable_se_resout_en_lui_meme():
    assert fpa.resoudre("gemini") == "gemini"
    assert fpa.resoudre("groq") == "groq"


def test_un_nom_du_hub_se_resout_vers_le_nom_executable():
    """Le cas exact qui a coute cinq passes."""
    assert fpa.resoudre("gemini_flash") == "gemini"
    assert fpa.resoudre("groq_fast") == "groq"
    assert fpa.resoudre("mistral_small") == "mistral"
    assert fpa.resoudre("xai_grok3") == "grok"


def test_ask_resout_les_noms_du_hub_par_la_table_si_le_modele_est_tenu():
    """Chemin REEL (2026-09-24). La table etait branchee nulle part ; la brancher SANS controle
    transformait un echec bruyant en substitution SILENCIEUSE (owner : « gemini-flash-lite-latest
    via provider n'est pas le modele fort atteignable via le cli agy »). Mesure du jour : la cible
    d'un alias repond avec son modele PAR DEFAUT (github_codestral -> gpt-4o)."""
    from nokido_agent.app import forge_agent_proxy as fap

    assert fap.get_provider("groq_fast") is fap.get_provider("groq") is not None, "resolution FIDELE accordee"
    assert fap.get_provider("github_codestral") is None, "substitution de modele refusee"
    assert "substitution refusee" in fap._raison_alias("github_codestral")
    assert fap.get_provider("provider_totalement_invente") is None


def test_les_noms_gemini_trompeurs_sont_refuses_sans_supposer_la_surface():
    """Owner : « Nokido devrait dans sa version dist savoir utiliser la surface presente ». La raison
    ne nomme pas la surface de l'owner : elle CALCULE les surfaces agents presentes sur la machine."""
    from nokido_agent.app import forge_agent_proxy as fap

    for nom in ("gemini_flash", "gemini_pro"):
        assert fap.get_provider(nom) is None, "%s servirait flash-lite en silence" % nom
        raison = fap._raison_alias(nom)
        assert "surfaces agents presentes ici" in raison and "gemini_flash_lite" in raison
    assert "AGY" not in "".join(fpa.NOMS_TROMPEURS.values()), "aucune surface d'owner ecrite en dur"
    assert fap.get_provider("gemini_flash_lite") is not None, "le nom HONNETE de flash-lite reste servi"


def test_surfaces_agents_calculees_et_sonde_illisible_comptee(monkeypatch):
    from nokido_agent.app import forge_agent_proxy as fap

    class _P:
        def __init__(self, etat):
            self.etat = etat

        def is_available(self):
            if self.etat == "leve":
                raise NameError("get_secret")
            return self.etat

    monkeypatch.setattr(fap, "_PROVIDERS", {"a_cli": _P(True), "b_cli": _P(False), "c_cli": _P("leve"),
                                            "groq": _P(True)})
    s = fap._surfaces_agents_presentes()
    assert "a_cli" in s and "b_cli" not in s and "groq" not in s and "1 sonde(s) illisible(s)" in s
    monkeypatch.setattr(fap, "_PROVIDERS", {})
    assert "aucune detectee" in fap._surfaces_agents_presentes()


def test_normalisation_du_modele():
    assert fpa._queue_modele("openai/gpt-oss-120b") == "gpt-oss-120b"
    assert fpa._queue_modele("grok-3-mini-latest") == fpa._queue_modele("grok-3-mini")
    assert fpa._queue_modele("gpt-4o") != fpa._queue_modele("openai/gpt-4o-mini")


def test_un_nom_inconnu_rend_None_et_n_invente_RIEN():
    """Un alias plausible fabrique un appel qui echoue loin de sa cause.
    `nvidia_nemotron_super` -> `nvidia_nim` ne se DEVINE pas : il se declare."""
    assert fpa.resoudre("provider_totalement_invente") is None
    assert fpa.resoudre("gemini_ultra_9000") is None


def test_le_mapping_est_declare_et_non_deduit_par_prefixe():
    """Une regle de prefixe marcherait sur la plupart des cas et fabriquerait
    des erreurs silencieuses sur le reste."""
    assert fpa.ALIAS["nvidia_nemotron_super"] == "nvidia_nim", (
        "ce mapping ne se deduit d'aucun prefixe -- il doit rester explicite")
    assert fpa.ALIAS["lmstudio_native"] == "lmstudio"


# --------------------------------------------------------------------------- #
# La dette, nommee pour rester traitable
# --------------------------------------------------------------------------- #

def test_together_ai_est_desormais_CABLE(diag):
    """Il avait une clef et 7 modeles gratuits au catalogue, sans entree dans
    ask() : paye, disponible, inatteignable. Cable le 2026-09-02."""
    assert "together_ai" not in diag["absents_de_ask"]
    assert fpa.resoudre("together_ai") == "together_ai", (
        "together_ai n'est plus executable : le cablage a ete perdu")


def test_le_TROISIEME_etat_est_declare_clef_presente_mais_REFUSEE(diag):
    """Entre « joignable » et « non configure » il y a « la clef existe et le
    service la refuse ». Sans cette categorie on range ces cas en injoignable et
    on cherche la panne du mauvais cote -- j'ai enterre des fournisseurs entiers
    sur ce malentendu."""
    refusees = diag["clef_refusee"]
    assert "together_ai" in refusees, "401 mesure : le cablage est bon, la clef non"
    assert "grok" in refusees, "400 mesure sur XAI_API_KEY"
    for nom, motif in refusees.items():
        assert any(c.isdigit() for c in motif), (
            "%s : un etat de refus doit porter le CODE mesure, pas une impression"
            % nom)


def test_le_module_dit_qu_il_ne_fusionne_pas():
    """Garde de LECTURE : ce module DECLARE un mapping, il n'unifie pas les
    registres. Le croire unificateur ferait supprimer l'un des deux."""
    assert "NE FUSIONNE RIEN" in fpa.__doc__.upper()
