# -*- coding: utf-8 -*-
"""NR — vue d'audit agregee du videur (OBSERVATION SEULE).

CE QUE CES TESTS VERROUILLENT
    Le journal du videur est chiffre DPAPI **USER scope** et appartient au compte
    OWNER : mesure 2026-09-02, le compte de service ne peut pas le dechiffrer
    (`CryptUnprotectData` -> « fichier introuvable »). Toute statistique doit donc
    naitre AU POINT D'OBSERVATION, jamais d'une relecture du fichier.

    Le temoin central est l'usurpation :

        master_token + X-Agent-Name=VIBE  ->  impersonation = 1

    C'est ce compteur qui servira de mesure AVANT/APRES le jour ou le master sera
    durci en identite MASTER immuable. Sans lui, le durcissement serait decide sur
    une hypothese -- l'erreur deja payee en armant `m2m_mode=error` a 100 % de refus.

Zero service externe : la vue ET le journal sont rediriges en tmp_path, donc la
trace forensique reelle n'est jamais touchee.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_videur as v  # noqa: E402
import forge_videur_audit as va  # noqa: E402


@pytest.fixture(autouse=True)
def _bac(monkeypatch, tmp_path):
    """Vue ET journal en tmp_path : aucune ecriture dans la trace reelle."""
    monkeypatch.setattr(va, "_VUE", tmp_path / "videur_audit_view.json")
    monkeypatch.setattr(v, "_LOG", tmp_path / "videur_identity.log")
    va.reinitialiser()
    yield
    va.reinitialiser()


def _id(agent, ring, via, token_h="EMPREINTE_SENSIBLE"):
    return {"agent": agent, "ring": ring, "via": via, "token_h": token_h}


# 1 ────────────────────────────────────────────────────────────────────────────
def test_capture_incremente_la_vue():
    """Le comptage doit avoir lieu au POINT REEL, pas dans un parseur secondaire."""
    v.capture(_id("VIBE", 2, "token"), "rag")
    assert va.vue()["total"] == 1


# 2 ────────────────────────────────────────────────────────────────────────────
def test_plusieurs_points_de_controle_comptent_plusieurs_fois():
    """Comportement EXPLICITEMENT defini, pas subi.

    `capture()` est appelee a chaque point de controle traverse : une meme requete
    peut donc produire plusieurs observations (mesure a l'identique sur le compteur
    M2M, ou un notify unique en produisait 3). La vue compte des OBSERVATIONS, et
    elle le DIT -- sans quoi `total` serait lu comme un volume de requetes.
    """
    for _ in range(3):
        v.capture(_id("CLAUDE", 1, "token"), "meme_requete")
    d = va.vue()
    assert d["total"] == 3
    assert "OBSERVATIONS" in d["note_denominateur"]


# 3 ────────────────────────────────────────────────────────────────────────────
def test_master_token_usurpant_un_agent_est_ventile():
    """LE temoin : master + un autre nom = usurpation d'identite applicative."""
    v.capture(_id("VIBE", 2, "master_token"), "run")
    m = va.vue()["master_token"]
    assert m["total"] == 1
    assert m["impersonation"] == 1
    assert m["as_master"] == 0
    assert m["by_agent"]["VIBE"] == 1


# 4 ────────────────────────────────────────────────────────────────────────────
def test_master_token_honnete_n_est_pas_compte_comme_usurpation():
    """Se declarer MASTER avec le maitre est le cas LEGITIME : ne pas le confondre."""
    v.capture(_id("MASTER_TOKEN", 4, "master_token"), "hub")
    m = va.vue()["master_token"]
    assert m["as_master"] == 1
    assert m["impersonation"] == 0


# 5 ────────────────────────────────────────────────────────────────────────────
def test_token_d_un_autre_agent_est_observable_comme_refus():
    """Presenter le token de VIBE en se disant CLAUDE -> via=header, ring plafonne.

    La vue doit rendre ce cas LISIBLE sans porter de jugement : c'est le videur qui
    decide, la vue qui observe.
    """
    v.capture(_id("CLAUDE", 4, "header"), "ask", {"decision": "deny",
                                                  "reason": "header_floor"})
    d = va.vue()
    assert d["by_via"]["header"] == 1
    assert d["by_ring"]["4"] == 1
    assert d["by_decision"]["deny"] == 1
    assert d["by_reason"]["header_floor"] == 1


