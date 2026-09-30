"""Non-regression : la politique de partage, et surtout ce qu'elle REFUSE.

Une seule question : « ai-je le droit de donner CETTE information a CE cerveau
pour CETTE tache ? ». Les cas qui protegent sont les refus -- un ALLOW isole ne
prouverait qu'une chose : que la fonction rend quelque chose.

L'invariant central, celui qui a motive le module : **la collaboration n'efface
jamais la sensibilite**. Une tache SWARM et CONFIDENTIAL reste confidentielle ;
si le pool confidentiel est vide, la reponse est REFUSE, pas « le moins mauvais ».
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_share_policy as sp  # noqa: E402

LOCAUX = ("llamacpp", "ollama", "lmstudio", "llamacpp_native", "llamacpp_python", "local")


# --------------------------------------------------------------------------- #
# L'invariant : collaboration n'est pas declassement
# --------------------------------------------------------------------------- #

def test_confidentiel_en_swarm_ne_part_pas_au_cloud_approuve():
    """LE cas qui justifie le module."""
    v = sp.preflight("CONFIDENTIAL", "SWARM")
    if v["decision"] == sp.ALLOW:
        assert all(p in LOCAUX for p in v["pool"]), (
            "une donnee CONFIDENTIAL est partie hors du local : %s" % v["pool"])
    else:
        assert "admissible" in v["raison"]


def test_secret_en_swarm_reste_local():
    v = sp.preflight("SECRET", "SWARM")
    assert v["decision"] == sp.ALLOW
    assert all(p in LOCAUX for p in v["pool"]), v["pool"]
    assert "gemini" not in v["pool"] and "groq" not in v["pool"]


def test_interne_en_swarm_ouvre_un_pool_plus_large():
    v = sp.preflight("INTERNAL", "SWARM")
    assert v["decision"] == sp.ALLOW
    assert any(p not in LOCAUX for p in v["pool"]), v["pool"]


def test_public_en_swarm_ouvre_le_catalogue():
    pub = sp.preflight("PUBLIC", "SWARM")
    inte = sp.preflight("INTERNAL", "SWARM")
    assert pub["decision"] == sp.ALLOW
    assert len(pub["pool"]) >= len(inte["pool"]), (pub["pool"], inte["pool"])


def test_prive_ne_partage_rien_meme_en_public():
    """PRIVATE borne par le HAUT : meme une donnee publique ne part pas."""
    v = sp.preflight("PUBLIC", "PRIVATE")
    assert v["decision"] == sp.ALLOW
    assert all(p in LOCAUX for p in v["pool"]), v["pool"]


# --------------------------------------------------------------------------- #
# Ne pas savoir n'est pas autoriser
# --------------------------------------------------------------------------- #

def test_classe_non_declaree_est_refusee():
    v = sp.preflight(None, "SWARM")
    assert v["decision"] == sp.REFUSE
    assert "NON DECLARE" in v["raison"]


def test_classe_inconnue_est_refusee_et_nommee():
    v = sp.preflight("TOP_SECRET_DEFENSE", "SWARM")
    assert v["decision"] == sp.REFUSE
    assert "inconnue" in v["raison"]


def test_collaboration_inconnue_est_refusee():
    v = sp.preflight("PUBLIC", "TOUT_LE_MONDE")
    assert v["decision"] == sp.REFUSE
    assert "inconnu" in v["raison"]


def test_politique_illisible_refuse_au_lieu_d_ouvrir(monkeypatch):
    """Un fichier absent ne doit jamais se lire comme « aucune restriction »."""
    monkeypatch.setattr(sp, "POLICY", ROOT / "config" / "_inexistant_.json")
    monkeypatch.setattr(sp, "_cache", None)
    v = sp.preflight("PUBLIC", "SWARM")
    assert v["decision"] == sp.REFUSE
    assert "illisible" in v["raison"]


# --------------------------------------------------------------------------- #
# Audience
# --------------------------------------------------------------------------- #

def test_selected_agents_sans_audience_est_refuse():
    """Une audience vide n'est pas un partage universel."""
    v = sp.preflight("INTERNAL", "SELECTED_AGENTS", audience=[])
    assert v["decision"] == sp.REFUSE
    assert "audience" in v["raison"]


