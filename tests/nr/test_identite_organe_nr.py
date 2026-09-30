"""NR -- doctrine RBAC anatomique : chaque organe porte son propre marqueur.

Directive owner du 2026-09-02 : respecter l'analogie du corps dans la
hierarchie des organes vis-a-vis du RBAC, et savoir quel organe porte
l'authentification POUR QUI.

La reponse, et elle est structurante : **aucun organe n'authentifie pour un
autre**. Chaque cellule porte son CMH-I ; celle qui n'en exprime aucun se fait
eliminer, celle qui emprunte celui d'une voisine rend la chaine irremontable.
Ce qui est CENTRAL, c'est la VERIFICATION (le videur, ganglion du corps),
jamais l'emission d'identite.

Ces tests verrouillent trois choses :
1. le superviseur EXISTE comme identite declaree (une identite invisible au
   chargeur est une identite anonyme -- paye le 2026-08-05 sur ORGAN_PULSE,
   COAGULATION et RESCUE, qui recevaient 401) ;
2. son ring correspond a sa FONCTION dans le corps (il regule -> niveau des
   vitaux, comme TDR_SENTINEL, sans etre ring 0 qui reste l'owner) ;
3. la hierarchie ne derive pas : les hooks restent sans privilege.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REGISTRE = ROOT / "config" / "agent_identities.json"
SUPERVISEUR = ROOT / "proxy_deno" / "core" / "supervisor.ts"


@pytest.fixture(scope="module")
def agents() -> dict:
    d = json.loads(REGISTRE.read_text(encoding="utf-8"))
    ag = d.get("agents") or {}
    assert len(ag) > 100, "registre tronque : le reste du test serait vide de sens"
    return ag


def test_le_superviseur_a_une_identite_declaree(agents):
    """Sans entree au registre, il reste anonyme quoi qu'il envoie."""
    assert "SUPERVISOR" in agents


def test_le_ring_du_superviseur_suit_sa_fonction(agents):
    """Il REGULE les autres organes (spawn, arret, differe) : niveau des vitaux.
    Pas ring 0 -- celui-la reste l'owner."""
    s = agents["SUPERVISOR"]
    assert s["ring"] == 1, s["ring"]
    assert agents["TDR_SENTINEL"]["ring"] == 1, (
        "l'ancrage de comparaison a bouge : re-mesurer la hierarchie")


def test_le_superviseur_est_un_organe_pas_une_surface(agents):
    assert agents["SUPERVISOR"]["kind"] == "service"
    assert agents["SUPERVISOR"]["actor"] == "SUPERVISOR"


def test_l_identite_porte_sa_raison_anatomique(agents):
    """Un ring sans motif se relit comme arbitraire trois semaines plus tard."""
    s = agents["SUPERVISOR"]
    assert "organe" in s and len(s["organe"]) > 60
    assert "porte_son_propre_marqueur" in s


def test_aucun_hook_n_a_de_privilege(agents):
    """15 hooks, tous ring 4. Un hook qui monterait en privilege serait un
    chemin d'escalade invisible : il s'execute sur evenement, sans decision."""
    hooks = {n: v for n, v in agents.items() if v.get("kind") == "hook"}
    assert hooks, "plus aucun hook declare : verifier le registre"
    fautifs = {n: v["ring"] for n, v in hooks.items() if v.get("ring") != 4}
    assert not fautifs, "hooks avec privilege : %s" % fautifs


def test_le_ring_zero_reste_a_l_owner(agents):
    """Aucun organe ne doit s'attribuer le ring de la volonte."""
    r0 = [n for n, v in agents.items() if v.get("ring") == 0]
    assert not r0, "identites au ring 0 (reserve owner) : %s" % r0


# --------------------------------------------------------------------------- #
# Cote superviseur : il porte SON marqueur, pas celui du corps entier
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def src() -> str:
    return SUPERVISEUR.read_text(encoding="utf-8", errors="replace")


def test_le_superviseur_se_nomme_dans_ses_appels(src):
    assert 'LaForge-Agent-Name": "SUPERVISOR"' in src


def test_il_cherche_son_marqueur_propre_avant_le_master(src):
    """L'ordre compte : le master rend l'organe indiscernable dans le journal."""
    i_propre = src.find("FORGE_TOKEN_SUPERVISOR")
    i_master = src.find('Deno.env.get("FORGE_MCP_TOKEN") ?? ""\n  const token')
    assert i_propre > 0
    corps = src[src.find("function _hubAuthHeaders"):][:600]
    assert corps.index("FORGE_TOKEN_SUPERVISOR") < corps.index("FORGE_MCP_TOKEN"), (
        "le repli master est consulte avant le marqueur propre")


def test_le_marqueur_propre_est_charge_depuis_le_coffre(src):
    """Declare mais jamais charge = identite qui n'arrive jamais."""
    i = src.find("function _loadVaultToEnv")
    assert i > 0
    assert "FORGE_TOKEN_SUPERVISOR" in src[:i], (
        "le marqueur n'est pas dans la liste des clefs chargees du coffre")


