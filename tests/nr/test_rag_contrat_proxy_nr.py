"""Non-regression : le contexte RAG injecte au provider doit CONTENIR le contenu.

Defaut mesure le 2026-08-25, introduit le 2026-05-29 (commit 4d1bd104a) : 88 jours.
`_get_rag_context` lisait `r.get("text", "")` alors que `RAGEngine.search()` construit
ses documents avec `content` (forge_rag_engine.py:2096-2107 — cles id / source /
content / score / type / domain / role_hint, AUCUNE cle `text`).

Le contexte injecte au provider etait donc fait d'en-tetes `[rag:source]` et de
separateurs `---`, avec ZERO contenu, pendant que le retrieval reussissait. Le prompt
paraissait enrichi et ne l'etait pas.

Pourquoi ca a tenu 88 jours : un contexte vide est indiscernable de « aucun resultat ».
C'est le motif de la journee entiere - un silence lu comme une absence. Le remede n'est
donc pas seulement de lire la bonne clef : c'est de faire CRIER un contrat rompu.

Hermetique : le moteur RAG est double, aucun index n'est charge.
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : SQLite timeout=30 sur la VRAIE base (code
#   appele) (l.52)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import forge_agent_proxy as proxy  # noqa: E402


class _FauxRag:
    def __init__(self, docs):
        self._docs = docs

    async def search(self, query, k=3, **kw):
        return self._docs


def _brancher(monkeypatch, docs):
    """Double `get_rag`, importe DANS la fonction : on patche le module source."""
    faux = types.ModuleType("forge_app_context")
    faux.get_rag = lambda: _FauxRag(docs)
    monkeypatch.setitem(sys.modules, "forge_app_context", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_app_context", faux)


def _appel(query="watchdog heartbeat"):
    return asyncio.run(proxy._get_rag_context(query, k=3))


# --------------------------------------------------- le contrat reel du moteur

def test_le_contenu_du_moteur_arrive_bien_dans_le_prompt(monkeypatch):
    """La forme EXACTE que rend RAGEngine.search : cle `content`, pas `text`."""
    _brancher(monkeypatch, [
        {"id": "c1", "source": "rag:doc_a", "content": "le keeper bat mais gemma est down",
         "score": 0.9, "type": "rag", "domain": "general", "role_hint": "chat"},
        {"id": "c2", "source": "rag:doc_b", "content": "la quarantaine dure six heures",
         "score": 0.8, "type": "rag", "domain": "general", "role_hint": "chat"},
    ])
    ctx = _appel()
    assert "le keeper bat mais gemma est down" in ctx, ctx
    assert "la quarantaine dure six heures" in ctx, ctx
    assert "rag:doc_a" in ctx


def test_le_defaut_dorigine_ne_peut_plus_revenir(monkeypatch):
    """Le temoin qui aurait attrape le defaut des le 29/05 : un contexte qui ne
    porte QUE des en-tetes et des separateurs n'est pas un contexte."""
    _brancher(monkeypatch, [
        {"source": "rag:a", "content": "AAA"}, {"source": "rag:b", "content": "BBB"}])
    ctx = _appel()
    sans_decor = ctx.replace("---", "").replace("[rag:a]", "").replace("[rag:b]", "")
    assert sans_decor.strip(), "contexte reduit aux en-tetes : le contrat est rompu"


def test_la_clef_text_reste_toleree(monkeypatch):
    """On accepte les deux clefs plutot que d'imposer un contrat a des producteurs
    tiers qu'on ne voit pas d'ici."""
    _brancher(monkeypatch, [{"source": "autre:x", "text": "contenu par l ancienne clef"}])
    assert "contenu par l ancienne clef" in _appel()


# ------------------------------------------------- un contrat rompu doit CRIER

def test_des_resultats_sans_contenu_font_crier_le_garde(monkeypatch, caplog):
    """Sans ce cri, un producteur qui changerait de clef demain rendrait a nouveau un
    prompt silencieusement vide - et on repartirait pour 88 jours."""
    _brancher(monkeypatch, [{"source": "rag:a", "corps": "clef inconnue"},
                            {"source": "rag:b", "corps": "clef inconnue"}])
    with caplog.at_level("WARNING"):
        ctx = _appel()
    assert ctx == ""
    assert any("contrat de donnees rompu" in r.message.lower()
               or "aucun contenu exploitable" in r.message.lower()
               for r in caplog.records), [r.message for r in caplog.records]


def test_un_extrait_vide_est_ecarte_sans_faire_crier(monkeypatch):
    """Un seul extrait vide n'est pas une rupture de contrat : il est ecarte, et les
    autres passent. Un garde qui crie sur un cas normal se fait desarmer."""
    _brancher(monkeypatch, [{"source": "rag:a", "content": "   "},
                            {"source": "rag:b", "content": "utile"}])
    ctx = _appel()
    assert "utile" in ctx
    assert "rag:a" not in ctx


