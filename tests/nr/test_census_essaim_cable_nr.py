# -*- coding: utf-8 -*-
"""NR — l'essaim free tier est CÂBLÉ : le census produit le registre des membres vivants, l'essaim le lit.

__FORGE_COLOR__ = "immunitaire/guard : non-regression du cablage census -> essaim free tier"

CE QUI A ÉTÉ PAYÉ (21/10, job_84f9ed8ef8fc). Demande owner : « swarm via le LLM cloud en free tier, avec census au
préalable ». Les briques existaient et passaient leurs tests (tests/nr/test_census_essaim_cloud_nr.py : porteurs_du_proxy,
membres_essaim, sonder_essaim, ecrire_membres_vivants, membres_par_defaut) -- mais AUCUN point d'entrée ne les appelait :
dette de câblage, un mécanisme présent n'est pas un effet. Claude a donc lancé l'essaim sur les clés `verdicts` du
census, qui sont RECOPIÉES du registre précédent (périmées) et nommées `fournisseur:modèle` (`openrouter`, `zai`),
noms qu'ask() ne connaît pas : 6 membres sur 8 en « Provider inconnu ».
Contrat :
- `forge_free_tier_census.candidats_frais(doc)` -> {fournisseur: [modèles]} pris des SEULES preuves fraîches
  (`fournisseurs[].preuves`, joignable vrai), jamais de `verdicts` ;
- `forge_free_tier_census.py --essaim` : candidats frais -> porteurs du proxy (`_registre_proxy()`) -> membres
  `porteur:modèle` -> sondés par ask (`_ask_essaim`) -> `REGISTRE_ESSAIM` ; les fournisseurs sans porteur sont DITS ;
- `forge_cli_swarm.py "<tâche>"` sans liste de membres lit `REGISTRE` (le même fichier) par membres_par_defaut, et DIT
  la raison quand il retombe sur la liste historique.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _charger(monkeypatch, nom):
    spec = importlib.util.spec_from_file_location(nom + "_cable_nr", ROOT / "tools" / (nom + ".py"))
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, nom + "_cable_nr", mod)
    spec.loader.exec_module(mod)
    return mod


DOC = {
    "horodatage": "2026-10-21T15:33:37",
    "fournisseurs": [
        {"fournisseur": "openrouter", "preuves": [{"modele": "frais:free", "joignable": True, "motif": ""},
                                                 {"modele": "mort:free", "joignable": False, "motif": "HTTP 404"}]},
        {"fournisseur": "inconnu_du_proxy", "preuves": [{"modele": "x", "joignable": True, "motif": ""}]},
        {"fournisseur": "groq", "code": 401, "etat": "NON_MESURE"},
    ],
    "verdicts": {"openrouter:perime": {"etat": "OK"}, "zai:glm-perime": {"etat": "OK"}},
}


class _P:
    def __init__(self, url):
        self.base_url = url


def test_candidats_frais_ignorent_les_verdicts_recopies(monkeypatch):
    ft = _charger(monkeypatch, "forge_free_tier_census")
    c = ft.candidats_frais(DOC)
    assert c.get("openrouter") == ["frais:free"], c
    assert "perime" not in json.dumps(c), "un verdict RECOPIE du registre precedent a ete pris pour une preuve fraiche"


def test_candidats_frais_prennent_les_verdicts_cibles_horodates_frais(monkeypatch):
    """21/10 suite : les MEILLEURES mesures du jour sont les passes --cible (verdicts horodates `mesure_le`) ; un
    verdict JOIGNABLE de moins de 6 h est une preuve fraiche, un verdict sans horodatage ou trop vieux ne l'est pas."""
    ft = _charger(monkeypatch, "forge_free_tier_census")
    maintenant = time.mktime(time.strptime("2026-10-21T18:00:00", "%Y-%m-%dT%H:%M:%S"))
    doc = {"fournisseurs": [], "verdicts": {
        "groq:openai/gpt-oss-120b": {"joignable": True, "mesure_le": "2026-10-21T16:30:00"},
        "mistral:codestral-2508": {"joignable": True, "mesure_le": "2026-10-21T08:00:00"},  # 10 h : perime
        "zai:glm-4.7-flash": {"joignable": False, "mesure_le": "2026-10-21T17:00:00"},
        "openrouter:sans-date": {"joignable": True}}}
    c = ft.candidats_frais(doc, maintenant=maintenant)
    assert c == {"groq": ["openai/gpt-oss-120b"]}, c


