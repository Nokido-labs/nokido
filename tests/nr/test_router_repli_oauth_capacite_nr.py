"""NR -- une cascade epuisee par la CAPACITE se replie sur AGY puis Claude Code (OAuth) ; jamais apres un refus de garde.

MESURE 2026-09-25 (recensement free tier + sondes) : groq 403 (cle refusee), deepseek/cerebras/hf 402,
mistral-large/medium/small hors palier (limite 0 req/min), zai/mammouth 429, locaux injoignables.
Le repli OAuth de fin de cascade n'existait que si TOUS les echecs etaient des 429 : avec des 402/403
il ne se declenchait jamais. Et il appelait un `gemini.cmd` code en dur (profil SYSTEM) en annoncant
« gemini-2.5-pro » sans preuve -- un modele que le fournisseur dit ne plus servir aux nouveaux comptes.

Demande owner (25/09) : « au pire tu routes vers agy oauth ou claude code ». Repli par les
fournisseurs DECLARES du proxy (gemini_cli = agy.exe, puis claude_cli), modele rendu = celui du
fournisseur. Liste BLANCHE des echecs de capacite : une erreur inconnue ne reroute pas. Et JAMAIS
apres un refus de garde (pare-feu, DLP, injection, SecretGuard) : rerouter vers le cloud contournerait
la garde qui avait restreint la chaine au local.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_llm_router as lr  # noqa: E402

CAPACITE = [("groq_fast", "Error code: 403 - cle ecartee"), ("mistral_large", "403 tier_not_allowed"),
            ("deepseek", "402 Payment Required"), ("openrouter_free", "429 rate limit exceeded"),
            ("ollama_local", "Connection refused")]


def test_des_echecs_de_capacite_autorisent_le_repli():
    assert lr.repli_oauth_autorise(CAPACITE, garde_a_parle=False) is True


def test_une_cascade_entierement_ecartee_autorise_le_repli():
    # tous les slots sautes (quota, disjoncteur, cooldown) : rien n'a ete REFUSE par une garde
    assert lr.repli_oauth_autorise([], garde_a_parle=False) is True


def test_la_garde_interdit_le_repli():
    assert lr.repli_oauth_autorise(CAPACITE, garde_a_parle=True) is False


def test_un_refus_de_secretguard_interdit_le_repli():
    assert lr.repli_oauth_autorise(CAPACITE + [("groq_fast", "SecretGuard: cle detectee")], False) is False


def test_une_erreur_inconnue_n_autorise_pas_le_repli():
    assert lr.repli_oauth_autorise([("x", "KeyError: 'choices'")], False) is False


def _neutraliser(monkeypatch, reponses):
    appels = []

    def faux(fournisseur, prompt, system, max_tokens, timeout):
        appels.append(fournisseur)
        return reponses[fournisseur]

    monkeypatch.setattr(lr, "_demander_au_proxy", faux)
    monkeypatch.setattr(lr, "_emit_nervous_event", lambda *a, **k: None)
    return appels


def test_agy_d_abord_puis_claude_code(monkeypatch):
    appels = _neutraliser(monkeypatch, {"gemini_cli": {"ok": False, "error": "agy indisponible"},
                                        "claude_cli": {"ok": True, "text": "reponse", "model": "modele-du-compte"}})
    tentatives = list(CAPACITE)
    r = lr.repli_oauth(tentatives, False, "p", "", 100, 30, "reasoning", time.monotonic())
    assert appels == ["gemini_cli", "claude_cli"]
    assert r["ok"] is True and r["provider"] == "claude_cli"
    assert r["model"] == "modele-du-compte"          # le modele du FOURNISSEUR, jamais invente
    assert ("gemini_cli", "agy indisponible") in r["attempts"]


def test_agy_suffit(monkeypatch):
    appels = _neutraliser(monkeypatch, {"gemini_cli": {"ok": True, "text": "ok", "model": "m"},
                                        "claude_cli": {"ok": True, "text": "jamais", "model": "m"}})
    r = lr.repli_oauth(list(CAPACITE), False, "p", "", 100, 30, "reasoning", time.monotonic())
    assert appels == ["gemini_cli"] and r["provider"] == "gemini_cli"


def test_pas_de_repli_apres_la_garde(monkeypatch):
    appels = _neutraliser(monkeypatch, {"gemini_cli": {"ok": True, "text": "fuite", "model": "m"},
                                        "claude_cli": {"ok": True, "text": "fuite", "model": "m"}})
    assert lr.repli_oauth(list(CAPACITE), True, "p", "", 100, 30, "reasoning", time.monotonic()) is None
    assert appels == []


def test_les_deux_replis_echouent_et_c_est_dit(monkeypatch):
    _neutraliser(monkeypatch, {"gemini_cli": {"ok": False, "error": "e1"},
                               "claude_cli": {"ok": True, "text": "  ", "model": "m"}})
    tentatives = list(CAPACITE)
    assert lr.repli_oauth(tentatives, False, "p", "", 100, 30, "reasoning", time.monotonic()) is None
    assert ("gemini_cli", "e1") in tentatives and tentatives[-1][0] == "claude_cli"


def test_le_pont_synchrone_marche_hors_et_dans_une_boucle(monkeypatch):
    recus = []

    async def ask(fournisseur, message, **k):
        recus.append(k)
        return {"ok": True, "text": fournisseur}

    faux = types.ModuleType("forge_agent_proxy")
    faux.ask = ask
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_agent_proxy", faux)
    assert lr._demander_au_proxy("gemini_cli", "p", "sys", 10, 5)["text"] == "gemini_cli"

    async def dans_une_boucle():
        return lr._demander_au_proxy("claude_cli", "p", "", 10, 5)

    assert asyncio.run(dans_une_boucle())["text"] == "claude_cli"
    assert all(k.get("raw") is True and k.get("rag_context") is False for k in recus)


def test_un_403_nu_n_autorise_pas_le_repli():
    # Debat CLAUDE<->AGY tour 2 (26/09, ACK-AUTOAMELIO) : un 403 de MODERATION de contenu cote
    # fournisseur n'est pas une capacite -- le rerouter contournerait un refus de contenu.
    assert lr.repli_oauth_autorise([("x", "Error code: 403 - Forbidden")], False) is False
    assert lr.repli_oauth_autorise([("x", "403 content policy violation")], False) is False


def test_un_403_de_palier_ou_de_cle_reste_une_capacite():
    assert lr.repli_oauth_autorise([("m", "403 tier_not_allowed")], False) is True
    assert lr.repli_oauth_autorise([("g", "Error code: 403 - cle ecartee")], False) is True
    assert lr.repli_oauth_autorise([("o", "403 invalid_api_key")], False) is True


def test_le_repli_est_plafonne_par_heure(monkeypatch):
    # Debat tour 2 : sans plafond, une panne large des API gratuites draine le quota OAuth.
    _neutraliser(monkeypatch, {"gemini_cli": {"ok": True, "text": "ok", "model": "m"},
                               "claude_cli": {"ok": True, "text": "ok", "model": "m"}})
    monkeypatch.setattr(lr, "_REPLI_OAUTH_PLAFOND_H", 2)
    monkeypatch.setattr(lr, "_REPLIS_RECENTS", [])
    assert lr.repli_oauth(list(CAPACITE), False, "p", "", 100, 30, "u", time.monotonic()) is not None
    assert lr.repli_oauth(list(CAPACITE), False, "p", "", 100, 30, "u", time.monotonic()) is not None
    tentatives = list(CAPACITE)
    assert lr.repli_oauth(tentatives, False, "p", "", 100, 30, "u", time.monotonic()) is None
    assert tentatives[-1][0] == "repli_oauth" and "plafond" in tentatives[-1][1]


def test_le_pont_rend_la_main_a_l_expiration_meme_si_le_fournisseur_traine(monkeypatch):
    # Defaut trouve a la relecture : `with ThreadPoolExecutor` attendait la fin du fil APRES
    # l'expiration de result(timeout) -- la borne ne protegeait rien.
    async def ask_lent(fournisseur, message, **k):
        await asyncio.sleep(3)
        return {"ok": True, "text": "trop tard"}

    faux = types.ModuleType("forge_agent_proxy")
    faux.ask = ask_lent
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_agent_proxy", faux)
    monkeypatch.setattr(lr, "_MARGE_PONT_S", 0)

    async def dans_une_boucle():
        t0 = time.monotonic()
        try:
            lr._demander_au_proxy("gemini_cli", "p", "", 10, 0.2)
        except Exception:  # noqa: BLE001 - l'expiration leve, c'est attendu
            pass
        return time.monotonic() - t0

    assert asyncio.run(dans_une_boucle()) < 2.0


def test_call_cascade_emprunte_le_repli_declare():
    classe = next(v for v in vars(lr).values() if isinstance(v, type) and hasattr(v, "call_cascade"))
    source = inspect.getsource(classe.call_cascade)
    assert "repli_oauth(" in source and "garde_a_parle" in source
    assert "gemini.cmd" not in source and "gemini-2.5-pro" not in source