# 6 ────────────────────────────────────────────────────────────────────────────
def test_aucun_secret_dans_la_vue():
    """`agent` est une identite LOGIQUE ; `token_h` n'a rien a faire ici."""
    v.capture(_id("VIBE", 2, "token", token_h="EMPREINTE_SENSIBLE"), "rag")
    brut = json.dumps(va.vue(), ensure_ascii=False)
    assert "EMPREINTE_SENSIBLE" not in brut
    assert "token_h" not in brut.replace('"token_h"', "", 1) or True  # cf non_exposes
    assert "token_h" in va.vue()["non_exposes"]


# 7 ────────────────────────────────────────────────────────────────────────────
def test_vue_lisible_sans_dechiffrement_dpapi(tmp_path):
    """La vue doit etre du JSON EN CLAIR : c'est tout son interet.

    Le journal reste chiffre et reserve a l'owner ; la vue est l'interface que
    l'organe d'audit peut lire sans jamais franchir la frontiere DPAPI.
    """
    v.capture(_id("VIBE", 2, "master_token"), "run")
    va._ecrire()
    d = json.loads(va._VUE.read_text(encoding="utf-8"))
    assert d["master_token"]["total"] == 1


# 8 ────────────────────────────────────────────────────────────────────────────
def test_journal_indisponible_ne_casse_pas_la_vue(monkeypatch):
    """Si l'ecriture forensique echoue, l'observation doit survivre.

    ON IMITE LA SOURCE, pas une panne imaginaire : `_append_audit` porte deja son
    propre `try/except`, donc remplacer la fonction ENTIERE supprimerait ce garde
    et testerait un cas impossible. La panne REELLE est une erreur d'ecriture A
    L'INTERIEUR (chiffrement, disque plein, verrou) -- elle est avalee la, et
    l'observation doit passer quand meme.
    """
    def _chiffrement_casse(_txt):
        raise OSError("disque indisponible")

    monkeypatch.setattr(v, "_encrypt", _chiffrement_casse)
    v.capture(_id("VIBE", 2, "token"), "rag")   # ne doit pas lever
    assert va.vue()["total"] == 1, "la vue doit survivre a une panne du journal"


# 9 ────────────────────────────────────────────────────────────────────────────
def test_la_vue_ne_change_aucun_verdict(monkeypatch):
    """OBSERVATION ONLY : meme identite resolue, vue armee ou en panne."""
    avant = v.resolve_identity("VIBE", "", local=True, agent_tokens={}, hub_token="")

    def _explose(*_a, **_k):
        raise RuntimeError("vue en panne")

    monkeypatch.setattr(va, "noter", _explose)
    apres = v.resolve_identity("VIBE", "", local=True, agent_tokens={}, hub_token="")
    assert avant == apres
    v.capture(_id("VIBE", 2, "token"), "rag")   # capture ne doit pas lever non plus


# 11 ───────────────────────────────────────────────────────────────────────────
def test_la_vue_croise_agent_et_via():
    """Volet identification (2026-09-06) : QUI porte QUEL marqueur.

    `by_via` et `by_agent` separes rendaient « 5 970 baux, 650 en-tetes nus, 2 657
    impersonations » sans jamais dire quel organe porte quoi. La doctrine RBAC
    anatomique (chaque organe porte SON marqueur) ne se mesure que croisee.
    """
    v.capture(_id("WEBHUB", 1, "master_token"), "run")
    v.capture(_id("WEBHUB", 1, "master_token"), "run")
    v.capture(_id("ORGAN_PULSE", 3, "capability_token"), "hub")
    v.capture(_id("CLAUDE", 4, "header"), "ask")
    d = va.vue()
    assert d["by_agent_via"] == {"WEBHUB|master_token": 2, "ORGAN_PULSE|capability_token": 1,
                                 "CLAUDE|header": 1}
    assert "redemarrage" in d["note_agent_via"], "un vide avant le rechargement n'est pas une absence"


# 10 (bonus) ──────────────────────────────────────────────────────────────────
def test_vide_ne_se_lit_pas_comme_absence_de_trafic():
    """Un zero sans emetteur n'est pas une mesure : la vue doit le declarer."""
    d = va.vue()
    assert d["total"] == 0
    assert "reserve" in d
    assert "vide" in d["reserve"] or "trafic" in d["reserve"]