def test_selected_agents_avec_audience_passe():
    v = sp.preflight("INTERNAL", "SELECTED_AGENTS", audience=["ANTIGRAVITY"])
    assert v["decision"] == sp.ALLOW
    assert v["audience"] == ["ANTIGRAVITY"]


# --------------------------------------------------------------------------- #
# Pool vide, exclusions, joignabilite
# --------------------------------------------------------------------------- #

def test_pool_vide_refuse_sans_repli():
    """Aucun fallback vers « le moins mauvais »."""
    v = sp.preflight("SECRET", "SWARM", providers_candidats=["gemini", "groq"])
    assert v["decision"] == sp.REFUSE
    assert v["pool"] == []
    assert v["exclus"], "les exclusions doivent etre NOMMEES"


def test_chaque_exclusion_porte_sa_raison():
    v = sp.preflight("INTERNAL", "SWARM", providers_candidats=["gemini", "zia_inconnu"])
    noms = {e["provider"] for e in v["exclus"]}
    assert "zia_inconnu" in noms
    for e in v["exclus"]:
        assert e.get("raison"), e


def test_autorise_mais_non_joignable_est_exclu_et_le_dit():
    """Autorise et joignable sont DEUX choses : l'exclusion doit dire laquelle manque."""
    v = sp.preflight("INTERNAL", "SWARM", providers_candidats=["gemini", "groq"],
                     joignables=["groq"])
    assert v["decision"] == sp.ALLOW
    assert v["pool"] == ["groq"]
    raisons = " ".join(e["raison"] for e in v["exclus"])
    assert "NON JOIGNABLE" in raisons


def test_tous_injoignables_donne_refuse():
    v = sp.preflight("INTERNAL", "SWARM", providers_candidats=["gemini"], joignables=[])
    assert v["decision"] == sp.REFUSE


# --------------------------------------------------------------------------- #
# Mode : mesurer avant d'armer
# --------------------------------------------------------------------------- #

def test_le_mode_par_defaut_observe_sans_bloquer(monkeypatch):
    """Armer d'emblee refuserait tout appelant qui ne declare pas sa classe --
    l'erreur exacte payee sur le M2M le 2026-09-01."""
    monkeypatch.delenv("LAFORGE_SHARE_POLICY_MODE", raising=False)
    assert sp.mode() == "shadow"
    assert sp.applique({"decision": sp.REFUSE}) is False


def test_le_mode_error_bloque_vraiment(monkeypatch):
    monkeypatch.setenv("LAFORGE_SHARE_POLICY_MODE", "error")
    assert sp.mode() == "error"
    assert sp.applique({"decision": sp.REFUSE}) is True
    assert sp.applique({"decision": sp.ALLOW}) is False


def test_un_mode_inconnu_retombe_sur_shadow(monkeypatch):
    """Une valeur fautive ne doit pas armer un blocage par accident."""
    monkeypatch.setenv("LAFORGE_SHARE_POLICY_MODE", "bloque-tout")
    assert sp.mode() == "shadow"


# --------------------------------------------------------------------------- #
# CABLAGE : un mecanisme present n'est pas un mecanisme appele
# --------------------------------------------------------------------------- #