def test_le_gate_de_ressource_s_identifie(src):
    """423 appels anonymes mesures avant correction : c'etait le plus gros flux
    sans identite du hub, alors que le mecanisme existait deja pour
    /admin/run_job."""
    i = src.find("/api/resource/should_spawn")
    assert i > 0
    assert "_hubAuthHeaders()" in src[i:i + 1600]


def test_la_telemetrie_s_identifie_aussi(src):
    import re

    # Ancrer sur le FETCH, pas sur la mention : la premiere occurrence de la
    # route est dans un commentaire, et un test qui la compte se declare rouge
    # sur de la prose.
    sites = list(re.finditer(r'fetch\("http://127\.0\.0\.1:8766/api/swarm/health"', src))
    assert len(sites) >= 2, "les deux sondes de telemetrie ont disparu"
    for m in sites:
        assert "_hubAuthHeaders()" in src[m.start():m.start() + 400], (
            "sonde de telemetrie anonyme a l'offset %d" % m.start())


def test_hub_auth_headers_est_au_niveau_module(src):
    """Defaut attrape par `deno check` le 2026-09-02 (TS2304 sur deux sites) :
    definie dans une portee locale, elle n'etait visible que du gate. Un
    parse-check ne l'aurait pas vu -- seul le type-check."""
    i_fn = src.find("function _hubAuthHeaders")
    i_gate = src.find("/api/resource/should_spawn")
    assert 0 < i_fn < i_gate, (
        "la definition doit preceder tous ses usages au niveau module")
    ligne = src[:i_fn].split("\n")[-1]
    assert ligne == "", "la fonction n'est pas en colonne 0 (portee locale ?)"


# --------------------------------------------------------------------------- #
# Recablage des organes : le marqueur PROPRE avant le maitre
# --------------------------------------------------------------------------- #

# Organes recables, et le fichier qui porte leur identite. Cette table grandit a
# mesure qu'on retire des passe-partout : au 2026-09-02, le journal montrait
# encore STATE_ENCODER et DENOHUBMCP au maitre (CLAUDE_HOOK et OPENAI_PROXY
# etaient designes par l'analyse statique mais n'avaient pas rappele -- leur
# silence ne les innocente pas).
# (agent, fichier, fonction qui CHOISIT le jeton). La fonction est nommee parce
# qu'une premiere version comparait les positions dans TOUT le fichier : chez le
# superviseur, la liste des clefs chargees du coffre mentionne le maitre bien
# avant la fonction de choix, et le test se declarait rouge sur un ordre qui
# n'avait aucun rapport avec la priorite de lecture.
ORGANES_RECABLES = {
    "STATE_ENCODER": (ROOT / "app" / "forge_state_encoder.py", "def _entetes_hub"),
    "SUPERVISOR": (ROOT / "proxy_deno" / "core" / "supervisor.ts",
                   "function _hubAuthHeaders"),
}


@pytest.mark.parametrize("agent,fichier,selecteur", sorted(
    (a, f, s) for a, (f, s) in ORGANES_RECABLES.items()))
def test_l_organe_cherche_son_marqueur_avant_le_maitre(agent, fichier, selecteur):
    """L'ORDRE est la seule chose qui compte ici : le maitre est un
    passe-partout (son porteur peut se declarer un autre agent et heriter de son
    ring), le derive non. Le consulter en premier annulerait le recablage sans
    qu'aucun test ne rougisse."""
    src = fichier.read_text(encoding="utf-8", errors="replace")
    i = src.find(selecteur)
    assert i > 0, "selecteur %r introuvable : la mesure n'est plus verifiable" % selecteur
    # Fenetre LARGE : une version a 1200 caracteres a rougi le jour meme ou j'ai
    # documente la fonction. Un test a fenetre etroite punit la documentation,
    # et un test qui punit finit desactive. Troisieme occurrence du motif
    # aujourd'hui -- ancrer sur la portee, pas sur un nombre d'octets.
    corps = src[i:i + 3000]
    propre = "FORGE_TOKEN_%s" % agent
    assert propre in corps, "%s ne cherche pas son marqueur propre" % agent
    i_maitre = corps.find("FORGE_MCP_TOKEN")
    if i_maitre >= 0:
        assert corps.find(propre) < i_maitre, (
            "%s consulte le maitre AVANT son marqueur propre" % agent)


@pytest.mark.parametrize("agent,fichier", sorted(
    (a, f) for a, (f, _s) in ORGANES_RECABLES.items()))
def test_l_organe_se_nomme(agent, fichier):
    """Nommer n'autorise pas -- un nom sans jeton apparie tombe au plancher --
    mais sans le nom, la trace ne remonte pas jusqu'a l'organe."""
    src = fichier.read_text(encoding="utf-8", errors="replace")
    assert ('"LaForge-Agent-Name": "%s"' % agent) in src, agent


def test_les_organes_recables_sont_declares_au_registre(agents):
    for agent in ORGANES_RECABLES:
        assert agent in agents, (
            "%s porte une identite qu'aucun registre ne declare : elle sera "
            "traitee comme anonyme" % agent)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
