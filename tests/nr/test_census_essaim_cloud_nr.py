"""NR -- le census interroge TOUS les endpoints de l'essaim cloud, via chaque provider parametre (owner 19/10).

Constat sur piece (19/10) : `forge_free_tier_census` ne sondait qu'un ECHANTILLON par fournisseur (5 preuves
pour 30 gratuits annonces, 984 declares) et `forge_cli_swarm` tirait ses membres d'une liste EN DUR
(claude_cli, gemini_cli, groq, cerebras), sans lien avec le census. Un essaim ne s'assigne que sur des couples
provider:modele PROUVES vivants par un census frais.

Chemin REEL de l'essaim : `forge_cli_swarm._one` -> `forge_agent_proxy.ask(provider, model=<id brut>)` sur le
registre `_PROVIDERS` du PROXY (pas celui du routeur : 1re version de ce RED corrigee le 19/10, elle visait
forge_llm_router.PROVIDERS que l'essaim n'emprunte pas).

Contrat :
  * `porteurs_du_proxy(registre, surfaces)` : un fournisseur du census est PORTE par les providers du proxy qui
    parlent au meme HOTE d'API (base_url du provider ou de son client) ;
  * `membres_essaim(candidats, porteurs)` : chaque modele candidat devient un membre `porteur:id_brut` (le premier
    porteur par nom) ; un fournisseur sans porteur est NOMME (`sans_porteur`), jamais tu ;
  * `sonder_essaim(membres, ask_fn)` : sonde chaque membre par ask et classe OK / VIDE / KO / INDETERMINE
    (liste blanche de forge_cli_swarm._classer) ;
  * `ecrire_membres_vivants` : seuls les OK sont membres ; registre horodate ;
  * `forge_cli_swarm.membres_par_defaut` : registre frais -> ses membres OK ; absent / perime / vide -> la liste
    historique ET la raison.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import forge_free_tier_census as ft  # noqa: E402
import forge_cli_swarm as cs  # noqa: E402

SURFACES = [
    ("groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1"),
    ("mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    ("cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1"),
]
REGISTRE = {
    "groq": NS(base_url="https://api.groq.com/openai/v1"),
    "mistral": NS(client=NS(base_url="https://api.mistral.ai/v1/")),
    "mistral_codestral": NS(base_url="https://api.mistral.ai/v1"),
    "ollama": NS(base_url="http://127.0.0.1:11434/v1"),
    "sans_url": NS(),
}


def test_un_fournisseur_est_porte_par_les_providers_du_meme_hote():
    p = ft.porteurs_du_proxy(REGISTRE, SURFACES)
    assert p == {"groq": ["groq"], "mistral": ["mistral", "mistral_codestral"]}


def test_chaque_modele_gratuit_devient_un_membre_et_le_sans_porteur_est_nomme():
    porteurs = {"groq": ["groq"], "mistral": ["mistral", "mistral_codestral"]}
    candidats = {"groq": ["openai/gpt-oss-20b", "llama-3.1-8b"],
                 "mistral": ["codestral-latest"], "cerebras": ["llama3.1-8b"]}
    r = ft.membres_essaim(candidats, porteurs)
    assert sorted(r["membres"]) == sorted(["groq:openai/gpt-oss-20b", "groq:llama-3.1-8b",
                                           "mistral:codestral-latest"])
    assert r["sans_porteur"] == ["cerebras"]


def test_la_sonde_passe_par_ask_et_classe_en_liste_blanche():
    reponses = {
        "groq:openai/gpt-oss-20b": {"ok": True, "text": "pong"},
        "groq:llama-3.1-8b": {"ok": True, "text": ""},
        "mistral:codestral-latest": {"ok": True, "text": "[ERR mistral] HTTP Error 429"},
        "mistral:ministral-8b-latest": {"ok": False, "text": "", "error": "timeout"},
    }
    appels = []

    async def faux_ask(provider, tache, **kw):
        membre = "%s:%s" % (provider, kw.get("model"))
        appels.append(membre)
        return reponses[membre]

    v = asyncio.run(ft.sonder_essaim(list(reponses), faux_ask))
    assert sorted(appels) == sorted(reponses)
    assert {m: x["etat"] for m, x in v.items()} == {
        "groq:openai/gpt-oss-20b": "OK", "groq:llama-3.1-8b": "VIDE",
        "mistral:codestral-latest": "KO", "mistral:ministral-8b-latest": "KO",
    }


def test_seuls_les_ok_sont_membres_et_le_swarm_les_lit(tmp_path):
    chemin = tmp_path / "swarm_membres_vivants.json"
    ft.ecrire_membres_vivants({"a:c": {"etat": "OK", "ms": 10}, "d:f": {"etat": "VIDE", "ms": 9}},
                              chemin, maintenant=1000.0)
    doc = json.loads(chemin.read_text(encoding="utf-8"))
    assert doc["membres_ok"] == ["a:c"]
    membres, raison = cs.membres_par_defaut(chemin, maintenant=1000.0 + 60)
    assert membres == ["a:c"] and raison == ""


def test_registre_absent_ou_perime_repli_dit(tmp_path):
    chemin = tmp_path / "swarm_membres_vivants.json"
    membres, raison = cs.membres_par_defaut(chemin, maintenant=1000.0)
    assert membres == cs.DEFAULT_MEMBERS and "absent" in raison
    ft.ecrire_membres_vivants({"a:c": {"etat": "OK", "ms": 10}}, chemin, maintenant=1000.0)
    membres, raison = cs.membres_par_defaut(chemin, maintenant=1000.0 + 7 * 3600, max_age_s=6 * 3600)
    assert membres == cs.DEFAULT_MEMBERS and "perime" in raison