def test_le_routeur_appelle_reellement_la_politique(monkeypatch):
    """Le motif « garde branche sur un signal que personne n'emet » a deja ete paye
    deux fois ici. On prouve donc l'APPEL, pas la presence du code."""
    import forge_swarm_router as sr

    vus = {}

    def _faux_preflight(dc, co, **kw):
        vus["appel"] = (dc, co, kw.get("audience"))
        return {"decision": sp.ALLOW, "pool": ["llamacpp"], "exclus": [],
                "raison": "test", "data_class": dc, "collaboration": co,
                "mode": "shadow"}

    monkeypatch.setattr(sp, "preflight", _faux_preflight)
    monkeypatch.setattr(sr, "authorize",
                        lambda **kw: {"allow": True, "ring": 2, "via": "test"})
    monkeypatch.setattr(sr, "router_call",
                        lambda **kw: {"ok": True, "text": "reponse", "provider": "llamacpp"})

    rep = sr.route_subtask("VIBE", "tache", token="t",
                           data_class="CONFIDENTIAL", collaboration="SWARM",
                           audience=["ANTIGRAVITY"])
    # L'audience arrive en TUPLE : le contexte est immuable (frozen dataclass), pour
    # qu'un maillon aval ne puisse pas elargir l'audience apres la decision.
    assert vus.get("appel") == ("CONFIDENTIAL", "SWARM", ("ANTIGRAVITY",)), vus
    assert rep["status"] == "ok"
    assert rep["partage"]["decision"] == sp.ALLOW


def test_en_mode_error_le_routeur_bloque_avant_d_appeler_le_provider(monkeypatch):
    """La preuve qui compte : le provider ne doit JAMAIS etre atteint."""
    import forge_swarm_router as sr

    appels = []
    monkeypatch.setenv("LAFORGE_SHARE_POLICY_MODE", "error")
    monkeypatch.setattr(sr, "authorize",
                        lambda **kw: {"allow": True, "ring": 2, "via": "test"})
    monkeypatch.setattr(sr, "router_call",
                        lambda **kw: appels.append(kw) or {"ok": True, "text": "x"})

    rep = sr.route_subtask("VIBE", "tache", token="t")  # aucune classe declaree
    assert rep["status"] == "error", rep
    assert "partage" in rep["reason"]
    assert appels == [], "le provider a ete appele malgre le refus"


def test_en_shadow_le_refus_n_empeche_pas_l_appel(monkeypatch):
    """Symetrique : en observation, on mesure sans couper le corps."""
    import forge_swarm_router as sr

    appels = []
    monkeypatch.delenv("LAFORGE_SHARE_POLICY_MODE", raising=False)
    monkeypatch.setattr(sr, "authorize",
                        lambda **kw: {"allow": True, "ring": 2, "via": "test"})
    monkeypatch.setattr(sr, "router_call",
                        lambda **kw: appels.append(kw) or {"ok": True, "text": "x"})

    rep = sr.route_subtask("VIBE", "tache", token="t")  # aucune classe declaree
    assert rep["status"] == "ok"
    assert len(appels) == 1
    assert rep["partage"]["decision"] == sp.REFUSE, (
        "la decision doit etre CALCULEE meme quand elle n'est pas appliquee")


def test_les_champs_de_politique_ne_fuient_pas_vers_le_provider(monkeypatch):
    """`data_class` & co ne doivent pas partir dans les kwargs de router_call."""
    import forge_swarm_router as sr

    recus = {}
    monkeypatch.setattr(sr, "authorize",
                        lambda **kw: {"allow": True, "ring": 2, "via": "test"})

    def _rc(**kw):
        recus.update(kw)
        return {"ok": True, "text": "x"}

    monkeypatch.setattr(sr, "router_call", _rc)
    sr.route_subtask("VIBE", "tache", token="t", data_class="PUBLIC",
                     collaboration="SWARM", audience=["X"], max_tokens=32)
    for interdit in ("data_class", "collaboration", "audience"):
        assert interdit not in recus, interdit
    assert recus.get("max_tokens") == 32, "les kwargs legitimes doivent passer"


# --------------------------------------------------------------------------- #
# Contexte de requete : ABSENT, INCONNU et CLASSE sont TROIS etats
# --------------------------------------------------------------------------- #