def test_un_membre_ko_dit_pourquoi(monkeypatch, tmp_path, capsys):
    """21/10 : `--essaim` reel = 13/14 OK, et RIEN ne disait pourquoi le 14e (zai_glm_flash) etait ecarte ; rejoue
    a la main il repondait. La raison (erreur rendue, ou type d'exception) est gardee au verdict et imprimee."""
    ft = _charger(monkeypatch, "forge_free_tier_census")

    async def faux_ask(provider, task, **k):
        if provider == "lent":
            raise TimeoutError("trop long")
        return {"ok": False, "text": "", "error": "HTTP 429 concurrency"}

    v = asyncio.run(ft.sonder_essaim(["zai_glm_flash:glm-4.5-flash", "lent:m"], faux_ask))
    assert "429" in v["zai_glm_flash:glm-4.5-flash"]["raison"], v
    assert v["lent:m"]["etat"] == "INDETERMINE" and "TimeoutError" in v["lent:m"]["raison"], v


def test_les_porteurs_se_trouvent_dans_le_VRAI_registre_du_proxy(monkeypatch):
    """21/10, `--essaim` reel : 0 membre, groq/openrouter/mistral/ollama/zai « sans porteur ». Aucun des 41 providers
    du proxy n'expose son URL : l'appariement par hote ne trouve RIEN dans le vrai registre -- son NR passait sur un
    faux registre muni de base_url. Repli : table DECLAREE fournisseur -> providers, filtree sur les noms presents."""
    ft = _charger(monkeypatch, "forge_free_tier_census")
    registre = ft._registre_proxy()
    porteurs = ft.porteurs_du_proxy(registre, ft.SURFACES)
    for fournisseur in ("groq", "openrouter", "mistral", "zai", "ollama"):
        assert porteurs.get(fournisseur), "aucun porteur pour %s dans le vrai registre : %s" % (fournisseur, porteurs)
        assert all(nom in registre for nom in porteurs[fournisseur]), porteurs[fournisseur]


def test_cli_essaim_ecrit_le_registre_des_membres_vivants(monkeypatch, tmp_path, capsys):
    ft = _charger(monkeypatch, "forge_free_tier_census")
    census = tmp_path / "free_tier_census.json"
    census.write_text(json.dumps(DOC), encoding="utf-8")
    registre = tmp_path / "swarm_membres_vivants.json"
    monkeypatch.setattr(ft, "SORTIE", census)
    monkeypatch.setattr(ft, "REGISTRE_ESSAIM", registre)
    monkeypatch.setattr(ft, "SURFACES", [("openrouter", None, "https://openrouter.ai/api/v1"),
                                         ("inconnu_du_proxy", None, "https://nulle-part.example/v1")])
    monkeypatch.setattr(ft, "_registre_proxy", lambda: {"openrouter_free": _P("https://openrouter.ai/api/v1")})
    vus = []

    async def faux_ask(provider, task, **k):
        vus.append((provider, k.get("model")))
        return {"ok": True, "text": "OK"}

    monkeypatch.setattr(ft, "_ask_essaim", faux_ask)
    monkeypatch.setattr(sys, "argv", ["forge_free_tier_census.py", "--essaim"])
    assert ft.main() == 0
    doc = json.loads(registre.read_text(encoding="utf-8"))
    assert doc["membres_ok"] == ["openrouter_free:frais:free"], doc
    assert ("openrouter_free", "frais:free") in vus, vus
    assert "inconnu_du_proxy" in capsys.readouterr().out, "un fournisseur sans porteur doit etre DIT"


def test_essaim_sans_membres_lit_le_registre(monkeypatch, tmp_path):
    cs = _charger(monkeypatch, "forge_cli_swarm")
    registre = tmp_path / "swarm_membres_vivants.json"
    registre.write_text(json.dumps({"membres_ok": ["groq:openai/gpt-oss-20b"], "mesure_le": time.time()}),
                        encoding="utf-8")
    monkeypatch.setattr(cs, "REGISTRE", registre)
    pris = []

    async def faux_swarm(task, members, *a, **k):
        pris.append(list(members))
        return {"answers": [], "synthesis": ""}

    monkeypatch.setattr(cs, "swarm", faux_swarm)
    monkeypatch.setattr(cs, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["forge_cli_swarm.py", "une tache"])
    assert cs.main() == 0
    assert pris == [["groq:openai/gpt-oss-20b"]], pris


def test_essaim_sans_registre_dit_pourquoi_il_retombe(monkeypatch, tmp_path, capsys):
    cs = _charger(monkeypatch, "forge_cli_swarm")
    monkeypatch.setattr(cs, "REGISTRE", tmp_path / "absent.json")

    async def faux_swarm(task, members, *a, **k):
        return {"answers": [], "synthesis": ""}

    monkeypatch.setattr(cs, "swarm", faux_swarm)
    monkeypatch.setattr(cs, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["forge_cli_swarm.py", "une tache"])
    assert cs.main() == 0
    assert "registre absent" in capsys.readouterr().out
