"""NR — roles agentiques : aucun role accorde sans epreuve reussie.

Les `use_case` disent qui repond ; les roles disent qui peut FAIRE quoi dans une
boucle d'agent. Sept roles existent dans Nokido et n'avaient jamais ete
confrontes aux modeles censes les tenir.

Ce qu'on protege ici : qu'un role reste refuse tant que la capacite n'est pas
prouvee. Le piege est toujours le meme, et il a coute la journee du 2026-08-18 :
une DECLARATION (« supporte les outils », « sait faire du JSON ») ne vaut pas une
mesure. Un modele qui repond « Bien sur ! Voici le JSON : {...} » casse un
parseur en production ; un modele qui commente sa classification au lieu de
rendre l'etiquette casse un routeur.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_agentic_roles_probe as A  # noqa: E402

ECHEC = {"reussi": False, "motif": "x", "secondes": 0.1}


def _resultats(verdict=False, etiquette=False, plan=False, exact=False, secondes=0.5):
    return {
        "verdict": {"reussi": verdict, "secondes": secondes},
        "etiquette": {"reussi": etiquette, "exact": exact, "secondes": secondes},
        "plan": {"reussi": plan, "secondes": secondes},
    }


# ── aucun role par defaut ────────────────────────────────────────────────────

def test_un_modele_qui_echoue_partout_ne_tient_aucun_role():
    assert A.roles_tenus(_resultats(), {}) == []


def test_le_verdict_structure_ouvre_REVIEWER():
    assert "REVIEWER" in A.roles_tenus(_resultats(verdict=True), {})


def test_le_plan_exploitable_ouvre_PLANNER():
    assert "PLANNER" in A.roles_tenus(_resultats(plan=True), {})


def test_une_etiquette_APPROXIMATIVE_n_ouvre_pas_ROUTER():
    """Reussir « en gros » ne suffit pas : un routeur a besoin du mot EXACT,
    sinon il faut un post-traitement que personne n'ecrira."""
    roles = A.roles_tenus(_resultats(etiquette=True, exact=False), {})
    assert "ROUTER" not in roles


def test_une_etiquette_exacte_et_rapide_ouvre_la_surveillance():
    roles = A.roles_tenus(_resultats(etiquette=True, exact=True, secondes=0.4), {})
    assert {"ROUTER", "SENTINEL", "MONITOR"} <= set(roles)


def test_une_etiquette_exacte_mais_LENTE_n_ouvre_pas_la_surveillance():
    """MONITOR tourne en boucle : a 5 s l'appel, il coute plus qu'il ne
    surveille."""
    roles = A.roles_tenus(_resultats(etiquette=True, exact=True, secondes=5.0), {})
    assert "ROUTER" in roles
    assert "SENTINEL" not in roles and "MONITOR" not in roles


def test_EXECUTOR_vient_de_la_mesure_d_outils_pas_d_une_declaration():
    """La capacite d'appel est LUE dans la table du routeur, ou elle a ete
    inscrite apres mesure — on ne la remesure pas, on ne la suppose pas."""
    assert "EXECUTOR" in A.roles_tenus(_resultats(), {"outils": True})
    assert "EXECUTOR" not in A.roles_tenus(_resultats(), {"outils": False})
    assert "EXECUTOR" not in A.roles_tenus(_resultats(), {})


def test_SUMMARIZER_exige_une_grande_fenetre():
    assert "SUMMARIZER" in A.roles_tenus(_resultats(), {"contexte": 262_144})
    assert "SUMMARIZER" not in A.roles_tenus(_resultats(), {"contexte": 8_192})


# ── severite de forme : ce qu'un agent recevrait vraiment ────────────────────

def test_un_json_encadre_de_texte_est_tolere_mais_signale():
    """On accepte la reponse, sans pretendre qu'elle etait propre : la colonne
    `propre` distingue le modele utilisable sans post-traitement."""
    assert A._json_dans('Voici : {"verdict": "ok"} merci') == {"verdict": "ok"}


def test_une_reponse_sans_json_ne_passe_pas():
    assert A._json_dans("Le code semble risque.") is None


def test_un_json_casse_ne_passe_pas():
    assert A._json_dans('{"verdict": "ok"') is None


def test_les_etiquettes_forment_un_ensemble_ferme():
    """Un ensemble ouvert rendrait le test de ROUTER ininterpretable."""
    assert "aucun" in A.ETIQUETTES and len(A.ETIQUETTES) >= 3


# ── deux artefacts de sonde, corriges le 2026-08-18 ─────────────────────────

def test_un_accent_ne_recale_pas_une_reponse_juste():
    """`qwen2.5-7b` a repondu « securité » et a ete compte en echec : le modele
    avait raison, c'est la reference qui etait ecrite sans accent."""
    assert A._sans_accents("securité") == "securite"
    assert A._sans_accents("LISIBILITÉ".lower()) == "lisibilite"


def test_la_fiche_est_celle_du_MODELE_pas_du_premier_slot_du_fournisseur():
    """Associer par prefixe donnait a `allam-2-7b` la fiche de `groq_fast`
    (outils: True) alors qu'allam REFUSE les outils : il heritait d'EXECUTOR,
    le role exact qu'un slot distinct devait lui interdire."""
    providers = {
        "groq_fast": {"models": ["groq/openai/gpt-oss-20b"], "outils": True},
        "groq_allam": {"models": ["groq/allam-2-7b"], "outils": False},
    }
    assert A.fiche_du_modele(providers, "groq", "allam-2-7b")["_slot"] == "groq_allam"
    assert A.fiche_du_modele(providers, "groq", "openai/gpt-oss-20b")["_slot"] == "groq_fast"


def test_un_modele_inconnu_de_la_table_n_herite_d_aucune_capacite():
    """Sans fiche, aucun role de capacite : l'absence de mesure n'est pas un
    laissez-passer."""
    providers = {"groq_fast": {"models": ["groq/openai/gpt-oss-20b"], "outils": True}}
    assert A.fiche_du_modele(providers, "groq", "modele-jamais-vu") == {}
    assert "EXECUTOR" not in A.roles_tenus(_resultats(), {})