def test_aucun_resultat_rend_une_chaine_vide(monkeypatch):
    """Temoin : l'absence de resultat reste un cas normal, pas une alerte."""
    _brancher(monkeypatch, [])
    assert _appel() == ""


def test_le_contexte_reste_borne(monkeypatch):
    """Le budget de 3000 caracteres protege le prompt : le reparer ne doit pas le
    faire exploser."""
    _brancher(monkeypatch, [{"source": "rag:%d" % i, "content": "x" * 900}
                            for i in range(6)])
    assert len(_appel()) <= 3000


# ============================================================================
# BUDGET DE TOKENS D'ENTREE
#
# `MAX_THREAD_MESSAGES = 20` borne le NOMBRE de messages et jamais leur taille :
# vingt messages massifs partaient integralement au provider, et `max_tokens` ne
# borne QUE la sortie. Mesure 2026-08-25.
# ============================================================================

def _msg(role, contenu):
    return {"role": role, "content": contenu}


def test_un_contexte_normal_nest_pas_touche():
    """Temoin d'abord : un filet qui mord sur l'usage courant serait une regression,
    pas une protection."""
    msgs = [_msg("user", "bonjour"), _msg("assistant", "salut")]
    gardes, rapport = proxy._borner_contexte(msgs, "systeme", "question", "openai")
    assert gardes == msgs
    assert rapport["borne"] is False


def test_vingt_messages_massifs_sont_elagues(monkeypatch):
    """Le defaut d'origine : la borne comptait les tours, pas les tokens."""
    monkeypatch.setattr(proxy, "_INPUT_TOKEN_BUDGET", 500)
    msgs = [_msg("user", "y" * 400) for _ in range(20)]
    gardes, rapport = proxy._borner_contexte(msgs, "sys", "q", "openai")
    assert rapport["borne"] is True
    assert rapport["ecartes"] > 0
    assert len(gardes) < 20


def test_le_dernier_echange_nest_jamais_sacrifie(monkeypatch):
    """Sans lui, l'appel n'a plus d'objet : elaguer jusqu'au vide serait pire que
    laisser le provider tronquer."""
    monkeypatch.setattr(proxy, "_INPUT_TOKEN_BUDGET", 10)
    msgs = [_msg("user", "z" * 5000) for _ in range(8)]
    gardes, rapport = proxy._borner_contexte(msgs, "sys", "q", "openai")
    assert len(gardes) == proxy._MIN_MESSAGES_GARDES
    assert rapport.get("depassement", 0) > 0, "un depassement irreductible doit etre DIT"


def test_ce_qui_est_elague_est_compte_et_declare(monkeypatch, caplog):
    """Une troncature silencieuse fait passer un contexte ampute pour un contexte
    complet - le defaut meme que ce garde existe pour empecher."""
    monkeypatch.setattr(proxy, "_INPUT_TOKEN_BUDGET", 600)
    msgs = [_msg("user", "w" * 300) for _ in range(10)]
    with caplog.at_level("INFO"):
        _gardes, rapport = proxy._borner_contexte(msgs, "sys", "q", "openai")
    assert rapport["ecartes"] >= 1
    assert any("borne" in r.message or "HORS BUDGET" in r.message
               for r in caplog.records), [r.message for r in caplog.records]


def test_les_anciens_partent_avant_les_recents(monkeypatch):
    """Le plus ancien est le moins couteux a perdre : c'est l'ordre de sacrifice.

    Budget volontairement irreductible plutot que calibre : une premiere version de
    ce test fixait 700 en RAISONNANT EN CARACTERES, or tiktoken compresse fortement
    une repetition (`"a" * 300` ne coute pas 300 tokens) — le total restait sous le
    budget et rien n'etait elague. C'est exactement l'erreur que ce garde existe pour
    empecher : l'unite est le TOKEN, jamais le caractere.
    """
    monkeypatch.setattr(proxy, "_INPUT_TOKEN_BUDGET", 1)
    msgs = [_msg("user", "vieux message"), _msg("user", "milieu message"),
            _msg("user", "recent message")]
    gardes, rapport = proxy._borner_contexte(msgs, "", "", "openai")
    assert len(gardes) == proxy._MIN_MESSAGES_GARDES
    textes = " ".join(m["content"] for m in gardes)
    assert "recent" in textes and "milieu" in textes
    assert "vieux" not in textes, textes
    assert rapport["ecartes"] == 1


def test_le_repli_du_compteur_ne_sous_estime_jamais(monkeypatch):
    """Si le tokenizer est indisponible, on majore par len() : un filet qui se trompe
    doit se tromper du cote SUR."""
    import forge_tokenizer

    def _casse(*a, **k):
        raise RuntimeError("tokenizer indisponible")

    monkeypatch.setattr(forge_tokenizer, "count_tokens", _casse)
    assert proxy._compter("abcdef", "openai") == 6