def test_contexte_absent_et_contexte_inconnu_ne_se_confondent_pas():
    """Sans cette distinction, impossible de mesurer la progression du cablage :
    « personne ne m'a instrumente » et « je ne sais pas classer » appellent des
    actions differentes, meme si les deux refusent."""
    absent = sp.preflight_contexte(None)
    legacy = sp.preflight_contexte(sp.contexte_legacy(provenance="p"))
    assert absent["contexte"] == "ABSENT"
    assert legacy["contexte"] == "PRESENT_MAIS_INCONNU"
    assert absent["decision"] == legacy["decision"] == sp.REFUSE


def test_un_contexte_classe_est_reconnu_instrumente():
    ctx = sp.SwarmRequestContext(identity="VIBE", data_class="INTERNAL",
                                 collaboration="SWARM")
    assert ctx.est_instrumente() is True
    v = sp.preflight_contexte(ctx)
    assert v["contexte"] == "PRESENT"
    assert v["decision"] == sp.ALLOW


def test_le_contexte_est_immuable():
    """Un maillon aval ne doit pas pouvoir elargir l'audience APRES la decision."""
    ctx = sp.SwarmRequestContext(audience=("VIBE",))
    with pytest.raises(Exception):
        ctx.audience = ("VIBE", "TOUT_LE_MONDE")  # type: ignore[misc]


def test_le_contexte_legacy_ne_porte_aucune_valeur_permissive():
    ctx = sp.contexte_legacy(identity="X")
    assert ctx.data_class == sp.INCONNU
    assert ctx.collaboration == sp.INCONNU
    assert ctx.audience == ()


def test_le_resume_ne_porte_pas_de_contenu():
    """Le canal transporte des METADONNEES et un pointeur, jamais la charge utile."""
    ctx = sp.SwarmRequestContext(identity="VIBE", data_class="SECRET",
                                 provenance="bb:zone/cle")
    r = ctx.resume()
    assert r["provenance"] == "bb:zone/cle"
    assert not any(isinstance(v, str) and len(v) > 200 for v in r.values())


def test_chaque_chemin_connu_transmet_bien_un_contexte(monkeypatch):
    """Etape 5 du mandat : l'appel via CHAQUE chemin, pas seulement route_subtask.

    On instrumente le point de convergence lui-meme : c'est l'EFFET final qui est
    verifie, pas le fait qu'une fonction intermediaire ait ete polie.
    """
    import forge_llm_router as llm

    recu = {}

    class _FauxRouteur:
        def call(self, prompt, use_case, max_tokens, **kw):
            return {"ok": True, "text": "x"}

    monkeypatch.setattr(llm, "get_router", lambda: _FauxRouteur())

    def _sonde(prompt, use_case="general", max_tokens=500, context=None, **kw):
        recu["context"] = context
        return {"ok": True, "text": "x"}

    # forge_router_gateway.generate
    import forge_router_gateway as gw
    monkeypatch.setattr(gw, "router_call", _sonde, raising=False)

    # La verification structurelle vaut pour les 4 chemins : chacun importe
    # `contexte_legacy` et le passe en `context=`. La cartographie AST
    # (test_share_policy_couverture_nr) le prouve pour les 5 sans les executer,
    # ce qui evite de faire tourner des chemins qui touchent le reseau.
    from pathlib import Path as _P
    racine = _P(__file__).resolve().parent.parent.parent / "app"
    for f in ("forge_handoff.py", "forge_internal_sampling.py",
              "forge_router_gateway.py", "mcp_server_tools.py"):
        src = (racine / f).read_text(encoding="utf-8", errors="replace")
        assert "context=_ctx_legacy(" in src, f


def test_le_verdict_porte_de_quoi_journaliser():
    v = sp.preflight("INTERNAL", "SWARM", providers_candidats=["gemini", "inconnu"])
    for champ in ("decision", "pool", "exclus", "raison", "data_class",
                  "collaboration", "mode"):
        assert champ in v, champ
