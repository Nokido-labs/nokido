# -*- coding: utf-8 -*-
"""NR — `hub action=demander_ordre` : l'accord de l'owner passe par SON dialogue, jamais par l'agent.

Owner 2026-09-29 : « je ne vais pas taper des commandes admin a chaque fois pour les
communications » et « tailscale par le tray oui ». Une porte generique (derogation unique sur
le registre critique) route vers app/forge_ordres_bureau.py :
- ordres du TRAY (Tailscale) : question par elicitation, depot sur ACCEPTE ; statut sans question ;
- ordres du HUB (pairs) : question, puis execution avec une PREUVE a usage unique, qui ne vit
  qu'en memoire du hub -- un processus qui l'invente trouve un registre vide.
"""
import asyncio
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def ob(monkeypatch, tmp_path):
    import sys
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app import forge_ordres_bureau as m
    monkeypatch.setattr(m, "JOURNAL", tmp_path / "ordres.jsonl")
    m._ORDRES.clear()
    m._PREUVES.clear()
    return m


def _confirmer(etat, appels):
    async def f(titre, detail):
        appels.append((titre, detail))
        return {"etat": etat}
    return f


def test_un_ordre_inconnu_est_refuse_et_dit(ob):
    r = asyncio.run(ob.demander_ordre("CLAUDE", "formater-le-disque", confirmer=_confirmer("ACCEPTE", [])))
    assert r["etat"] == ob.REFUSE and "inconnu" in r["raison"]


def test_le_statut_tailscale_part_sans_question(ob):
    appels = []
    r = asyncio.run(ob.demander_ordre("CLAUDE", "tailscale-statut", confirmer=_confirmer("ACCEPTE", appels)))
    assert r["etat"] == ob.DEPOSE and not appels, "une lecture seule ne doit pas questionner l'owner"


def test_ouvrir_le_funnel_exige_ACCEPTE(ob):
    appels = []
    r = asyncio.run(ob.demander_ordre("CLAUDE", "funnel-ouvrir", confirmer=_confirmer("REFUSE", appels)))
    assert appels and r.get("depose") is False and not ob.en_attente()
    r = asyncio.run(ob.demander_ordre("CLAUDE", "funnel-ouvrir", confirmer=_confirmer("ACCEPTE", appels)))
    assert r["etat"] == ob.DEPOSE and [o["action"] for o in ob.en_attente()] == ["funnel-ouvrir"]


def test_la_preuve_ne_vaut_qu_une_fois_et_pour_sa_cible(ob):
    p = ob.emettre_preuve("pair-approuver", "pair_x")
    assert not ob.consommer_preuve(p, "pair-approuver", "pair_AUTRE"), "cible differente acceptee"
    p = ob.emettre_preuve("pair-approuver", "pair_x")
    assert not ob.consommer_preuve(p, "pair-repondre", "pair_x"), "ordre different accepte"
    p = ob.emettre_preuve("pair-approuver", "pair_x")
    assert ob.consommer_preuve(p, "pair-approuver", "pair_x")
    assert not ob.consommer_preuve(p, "pair-approuver", "pair_x"), "preuve reutilisee"
    p = ob.emettre_preuve("pair-approuver", "pair_x", maintenant=0.0)
    assert not ob.consommer_preuve(p, "pair-approuver", "pair_x"), "preuve echue acceptee"
    assert not ob.consommer_preuve("accord-invente", "pair-approuver", "pair_x")


def test_pair_approuver_n_execute_qu_apres_ACCEPTE_avec_une_preuve_valide(ob, monkeypatch):
    vus = []

    class FausseQuarantaine:
        def lister(self):
            return [{"id": "pair_x", "de": "PAIR:c", "methode": "pair.soumettre_tache", "genre": "executer",
                     "intent": "HANDOFF_NEXT", "destinataire": "CLAUDE", "texte_externe": "bonjour"}]

        def approuver(self, ident, preuve=""):
            vus.append(ob.consommer_preuve(preuve, "pair-approuver", ident))
            return {"ok": vus[-1]}

    monkeypatch.setattr(ob, "_quarantaine", lambda: FausseQuarantaine())
    appels = []
    r = asyncio.run(ob.demander_ordre("CLAUDE", "pair-approuver", cible="pair_x", confirmer=_confirmer("REFUSE", appels)))
    assert r.get("depose") is False and not vus, "execute sans ACCEPTE"
    assert "PAIR:c" in appels[0][1] and "bonjour" in appels[0][1], "l'owner doit voir ce qu'il approuve"
    r = asyncio.run(ob.demander_ordre("CLAUDE", "pair-approuver", cible="pair_x", confirmer=_confirmer("ACCEPTE", appels)))
    assert r["etat"] == "EXECUTE" and vus == [True]


def test_la_quarantaine_refuse_une_preuve_inventee(ob):
    q = _charger("forge_pair_quarantaine_nr_preuve", ROOT / "tools" / "forge_pair_quarantaine.py")
    r = q.approuver("pair_inexistant", preuve="accord-invente")
    assert r["ok"] is False and "preuve" in r["erreur"]
    r = q.repondre("client", "commit:abc", "OK_DONE", "texte", preuve="accord-invente")
    assert r["ok"] is False and "preuve" in r["erreur"]


def test_le_tray_et_le_lanceur_connaissent_chaque_ordre_du_tray():
    """Le tray n'invente rien : chaque ordre depose doit etre une action du tray ET du lanceur."""
    import sys
    sys.path.insert(0, str(ROOT))
    from nokido_agent.app.forge_ordres_bureau import ACTIONS
    import ast
    arbre = ast.parse((ROOT / "tools" / "nokido_tray.py").read_text(encoding="utf-8"))
    actions_tray = next(set(ast.literal_eval(n.value)) for n in arbre.body if isinstance(n, ast.Assign)
                        and any(getattr(c, "id", "") == "ACTIONS_PANNEAU" for c in n.targets))
    lanceur = (ROOT / "tools" / "nokido_launcher.py").read_text(encoding="utf-8")
    actions_lanceur = set(re.findall(r'^\s+"([\w-]+)":\s*lambda', lanceur, re.M))
    for a in ACTIONS:
        assert a in actions_tray, "%s : ordre deposable que le tray ignorerait" % a
        assert a in actions_lanceur, "%s : action inconnue du lanceur" % a


def test_le_registre_route_demander_ordre():
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    assert '"demander_ordre",' in src and "_ob.demander_ordre(" in src, "porte demander_ordre non cablee"
    elic = (ROOT / "app" / "forge_mcp_elicitation.py").read_text(encoding="utf-8")
    assert '"demander_ordre"' in elic, "demander_ordre ne peut pas questionner l'owner"
